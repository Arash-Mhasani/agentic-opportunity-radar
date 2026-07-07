"""
Fixed business-agent test.

The original test was broken: it called AgentRunner(api_key=, fast_model=, reasoning_model=)
and run_business_agent(static_context, curated_signals) — none of which match the real
API. This version uses the real signatures and the offline LLM client (no API key, no
network), then asserts the output is schema-valid and constraint-compliant.
"""
import os
import tempfile

import pytest

from config import RadarConfig
from agents.llm_client import LLMClient, OfflineResponder
from agents.agent_runners import AgentRunner, _extract_json
from core.message_bus import MessageBus
from evals.rubric import score_functional_correctness, score_constraint_compliance

SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")


def _runner(tmp, responder=None):
    cfg = RadarConfig()
    cfg.offline = True
    llm = LLMClient(cfg, offline_responder=responder)
    bus = MessageBus(os.path.join(tmp, "bus"))
    return AgentRunner(llm, SKILLS_DIR, bus), bus


def test_business_agent_offline_schema_valid():
    with tempfile.TemporaryDirectory() as tmp:
        runner, _ = _runner(tmp)
        ideas = runner.run_business(
            static_context="### HARD CONSTRAINTS ###\n- solo: true",
            evergreen_context="### EVERGREEN ###\n(none)",
            curated=[{"id": "x", "why": "pain point in tactile sensing", "evergreen": False}],
        )
        assert isinstance(ideas, list) and ideas, "expected a non-empty list of ideas"
        fc = score_functional_correctness(ideas)
        assert fc["pass"], f"ideas missing required fields: {fc['detail']}"


def test_business_agent_rejects_banned_patterns():
    """If the model ever emits a banned idea, the constraint check must catch it."""
    bad = OfflineResponder(lambda s, u, t: '[{"id":"b","title":"New robot",'
                                           '"description":"Build a new humanoid robot from scratch.",'
                                           '"revenue_path":"sell hardware","adjacent_tech_transfer":"n/a",'
                                           '"first_motion":"n/a"}]')
    with tempfile.TemporaryDirectory() as tmp:
        runner, _ = _runner(tmp, responder=bad)
        ideas = runner.run_business("c", "e", [{"id": "x"}])
        cc = score_constraint_compliance(ideas)
        assert not cc["pass"], "banned 'build a new robot' idea should fail constraint check"


def test_source_skill_runs_for_real_offline():
    """The skill loader path must produce a record dict (no fake 'simulate' output)."""
    with tempfile.TemporaryDirectory() as tmp:
        runner, bus = _runner(tmp)
        uri = bus.write_raw({"source": "GrantsGov", "title": "[DOD] Manipulation",
                             "summary": "open funding", "url": "https://x", "category": "grant"})
        rec = runner.run_source_skill("grant", uri)
        assert isinstance(rec, dict)
        assert "summary" in rec and "url" in rec


def test_curation_handles_empty():
    with tempfile.TemporaryDirectory() as tmp:
        runner, _ = _runner(tmp)
        assert runner.run_curation([]) == []


def test_extract_json_array_and_object():
    assert _extract_json('garbage [1,2,3] trailing', "array") == [1, 2, 3]
    assert _extract_json('```json\n{"a":1}\n```', "object") == {"a": 1}
    with pytest.raises(ValueError):
        _extract_json("no json here", "object")
