"""
LLM client abstraction.

Why this exists:
  * One choke point for every model call → one place to enforce the Denial-of-Wallet
    budget and to emit observability spans.
  * An OFFLINE mode so the pipeline + tests run deterministically with no API key
    and no network (essential for eval-as-unit-test).
  * A real, bounded tool-use loop (the old code faked skill execution; this runs the
    actual Anthropic tool protocol with a max-iteration cap).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    import anthropic
except ImportError:  # graceful degradation
    anthropic = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

log = logging.getLogger("radar.llm")

# Rough per-MTok USD prices for budget estimation only (input, output).
_PRICES = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
}


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    tool_iterations: int = 0
    raw: Any = None

    @property
    def est_usd(self) -> float:
        pin, pout = _PRICES.get(self.model, (3.0, 15.0))
        return (self.input_tokens / 1e6) * pin + (self.output_tokens / 1e6) * pout


# A tool the model can call. handler(tool_input: dict) -> str (tool result text).
@dataclass
class Tool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], str]
    mutates_state: bool = False

    def anthropic_spec(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


class OfflineResponder:
    """
    Deterministic stand-in used when CONFIG.offline or no client is available.
    Lets the entire DAG + tests run with zero credentials. A custom responder can
    be injected in tests to simulate specific model behavior.
    """

    def __init__(self, fn: Optional[Callable[[str, str, List[Tool]], str]] = None):
        self.fn = fn

    def respond(self, system: str, user: str, tools: List[Tool]) -> str:
        if self.fn:
            return self.fn(system, user, tools)
        # Heuristic defaults keyed off the system persona so the pipeline produces
        # plausible, schema-valid output offline.
        s = system.lower()
        if "startup judge" in s:
            return json.dumps({"winner": "A", "reason": "offline-default"})
        if "signal curator" in s:
            return json.dumps({"curated": [{"id": "offline", "why": "offline", "evergreen": False}]})
        if "startup strategist" in s:
            return json.dumps([{
                "id": "offline-wedge",
                "title": "Offline placeholder wedge",
                "description": "Deterministic offline output for testing the harness.",
                "revenue_path": "n/a (offline)", "adjacent_tech_transfer": "n/a",
                "first_motion": "n/a",
            }])
        # source-processing default
        return json.dumps({"summary": "offline summary", "pain_point": None, "evergreen": False})


class LLMClient:
    def __init__(self, config, budget=None, tracer=None, offline_responder: Optional[OfflineResponder] = None):
        self.config = config
        self.budget = budget
        self.tracer = tracer
        self.offline_responder = offline_responder or OfflineResponder()
        self._anthropic = None
        if not config.offline and anthropic and config.anthropic_api_key:
            self._anthropic = anthropic.Anthropic(api_key=config.anthropic_api_key)
        if not config.offline and genai and config.gemini_api_key:
            try:
                genai.configure(api_key=config.gemini_api_key)
            except Exception as e:  # pragma: no cover
                log.warning("Gemini configure failed: %s", e)

    @property
    def is_offline(self) -> bool:
        return self.config.offline or self._anthropic is None

    # ── main entry: a single model turn, optionally with a bounded tool loop ──
    def complete(
        self,
        system: str,
        user: str,
        *,
        model: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        max_tokens: int = 4000,
        thinking_budget: int = 0,
        node: str = "llm",
    ) -> LLMResult:
        model = model or self.config.model_curation
        tools = tools or []
        if self.budget:
            self.budget.charge_call(node)  # raises CircuitBreakerTripped if over budget

        if self.is_offline:
            text = self.offline_responder.respond(system, user, tools)
            res = LLMResult(text=text, model=model, input_tokens=len(user) // 4,
                            output_tokens=len(text) // 4)
            if self.budget:
                self.budget.charge_usd(res.est_usd, node)
            return res

        return self._anthropic_loop(system, user, model, tools, max_tokens, thinking_budget, node)

    def _anthropic_loop(self, system, user, model, tools, max_tokens, thinking_budget, node) -> LLMResult:
        messages: List[Dict[str, Any]] = [{"role": "user", "content": user}]
        tool_specs = [t.anthropic_spec() for t in tools] if tools else None
        by_name = {t.name: t for t in tools}
        in_tok = out_tok = iters = 0
        final_text = ""

        for _ in range(self.config.max_tool_iterations):
            kwargs: Dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
            if tool_specs:
                kwargs["tools"] = tool_specs
            if thinking_budget > 0:
                # budget_tokens is rejected on Fable 5 / Opus 4.7+; adaptive lets the
                # model set its own depth. The budget now only sizes output headroom.
                kwargs["thinking"] = {"type": "adaptive"}
                kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)
            resp = self._anthropic.messages.create(**kwargs)
            in_tok += getattr(resp.usage, "input_tokens", 0)
            out_tok += getattr(resp.usage, "output_tokens", 0)

            tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            texts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
            final_text = "\n".join(texts) if texts else final_text

            if not tool_uses or resp.stop_reason != "tool_use":
                break

            iters += 1
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                tool = by_name.get(tu.name)
                if tool is None:
                    out = f"ERROR: unknown tool {tu.name}"
                else:
                    if self.budget:
                        self.budget.charge_tool(tu.name, node)
                    try:
                        out = tool.handler(dict(tu.input))
                    except Exception as e:  # surface tool errors to the model
                        out = f"ERROR: {e}"
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": str(out)[:8000]})
            messages.append({"role": "user", "content": results})

        res = LLMResult(text=final_text, input_tokens=in_tok, output_tokens=out_tok,
                        model=model, tool_iterations=iters)
        if self.budget:
            self.budget.charge_usd(res.est_usd, node)
        return res

    # ── optional heterogeneous judge (Gemini) ────────────────────────────────
    def judge_gemini(self, system: str, user: str) -> Optional[str]:
        """Returns text, or None if Gemini is unavailable (caller falls back to Claude)."""
        if self.is_offline or genai is None or not self.config.gemini_api_key:
            return None
        try:
            model = genai.GenerativeModel(model_name=self.config.model_judge, system_instruction=system)
            resp = model.generate_content(user)
            if self.budget:
                self.budget.charge_call("judge-gemini")
            return resp.text
        except Exception as e:  # pragma: no cover
            log.warning("Gemini judge failed, falling back to Claude: %s", e)
            return None
