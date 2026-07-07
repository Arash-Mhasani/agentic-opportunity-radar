# Agentic Opportunity Radar

**Capstone submission — Kaggle × Google "AI Agents: Intensive Vibe Coding" course.**

A once-daily, multi-agent pipeline that scans the robotics/humanoid ecosystem (arXiv,
Semantic Scholar, Grants.gov, Hacker News, SEC EDGAR, Y Combinator, optionally YouTube
and Notion) and turns raw signals into ranked, founder-ready business opportunities —
scored by an Elo tournament with a heterogeneous LLM judge.

Built as `Agent = Model + Harness`: the models are swappable config
(Claude Fable 5 for deep business reasoning, Sonnet 4.6 for curation/skills,
Haiku 4.5 for classification, Gemini as the diversity judge); the harness is the
production scaffolding this repo is really about.

## Course concepts demonstrated

| Concept | Where in this repo |
|---|---|
| **Agent orchestration** (DAG, multi-agent) | `agentic_radar/core/orchestrator.py` — fetch → source skills → curation → business reasoning → Elo tournament → report, with cycle detection and per-node tracing |
| **Tools & interoperability** (MCP, external APIs) | `agentic_radar/connectors/` — official Notion MCP + yt-mcp via stdio, GitHub MCP via streamable-http; 7 public data APIs in `agentic_radar/skills/data_fetchers.py` |
| **Agent-to-agent communication** | `agentic_radar/message_bus/` (created at runtime) — file-based bus of raw + compressed records between the source, curation, and business agents, with path-traversal protection |
| **Memory engineering** | `agentic_radar/memory/` — SQLite dynamic memory (signal dedup, idea Elo history, evergreen promotion) + static JSON thesis memory |
| **Evaluation** | `agentic_radar/evals/` — eval-as-unit-test CI gate (8 checks incl. the 4 failure modes), behavioural-drift gate vs. a baseline, online LLM-judge rubric; 38-test pytest suite |
| **Safety & production readiness** | Human-in-the-loop gate on every external write, Zero-Trust policy server (role + PII checks) in `agentic_radar/governance/`, Denial-of-Wallet circuit breaker, OTel-style tracing, non-root read-only-FS `Dockerfile` |

## Quick start (zero keys required)

```bash
pip install -r agentic_radar/requirements.txt

# hermetic run with a deterministic offline model:
RADAR_OFFLINE=1 python agentic_radar/core/orchestrator.py

# the CI gates:
python -m pytest agentic_radar/tests -q            # expect: 38 passed
python agentic_radar/evals/run_evals.py --offline  # expect: 8/8, drift gate ok
```

## Live run

```bash
cp agentic_radar/.env.example agentic_radar/.env   # add ANTHROPIC_API_KEY (Gemini optional)
set -a; source agentic_radar/.env; set +a          # nothing auto-loads .env — source it
export RADAR_MAX_USD=2 RADAR_MAX_MODEL_CALLS=200 RADAR_MIN_RESEARCH_SIGNALS=5
python agentic_radar/core/orchestrator.py
streamlit run agentic_radar/core/dashboard.py      # ideas, agent traces, budget
```

A full live cycle costs ≈ $1.90 with the caps above (106 model calls) and produces
Elo-ranked opportunities such as *"Sensorless Tactile Inference SDK"* (Elo 1275).
If the budget breaker trips, that is the Denial-of-Wallet safety net working —
raise the caps deliberately.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design and data flow
- [TESTING.md](TESTING.md) — 7-phase layered test plan (offline → live → sandboxed)
- [CONFORMANCE.md](CONFORMANCE.md) — mapping to the course's whitepaper requirements
- [opportunity_radar.spec.md](opportunity_radar.spec.md) — the product spec
- [agentic_radar/README.md](agentic_radar/README.md) — package-level deep dive

## Security posture

No credentials in code — everything reads from environment variables
(`agentic_radar/.env.example` is the template; the real `.env` is git-ignored).
External writes (Notion) require explicit human confirmation and fail **closed**.
The Docker image runs as uid 10001 on a read-only filesystem.
