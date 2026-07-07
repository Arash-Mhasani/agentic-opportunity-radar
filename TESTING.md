# TESTING.md — Step-by-step test plan

A layered plan: each phase adds one new dependency (first nothing, then an Anthropic
key, then real Notion/YouTube accounts). Run the phases in order — if Phase 1 fails,
stop and fix before spending money in Phase 3.

Everything in **Phases 0–2 needs no API keys and no paid calls.**

---

## Phase 0 — Setup (2 min)

```bash
cd agentic_radar            # the package root (contains AGENTS.md, config.py, conftest.py)
python --version           # expect 3.10+ (built/tested on 3.12)
pip install -r requirements.txt
cp .env.example .env        # leave secrets blank for now
```

**Pass check:** `pip` finishes with no error. `pyyaml`, `pytest`, `requests` import cleanly:
```bash
python -c "import yaml, pytest, requests; print('deps ok')"
```

---

## Phase 1 — Offline gates (no keys, no network spend) ✅ the "nothing is broken" proof

### Step 1.1 — Unit test suite
```bash
cd ..                       # run from the directory ABOVE agentic_radar
python -m pytest agentic_radar/tests -q
```
**Expect:** `27 passed`. These cover Elo math, the skill loader + conformance, the YC
robotics/recency filter, the message bus (incl. path-traversal block), the MCP HITL
gate + read-only enforcement, the DAG (ordering + cycle detection), the Denial-of-Wallet
breaker, tracing spans, and evergreen promotion.

**If it fails:** read the failing test name — it maps 1:1 to a component. Re-run a single
file with `-x -v`, e.g. `python -m pytest agentic_radar/tests/test_harness.py -x -v`.

### Step 1.2 — Eval-as-unit-test gate
```bash
python agentic_radar/evals/run_evals.py --offline
```
**Expect:** `Offline: 8/8 checks passed` and exit code 0. This is the CI gate; it exercises
the 4 failure modes (trigger routing, execution/Elo, adversarial/regression, Denial-of-Wallet)
plus skill conformance, functional correctness, quality, and self-repair.

**Useful variant:** `python agentic_radar/evals/run_evals.py --offline --json` for machine-readable output.

**Set the drift baseline (Day-5 behavioural-drift gate).** First run, record a baseline:
```bash
python agentic_radar/evals/run_evals.py --offline --update-baseline
```
Thereafter, `run_evals.py --offline` also fails (exit 1) if any score drops more than
`--margin` (default 0.10) below `evals/baseline.json`. **Expect:** `Drift gate: ok`.
This is distinct from the pass/fail checks: it catches quality *erosion*, not just breakage.

### Step 1.3 — Skill-loader conformance spot check
```bash
python -c "
import sys; sys.path.insert(0,'agentic_radar')
from skills.skill_loader import SkillRegistry
r = SkillRegistry('agentic_radar/skills')
print('skills found:', sorted(s.name for s in r.all()))
print('conformance:', r.conformance_report())
"
```
**Expect:** exactly **6** skills, `youtube_search` absent, and every `warnings` list empty.

### Step 1.4 — Whole-pipeline dry run (offline model, hermetic)
This proves the DAG wires end-to-end. `RADAR_OFFLINE=1` makes the **model** deterministic;
to also avoid network, stub the fetch node with a fixture:
```bash
rm -f /tmp/radar_test.db
RADAR_OFFLINE=1 RADAR_DB_PATH=/tmp/radar_test.db RADAR_BUS_DIR=/tmp/radar_bus python -c "
import sys; sys.path.insert(0,'agentic_radar')
from config import RadarConfig
import core.orchestrator as O
cfg = RadarConfig(); cfg.offline = True
o = O.Orchestrator(cfg)
o._node_fetch = lambda ctx: ctx.__setitem__('raw_signals', [
  {'source':'arXiv','title':'Diffusion policy for grasping','summary':'a method','url':'https://a/1','category':'paper'},
  {'source':'GrantsGov','title':'[DOD] Manipulation','summary':'funding','url':'https://g/1','category':'grant'},
]) or ctx['raw_signals']
r = o.run()
print('cycle:', r['cycle_id'], '| floor_met:', r['floor_met'], '| spans:', len(o.tracer.spans_for_cycle()))
print('top:', [(i['title'], round(i['elo_score'])) for i in r.get('top_ideas', [])])
"
```
**Expect:** a cycle id prints, `floor_met: False` (only 1 paper < the 100 floor — correct),
several spans recorded, and a non-empty `top` list. No traceback.

