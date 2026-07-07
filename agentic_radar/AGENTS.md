# AGENTS.md — Agentic Opportunity Radar

> This file is **always-on context**. Unlike a skill (which only loads if its
> description triggers — and the trigger-miss rate is ~56% per Vercel's evals and
> the Day-3 deck), everything here is true on *every* turn for *every* agent that
> touches this repo. Must-always-apply facts live here, never in a skill.

## What this system is

A once-daily, deep-reasoning pipeline that turns humanoid/robotics-industry signals
into specific, high-conviction **$1M+/yr entrepreneurial** opportunities for a
**solo founder**. It is `Agent = Model + Harness`:

- **Model tier** (swappable, see `config.py`):
  - `claude-opus-4-8`   — business reasoning (the "Business" node), extended thinking
  - `claude-sonnet-4-6` — curation + source-processing (skill execution)
  - `claude-haiku-4-5`  — cheap classification / routing
  - Gemini (optional)   — a *diverse* judge for the Elo tournament (reduces self-eval bias)
- **Harness**: MCP tools, standard Agent Skills, a DAG + file message bus, capability
  profiles, observability spans, an eval suite, and the guardrails below.

## Founder's HARD CONSTRAINTS (must always hold — never relax these in any node)

These are duplicated into `memory/static_memory.json` and injected into every
reasoning prompt. They are repeated here because they must survive even if a skill
fails to trigger.

1. **Solo** — exactly one person, no employees.
2. **≤20 hours/week.**
3. **Low capital** — five-figure / grant-scale; no VC raised; **no hardware capex**.
4. **Robotics-only focus**, entrepreneur path (not employment).
5. Rank by **market opportunity**, never by proximity to current skills.
6. Never propose "build a foundation model" or "build a new robot."

## Safety & operational rules (always-on)

- **Credentials**: never hardcode API keys/tokens. All secrets come from environment
  variables (see `.env.example`). Code must run — degrading gracefully — when a
  secret is absent. Use `[[PLACEHOLDER]]` syntax in args/specs; the Context Resolver
  (`governance/context_resolver.py`) resolves them from env/runtime state at call time.
- **Every external tool call is intercepted (Zero-Trust, Day-5)**: the Policy Server
  (`governance/policy_server.py`) applies (1) structural gating — deterministic role/
  environment allow-lists in `governance/policies.yaml` — and (2) semantic gating — an
  LLM/PII screen on writes. Then the Human-In-The-Loop gate guards any mutation.
  Governance logic is separate from execution logic by design.
- **MCP writes are gated**: any tool that mutates an external system (e.g. writing to
  Notion) MUST pass the HITL gate AND the Policy Server. Reads default to read-only.
- **Denial-of-Wallet**: every model/tool loop is bounded by the budget +
  circuit-breaker in `observability/tracing.py`. Never write an unbounded agentic loop.
- **Determinism belongs in code** ("shift intelligence left"): Elo math, the research-
  signal floor, dedup keys, date filters, and constraint checks are pure Python — not
  LLM calls. The LLM only does what genuinely needs judgment.
- **Observability is mandatory**: every node opens a span via
  `observability/tracing.py`. "Success" without a trace is not success.
- **Sandbox in production**: run via the provided `Dockerfile` (non-root, read-only FS,
  dropped caps) so a tricked tool call cannot touch the host.

## How to run

```bash
pip install -r requirements.txt
cp .env.example .env            # then fill in only the secrets you have
python -m agentic_radar.core.orchestrator        # one pipeline cycle
streamlit run agentic_radar/core/dashboard.py    # the review canvas
python -m pytest agentic_radar/tests -q          # offline test suite (no keys needed)
python -m agentic_radar.evals.run_evals --offline  # eval-as-unit-test (no keys needed)
```

## Repo conventions

- **`specs/` is the source of truth (Spec-Driven Development, Day-5).** The technical
  design is `specs/opportunity_radar.spec.md` (Markdown narrative), data contracts are
  `specs/schemas.yaml` (YAML for nested config), guaranteed behaviors are
  `specs/scenarios.feature` (Gherkin, each linked to its test). Update the spec first;
  code is regenerable from it.
- **Format**: narrative in Markdown, nested config/schemas in YAML (Day-5 SkCC: YAML
  parses ~52% accurate vs ~43% JSON for deep nesting). Avoid heavy JSON "format tax".
- Skills live in `skills/<snake_case>/SKILL.md`; skill `name:` is kebab-case, a gerund,
  with a `when NOT to use` and a pinned `version`. See `skills/skill_loader.py`.
- **Consume, don't build**: data acquisition for GitHub / YouTube / Notion / HF /
  PDF is done via MCP or vetted skills, not hand-rolled fetchers. Only genuinely
  niche sources (Grants.gov, YC, SEC) keep Python pollers in `skills/data_fetchers.py`.
- The file message bus (`core/message_bus.py`) stores **compressed** structured
  records. Reason over records, never re-inject raw 50k-token transcripts.
