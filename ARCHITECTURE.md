# ARCHITECTURE.md — How the system fits together

`Agent = Model + Harness`. Two views below: a **component & data-flow** diagram (what the
pieces are and how data moves), and a **runtime sequence** diagram (what happens during one
daily cycle). Both render on GitHub, GitLab, Notion, VS Code, and mermaid.live.

---

## 1. Component & data-flow

```mermaid
flowchart TB
    subgraph IN["1 · Acquisition"]
        direction TB
        POLL["Niche pollers<br/>skills/data_fetchers.py<br/>arXiv · Semantic Scholar · Grants.gov<br/>HackerNews · Reddit · SEC"]
        YC["YC Robotics Radar<br/>radars/yc_startup_radar.py<br/>robotics + founded ≤ 2 yrs"]
    end

    subgraph MCPX["External MCP — consume, not build · connectors/"]
        direction TB
        NOT["Notion MCP<br/>read + HITL-gated write"]
        YT["yt-mcp<br/>your playlist + transcripts"]
        GH["GitHub MCP<br/>read-only"]
    end

    subgraph ORCH["2 · Orchestrator + DAG · core/orchestrator.py, core/dag.py"]
        direction LR
        N1["fetch"] --> N2["source"] --> N3["curation"] --> N4["business"] --> N5["tournament"]
    end

    subgraph BUS["3 · File Message Bus · core/message_bus.py"]
        RAW[("raw records")]
        CMP[("compressed records<br/>summarize-before-synthesize")]
    end

    subgraph SKILLS["4 · Skills · skills/skill_loader.py + 6 SKILL.md"]
        LOADER["Skill loader<br/>parse SKILL.md → system prompt<br/>+ real read_bus_record tool"]
    end

    subgraph MODEL["5 · Model tier · agents/llm_client.py"]
        direction TB
        SRC["source · sonnet-4-6"]
        CUR["curation · sonnet-4-6"]
        BIZ["business · opus-4-8 + extended thinking"]
        JDG["judge · gemini → haiku-4-5 fallback<br/>swapped A/B positions"]
    end

    subgraph DET["6 · Deterministic logic — shift intelligence left"]
        ELO["Elo math<br/>memory/elo.py"]
        FLOOR["research-signal floor ≥ 100"]
        CONS["constraint filter<br/>evals/rubric.py"]
    end

    subgraph MEM["7 · Memory · memory/memory_manager.py (SQLite)"]
        IDEAS[("ideas + elo")]
        SIG[("signal_memory<br/>+ is_evergreen")]
        STAT["static_memory.json<br/>always-on constraints"]
    end

    subgraph OBS["8 · Observability · observability/tracing.py"]
        TR[("trace_spans (SQLite)")]
        BUD["Denial-of-Wallet<br/>budget + circuit breaker"]
    end

    subgraph OUT["9 · Outputs"]
        REP["daily report (markdown)"]
        DASH["Dashboard · core/dashboard.py<br/>Traces · Evergreen · Budget · Vibe-diff"]
    end

    subgraph GOV["10 · Zero-Trust governance · governance/"]
        CTX["Context Resolver<br/>resolve [[placeholders]]"]
        POL["Policy Server<br/>structural + semantic gating"]
        HITL["Human-in-the-Loop gate"]
    end

    %% acquisition -> fetch
    POLL --> N1
    YC --> N1
    NOT -. read .-> N1
    YT -. read .-> N1
    GH -. read .-> N1
    N1 --> RAW

    %% source skills (REAL execution)
    RAW --> N2 --> LOADER --> SRC --> CMP

    %% curation + evergreen promotion
    CMP --> N3 --> CUR
    N3 -- promote_evergreen --> SIG

    %% business reasoning
    N4 --> BIZ
    STAT -. injected .-> BIZ
    SIG -. evergreen ctx .-> BIZ
    CMP -. curated .-> BIZ

    %% tournament: LLM judges, deterministic math
    N5 --> JDG --> ELO
    N5 --> ELO --> IDEAS

    %% gates + outputs (every external write passes governance)
    FLOOR -. confidence gate .-> REP
    CONS -. checks .-> REP
    IDEAS --> REP
    REP --> CTX --> POL --> HITL --> NOT
    IDEAS --> DASH
    TR --> DASH
    BUD --> DASH

    %% governance also intercepts MCP reads
    POL -. gates every tool call .-> MCPX

    %% cross-cutting observability
    N3 -. spans .-> TR
    BIZ -. calls + USD .-> BUD
    BUD -. trips .-> ORCH
```

