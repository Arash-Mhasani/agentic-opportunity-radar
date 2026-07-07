"""
Hybrid Policy Server (Day-5, "Policy Server").

Intercepts every tool call before it reaches an external system and applies two
layers, separating governance logic from execution logic:

  1. Structural Gating ("traffic lights") — deterministic role/environment rules from
     policies.yaml. Fast, binary, no LLM. (e.g. a viewer role cannot call a write tool;
     localhost cannot send_email.)
  2. Semantic Gating ("intelligent referee") — for tools that send/write data, a
     secondary check on *how* the tool is used. Prefers an LLM judge ("does this action
     leak unmasked PII?"); falls back to a deterministic PII screen when no LLM is
     available (so it still works offline). You cannot regex every PII leak, but the
     regex screen is a safe backstop, and the LLM catches the rest.

On denial the server returns a decision the caller surfaces to the agent as a
"Policy Violation", allowing self-correction or graceful failure rather than a crash.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from governance.context_resolver import find_pii

log = logging.getLogger("radar.policy")


@dataclass
class PolicyDecision:
    allowed: bool
    layer: str          # "structural" | "semantic" | "ok"
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


_SEMANTIC_PROMPT = (
    "You are a security policy referee. Decide if the following tool action would leak "
    "unmasked PII (plain-text email addresses, API keys/tokens, or private/internal URLs) "
    "into an external system. Reply with exactly 'VIOLATION' or 'OK' on the first line.\n\n"
    "Tool: {tool}\nArguments:\n{args}"
)


class PolicyServer:
    def __init__(self, config=None, llm_client=None, policies_path: Optional[str] = None):
        self.config = config
        self.llm = llm_client
        path = policies_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "policies.yaml")
        with open(path, encoding="utf-8") as f:
            self.policies: Dict[str, Any] = yaml.safe_load(f) or {}

    # ── layer 1: structural ───────────────────────────────────────────────────
    def _structural(self, tool: str, role: str, env: str) -> PolicyDecision:
        envs = self.policies.get("environments", {})
        blocked = (envs.get(env, {}) or {}).get("blocked_tools", []) or []
        if tool in blocked:
            return PolicyDecision(False, "structural", f"tool '{tool}' is blocked in environment '{env}'")
        roles = self.policies.get("roles", {})
        allowed = (roles.get(role, {}) or {}).get("allowed_tools", []) or []
        if "*" in allowed or tool in allowed:
            return PolicyDecision(True, "structural")
        return PolicyDecision(False, "structural", f"role '{role}' is not permitted to call '{tool}'")

    # ── layer 2: semantic ─────────────────────────────────────────────────────
    def _needs_semantic(self, tool: str) -> bool:
        return tool in (self.policies.get("semantic_check_tools", []) or [])

    def _semantic(self, tool: str, args: Dict[str, Any]) -> PolicyDecision:
        # Prefer the LLM referee when available; fall back to the deterministic PII screen.
        if self.llm is not None and not getattr(self.llm, "is_offline", True):
            try:
                prompt = _SEMANTIC_PROMPT.format(tool=tool, args=json.dumps(args, default=str)[:4000])
                verdict = self.llm.complete("", prompt, model=self.config.model_cheap if self.config else None,
                                            max_tokens=20, node="policy-semantic").text.strip().upper()
                if verdict.startswith("VIOLATION"):
                    return PolicyDecision(False, "semantic", "LLM referee flagged a PII/policy violation")
                return PolicyDecision(True, "semantic")
            except Exception as e:  # never let governance crash the pipeline; fall through to regex
                log.warning("semantic LLM check failed, using PII backstop: %s", e)
        kinds = find_pii(args)
        if kinds:
            return PolicyDecision(False, "semantic", f"unmasked PII in arguments: {kinds}")
        return PolicyDecision(True, "semantic")

    # ── public entry ──────────────────────────────────────────────────────────
    def check(self, tool: str, args: Dict[str, Any], *, role: str = "radar", env: str = "development") -> PolicyDecision:
        structural = self._structural(tool, role, env)
        if not structural.allowed:
            log.info("POLICY DENY [structural] %s: %s", tool, structural.reason)
            return structural
        if self._needs_semantic(tool):
            semantic = self._semantic(tool, args)
            if not semantic.allowed:
                log.info("POLICY DENY [semantic] %s: %s", tool, semantic.reason)
                return semantic
        return PolicyDecision(True, "ok")
