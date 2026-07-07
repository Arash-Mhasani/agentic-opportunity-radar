"""
Agent runners — the harness nodes.

Fixes vs the old agent_runners.py:
  * Real skill execution: loads SKILL.md into the system prompt and gives the model a
    real `read_bus_record` tool (the old code faked it).
  * Correct model IDs (config.py), not 'claude-4-8-opus'.
  * Judge runs TWICE with swapped A/B order to neutralize position bias (Day-3 sl.20),
    uses Gemini if available (model diversity) and falls back to Claude otherwise.
  * Robust JSON parsing; tracing via clean `with` blocks (nullcontext when no tracer).
"""
from __future__ import annotations

import json
import logging
import contextlib
from typing import Any, Dict, List, Optional

from agents.prompts import (BUSINESS_SYSTEM, CURATION_SYSTEM, JUDGE_SYSTEM, SOURCE_BASE_SYSTEM)
from skills.skill_loader import SkillRegistry, make_bus_tools

log = logging.getLogger("radar.agents")


def _extract_json(text: str, kind: str = "object"):
    """Best-effort JSON extraction from a model response."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    open_c, close_c = ("[", "]") if kind == "array" else ("{", "}")
    i, j = text.find(open_c), text.rfind(close_c)
    if i == -1 or j == -1:
        raise ValueError(f"no JSON {kind} found")
    return json.loads(text[i:j + 1])


class _NullHandle:
    def set(self, **kw):
        pass


class AgentRunner:
    def __init__(self, llm_client, skills_dir: str, message_bus, tracer=None):
        self.llm = llm_client
        self.registry = SkillRegistry(skills_dir)
        self.bus = message_bus
        self.tracer = tracer

    def _span(self, name: str, kind: str = "node", **attrs):
        if self.tracer:
            return self.tracer.span(name, kind=kind, **attrs)
        return contextlib.nullcontext(_NullHandle())

    # ── source processing: pick a skill by category, run it for real ──────────
    def run_source_skill(self, category: str, record_uri: str) -> Dict[str, Any]:
        skill = self.registry.for_category(category)
        if skill is None:
            return {"source_type": category, "summary": "(no skill matched)", "url": record_uri}

        import os

        def _read_reference(name: str) -> str:
            ref = os.path.join(os.path.dirname(skill.path), "references", os.path.basename(name))
            if os.path.isfile(ref):
                with open(ref, encoding="utf-8") as f:
                    return f.read()
            return f"reference {name} not found"

        tools = make_bus_tools(self.bus.read_text, _read_reference)
        system = SOURCE_BASE_SYSTEM + "\n\n" + skill.system_block
        user = f"Process this record. Its URI is: {record_uri}\nCall read_bus_record(uri) first."

        with self._span(f"skill:{skill.name}", kind="model", category=category,
                        skill_version=skill.version) as h:
            res = self.llm.complete(system, user, model=self.llm.config.model_source,
                                    tools=tools, max_tokens=1200, node=f"source:{skill.name}")
            try:
                record = _extract_json(res.text, "object")
            except Exception:
                record = {"source_type": category, "summary": res.text[:400], "url": record_uri,
                          "pain_point": None, "evergreen_candidate": False}
            record.setdefault("url", record_uri)
            h.set(tool_iterations=res.tool_iterations)
            return record

    # ── curation: filter + evergreen promotion ────────────────────────────────
    def run_curation(self, compressed_records: List[Dict[str, Any]], feedback: str = "") -> List[Dict[str, Any]]:
        if not compressed_records:
            return []
        payload = json.dumps(compressed_records, default=str)[:60000]
        user = f"Records:\n{payload}"
        if feedback:
            user += f"\n\nUser steering for resource filtering: {feedback}"
        with self._span("node:curation", kind="node", n_in=len(compressed_records)) as h:
            res = self.llm.complete(CURATION_SYSTEM, user, model=self.llm.config.model_curation,
                                    max_tokens=3000, node="curation")
            try:
                out = _extract_json(res.text, "object").get("curated", [])
            except Exception:
                out = [{"id": r.get("title", "?"), "why": "parse-fallback", "evergreen": False}
                       for r in compressed_records[:10]]
            h.set(n_out=len(out))
            return out

    # ── business: deep reasoning → opportunities ──────────────────────────────
    def run_business(self, static_context: str, evergreen_context: str,
                     curated: List[Dict[str, Any]], feedback: str = "") -> List[Dict[str, Any]]:
        user = (f"{static_context}\n\n{evergreen_context}\n\n"
                f"### CURATED SIGNALS ###\n{json.dumps(curated, default=str)[:40000]}\n")
        if feedback:
            user += f"\n### USER FEEDBACK ON BUSINESS LOGIC ###\n{feedback}\n"
        with self._span("node:business", kind="node") as h:
            res = self.llm.complete(BUSINESS_SYSTEM, user, model=self.llm.config.model_business,
                                    max_tokens=8000, thinking_budget=4000, node="business")
            try:
                ideas = _extract_json(res.text, "array")
            except Exception as e:
                log.warning("business JSON parse failed: %s", e)
                ideas = []
            h.set(n_ideas=len(ideas))
            return ideas

    # ── judge: ONE match, position-swapped to neutralize ordering bias ────────
    def judge_match(self, a: Dict[str, Any], b: Dict[str, Any], constraints: str) -> bool:
        """Return True if a beats b. Runs twice (A/B and B/A); ties broken by Elo then id."""
        def _ask(first, second):
            user = (f"Constraints:\n{constraints}\n\nA = {json.dumps(first, default=str)}\n"
                    f"B = {json.dumps(second, default=str)}")
            txt = self.llm.judge_gemini(JUDGE_SYSTEM, user)
            diverse = txt is not None
            if txt is None:  # fall back to Claude judge
                txt = self.llm.complete(JUDGE_SYSTEM, user, model=self.llm.config.model_cheap,
                                        max_tokens=200, node="judge").text
            try:
                w = _extract_json(txt, "object").get("winner", "").upper()
            except Exception:
                w = ""
            return w, diverse

        w1, d1 = _ask(a, b)            # A=a, B=b  → 'A' means a wins
        w2, d2 = _ask(b, a)            # A=b, B=a  → 'A' means b wins
        a_votes = (1 if w1 == "A" else 0) + (1 if w2 == "B" else 0)
        b_votes = (1 if w1 == "B" else 0) + (1 if w2 == "A" else 0)
        with self._span("judge:match", kind="model", a=a.get("id"), b=b.get("id"),
                        a_votes=a_votes, b_votes=b_votes, model_diverse=bool(d1 and d2)):
            pass
        if a_votes != b_votes:
            return a_votes > b_votes
        if a.get("elo_score", 0) != b.get("elo_score", 0):
            return a.get("elo_score", 0) > b.get("elo_score", 0)
        return str(a.get("id", "")) <= str(b.get("id", ""))