**Reading it:** acquisition (1) feeds the DAG (2). Each node writes/reads the file bus (3),
which holds *raw* records on ingest and *compressed* records after the skill layer (4) runs
the model (5) for real. Subjective work (which idea wins, what's actionable) is the model's;
arithmetic and hard rules (6) stay in testable code. State lives in SQLite memory (7), every
step emits a span and is bounded by the budget breaker (8), and outputs (9) include the
HITL-gated Notion write and the dashboard.

---

## 2. Runtime sequence — one daily cycle

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator / DAG
    participant T as Tracer + Budget
    participant F as Fetchers / Radars / MCP reads
    participant B as Message Bus
    participant SK as Skill Loader
    participant M as Model tier
    participant ME as Memory (SQLite)
    participant G as Governance (policy + context)
    participant N as Notion (HITL)

    O->>T: open cycle span + budget
    O->>F: fetch (niche pollers + YC + your YouTube/Notion)
    F-->>B: write_raw(signal) → uri

    loop each new, unseen signal
        O->>SK: load SKILL.md for the signal's category
        SK->>M: system = base + skill body; tool = read_bus_record
        M->>B: read_bus_record(uri)
        M-->>O: compressed record (JSON)
        O->>B: write_compressed(record)
        O->>ME: mark_url_processed
    end

    O->>M: curation(compressed records)
    M-->>O: curated + evergreen flags
    O->>ME: promote_evergreen(url)
    Note right of ME: evergreen promotion (the previously-missing step)

    O->>M: business(static + evergreen + curated)  [opus + thinking]
    M-->>O: candidate opportunities

    loop each pair A,B
        O->>M: judge_match(A,B) twice with swapped positions
        M-->>O: winner (Gemini, else Claude fallback)
        O->>O: deterministic Elo update (memory/elo.py)
    end
    O->>ME: save ideas + elo

    O->>O: enforce research-signal floor (≥100)
    O->>G: sanitize args (resolve [[placeholders]])
    G->>G: Policy Server — structural + semantic gating
    alt policy + HITL approve
        G->>N: write_report(parent, markdown)
        N-->>O: page created
    else denied or unconfirmed
        G-->>O: Policy Violation / not approved → skip write
    end
    O->>T: budget snapshot + close spans

    Note over T: if calls/USD exceed budget → CircuitBreakerTripped<br/>→ freeze cycle, preserve state for forensics
```

---

## 3. Key design choices encoded above

- **The skill layer is real, not cosmetic.** The loader injects the `SKILL.md` body into the
  system prompt *and* hands the model a `read_bus_record` tool, then runs a bounded tool loop.
- **Summarize-before-synthesize.** Raw 50k-token transcripts are written once to the bus and
  distilled to ~80-token records; only records flow downstream. (We do not claim "memory
  flushing" — each model call is already stateless.)
- **Judgment is split correctly.** The model decides winners and what's actionable; Elo
  arithmetic, the signal floor, dedup, and constraint checks are deterministic code.
- **Two safety gates.** The HITL gate guards every external write; the Denial-of-Wallet
  breaker bounds every loop and freezes the cycle for forensics if exceeded.
- **Everything is observable.** Each node/model/tool is a span in `trace_spans`, surfaced in
  the dashboard's Agent Traces tab.
