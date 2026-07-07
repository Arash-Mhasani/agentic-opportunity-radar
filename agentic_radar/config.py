"""
Central configuration for the Agentic Opportunity Radar.

Design rules honored here:
  * No hardcoded credentials — every secret is read from the environment.
  * Correct, current model IDs — 'claude-fable-5' for deep reasoning,
    Sonnet/Haiku tiers for curation and classification.
  * One place to swap the model tier (Agent = Model + Harness → the Model is config).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "")


# ── Model tier (the swappable half of Agent = Model + Harness) ────────────────
# Real, current Anthropic API model strings.
MODEL_BUSINESS = _env("RADAR_MODEL_BUSINESS", "claude-fable-5")       # deep reasoning
MODEL_CURATION = _env("RADAR_MODEL_CURATION", "claude-sonnet-4-6")    # curation
MODEL_SOURCE = _env("RADAR_MODEL_SOURCE", "claude-sonnet-4-6")        # skill execution
MODEL_CHEAP = _env("RADAR_MODEL_CHEAP", "claude-haiku-4-5")           # classification
# Optional heterogeneous judge for the Elo tournament (model diversity reduces
# self-evaluation bias). If unset / SDK missing, the harness falls back to a
# Claude judge and records reduced-diversity in the trace.
MODEL_JUDGE_GEMINI = _env("RADAR_MODEL_JUDGE", "gemini-2.5-pro")


@dataclass
class RadarConfig:
    # credentials (all optional → graceful degradation)
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))

    # models
    model_business: str = MODEL_BUSINESS
    model_curation: str = MODEL_CURATION
    model_source: str = MODEL_SOURCE
    model_cheap: str = MODEL_CHEAP
    model_judge: str = MODEL_JUDGE_GEMINI

    # deterministic guardrails ("shift intelligence left")
    min_research_signals: int = int(_env("RADAR_MIN_RESEARCH_SIGNALS", "100") or 100)
    elo_k_factor: float = 32.0
    elo_default: float = 1200.0

    # Denial-of-Wallet budget (per pipeline cycle)
    max_model_calls: int = int(_env("RADAR_MAX_MODEL_CALLS", "200") or 200)
    max_tool_iterations: int = int(_env("RADAR_MAX_TOOL_ITERS", "6") or 6)
    max_usd_budget: float = float(_env("RADAR_MAX_USD", "15") or 15)

    # behavior toggles
    offline: bool = field(default_factory=lambda: _env_bool("RADAR_OFFLINE", False))
    require_write_confirmation: bool = field(
        default_factory=lambda: _env_bool("RADAR_REQUIRE_WRITE_CONFIRMATION", True)
    )

    # Day-5 Zero-Trust governance
    environment: str = field(default_factory=lambda: _env("RADAR_ENV", "development") or "development")
    role: str = field(default_factory=lambda: _env("RADAR_ROLE", "radar") or "radar")
    enable_policy_server: bool = field(default_factory=lambda: _env_bool("RADAR_ENABLE_POLICY", True))

    # paths
    base_dir: str = field(default_factory=lambda: os.path.dirname(os.path.abspath(__file__)))

    @property
    def db_path(self) -> str:
        return _env("RADAR_DB_PATH", os.path.join(self.base_dir, "memory", "dynamic_memory.db"))

    @property
    def static_memory_path(self) -> str:
        return os.path.join(self.base_dir, "memory", "static_memory.json")

    @property
    def message_bus_dir(self) -> str:
        return _env("RADAR_BUS_DIR", os.path.join(self.base_dir, "message_bus"))

    @property
    def skills_dir(self) -> str:
        return os.path.join(self.base_dir, "skills")


# ── MCP server registry (consume, don't build — Day 2 sl.16) ──────────────────
# Credentials are passed by ENV VAR NAME, never inlined. read_only is enforced
# by mcp_client unless a server is explicitly allowed to write.
@dataclass
class MCPServerSpec:
    name: str
    transport: str               # "stdio" | "streamable-http"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    url: Optional[str] = None
    env_passthrough: List[str] = field(default_factory=list)  # env var NAMES to forward
    read_only: bool = True
    write_tools: List[str] = field(default_factory=list)      # tool names that mutate state


def default_mcp_registry() -> Dict[str, MCPServerSpec]:
    """The vetted, first-party MCP servers this project consumes."""
    return {
        # Official Notion MCP (local server, headless-friendly via integration token).
        # Reads use a read-only integration token; writes are HITL-gated.
        "notion": MCPServerSpec(
            name="notion",
            transport="stdio",
            command="npx",
            args=["-y", "@notionhq/notion-mcp-server"],
            env_passthrough=["NOTION_TOKEN"],
            read_only=_env_bool("NOTION_READ_ONLY", True),
            write_tools=[
                "notion-create-pages", "notion-update-page",
                "notion-append-block-children", "API-post-page", "API-patch-block-children",
            ],
        ),
        # yt-mcp: reads YOUR OWN playlists via getMyPlaylists (OAuth) + transcripts.
        "youtube": MCPServerSpec(
            name="youtube",
            transport="stdio",
            command="npx",
            args=["-y", "yt-mcp"],
            env_passthrough=[
                "YOUTUBE_API_KEY", "YOUTUBE_TRANSCRIPT_LANG",
                "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "OAUTH_REDIRECT_URI",
            ],
            read_only=True,
        ),
        # Official GitHub MCP registry server (read-only repo/code search).
        "github": MCPServerSpec(
            name="github",
            transport="streamable-http",
            url="https://api.githubcopilot.com/mcp/",
            env_passthrough=["GITHUB_TOKEN"],
            read_only=True,
        ),
    }


CONFIG = RadarConfig()
