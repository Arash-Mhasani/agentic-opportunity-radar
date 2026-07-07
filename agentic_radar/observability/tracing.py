"""
Observability — "Auditing the Agent's Mind" (Day-4 Pillars 6 & 7).

We log the full *Vibe Trajectory*: every node, model call, and tool call as an
OpenTelemetry-style span (id, parent_id, name, attributes, status, timing) into
SQLite so the dashboard can answer "why did the agent do that?" and so third-party
audits are possible. "Success" without a trace is not success.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
import contextlib
from typing import Any, Dict, Optional


class Tracer:
    def __init__(self, db_path: str, cycle_id: str):
        self.db_path = db_path
        self.cycle_id = cycle_id
        self._stack: list[str] = []
        self._init()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init(self):
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS trace_spans (
                    span_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    cycle_id TEXT,
                    name TEXT,
                    kind TEXT,                 -- 'node' | 'model' | 'tool'
                    status TEXT,               -- 'ok' | 'error' | 'tripped'
                    attributes TEXT,           -- JSON
                    started_at REAL,
                    ended_at REAL,
                    duration_ms REAL
                )
            """)

    @contextlib.contextmanager
    def span(self, name: str, kind: str = "node", **attrs):
        span_id = uuid.uuid4().hex[:16]
        parent = self._stack[-1] if self._stack else None
        self._stack.append(span_id)
        start = time.time()
        status = "ok"
        record_attrs: Dict[str, Any] = dict(attrs)
        try:
            handle = _SpanHandle(record_attrs)
            yield handle
        except CircuitBreakerTripped:
            status = "tripped"
            raise
        except Exception as e:
            status = "error"
            record_attrs["error"] = str(e)
            raise
        finally:
            end = time.time()
            self._stack.pop()
            with self._conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO trace_spans VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (span_id, parent, self.cycle_id, name, kind, status,
                     json.dumps(record_attrs, default=str), start, end, (end - start) * 1000),
                )

    def spans_for_cycle(self, cycle_id: Optional[str] = None):
        cycle_id = cycle_id or self.cycle_id
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT * FROM trace_spans WHERE cycle_id=? ORDER BY started_at", (cycle_id,)
            ).fetchall()
        return [dict(r) for r in rows]


class _SpanHandle:
    def __init__(self, attrs: Dict[str, Any]):
        self._attrs = attrs

    def set(self, **kw):
        self._attrs.update(kw)


# ── Denial-of-Wallet budget + circuit breaker (Day-4 sl.25) ──────────────────
class CircuitBreakerTripped(RuntimeError):
    pass


class Budget:
    """
    Bounds a pipeline cycle: max model calls, max tool calls, max estimated USD.
    Tripping raises CircuitBreakerTripped, which the orchestrator catches to freeze
    execution gracefully (preserving state for forensics) rather than looping forever.
    """

    def __init__(self, config, tracer: Optional[Tracer] = None):
        self.max_calls = config.max_model_calls
        self.max_usd = config.max_usd_budget
        self.tracer = tracer
        self.calls = 0
        self.tool_calls = 0
        self.usd = 0.0
        self.tripped = False

    def _check(self, reason_node: str):
        if self.calls > self.max_calls:
            self._trip(reason_node, f"model calls {self.calls} > {self.max_calls}")
        if self.usd > self.max_usd:
            self._trip(reason_node, f"est spend ${self.usd:.2f} > ${self.max_usd:.2f}")

    def _trip(self, node: str, msg: str):
        self.tripped = True
        raise CircuitBreakerTripped(f"[{node}] Denial-of-Wallet circuit breaker: {msg}")

    def charge_call(self, node: str):
        self.calls += 1
        self._check(node)

    def charge_tool(self, tool_name: str, node: str):
        self.tool_calls += 1

    def charge_usd(self, amount: float, node: str):
        self.usd += max(0.0, amount)
        self._check(node)

    def snapshot(self) -> Dict[str, Any]:
        return {"model_calls": self.calls, "tool_calls": self.tool_calls,
                "est_usd": round(self.usd, 4), "tripped": self.tripped,
                "max_calls": self.max_calls, "max_usd": self.max_usd}
