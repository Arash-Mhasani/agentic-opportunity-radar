"""
Minimal DAG engine (Day-3 sl.41: "Graph-based ... execution with file-bus state
passing ... Cycle prevention and strict context isolation").

Each node is a pure function of an explicit `ctx` dict (state passed via the file bus
or small in-memory handles). Nodes declare their dependencies; the engine runs them in
topological order, opens a trace span per node, and refuses cycles. This replaces the
old implicit top-to-bottom linear pipeline with a real, inspectable graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class Node:
    name: str
    run: Callable[[Dict[str, Any]], Any]   # run(ctx) -> result; may mutate ctx
    deps: List[str] = field(default_factory=list)


class DAG:
    def __init__(self, tracer=None):
        self.nodes: Dict[str, Node] = {}
        self.tracer = tracer

    def add(self, name: str, run, deps: List[str] = None) -> "DAG":
        self.nodes[name] = Node(name=name, run=run, deps=deps or [])
        return self

    def _toposort(self) -> List[str]:
        visited, temp, order = set(), set(), []

        def visit(n: str):
            if n in visited:
                return
            if n in temp:
                raise ValueError(f"cycle detected at node '{n}'")
            temp.add(n)
            for d in self.nodes[n].deps:
                if d not in self.nodes:
                    raise ValueError(f"node '{n}' depends on unknown node '{d}'")
                visit(d)
            temp.discard(n)
            visited.add(n)
            order.append(n)

        for name in self.nodes:
            visit(name)
        return order

    def run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        for name in self._toposort():
            node = self.nodes[name]
            if self.tracer:
                with self.tracer.span(f"node:{name}", kind="node", deps=node.deps):
                    ctx[name] = node.run(ctx)
            else:
                ctx[name] = node.run(ctx)
        return ctx