> Note: without the fixture, `RADAR_OFFLINE=1 python agentic_radar/core/orchestrator.py`
> still runs, but the niche pollers will attempt real network calls (degrading to empty on
> failure). The fixture above is the fully hermetic version.

### Step 1.5 — Dashboard launches
```bash
RADAR_DB_PATH=/tmp/radar_test.db streamlit run agentic_radar/core/dashboard.py
```
**Expect:** the app opens with five tabs. The **Agent Traces** tab shows the spans from
Step 1.4 (name, kind, status, ms). Evergreen/Budget tabs populate from the same DB.

---

## Phase 2 — Component behavior verification (still no keys)

### Step 2.1 — MCP HITL gate (the safety-critical path)
```bash
python -c "
import sys; sys.path.insert(0,'agentic_radar')
from config import default_mcp_registry
from connectors.mcp_client import MCPClient, deny_all_confirm
spec = default_mcp_registry()['notion']

spec.read_only = True
print('read-only blocks write :', MCPClient(spec).call_tool('notion-create-pages', {}).skipped_reason)

spec.read_only = False
print('no-confirm blocks write :', MCPClient(spec, confirm_fn=deny_all_confirm).call_tool('notion-create-pages', {}).skipped_reason)

print('confirmed write degrades:', MCPClient(spec, confirm_fn=lambda s,t,a: True).call_tool('notion-create-pages', {}).skipped_reason)
"
```
**Expect, in order:** `...read-only...`, `...not confirmed...`, `...unavailable...`.
The third line proves that even when a human approves, a missing SDK/credential fails
**closed** (never crashes, never writes).

### Step 2.2 — YC robotics + recency filter
```bash
python -c "
import sys, datetime; sys.path.insert(0,'agentic_radar')
from radars import yc_startup_radar as yc
companies=[
 {'name':'GripAI','oneLiner':'humanoid manipulation software','batch':'W25','tags':['Robotics']},
 {'name':'OldBot','oneLiner':'robotics','batch':'W19'},
 {'name':'PayCo','oneLiner':'payments api','batch':'S25'},
]
out=yc.filter_robotics_recent(companies, years=2, now=datetime.date(2026,6,1))
print('kept:', [c['name'] for c in out])   # expect ['GripAI']
"
```
**Expect:** `kept: ['GripAI']` (OldBot too old, PayCo not robotics).

### Step 2.3 — Denial-of-Wallet breaker trips
```bash
python -c "
import sys; sys.path.insert(0,'agentic_radar')
from config import RadarConfig
from observability.tracing import Budget, CircuitBreakerTripped
cfg=RadarConfig(); cfg.max_model_calls=2; b=Budget(cfg)
try:
  [b.charge_call('t') for _ in range(10)]
except CircuitBreakerTripped as e:
  print('TRIPPED as expected:', e)
"
```
**Expect:** `TRIPPED as expected: ...circuit breaker...`.

