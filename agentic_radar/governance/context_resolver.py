"""
Context Hygiene & Prompt Sanitization (Day-5, "Context Hygiene & Prompt Sanitization").

Implements the Day-5 ContextResolver pattern: tool arguments and templates use
double-bracket placeholders like [[NOTION_PARENT_PAGE_ID]] which are resolved at
runtime from explicit state overrides or environment variables — so sensitive IDs,
emails, and URLs are never hardcoded into prompts, specs, or test suites.

It also provides PII masking used by the Policy Server's deterministic backstop, so
the "context hallucination" risk (an agent emitting a hardcoded address/URL it found
lying in context) is contained.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

# [[VARIABLE_NAME]] — the Day-5 placeholder syntax.
_PLACEHOLDER = re.compile(r"\[\[([^\]]+)\]\]")

# PII detectors (deterministic backstop for the semantic gate).
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_API_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9]{12,}|ntn_[A-Za-z0-9]{12,}|AIza[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b")
_PRIVATE_URL = re.compile(r"\bhttps?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|[A-Za-z0-9.-]+\.internal)\S*", re.I)


def resolve_context(template_str: Optional[str], override_state: Optional[Dict[str, Any]] = None) -> str:
    """Replace [[VAR]] with override_state[VAR], else os.environ[VAR], else leave intact."""
    if template_str is None:
        return ""
    state = override_state or {}

    def _sub(m: re.Match) -> str:
        var = m.group(1).strip()
        if var in state and state[var] is not None:
            return str(state[var])
        if var in os.environ and os.environ[var] is not None:
            return os.environ[var]
        return m.group(0)  # leave unresolved to surface, not silently fail

    return _PLACEHOLDER.sub(_sub, template_str)


def mask_pii(text: str) -> Tuple[str, List[str]]:
    """Return (masked_text, kinds_found). Used to sterilize values and to detect leaks."""
    found: List[str] = []
    out = text
    if _EMAIL.search(out):
        found.append("email"); out = _EMAIL.sub("[MASKED_EMAIL]", out)
    if _API_KEY.search(out):
        found.append("api_key"); out = _API_KEY.sub("[MASKED_KEY]", out)
    if _PRIVATE_URL.search(out):
        found.append("private_url"); out = _PRIVATE_URL.sub("[MASKED_URL]", out)
    return out, found


def find_pii(value: Any) -> List[str]:
    """Recursively scan a JSON-ish value and return the kinds of PII present."""
    kinds: set = set()

    def _walk(v: Any):
        if isinstance(v, str):
            _, found = mask_pii(v)
            kinds.update(found)
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                _walk(x)

    _walk(value)
    return sorted(kinds)


def sanitize_args(args: Dict[str, Any], override_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Resolve [[placeholders]] in every string argument before a tool runs (Day-5
    tool_policy_engine pattern), recursing through nested dicts and lists to any depth
    (e.g. Notion's pages: [{content: ...}]). Non-string scalars pass through. Does NOT
    auto-mask PII here — masking/denial is the Policy Server's job, keeping resolution
    and governance as separate concerns.
    """
    def _walk(v: Any) -> Any:
        if isinstance(v, str):
            return resolve_context(v, override_state)
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_walk(x) for x in v]
        return v

    return {k: _walk(x) for k, x in (args or {}).items()}
