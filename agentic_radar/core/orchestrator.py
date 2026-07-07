"""
Orchestrator — the harness that runs one daily cycle as an explicit DAG.

Flow:
  fetch (niche pollers + YC robotics + your YouTube playlist + your Notion read)
    -> message bus (raw)
    -> source skills (REAL skill execution -> compressed records)
    -> curation (filter + evergreen promotion)
    -> business (Opus + extended thinking)
    -> deterministic Elo tournament (swapped-position, model-diverse judge)
    -> memory persistence
    -> report (+ HITL-gated write to your Notion)

Everything is wrapped in observability spans and a Denial-of-Wallet budget breaker.
The research-signal floor (>= min_research_signals) is enforced before we conclude.
"""
from __future__ import annotations

import os
import sys
import json
import uuid
import logging
import datetime
import concurrent.futures
from typing import Any, Dict, List

# allow running as a module or a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CONFIG, default_mcp_registry
from observability.tracing import Tracer, Budget, CircuitBreakerTripped
from agents.llm_client import LLMClient
from agents.agent_runners import AgentRunner
from agents.capability_profiles import PROFILES
from core.message_bus import MessageBus
from core.dag import DAG
from memory.memory_manager import MemoryManager
from memory import elo
from skills.data_fetchers import DataFetcher
from radars.yc_startup_radar import fetch_yc_robotics_recent
from connectors.notion_connector import NotionConnector
from connectors.youtube_connector import YouTubeConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("radar.orchestrator")

RESEARCH_CATEGORIES = {"paper"}  # what counts toward the research-signal floor