### Step 2.4 — Zero-Trust governance (Day-5 Policy Server + Context Hygiene)
```bash
python -c "
import sys, os; sys.path.insert(0,'agentic_radar')
from governance.policy_server import PolicyServer
from governance.context_resolver import resolve_context, sanitize_args, find_pii
ps = PolicyServer()  # no LLM -> semantic gate uses the deterministic PII backstop

# structural: a viewer role may not write
print('structural deny :', ps.check('notion-create-pages', {}, role='viewer').reason)
# semantic: an external write carrying a plain-text email is blocked
print('semantic deny   :', ps.check('notion-create-pages',
      {'pages':[{'content':'mail me at a@b.com'}]}, role='radar').reason)
# context hygiene: placeholders resolve from env; no hardcoded secrets
os.environ['NOTION_PARENT_PAGE_ID']='page-123'
print('placeholder     :', resolve_context('[[NOTION_PARENT_PAGE_ID]]'))
print('nested resolve  :', sanitize_args({'pages':[{'id':'[[NOTION_PARENT_PAGE_ID]]'}]}))
"
```
**Expect:** a structural denial mentioning the `viewer` role, a semantic denial mentioning
unmasked PII (`email`), the placeholder resolving to `page-123`, and the nested arg
resolved too. This is the safety net that prevents the Day-5 "rogue agent emails 50 people"
class of incident.

---

## Phase 3 — Live single-model run (needs `ANTHROPIC_API_KEY`, small spend)

### Step 3.1 — Set the key, keep external MCP off
In `.env`: set `ANTHROPIC_API_KEY=...`, `RADAR_OFFLINE=0`, leave Notion/YouTube blank.
Cap spend hard for the first run:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export RADAR_MAX_USD=2 RADAR_MAX_MODEL_CALLS=40 RADAR_MIN_RESEARCH_SIGNALS=5
python agentic_radar/core/orchestrator.py
```
**Expect:** real signals fetched, real opportunities generated, a markdown report logged,
and a budget snapshot under your cap. If the breaker trips, that's the safety net working —
raise the caps deliberately.

### Step 3.2 — Validate the live output
```bash
python -c "
import sys, sqlite3; sys.path.insert(0,'agentic_radar')
from config import CONFIG
from evals.rubric import score_functional_correctness, score_constraint_compliance
import json
c=sqlite3.connect(CONFIG.db_path); c.row_factory=sqlite3.Row
ideas=[dict(r) for r in c.execute('SELECT id,title,description,elo_score FROM ideas ORDER BY elo_score DESC LIMIT 5')]
print('top live ideas:', [(i['title'], round(i['elo_score'])) for i in ideas])
"
```
**Check by hand:** Are the ideas software/data/consulting wedges (not "build a robot")?
Do they name a concrete adjacent technique? Open the dashboard **Agent Traces** tab and
confirm real `model` spans with non-zero token attributes — this is dimensions 4 (cost)
and 6 (trajectory) made visible.

### Step 3.3 — Online LLM-judge eval
```bash
python agentic_radar/evals/run_evals.py        # no --offline → adds the LLM judge
```
**Expect:** the offline block still 8/8, plus an `online` block with rubric scores
(intent_fit / specificity / feasibility_solo).

---

## Phase 4 — MCP integration (opt-in; uses YOUR real accounts)

> Do these one at a time. Each is independent.

### Step 4.1 — Notion READ (read-only token)
Create an internal Notion integration with **Read content** only; share a page with it.
```bash
export NOTION_TOKEN=ntn_...        # read-only integration
export NOTION_READ_ONLY=1
python -c "
import sys; sys.path.insert(0,'agentic_radar')
from config import default_mcp_registry
from connectors.notion_connector import NotionConnector
n=NotionConnector(default_mcp_registry()['notion'])
print('available:', n.available())
print(n.search('robotics').content)
"
```
**Expect:** `available: True` and search results. (Requires Node/`npx` available, since the
official Notion MCP server runs via `npx @notionhq/notion-mcp-server`.)

### Step 4.2 — Notion WRITE (the HITL gate, live)
Give the integration **Insert content**; grab a parent page id.
```bash
export NOTION_TOKEN=ntn_...        # write-capable integration
export NOTION_READ_ONLY=0
export NOTION_PARENT_PAGE_ID=<page-id>
export RADAR_REQUIRE_WRITE_CONFIRMATION=1
python agentic_radar/core/orchestrator.py
```
**Expect:** when it reaches the report write, you see a console prompt showing the exact
tool input and `Approve this write? [y/N]`. Type `n` → nothing is written. Re-run, type
`y` → a new page appears in your Notion. **This is the Day-2 HITL requirement in action.**

### Step 4.3 — YouTube (your playlist)
```bash
export YOUTUBE_API_KEY=...
export YOUTUBE_PLAYLIST_ID=<your-playlist-id>
python -c "
import sys; sys.path.insert(0,'agentic_radar')
from config import default_mcp_registry
from connectors.youtube_connector import YouTubeConnector
y=YouTubeConnector(default_mcp_registry()['youtube'])
print('available:', y.available())
sigs=y.fetch_playlist_signals('$YOUTUBE_PLAYLIST_ID', max_results=3)
print('video signals:', len(sigs))
"
```
**Expect:** `available: True` and ≥1 video signal with a transcript-derived summary.

---

## Phase 5 — Failure-mode tests (the four Day-3 modes, deliberately provoked)

| Mode | How to provoke | Expected behavior |
|---|---|---|
| **Trigger** | In a fixture signal set `category` to something unmapped (e.g. `"xyz"`). | Routed to `analyze-market-signal` (the safe default) — verify in the trace `skill:` span. |
| **Execution** | Inject a malformed record / force the model to return non-JSON (offline responder returning garbage). | `run_source_skill` falls back to a valid record; no crash, no corrupted bus entry. |
| **Regression** | After ANY code change, re-run `pytest` + `run_evals --offline`. | Still 38 passed / 8 passed, drift gate ok. A drop pinpoints the regression. |
| **Denial-of-Wallet** | `export RADAR_MAX_USD=0.001` then run a live cycle. | Breaker trips early, cycle freezes with state preserved, `circuit_breaker` field set in the result. |

---

## Phase 6 — Sandboxed run (Day-5 "Sandboxing")

Run the radar inside the ephemeral, low-privilege container so a tricked tool call cannot
touch the host. Requires Docker.

```bash
cd agentic_radar/..                      # parent of the package
docker build -t opportunity-radar agentic_radar
# offline plumbing test inside the sandbox (no keys, non-root, read-only FS):
docker run --rm --read-only --tmpfs /tmp --cap-drop ALL \
  -e RADAR_OFFLINE=1 -e RADAR_DB_PATH=/tmp/r.db -e RADAR_BUS_DIR=/tmp/bus \
  opportunity-radar python -m pytest agentic_radar/tests -q
