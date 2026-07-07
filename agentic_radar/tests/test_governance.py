"""
Day-5 Zero-Trust governance tests: the Policy Server (structural + semantic gating) and
Context Hygiene (placeholder resolution + PII masking). All run offline (no API key):
the semantic gate falls back to a deterministic PII screen when no judge LLM is present.
"""
import os

import pytest

from governance.policy_server import PolicyServer
from governance.context_resolver import resolve_context, sanitize_args, mask_pii, find_pii
from config import default_mcp_registry
from connectors.mcp_client import MCPClient


def _ps():
    return PolicyServer()  # no LLM → semantic gate uses the PII backstop


# ── structural gating ─────────────────────────────────────────────────────────
def test_structural_allows_radar_read():
    assert _ps().check("notion-search", {"query": "x"}, role="radar", env="development").allowed


def test_structural_denies_disallowed_role():
    d = _ps().check("notion-create-pages", {"x": 1}, role="viewer", env="development")
    assert not d.allowed and d.layer == "structural"


def test_structural_env_block():
    d = _ps().check("send_email", {"to": "a@b.com"}, role="radar", env="localhost")
    assert not d.allowed and d.layer == "structural"


# ── semantic gating (offline PII backstop) ────────────────────────────────────
def test_semantic_denies_unmasked_pii():
    args = {"pages": [{"content": "Contact me at alice@example.com about the report"}]}
    d = _ps().check("notion-create-pages", args, role="radar", env="development")
    assert not d.allowed and d.layer == "semantic" and "email" in d.reason


def test_semantic_allows_clean_write():
    args = {"pages": [{"content": "Opportunity Radar daily report: tactile calibration wedge"}]}
    d = _ps().check("notion-create-pages", args, role="radar", env="development")
    assert d.allowed


def test_reads_skip_semantic_even_with_pii():
    # reads are not in semantic_check_tools; structural-only
    d = _ps().check("notion-search", {"query": "alice@example.com"}, role="radar")
    assert d.allowed


# ── context hygiene ───────────────────────────────────────────────────────────
def test_context_resolver_resolves_placeholders(monkeypatch):
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "page-123")
    assert resolve_context("[[NOTION_PARENT_PAGE_ID]]") == "page-123"
    # runtime override beats env
    assert resolve_context("[[X]]", {"X": "override"}) == "override"
    # unknown placeholder is left intact (surfaced, not silently dropped)
    assert resolve_context("[[MISSING_VAR_XYZ]]") == "[[MISSING_VAR_XYZ]]"


def test_sanitize_args_recurses_lists(monkeypatch):
    monkeypatch.setenv("ID", "real-id")
    out = sanitize_args({"a": "[[ID]]", "b": ["[[ID]]", 5], "c": 7})
    assert out == {"a": "real-id", "b": ["real-id", 5], "c": 7}


def test_mask_and_find_pii():
    masked, kinds = mask_pii("ping bob@corp.io key sk-ABCDEFGHIJKLMNOP")
    assert "[MASKED_EMAIL]" in masked and "[MASKED_KEY]" in masked
    assert set(kinds) >= {"email", "api_key"}
    assert "email" in find_pii({"nested": ["x", {"y": "z@z.com"}]})


# ── integration through MCPClient ─────────────────────────────────────────────
def test_mcpclient_policy_denies_viewer_write():
    spec = default_mcp_registry()["notion"]
    spec.read_only = False
    client = MCPClient(spec, confirm_fn=lambda s, t, a: True, require_confirmation=True,
                       policy_server=_ps(), role="viewer", env="development")
    res = client.call_tool("notion-create-pages", {"x": 1})
    assert not res.ok and "policy violation" in (res.skipped_reason or "")


def test_mcpclient_resolves_placeholder_then_blocks_on_pii(monkeypatch):
    # placeholder resolves to a PII email → semantic gate must catch it post-resolution
    monkeypatch.setenv("LEAK", "secret@corp.com")
    spec = default_mcp_registry()["notion"]
    spec.read_only = False
    client = MCPClient(spec, confirm_fn=lambda s, t, a: True, require_confirmation=True,
                       policy_server=_ps(), role="radar", env="development")
    res = client.call_tool("notion-create-pages", {"pages": [{"content": "[[LEAK]]"}]})
    assert not res.ok and "semantic" in (res.skipped_reason or "")
