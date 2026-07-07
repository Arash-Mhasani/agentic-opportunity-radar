# Agentic Opportunity Radar

A once-daily, deep-reasoning pipeline that turns humanoid/robotics signals into
specific **$1M+/yr entrepreneurial** opportunities for a **solo founder**. Rebuilt
from a monolithic script into a production-standard agentic system: `Agent = Model + Harness`.

This README is honest about what changed and why, mapped to the three Google
whitepaper decks (Day-2 Tools/Interoperability, Day-3 Skills, Day-4 Security/Eval).

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env                                  # fill in only the keys you have

# Runs with ZERO keys (deterministic offline responder) — proves the harness works:
RADAR_OFFLINE=1 python agentic_radar/core/orchestrator.py

# The proof-it-isn't-broken gates (no keys, no network):
python -m pytest agentic_radar/tests -q
python agentic_radar/evals/run_evals.py --offline

# Live run + review canvas (needs ANTHROPIC_API_KEY; Notion/YouTube optional):
python agentic_radar/core/orchestrator.py
streamlit run agentic_radar/core/dashboard.py
```

## Architecture (`Agent = Model + Harness`)

```
                         ┌─────────────────── observability/ ───────────────────┐
                         │  tracing.py: OTel-style spans → SQLite trace_spans    │
                         │  budget: Denial-of-Wallet circuit breaker             │
                         └───────────────────────────────────────────────────────┘
 fetch ──► message bus ──► source skills ──► curation ──► business ──► Elo tournament
 (niche    (raw record)    (REAL skill       (+evergreen   (Opus +     (deterministic +
  pollers                   loader +          promotion)    thinking)   swapped diverse
  + YC +                    file-read tool)                             judge)
  your YT +
  your Notion)                                                   │
                                                                 ▼
                                          report ──► HITL-gated write to YOUR Notion
```

- **Model** (swappable, `config.py`): `claude-opus-4-8` (business), `claude-sonnet-4-6`
  (curation/source), `claude-haiku-4-5` (cheap), Gemini (optional diverse judge).
- **Harness**: MCP tools (`connectors/`), Agent Skills (`skills/`), DAG + file bus
  (`core/`), capability profiles (`agents/capability_profiles.py`), observability
  (`observability/`), evals (`evals/`), and the always-on guardrails in `AGENTS.md`.

## What changed vs the migrated code (and why)

| Fix | Whitepaper basis |
|---|---|
| **Real skill loader** — parses `SKILL.md`, injects the body into the system prompt, gives the model a real `read_bus_record` tool. The old loader only *said* "use skill X on file://Y" and faked the output. | Day-3 §3 skills are executable, not cosmetic |
| **Deterministic Elo restored** — Elo math + the 100-research-signal floor are pure Python again (`memory/elo.py`); the migration had handed ranking to a single LLM call. | Day-3 sl.41 "shift intelligence left" |
| **MCP consumption** — GitHub / YouTube / Notion are consumed via MCP, not hand-rolled. Env-var creds, read-only default, HITL gate on writes. | Day-2 sl.16 consume>build, read-only, HITL |
| **Observability** — every node/model/tool opens a span persisted to SQLite; the dashboard's formerly-empty "Agent Traces" tab now renders the real Vibe Trajectory. | Day-4 Pillars 6 & 7 |
| **Denial-of-Wallet breaker** — every loop is bounded by call/USD budgets; tripping freezes the cycle for forensics. | Day-4 sl.25 |
| **Eval suite** — `run_evals.py` covers the 7 dimensions, 5 patterns, and all 4 failure modes (trigger, execution, regression/adversarial, DoW). Offline mode needs no key. | Day-3 sl.19-20, Day-4 sl.30 |
| **Skills re-authored to standard** — kebab-case gerund names, descriptions with `when NOT to use`, pinned `version`, `references/` for progressive disclosure. The duplicate `youtube_search` was deleted. | Day-3 sl.46-48, "one skill, one job" |
| **`AGENTS.md`** — always-on facts (constraints, safety, model map) live here, not in a skill that may not trigger (~56% miss rate per Vercel + Day-3 sl.19). | Vercel ref 8 / Day-3 sl.19 |
| **Evergreen promotion** — the curation node now sets `is_evergreen=1`; the dashboard "Remove" button governs real data instead of an empty set. | — |
| **Summarize-before-synthesize** — the file bus stores compressed records; raw 50k-token transcripts never re-enter context. (We do NOT claim "memory flushing" — the API is already stateless per call.) | Chroma context-rot ref 13 |
| **Correct model IDs** — `claude-opus-4-8`, not `claude-4-8-opus`. | — |

## Reuse audit (consume, don't build)

- **Consumed via MCP / vetted servers**: GitHub MCP, `yt-mcp` (YouTube), official Notion
  MCP. `data_fetchers.py` shrank to genuinely-niche free pollers (arXiv, Semantic
  Scholar, Grants.gov, HackerNews, Reddit, SEC).
- **Kept custom** (no published equivalent): the six robotics-specific analysis skills.
- **Reuse when extending**: `anthropics/skills` (docx/pdf/xlsx/pptx, mcp-builder,
  skill-creator), `google/agents-cli` (eval + observability), `stripe/ai` (when billing).

## Layout

```
agentic_radar/
  AGENTS.md            always-on facts for any coding agent (and humans)
  config.py            model map, env loading, MCP registry — no hardcoded secrets
  core/                orchestrator (DAG), dag engine, message bus, dashboard
  agents/              llm_client (offline-capable), agent_runners, prompts, capability_profiles
  skills/              skill_loader + 6 standard SKILL.md skills + niche data_fetchers
  connectors/          mcp_client (HITL gate), notion_connector, youtube_connector
  radars/              yc_startup_radar (robotics + founded-last-2-years)
  observability/       tracing (spans→SQLite) + Denial-of-Wallet budget/breaker
  memory/              memory_manager (+ evergreen promotion), elo, static_memory.json
  evals/               run_evals (offline + LLM-judge), rubric (7 dims), golden_dataset
  tests/               offline test suite (no keys, no network)
```

## Notes / limits

- The system never handles your credentials directly — it reads them from environment
  variables and degrades gracefully when they're absent. Notion writes always pass the
  Human-In-The-Loop gate.
- X/Twitter has no compliant first-party MCP; that source is intentionally a no-op.
- The research-signal floor (default 100 papers) is a confidence gate: below it, the
  cycle still completes but flags its conclusions as low-confidence.
