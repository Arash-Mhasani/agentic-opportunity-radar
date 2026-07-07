"""
Harness unit tests — the deterministic core ("shift intelligence left" means this is
all testable without a model). Covers: Elo math, skill-loader parsing + conformance,
YC robotics/recency filter, message bus, MCP HITL gate + read-only enforcement, DAG
ordering + cycle detection, Denial-of-Wallet breaker, and evergreen promotion.
"""
import os
import datetime
import tempfile

import pytest

from memory import elo
from memory.memory_manager import MemoryManager
from skills.skill_loader import SkillRegistry, parse_skill
from radars import yc_startup_radar as yc
from core.message_bus import MessageBus
from core.dag import DAG
from config import RadarConfig, default_mcp_registry
from connectors.mcp_client import MCPClient, deny_all_confirm
from connectors.notion_connector import NotionConnector
from observability.tracing import Budget, Tracer, CircuitBreakerTripped

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(ROOT, "skills")


# ── Elo ──────────────────────────────────────────────────────────────────────
def test_elo_expected_score_symmetry():
    assert abs(elo.expected_score(1200, 1200) - 0.5) < 1e-9
    assert elo.expected_score(1400, 1200) > 0.5

def test_elo_update_conserves_points():
    ra, rb = elo.update_pair(1200, 1200, True, k=32)
    assert abs((ra + rb) - 2400) < 1e-6
    assert ra > rb

def test_elo_tournament_orders_by_strength():
    ideas = [{"id": "weak"}, {"id": "strong"}, {"id": "mid"}]
    rank = {"strong": 3, "mid": 2, "weak": 1}
    standings = elo.run_tournament(ideas, lambda a, b: rank[a["id"]] > rank[b["id"]], rounds=2)
    assert [s["id"] for s in standings] == ["strong", "mid", "weak"]


# ── skill loader ──────────────────────────────────────────────────────────────
def test_all_skills_parse_and_are_conformant():
    reg = SkillRegistry(SKILLS_DIR)
    assert len(reg.all()) == 6, "expected exactly 6 skills (youtube_search deleted)"
    report = reg.conformance_report()
    bad = [c for c in report if c["warnings"]]
    assert not bad, f"non-conformant skills: {bad}"

def test_youtube_search_is_deleted():
    reg = SkillRegistry(SKILLS_DIR)
    names = {s.name for s in reg.all()}
    assert "youtube_search" not in names and "youtube-search" not in names

def test_skill_routing_table():
    reg = SkillRegistry(SKILLS_DIR)
    assert reg.for_category("paper").name == "summarize-academic-paper"
    assert reg.for_category("video").name == "analyze-youtube-transcript"
    assert reg.for_category("unknown").name == "analyze-market-signal"  # default

def test_nonconformant_skill_is_flagged(tmp_path):
    d = tmp_path / "bad_skill"
    d.mkdir()
    (d / "SKILL.md").write_text('---\nname: BadName_NotKebab\ndescription: ""\n---\nbody\n')
    spec = parse_skill(str(d / "SKILL.md"))
    assert spec.warnings, "a non-kebab, no-description, no-version skill must produce warnings"


# ── YC radar filter ───────────────────────────────────────────────────────────
def test_batch_year_parsing():
    assert yc.batch_year("Winter 2024") == 2024
    assert yc.batch_year("S25") == 2025
    assert yc.batch_year("W24") == 2024
    assert yc.batch_year(None) is None

def test_yc_filter_robotics_and_recency():
    now = datetime.date(2026, 6, 1)
    companies = [
        {"name": "GripAI", "oneLiner": "humanoid manipulation software", "batch": "W25", "tags": ["Robotics"]},
        {"name": "OldBot", "oneLiner": "robotics", "batch": "W19"},                 # too old
        {"name": "FinTechCo", "oneLiner": "payments api", "batch": "S25"},          # not robotics
        {"name": "DroneX", "oneLiner": "autonomous drone inspection", "batch": "Summer 2025"},
    ]
    out = yc.filter_robotics_recent(companies, years=2, now=now)
    names = {c["name"] for c in out}
    assert names == {"GripAI", "DroneX"}

def test_yc_to_signals_shape():
    sigs = yc.fetch_yc_robotics_recent(years=2, companies=[
        {"name": "GripAI", "oneLiner": "robot manipulation", "batch": "W25", "website": "https://g.ai"}])
    assert sigs and sigs[0]["category"] == "startup" and sigs[0]["source"] == "YCombinator"


