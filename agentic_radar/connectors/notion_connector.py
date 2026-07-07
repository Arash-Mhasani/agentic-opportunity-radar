"""
Notion connector — reads YOUR workspace and writes the daily report to YOUR Notion,
entirely through the official Notion MCP server (consume, don't build).

Auth: set NOTION_TOKEN (an internal integration token, ntn_...) in the environment.
  * For reads, use a read-only integration ("Read content" capability only).
  * For writes, the integration needs "Insert/Update content"; every write still
    passes the Human-In-The-Loop gate (require_confirmation=True by default).

If NOTION_TOKEN / the MCP SDK is missing, every method returns a structured
"unavailable" result and the pipeline continues.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from connectors.mcp_client import MCPClient, MCPCallResult, ConfirmFn

log = logging.getLogger("radar.notion")


class NotionConnector:
    def __init__(self, server_spec, confirm_fn: Optional[ConfirmFn] = None, require_confirmation: bool = True,
                 policy_server=None, context_state=None, role: str = "radar", env: str = "development"):
        self.client = MCPClient(server_spec, confirm_fn=confirm_fn, require_confirmation=require_confirmation,
                                policy_server=policy_server, context_state=context_state, role=role, env=env)

    def available(self) -> bool:
        return self.client.available()

    # ── reads (own Notion) ────────────────────────────────────────────────────
    def search(self, query: str, page_size: int = 10) -> MCPCallResult:
        return self.client.call_tool("notion-search", {"query": query, "page_size": page_size})

    def fetch_page(self, page_id: str) -> MCPCallResult:
        return self.client.call_tool("notion-fetch", {"id": page_id})

    def read_database(self, data_source_url: str) -> MCPCallResult:
        return self.client.call_tool("notion-search", {"query": data_source_url})

    # ── write (own Notion) — HITL-gated ───────────────────────────────────────
    def write_report(self, parent_id: str, title: str, markdown_body: str) -> MCPCallResult:
        """
        Create a page under `parent_id` (a page or data-source the integration can
        access) containing the daily radar report. Blocked unless the HITL gate
        approves and the server spec permits writes.
        """
        args = {
            "parent": {"page_id": parent_id},
            "pages": [{
                "properties": {"title": title},
                "content": markdown_body,
            }],
        }
        return self.client.call_tool("notion-create-pages", args)
