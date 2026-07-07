# Kaggle Writeup draft — paste into the competition's "New Writeup" form

> Delete this header block before submitting. Fill in the two ALL-CAPS placeholders
> (repo URL, video URL) once you have them.

---

## Agentic Opportunity Radar — from research noise to founder-ready opportunities

### The problem

Solo founders in fast-moving deep-tech fields (robotics/humanoids in my case) face a
daily firehose: hundreds of arXiv papers, federal grant solicitations, YC batches,
SEC filings, and community chatter. The signal that matters — *"an adjacent technique
just made a new software wedge viable"* — is buried, and by the time a human curates
it, the window has often closed. Manually triaging this takes hours a day and still
misses cross-source patterns (a paper + a grant + three startups in the same niche).

### The solution

**Agentic Opportunity Radar** is a once-daily multi-agent pipeline that fetches
~185 signals per cycle from 7+ sources, routes each through a category-matched
analysis skill, curates and cross-references them, has a deep-reasoning agent
(Claude Fable 5, adaptive thinking) synthesize concrete solo-founder business
opportunities, and ranks them in an Elo tournament judged by a *different* model
family (Gemini) to reduce self-evaluation bias. Output: a ranked report of specific,
actionable wedges — e.g. **"Sensorless Tactile Inference SDK" (Elo 1275)**: ship
tactile sensing from motor-current signals alone, no hardware.

### The value

- Hours of daily triage → one autonomous ~20-minute cycle costing under $2.
- Ideas are constraint-checked (software/data wedges a solo founder can execute, not
  "build a robot"), deduplicated across days, and long-lived winners get promoted to
  an evergreen list.
- The harness is domain-agnostic: swap the fetchers and thesis memory and it becomes
  a radar for biotech, fintech, or climate.

### Architecture & course concepts (3+ demonstrated)

`Agent = Model + Harness`. Models are pure config; the harness does the real work:

1. **Orchestration** — a DAG orchestrator (fetch → source skills → curation →
   business → Elo tournament → report) with cycle detection and per-node
   OTel-style tracing into SQLite.
2. **Tools & interoperability** — consumes official MCP servers (Notion via
   `@notionhq/notion-mcp-server`, YouTube via `yt-mcp`, GitHub streamable-http)
   plus 7 public REST APIs; a skill loader with conformance checks routes each
   signal category to the right analysis skill.
3. **Agent-to-agent communication** — a file-based message bus passes raw and
   compressed records between agents, with path-traversal protection.
4. **Memory engineering** — dynamic SQLite memory (URL dedup, Elo history,
   evergreen promotion, behavioural-drift baselines) + static thesis memory.
5. **Evaluation** — an eval-as-unit-test CI gate (8 offline checks covering the four
   classic agent failure modes: trigger routing, execution, regression, and
   Denial-of-Wallet), a drift gate against a scored baseline, an online LLM-judge
   rubric, and a 38-test pytest suite.
6. **Safety & production readiness** — human-in-the-loop confirmation on every
   external write (fails closed), a Zero-Trust policy server (role checks + PII
   backstop on outbound content), a Denial-of-Wallet circuit breaker (caps model
   calls, tool calls, and USD per cycle), and a sandboxed non-root, read-only-FS
   Docker image.

### Try it

- **Code (public repo):** YOUR_GITHUB_REPO_URL
- **Video demo:** YOUR_VIDEO_URL
- Zero-key hermetic mode: `RADAR_OFFLINE=1 python agentic_radar/core/orchestrator.py`
- Gates: `pytest agentic_radar/tests -q` (38 passed) and
  `python agentic_radar/evals/run_evals.py --offline` (8/8, drift ok)
- Live dashboard: `streamlit run agentic_radar/core/dashboard.py`

### What a real run looks like

A verified live cycle on 2026-07-06: 185 signals fetched, 106 model calls,
$1.90 spend (under the $2 breaker), 6 ranked opportunities produced, every agent
step visible in the Traces tab. When the breaker was set low deliberately, it
tripped and froze the cycle with state preserved — the failure modes are not just
handled, they're tested.