# ── message bus ───────────────────────────────────────────────────────────────
def test_message_bus_roundtrip_and_compression():
    with tempfile.TemporaryDirectory() as tmp:
        bus = MessageBus(os.path.join(tmp, "bus"))
        uri = bus.write_raw({"title": "T", "summary": "long " * 1000, "category": "paper"})
        assert bus.read(uri)["title"] == "T"
        bus.write_compressed(uri, {"source_type": "paper", "summary": "short", "url": "u"})
        recs = bus.list_compressed()
        assert len(recs) == 1 and recs[0]["summary"] == "short"

def test_message_bus_blocks_path_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        bus = MessageBus(os.path.join(tmp, "bus"))
        with pytest.raises(ValueError):
            bus.read("file:///etc/passwd")


# ── MCP HITL gate + read-only enforcement ─────────────────────────────────────
def test_mcp_readonly_blocks_writes():
    spec = default_mcp_registry()["notion"]
    spec.read_only = True
    client = MCPClient(spec, require_confirmation=True)
    res = client.call_tool("notion-create-pages", {"x": 1})
    assert not res.ok and "read-only" in (res.skipped_reason or "")

def test_mcp_write_denied_without_confirmation():
    spec = default_mcp_registry()["notion"]
    spec.read_only = False                       # allow writes at server level
    client = MCPClient(spec, confirm_fn=deny_all_confirm, require_confirmation=True)
    res = client.call_tool("notion-create-pages", {"x": 1})
    assert not res.ok and "not confirmed" in (res.skipped_reason or "")

def test_mcp_write_allowed_when_confirmed_but_degrades_without_sdk():
    spec = default_mcp_registry()["notion"]
    spec.read_only = False
    client = MCPClient(spec, confirm_fn=lambda s, t, a: True, require_confirmation=True)
    res = client.call_tool("notion-create-pages", {"x": 1})
    # gate passes; without the mcp SDK/creds it degrades to 'unavailable', never crashes
    assert not res.ok and res.skipped_reason and "unavailable" in res.skipped_reason

def test_notion_connector_read_is_not_gated():
    spec = default_mcp_registry()["notion"]
    conn = NotionConnector(spec, require_confirmation=True)
    res = conn.search("q")     # read → not a write tool → only blocked by availability
    assert "unavailable" in (res.skipped_reason or "")


# ── DAG ───────────────────────────────────────────────────────────────────────
def test_dag_topological_order():
    order = []
    dag = DAG()
    dag.add("c", lambda ctx: order.append("c"), deps=["b"])
    dag.add("a", lambda ctx: order.append("a"))
    dag.add("b", lambda ctx: order.append("b"), deps=["a"])
    dag.run({})
    assert order == ["a", "b", "c"]

def test_dag_detects_cycles():
    dag = DAG()
    dag.add("a", lambda ctx: None, deps=["b"])
    dag.add("b", lambda ctx: None, deps=["a"])
    with pytest.raises(ValueError, match="cycle"):
        dag.run({})


# ── Denial-of-Wallet breaker ──────────────────────────────────────────────────
def test_budget_trips_on_calls():
    cfg = RadarConfig(); cfg.max_model_calls = 3
    b = Budget(cfg)
    with pytest.raises(CircuitBreakerTripped):
        for _ in range(10):
            b.charge_call("n")
    assert b.tripped

def test_budget_trips_on_usd():
    cfg = RadarConfig(); cfg.max_usd_budget = 1.0
    b = Budget(cfg)
    with pytest.raises(CircuitBreakerTripped):
        b.charge_usd(5.0, "n")


# ── tracing + evergreen promotion ─────────────────────────────────────────────
def test_tracer_records_spans():
    with tempfile.TemporaryDirectory() as tmp:
        tr = Tracer(os.path.join(tmp, "t.db"), "cycleX")
        with tr.span("outer", kind="node"):
            with tr.span("inner", kind="model"):
                pass
        spans = tr.spans_for_cycle("cycleX")
        assert len(spans) == 2
        inner = [s for s in spans if s["name"] == "inner"][0]
        assert inner["parent_id"] is not None and inner["status"] == "ok"

def test_evergreen_promotion_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        mm = MemoryManager(os.path.join(tmp, "m.db"),
                           os.path.join(ROOT, "memory", "static_memory.json"))
        url = "https://example.com/foundational"
        mm.mark_url_processed(url, "arXiv", "a canonical benchmark", is_evergreen=False)
        assert "(none yet)" in mm.get_evergreen_signals()
        mm.promote_evergreen(url)                       # the previously-missing step
        ever = mm.get_evergreen_signals()
        assert "canonical benchmark" in ever
