"""
Review canvas (Streamlit).

Rewritten so the "Agent Traces" tab is no longer an empty placeholder: it reads the
real OpenTelemetry-style spans from `trace_spans` (Day-4 Pillar 6, Vibe Trajectory).
Other tabs: ranked opportunities, evergreen memory (with a working remove button that
governs REAL data now that promotion is wired), the Denial-of-Wallet budget snapshot
per cycle, and a vibe-diff between two cycles.

Run:  streamlit run agentic_radar/core/dashboard.py
"""
from __future__ import annotations

import os
import sys
import json
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CONFIG
from memory.memory_manager import MemoryManager

try:
    import streamlit as st
    import pandas as pd
except ImportError:
    st = None


def _conn():
    return sqlite3.connect(CONFIG.db_path)


def _cycles():
    try:
        with _conn() as c:
            rows = c.execute("SELECT DISTINCT cycle_id FROM trace_spans ORDER BY cycle_id DESC").fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _spans(cycle_id):
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM trace_spans WHERE cycle_id=? ORDER BY started_at", (cycle_id,)).fetchall()
    return [dict(r) for r in rows]


def _budget_from_spans(spans):
    """Reconstruct the per-cycle budget snapshot from model/tool spans."""
    model_calls = sum(1 for s in spans if s["kind"] == "model")
    tools = 0
    for s in spans:
        try:
            tools += int(json.loads(s.get("attributes") or "{}").get("tool_iterations", 0))
        except Exception:
            pass
    tripped = any(s["status"] == "tripped" for s in spans)
    return {"model_spans": model_calls, "tool_iterations": tools, "tripped": tripped}


def main():
    if st is None:
        print("Streamlit not installed. `pip install streamlit pandas` to run the dashboard.")
        return

    st.set_page_config(page_title="Opportunity Radar", layout="wide")
    st.title("🛰️ Agentic Opportunity Radar")
    mem = MemoryManager(CONFIG.db_path, CONFIG.static_memory_path)

    tab_ideas, tab_trace, tab_ever, tab_budget, tab_diff = st.tabs(
        ["💡 Opportunities", "🧠 Agent Traces", "🌲 Evergreen", "💸 Budget", "🔬 Vibe-diff"])

    # ── opportunities ─────────────────────────────────────────────────────────
    with tab_ideas:
        ideas = mem.get_top_ideas(limit=25)
        if not ideas:
            st.info("No ideas yet. Run a pipeline cycle: `python agentic_radar/core/orchestrator.py`")
        else:
            for i, idea in enumerate(ideas, 1):
                st.markdown(f"**{i}. {idea['title']}** — Elo `{idea['elo_score']:.0f}`")
                st.caption(idea.get("description", ""))

    # ── agent traces (the formerly-empty tab, now real) ───────────────────────
    with tab_trace:
        cycles = _cycles()
        if not cycles:
            st.info("No traces yet. Spans are written to `trace_spans` on each cycle.")
        else:
            cid = st.selectbox("Cycle", cycles, key="trace_cycle")
            spans = _spans(cid)
            st.caption(f"{len(spans)} spans in this Vibe Trajectory.")
            rows = []
            for s in spans:
                attrs = {}
                try:
                    attrs = json.loads(s.get("attributes") or "{}")
                except Exception:
                    pass
                rows.append({
                    "name": s["name"], "kind": s["kind"], "status": s["status"],
                    "ms": round(s.get("duration_ms") or 0, 1),
                    "attributes": ", ".join(f"{k}={v}" for k, v in attrs.items() if k != "error"),
                    "error": attrs.get("error", ""),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            errs = [r for r in rows if r["status"] != "ok"]
            if errs:
                st.error(f"{len(errs)} non-ok span(s) — inspect for trajectory/self-repair failures.")

    # ── evergreen memory (remove button governs REAL data now) ────────────────
    with tab_ever:
        st.caption("Foundational signals promoted by the curation node (is_evergreen=1).")
        with _conn() as c:
            c.row_factory = sqlite3.Row
            ever = c.execute("SELECT url_hash, source, summary FROM signal_memory "
                             "WHERE is_evergreen=1 ORDER BY last_seen DESC").fetchall()
        if not ever:
            st.info("No evergreen signals yet.")
        for row in ever:
            col1, col2 = st.columns([8, 1])
            col1.markdown(f"[{(row['source'] or '?').upper()}] {row['summary']}")
            if col2.button("Remove", key=f"rm_{row['url_hash']}"):
                mem.remove_evergreen(row["url_hash"])
                st.rerun()

    # ── budget snapshot ───────────────────────────────────────────────────────
    with tab_budget:
        cycles = _cycles()
        if not cycles:
            st.info("No cycles yet.")
        else:
            cid = st.selectbox("Cycle", cycles, key="budget_cycle")
            snap = _budget_from_spans(_spans(cid))
            c1, c2, c3 = st.columns(3)
            c1.metric("Model spans", snap["model_spans"])
            c2.metric("Tool iterations", snap["tool_iterations"])
            c3.metric("Circuit breaker", "TRIPPED" if snap["tripped"] else "ok")

    # ── vibe-diff between two cycles ──────────────────────────────────────────
    with tab_diff:
        cycles = _cycles()
        if len(cycles) < 2:
            st.info("Need at least two cycles to diff.")
        else:
            a = st.selectbox("Cycle A", cycles, index=1, key="diff_a")
            b = st.selectbox("Cycle B", cycles, index=0, key="diff_b")
            na = {s["name"] for s in _spans(a)}
            nb = {s["name"] for s in _spans(b)}
            st.write("Only in A:", sorted(na - nb) or "—")
            st.write("Only in B:", sorted(nb - na) or "—")
            st.write("Shared nodes:", len(na & nb))


if __name__ == "__main__":
    main()
