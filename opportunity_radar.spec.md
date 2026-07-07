# Opportunity Radar — Technical Design Specification

> Day-5 Spec-Driven Development: this `specs/` folder is the **source of truth** ("the
> Architectural North Star"). Code is regenerable from it. Narrative lives here in
> Markdown; structured data contracts live in `schemas.yaml`; guaranteed behaviors live
> as Gherkin in `scenarios.feature`. Keep this in sync with the code — drift here is
> where hallucination starts.

## Background — the "Why"

A solo founder needs a daily, high-conviction shortlist of **$1M+/yr software/data/
consulting opportunities in robotics** that one low-capital person can start in ≤20
hrs/week. Implementation is not the bottleneck; *judgment under constraints* is. So the
system is built as `Agent = Model + Harness`: the model supplies judgment, the harness
supplies tools, memory, determinism, observability, and governance.

## Requirements

1. Ingest robotics signals daily from niche pollers, a YC robotics radar, the founder's
   own YouTube playlist, and the founder's own Notion — and rank opportunities by
   **market potential, never skill-proximity**.
2. Never propose building a foundation model, a robot, or any hardware product.
3. Every external write (to Notion) passes a Human-in-the-Loop gate **and** a Policy
   Server (structural + semantic). No secret is ever hardcoded.
4. Every run is observable (OpenTelemetry-style spans) and bounded by a Denial-of-Wallet
   circuit breaker.
5. Determinism (Elo, the research-signal floor, dedup, constraint checks) lives in
   tested code, not in prompts ("shift intelligence left").

## Full technical design

- **Orchestration**: an explicit DAG (`core/dag.py`) — fetch → source → curation →
  business → tournament — with file-bus state passing (`core/message_bus.py`) and
  per-node capability profiles (`agents/capability_profiles.py`).
- **Source layer**: a real skill loader (`skills/skill_loader.py`) injects the relevant
  `SKILL.md` into the system prompt and gives the model a `read_bus_record` tool;
  outputs the `compressed_record` schema.
- **Reasoning**: business node uses `claude-opus-4-8` + extended thinking; curation/
  source use `claude-sonnet-4-6`; cheap classification uses `claude-haiku-4-5`; an
  optional Gemini judge adds model diversity to the Elo tournament.
- **Ranking**: deterministic Elo (`memory/elo.py`) with a position-swapped judge.
- **Memory**: SQLite (`memory/memory_manager.py`) — ideas+Elo, signal memory with
  evergreen promotion; `static_memory.json` holds the always-on constraints.
- **Governance (Day-5)**: `governance/policy_server.py` (structural + semantic gating)
  and `governance/context_resolver.py` ([[placeholder]] resolution + PII masking),
  wired into `connectors/mcp_client.py` so every tool call is intercepted.
- **Connectors (consume, don't build)**: official Notion MCP, `yt-mcp`, GitHub MCP.
- **Observability**: `observability/tracing.py` (spans → SQLite) + Denial-of-Wallet
  budget/breaker.
- **Evaluation**: `evals/run_evals.py` — eval-as-unit-test (deterministic regressions)
  **plus** a baseline/tolerance-band drift gate (behavioural drift), over the 7
  evaluation dimensions.

### Data contracts
See `schemas.yaml` for the `signal`, `compressed_record`, `opportunity`,
`policy_decision`, and `constraints` schemas.

### Tools & libraries (pin versions — Day-5: agents fall back to stale training data)
- Python ≥ 3.10 (built on 3.12)
- `anthropic` ≥ 0.40, `mcp` ≥ 1.2, `anyio` ≥ 4.0, `pyyaml` ≥ 6.0
- `requests` ≥ 2.31, `feedparser` ≥ 6.0
- `google-generativeai` ≥ 0.8 (optional judge)
- `streamlit` ≥ 1.30, `pandas` ≥ 2.0 (dashboard); `pytest` ≥ 8.0 (dev)

## Scenarios
The guaranteed behaviors are specified as BDD/Gherkin in `scenarios.feature`, each
linked to the automated check that enforces it. If a scenario has no green check, it is
a hope, not a guarantee.

## Execution modes (Day-5)
- **Architect** (project generation): propose structure + stack first; never YOLO.
- **Builder** (features): match existing style; confirm multi-file diffs.
- **Forensic Specialist** (bug-fix): reproduce with a failing test first; fix only the
  root cause; use evidence, not symptoms.
- **Author** (docs): keep `README.md`, `docs/`, and this spec in sync — docs are truth.
