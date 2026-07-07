# PROJECT_STRUCTURE.md — how to lay this out before you test

Read this first. It tells you exactly what goes in which folder, the relative path of
every file, and how the Day-5 conventions (`specs/`, `AGENTS.md`, governance) map onto
this layout.

## Where to put the project

Put the package directory **`agentic_radar/`** anywhere you like; commands are run from
the directory **above** it (its parent). Example:

```
~/work/                         ← run commands from here (the parent)
└── agentic_radar/              ← the package (everything below lives here)
```

So: `cd ~/work && python -m pytest agentic_radar/tests -q`.

## The full tree (relative to the parent of `agentic_radar/`)

```
agentic_radar/
├── AGENTS.md                         # ALWAYS-ON context: constraints, model map, safety, run cmds
├── README.md                         # honest overview + quick start
├── Dockerfile                        # sandboxed (non-root, read-only FS) execution — Day-5
├── .dockerignore
├── .env.example                      # env-var template (copy to .env; NO secrets committed)
├── requirements.txt
├── conftest.py                       # puts the package dir on sys.path for pytest
├── config.py                         # model IDs, env loading, MCP registry, governance config
│
├── specs/                            # ★ SOURCE OF TRUTH (Spec-Driven Development, Day-5)
│   ├── opportunity_radar.spec.md     #   technical design / "North Star" (Markdown narrative)
│   ├── schemas.yaml                  #   data contracts (YAML — nested config)
│   └── scenarios.feature             #   BDD/Gherkin behaviors, each linked to a test
│
├── core/                             # orchestration + UI
│   ├── orchestrator.py               #   the DAG pipeline (run this for one cycle)
│   ├── dag.py                        #   DAG engine (toposort, cycle detection)
│   ├── message_bus.py                #   file bus: raw + compressed records
│   └── dashboard.py                  #   Streamlit review canvas (Traces/Evergreen/Budget)
│
├── agents/                           # the "model" side
│   ├── llm_client.py                 #   one choke point for model calls; offline mode
│   ├── agent_runners.py              #   source/curation/business/judge nodes
│   ├── prompts.py                    #   prompts (no CAPS walls)
│   └── capability_profiles.py        #   per-node model/token/tool bundles
│
├── skills/                           # Agent Skills + niche pollers
│   ├── skill_loader.py               #   parses/validates SKILL.md, injects body + file tool
│   ├── data_fetchers.py              #   niche free pollers (arXiv, Grants.gov, HN, Reddit, SEC)
│   ├── summarize_academic_paper/
│   │   ├── SKILL.md
│   │   └── references/cross_domain_transfer.md   # progressive disclosure
│   ├── analyze_youtube_transcript/SKILL.md
│   ├── analyze_social_sentiment/SKILL.md
│   ├── analyze_funding_signal/SKILL.md
│   ├── analyze_job_signal/SKILL.md
│   └── analyze_market_signal/SKILL.md
│
├── connectors/                       # consume, don't build (MCP)
│   ├── mcp_client.py                 #   generic client: context-resolve → policy → HITL → call
│   ├── notion_connector.py           #   read + HITL/policy-gated write
│   └── youtube_connector.py          #   your own playlist + transcripts
│
├── governance/                       # ★ Zero-Trust (Day-5)
│   ├── policy_server.py              #   structural + semantic gating of every tool call
│   ├── policies.yaml                 #   structural rules (roles, environments, PII kinds)
│   └── context_resolver.py           #   [[placeholder]] resolution + PII masking
│
├── radars/
│   └── yc_startup_radar.py           #   robotics + founded-≤2-yrs filter on yc-oss
│
├── observability/
│   └── tracing.py                    #   OTel-style spans → SQLite + Denial-of-Wallet breaker
│
├── memory/
│   ├── memory_manager.py             #   ideas+Elo, signal memory, evergreen promotion (SQLite)
│   ├── elo.py                        #   deterministic Elo math
│   └── static_memory.json            #   ALWAYS-ON founder constraints (injected every turn)
│
├── evals/
│   ├── run_evals.py                  #   eval-as-unit-test + LLM-judge + drift gate
│   ├── rubric.py                     #   the 7 evaluation dimensions
│   ├── golden_dataset.json           #   routing/good/adversarial/record cases
│   └── baseline.json                 #   drift baseline (regenerate with --update-baseline)
│
├── tests/                            # offline test suite (no keys, no network)
│   ├── test_business_agent.py
│   ├── test_harness.py
│   └── test_governance.py            #   Day-5 policy server + context hygiene
│
└── docs/
    ├── PROJECT_STRUCTURE.md          # this file
    ├── ARCHITECTURE.md               # mermaid diagrams
    ├── CONFORMANCE.md                # standards mapping (Days 2-5)
    └── TESTING.md                    # step-by-step test plan
```

## Runtime artifacts (created automatically — do not commit)

- `agentic_radar/memory/dynamic_memory.db` — SQLite (ideas, signal memory, **trace_spans**).
- `agentic_radar/message_bus/` — raw + compressed records for the current cycle.
- `.env` — your real secrets (gitignore it).

Override locations with `RADAR_DB_PATH` and `RADAR_BUS_DIR` if you prefer.

## How this maps to the Day-5 conventions

- **`specs/`** = Day-5's spec folder (the source of truth checked into version control).
- **`AGENTS.md`** = Day-5's "Shared Multi-Tool Config" — the cross-tool, always-on
  foundation. It sits at the package root so any coding agent picks it up.
- **`skills/<name>/SKILL.md`** = Agent Skills. If you open this repo in Antigravity,
  symlink or copy the skills into `.agent/skills/` so its workspace manager finds them;
  the loader here reads them directly from `skills/`.
- **`governance/policies.yaml` + `policy_server.py`** = Day-5's Policy Server pattern.
- **`Dockerfile`** = Day-5's sandbox (ephemeral, low-privilege container).

## Minimum you must do before testing

1. `cd` into the **parent** of `agentic_radar/`.
2. `pip install -r agentic_radar/requirements.txt`
3. `cp agentic_radar/.env.example agentic_radar/.env` (leave secrets blank for offline tests).
4. Follow `docs/TESTING.md` Phase 1 (no keys needed).
