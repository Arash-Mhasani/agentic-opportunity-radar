"""
YouTube connector — reads YOUR OWN curated playlist and its transcripts via the
vetted `yt-mcp` server (consume, don't build).

Auth:
  * YOUTUBE_API_KEY  — required for public reads (playlists, search, transcripts).
  * For YOUR private lists (Watch Later, private playlists), also set
    GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / OAUTH_REDIRECT_URI and use
    `get_my_playlists` (yt-mcp's getMyPlaylists). Read-only.

Returns normalized signal dicts (category="video") ready for the message bus, or an
empty list if unavailable.
"""
from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from connectors.mcp_client import MCPClient

log = logging.getLogger("radar.youtube")


class YouTubeConnector:
    def __init__(self, server_spec, policy_server=None, context_state=None, role: str = "radar", env: str = "development"):
        self.client = MCPClient(server_spec, require_confirmation=False,  # read-only
                                policy_server=policy_server, context_state=context_state, role=role, env=env)

    def available(self) -> bool:
        return self.client.available()

    def _now(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def my_playlists(self) -> List[Dict[str, Any]]:
        """List the signed-in user's own playlists (requires OAuth env vars)."""
        res = self.client.call_tool("getMyPlaylists", {})
        return self._as_list(res)

    def playlist_videos(self, playlist_id: str, max_results: int = 15) -> List[Dict[str, Any]]:
        res = self.client.call_tool("getPlaylistItems",
                                    {"playlistId": playlist_id, "maxResults": max_results})
        return self._as_list(res)

    def fetch_playlist_signals(self, playlist_id: str, max_results: int = 15) -> List[Dict[str, Any]]:
        """
        Pull videos from YOUR playlist, fetch transcripts, return normalized signals
        for the bus. Each signal carries the transcript so the analyze-youtube-transcript
        skill can extract bottlenecks.
        """
        if not self.available():
            log.info("YouTube MCP unavailable; returning no video signals.")
            return []
        signals: List[Dict[str, Any]] = []
        for v in self.playlist_videos(playlist_id, max_results):
            vid = v.get("videoId") or v.get("id") or ""
            title = v.get("title", "")
            transcript = self._transcript(vid)
            signals.append({
                "timestamp": self._now(), "source": "youtube",
                "title": title or f"video {vid}",
                "url": f"https://youtube.com/watch?v={vid}" if vid else "",
                "summary": (transcript or "")[:8000],
                "category": "video",
            })
        return signals

    def _transcript(self, video_id: str) -> str:
        if not video_id:
            return ""
        res = self.client.call_tool("getTranscript", {"videoId": video_id})
        if res.ok and res.content:
            return res.content if isinstance(res.content, str) else json.dumps(res.content)
        return ""

    @staticmethod
    def _as_list(res) -> List[Dict[str, Any]]:
        if not getattr(res, "ok", False) or res.content is None:
            return []
        c = res.content
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except Exception:
                return []
        if isinstance(c, dict):
            for key in ("items", "playlists", "videos", "data"):
                if key in c and isinstance(c[key], list):
                    return c[key]
            return [c]
        return c if isinstance(c, list) else []