```
**Expect:** the image builds, and the suite runs as uid 10001 with a read-only root
filesystem (only `/tmp` is writable). For a live cycle, add `--env-file agentic_radar/.env`
and mount a writable volume for `memory/`. If a command needs to write outside `/tmp`, that
is the sandbox doing its job — widen the mount deliberately, don't drop `--read-only`.

---

## Phase 7 — Acceptance checklist

- [ ] `pytest` → 38 passed (Phase 1.1)
- [ ] `run_evals --offline` → 8/8 **and** `Drift gate: ok` (Phase 1.2)
- [ ] 6 conformant skills, no `youtube_search` (Phase 1.3)
- [ ] Hermetic pipeline completes, spans recorded, policy server active (Phase 1.4)
- [ ] Dashboard Traces tab renders real spans (Phase 1.5)
- [ ] HITL gate blocks unconfirmed writes, fails closed (Phase 2.1)
- [ ] DoW breaker trips (Phase 2.3 / 5)
- [ ] Policy Server denies viewer writes + unmasked-PII writes; placeholders resolve (Phase 2.4)
- [ ] Live cycle produces constraint-compliant, specific ideas (Phase 3)
- [ ] Notion write only after explicit `y` approval (Phase 4.2)
- [ ] Re-running evals after a change still green, drift gate ok (Phase 5, regression)
- [ ] Image builds and runs sandboxed as non-root, read-only FS (Phase 6)

When every box is checked, the system is behaving to spec.