class Orchestrator:
    def __init__(self, config=CONFIG, confirm_fn=None):
        self.config = config
        self.cycle_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]
        self.tracer = Tracer(config.db_path, self.cycle_id)
        self.budget = Budget(config, self.tracer)
        self.llm = LLMClient(config, budget=self.budget, tracer=self.tracer)
        self.bus = MessageBus(config.message_bus_dir)
        self.memory = MemoryManager(config.db_path, config.static_memory_path)
        self.agents = AgentRunner(self.llm, config.skills_dir, self.bus, tracer=self.tracer)
        self.fetcher = DataFetcher()
        registry = default_mcp_registry()
        # Day-5 Zero-Trust: a hybrid Policy Server intercepts every tool call.
        self.policy_server = None
        if config.enable_policy_server:
            from governance.policy_server import PolicyServer
            self.policy_server = PolicyServer(config=config, llm_client=self.llm)
        gov = dict(policy_server=self.policy_server, role=config.role, env=config.environment)
        self.notion = NotionConnector(registry["notion"], confirm_fn=confirm_fn,
                                      require_confirmation=config.require_write_confirmation, **gov)
        self.youtube = YouTubeConnector(registry["youtube"], **gov)

    # ── DAG nodes ─────────────────────────────────────────────────────────────
    def _node_fetch(self, ctx) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        yt_playlist = os.environ.get("YOUTUBE_PLAYLIST_ID", "")
        tasks = {
            "arxiv": lambda: self.fetcher.fetch_arxiv_papers(
                ["cs.RO", "cs.AI", "cs.CV", "cs.LG"],
                ["vision language action", "dexterous manipulation", "diffusion policy", "sim-to-real"]),
            "semantic": lambda: self.fetcher.fetch_semantic_scholar(["vision language action robotics"]),
            "grants": lambda: self.fetcher.fetch_grant_solicitations(["robotics", "autonomous systems"]),
            "hn": lambda: self.fetcher.fetch_hackernews(["humanoid robot", "robot foundation model"]),
            "reddit": lambda: self.fetcher.fetch_reddit_posts(["isaac sim", "diffusion policy"]),
            "sec": lambda: self.fetcher.fetch_sec_filings_robotics(),
            "yc": lambda: fetch_yc_robotics_recent(years=2),
            "youtube": lambda: self.youtube.fetch_playlist_signals(yt_playlist) if yt_playlist else [],
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(fn): name for name, fn in tasks.items()}
            for fut in concurrent.futures.as_completed(futs):
                name = futs[fut]
                try:
                    res = fut.result() or []
                    signals.extend(res)
                    log.info("fetch[%s]: %d signals", name, len(res))
                except Exception as e:
                    log.error("fetch[%s] failed: %s", name, e)
        # optional: pull foundational context from YOUR Notion (read-only)
        if self.notion.available():
            try:
                r = self.notion.search("robotics wedge thesis", page_size=5)
                if r.ok and r.content:
                    signals.append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "source": "notion", "title": "Notion: prior thesis context",
                                    "url": "notion://search", "summary": str(r.content)[:500],
                                    "category": "market"})
            except Exception as e:
                log.warning("Notion read failed: %s", e)
        ctx["raw_signals"] = signals
        return signals

    def _node_source(self, ctx) -> List[Dict[str, Any]]:
        raw = ctx.get("raw_signals", [])
        records: List[Dict[str, Any]] = []
        for sig in raw:
            url = sig.get("url") or f"hash:{hash(sig.get('title'))}"
            if self.memory.is_url_processed(url):
                continue
            uri = self.bus.write_raw(sig)
            try:
                rec = self.agents.run_source_skill(sig.get("category", "other"), uri)
            except CircuitBreakerTripped:
                raise
            except Exception as e:
                log.warning("source skill failed for %s: %s", url, e)
                rec = {"source_type": sig.get("category"), "title": sig.get("title"),
                       "summary": sig.get("summary", "")[:300], "url": url,
                       "pain_point": None, "evergreen_candidate": False}
            rec.setdefault("url", url)
            rec["_category"] = sig.get("category")
            self.bus.write_compressed(uri, rec)
            self.memory.mark_url_processed(url, sig.get("source", "?"),
                                           rec.get("summary", "")[:500], is_evergreen=False)
            records.append(rec)
        ctx["records"] = records
        return records

    def _node_curation(self, ctx) -> List[Dict[str, Any]]:
        records = ctx.get("records", [])
        fb = ctx.get("feedback", {})
        resource_fb = "\n".join(fb.get("resource_quality", []))
        curated = self.agents.run_curation(records, feedback=resource_fb)
        # evergreen promotion — the missing step. Flagged records get is_evergreen=1.
        by_id = {r.get("title"): r for r in records}
        promoted = 0
        for c in curated:
            if c.get("evergreen"):
                rec = by_id.get(c.get("id")) or {}
                if rec.get("url"):
                    self.memory.promote_evergreen(rec["url"])
                    promoted += 1
        log.info("curation kept %d; promoted %d to evergreen.", len(curated), promoted)
        ctx["curated"] = curated
        return curated

    def _node_business(self, ctx) -> List[Dict[str, Any]]:
        fb = ctx.get("feedback", {})
        ideas = self.agents.run_business(
            static_context=self.memory.get_static_context(),
            evergreen_context=self.memory.get_evergreen_signals(limit=20),
            curated=ctx.get("curated", []),
            feedback="\n".join(fb.get("business_logic", [])),
        )
        ctx["new_ideas"] = ideas
        return ideas

    def _node_tournament(self, ctx) -> List[Dict[str, Any]]:
        new_ideas = ctx.get("new_ideas", [])
        incumbents = self.memory.get_top_ideas(limit=6)
        field = (incumbents + new_ideas)
        # de-dup by id/title, keep existing elo for incumbents
        seen, pool = set(), []
        for it in field:
            key = str(it.get("id") or it.get("title"))
            if key in seen:
                continue
            seen.add(key)
            it.setdefault("id", key)
            pool.append(it)
        if not pool:
            ctx["standings"] = []
            return []
        constraints = self.memory.get_static_context()
        judge = lambda a, b: self.agents.judge_match(a, b, constraints)
        standings = elo.run_tournament(pool, judge, k=self.config.elo_k_factor,
                                       default_elo=self.config.elo_default, rounds=1)
        # persist
        for idea in standings:
            self.memory.save_idea(idea["id"], idea.get("title", "Untitled"), idea.get("description", ""))
            self.memory.update_elo(idea["id"], idea["elo_score"])
        ctx["standings"] = standings
        return standings

    # ── run ───────────────────────────────────────────────────────────────────
    def run(self) -> Dict[str, Any]:
        log.info("=== Agentic Opportunity Radar cycle %s ===", self.cycle_id)
        ctx: Dict[str, Any] = {"feedback": self.memory.get_unprocessed_feedback()}
        self.memory.prune_memory(stale_days=7)

        dag = DAG(tracer=self.tracer)
        (dag.add("fetch", self._node_fetch)
            .add("source", self._node_source, deps=["fetch"])
            .add("curation", self._node_curation, deps=["source"])
            .add("business", self._node_business, deps=["curation"])
            .add("tournament", self._node_tournament, deps=["business"]))

        result: Dict[str, Any] = {"cycle_id": self.cycle_id}
        try:
            with self.tracer.span("pipeline", kind="node"):
                ctx = dag.run(ctx)
            # research-signal floor (deterministic guardrail)
            n_research = sum(1 for r in ctx.get("records", []) if r.get("_category") in RESEARCH_CATEGORIES)
            result["research_signals"] = n_research
            result["floor_met"] = n_research >= self.config.min_research_signals
            if not result["floor_met"]:
                log.warning("research-signal floor NOT met (%d < %d): treat conclusions as low-confidence.",
                            n_research, self.config.min_research_signals)
            top = self.memory.get_top_ideas(limit=3)
            result["top_ideas"] = top
            self._emit_report(top, result)
        except CircuitBreakerTripped as e:
            log.error("CIRCUIT BREAKER tripped — freezing cycle for forensics: %s", e)
            result["circuit_breaker"] = str(e)
        finally:
            result["budget"] = self.budget.snapshot()
            log.info("budget: %s", result["budget"])
        return result

    def _emit_report(self, top: List[Dict[str, Any]], result: Dict[str, Any]):
        lines = [f"# Opportunity Radar — {self.cycle_id}", "",
                 f"Research signals this cycle: {result.get('research_signals',0)} "
                 f"(floor {self.config.min_research_signals} "
                 f"{'met' if result.get('floor_met') else 'NOT met → low confidence'})", ""]
        for i, w in enumerate(top, 1):
            lines.append(f"## {i}. {w['title']}  (Elo {w['elo_score']:.0f})")
            lines.append(w.get("description", ""))
            lines.append("")
        report_md = "\n".join(lines)
        result["report_md"] = report_md
        for ln in lines:
            log.info(ln)
        # write to YOUR Notion (HITL-gated). parent page comes from env.
        parent = os.environ.get("NOTION_PARENT_PAGE_ID", "")
        if parent and self.notion.available():
            res = self.notion.write_report(parent, f"Opportunity Radar {self.cycle_id}", report_md)
            if res.ok:
                log.info("Wrote report to Notion.")
            else:
                log.info("Notion write not completed: %s", res.skipped_reason or res.error)


if __name__ == "__main__":
    # interactive confirmer so a human approves any Notion write
    from connectors.mcp_client import console_confirm
    Orchestrator(confirm_fn=console_confirm).run()
