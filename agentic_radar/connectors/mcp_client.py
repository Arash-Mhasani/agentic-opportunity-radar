"""
Generic MCP client wrapper.

Honors the Day-2 (sl.16) consumption rules:
  * Consume, don't build — we talk to first-party MCP servers (Notion, YouTube, GitHub)
    rather than hand-rolling REST wrappers.
  * Credentials are passed by ENV VAR NAME and forwarded to the server process; they
    are never inlined into prompts or code.
  * Reads default to read-only. A tool that mutates state must be explicitly listed in
    the server spec's `write_tools` AND pass the Human-In-The-Loop gate.
  * Graceful degradation: if the `mcp` SDK, `npx`, or credentials are missing, calls
    return a structured "unavailable" result and the pipeline keeps running.

Real transport uses the official `mcp` Python SDK when present. Because that requires
a live server + network + credentials, this module is import-safe and unit-testable
without any of them (see tests/test_mcp_gate.py).
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("radar.mcp")

# Optional dependency. Import is guarded so the package runs without it.
try:  # pragma: no cover - exercised only when the SDK is installed
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    _HAVE_MCP = True
except Exception:
    _HAVE_MCP = False


class WriteDenied(RuntimeError):
    pass


@dataclass
class MCPCallResult:
    ok: bool
    tool: str
    server: str
    content: Any = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None


# A confirmation gate: given (server, tool, arguments) returns True to allow a write.
ConfirmFn = Callable[[str, str, Dict[str, Any]], bool]


def deny_all_confirm(server: str, tool: str, args: Dict[str, Any]) -> bool:
    """Default for automated runs: deny writes unless an explicit confirmer is provided."""
    log.warning("HITL gate: no confirmer supplied; denying write %s.%s", server, tool)
    return False


def console_confirm(server: str, tool: str, args: Dict[str, Any]) -> bool:  # pragma: no cover
    """Interactive gate: show the exact tool input to the user before calling."""
    import json
    print(f"\n[HITL] {server}.{tool} wants to run with:\n{json.dumps(args, indent=2)}")
    return input("Approve this write? [y/N] ").strip().lower() == "y"


class MCPClient:
    def __init__(self, server_spec, confirm_fn: Optional[ConfirmFn] = None, require_confirmation: bool = True,
                 policy_server=None, context_state: Optional[Dict[str, Any]] = None,
                 role: str = "radar", env: str = "development"):
        self.spec = server_spec
        self.require_confirmation = require_confirmation
        self.confirm_fn = confirm_fn or deny_all_confirm
        # Day-5 Zero-Trust additions (all optional → existing behavior preserved when unset):
        self.policy_server = policy_server          # hybrid structural + semantic gating
        self.context_state = context_state or {}    # for [[placeholder]] resolution
        self.role = role
        self.env = env

    # ── credential / availability checks ─────────────────────────────────────
    def _missing_env(self) -> List[str]:
        return [k for k in self.spec.env_passthrough if not os.environ.get(k)]

    def available(self) -> bool:
        if not _HAVE_MCP:
            return False
        # require at least the primary credential to be present
        if self.spec.env_passthrough and len(self._missing_env()) == len(self.spec.env_passthrough):
            return False
        return True

    def _forward_env(self) -> Dict[str, str]:
        env = {k: os.environ[k] for k in self.spec.env_passthrough if os.environ.get(k)}
        return env

    # ── the gate ─────────────────────────────────────────────────────────────
    def _gate(self, tool: str, args: Dict[str, Any]) -> Optional[str]:
        """Return a skip reason if the call must be blocked, else None."""
        is_write = tool in (self.spec.write_tools or [])
        if is_write and self.spec.read_only:
            return f"server '{self.spec.name}' is read-only; write tool '{tool}' blocked"
        if is_write and self.require_confirmation:
            if not self.confirm_fn(self.spec.name, tool, args):
                return f"write '{tool}' not confirmed by Human-In-The-Loop gate"
        return None

    # ── call ─────────────────────────────────────────────────────────────────
    def call_tool(self, tool: str, arguments: Dict[str, Any]) -> MCPCallResult:
        # Day-5 Context Hygiene: resolve [[placeholders]] so no secrets/IDs are hardcoded.
        try:
            from governance.context_resolver import sanitize_args
            arguments = sanitize_args(arguments, self.context_state)
        except Exception:  # context resolver is optional; never block on it
            pass

        # Day-5 Policy Server: structural + semantic gating, before the read-only/HITL gate.
        if self.policy_server is not None:
            decision = self.policy_server.check(tool, arguments, role=self.role, env=self.env)
            if not decision.allowed:
                reason = f"policy violation [{decision.layer}]: {decision.reason}"
                log.info("MCP call denied by policy: %s", reason)
                return MCPCallResult(ok=False, tool=tool, server=self.spec.name, skipped_reason=reason)

        reason = self._gate(tool, arguments)
        if reason:
            log.info("MCP call skipped: %s", reason)
            return MCPCallResult(ok=False, tool=tool, server=self.spec.name, skipped_reason=reason)

        if not self.available():
            miss = "mcp SDK not installed" if not _HAVE_MCP else f"missing env: {self._missing_env()}"
            return MCPCallResult(ok=False, tool=tool, server=self.spec.name,
                                 skipped_reason=f"server unavailable ({miss})")

        try:  # pragma: no cover - requires a live server
            import anyio
            return anyio.run(self._call_async, tool, arguments)
        except Exception as e:  # pragma: no cover
            log.warning("MCP call failed %s.%s: %s", self.spec.name, tool, e)
            return MCPCallResult(ok=False, tool=tool, server=self.spec.name, error=str(e))

    async def _call_async(self, tool: str, arguments: Dict[str, Any]) -> MCPCallResult:  # pragma: no cover
        if self.spec.transport == "stdio":
            params = StdioServerParameters(command=self.spec.command, args=self.spec.args,
                                           env={**os.environ, **self._forward_env()})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
                    return MCPCallResult(ok=True, tool=tool, server=self.spec.name,
                                         content=_flatten(result))
        # streamable-http
        from mcp.client.streamable_http import streamablehttp_client
        headers = {}
        # forward a bearer token if a *_TOKEN env var is configured
        for k in self.spec.env_passthrough:
            if k.endswith("TOKEN") and os.environ.get(k):
                headers["Authorization"] = f"Bearer {os.environ[k]}"
        async with streamablehttp_client(self.spec.url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return MCPCallResult(ok=True, tool=tool, server=self.spec.name, content=_flatten(result))

    def list_tools(self) -> List[str]:  # pragma: no cover
        if not self.available():
            return []
        try:
            import anyio
            return anyio.run(self._list_async)
        except Exception as e:
            log.warning("MCP list_tools failed: %s", e)
            return []

    async def _list_async(self) -> List[str]:  # pragma: no cover
        if self.spec.transport == "stdio":
            params = StdioServerParameters(command=self.spec.command, args=self.spec.args,
                                           env={**os.environ, **self._forward_env()})
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return [t.name for t in tools.tools]
        return []


def _flatten(result) -> Any:  # pragma: no cover
    """Reduce an MCP CallToolResult to plain text/json."""
    try:
        parts = []
        for block in getattr(result, "content", []) or []:
            if getattr(block, "type", "") == "text":
                parts.append(block.text)
        return "\n".join(parts) if parts else getattr(result, "structuredContent", None)
    except Exception:
        return str(result)
