"""
Memory manager.

Carries over the v2/agentic schema (ideas, signal_memory, user_feedback) and fixes
the dead-evergreen bug: nothing in the old pipeline ever set is_evergreen=1, so the
dashboard's "Remove evergreen" button governed an empty set. We add an explicit
`promote_evergreen` step that the curation node calls.
"""
from __future__ import annotations

import sqlite3
import json
import os
import logging
import hashlib
from typing import Dict, Any, List

log = logging.getLogger("radar.memory")


class MemoryManager:
    def __init__(self, db_path: str, static_config_path: str):
        self.db_path = db_path
        self.static_config_path = static_config_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
        self.static_memory = self._load_static_memory()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS ideas (
                id TEXT PRIMARY KEY, title TEXT, description TEXT,
                elo_score REAL DEFAULT 1200.0, conviction_score REAL DEFAULT 0.0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active')""")
            c.execute("""CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT DEFAULT 'general',
                feedback_text TEXT, processed BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            c.execute("""CREATE TABLE IF NOT EXISTS signal_memory (
                url_hash TEXT PRIMARY KEY, url TEXT, source TEXT, summary TEXT,
                is_evergreen BOOLEAN DEFAULT 0,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    # ── static profile / constraints (always-on) ─────────────────────────────
    def _load_static_memory(self) -> Dict[str, Any]:
        if not os.path.exists(self.static_config_path):
            log.warning("static memory not found: %s", self.static_config_path)
            return {}
        with open(self.static_config_path, encoding="utf-8") as f:
            return json.load(f)

    def get_static_context(self) -> str:
        if not self.static_memory:
            return ""
        p = self.static_memory.get("profile", {})
        cons = self.static_memory.get("constraints", {})
        out = ["### FOUNDER PROFILE ###", f"Name: {p.get('name')}", f"Goal: {p.get('goal')}",
               f"Background (asset, not a filter): {', '.join(p.get('background', []))}",
               "", "### HARD CONSTRAINTS (always hold) ###"]
        for k, v in cons.items():
            out.append(f"- {k}: {v}")
        good = self.static_memory.get("few_shot_good_opportunities", [])
        bad = self.static_memory.get("few_shot_bad_opportunities", [])
        if good:
            out.append("\n### GOOD EXAMPLES ###")
            out += [f"- {g['description']}" for g in good]
        if bad:
            out.append("\n### BAD EXAMPLES (avoid) ###")
            out += [f"- {b['description']}" for b in bad]
        return "\n".join(out)

    # ── ideas + Elo ──────────────────────────────────────────────────────────
    def save_idea(self, idea_id: str, title: str, description: str):
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO ideas (id, title, description) VALUES (?,?,?)",
                      (idea_id, title, description))

    def update_elo(self, idea_id: str, new_elo: float):
        with self._conn() as c:
            c.execute("UPDATE ideas SET elo_score=?, last_updated=CURRENT_TIMESTAMP WHERE id=?",
                      (new_elo, idea_id))

    def get_top_ideas(self, limit: int = 5) -> List[Dict[str, Any]]:
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("""SELECT id,title,description,elo_score FROM ideas
                                WHERE status='active' ORDER BY elo_score DESC LIMIT ?""",
                             (limit,)).fetchall()
        return [dict(r) for r in rows]

    def prune_memory(self, stale_days: int = 7) -> int:
        with self._conn() as c:
            cur = c.execute(f"""UPDATE ideas SET status='archived'
                                WHERE last_updated < datetime('now','-{int(stale_days)} days')
                                AND status='active'""")
            n = cur.rowcount
        log.info("Pruned %d stale ideas.", n)
        return n

    # ── signal memory + REAL evergreen promotion ─────────────────────────────
    @staticmethod
    def _hash_url(url: str) -> str:
        return hashlib.sha256((url or "").encode()).hexdigest()

    def is_url_processed(self, url: str, stale_days: int = 30) -> bool:
        with self._conn() as c:
            row = c.execute(f"""SELECT 1 FROM signal_memory WHERE url_hash=?
                                AND last_seen >= datetime('now','-{int(stale_days)} days')""",
                            (self._hash_url(url),)).fetchone()
        return row is not None

    def mark_url_processed(self, url: str, source: str, summary: str, is_evergreen: bool = False):
        with self._conn() as c:
            c.execute("""INSERT INTO signal_memory (url_hash,url,source,summary,is_evergreen,last_seen)
                         VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
                         ON CONFLICT(url_hash) DO UPDATE SET summary=excluded.summary,
                           is_evergreen=MAX(signal_memory.is_evergreen, excluded.is_evergreen),
                           last_seen=CURRENT_TIMESTAMP""",
                      (self._hash_url(url), url, source, summary, int(is_evergreen)))

    def promote_evergreen(self, url: str) -> None:
        """The missing step: curation flags a record foundational → is_evergreen=1."""
        with self._conn() as c:
            c.execute("UPDATE signal_memory SET is_evergreen=1 WHERE url_hash=?",
                      (self._hash_url(url),))

    def remove_evergreen(self, url_hash: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE signal_memory SET is_evergreen=0 WHERE url_hash=?", (url_hash,))

    def get_evergreen_signals(self, limit: int = 20) -> str:
        with self._conn() as c:
            rows = c.execute("""SELECT url_hash,source,summary FROM signal_memory
                                WHERE is_evergreen=1 ORDER BY last_seen DESC LIMIT ?""",
                             (limit,)).fetchall()
        if not rows:
            return "### EVERGREEN FOUNDATIONAL KNOWLEDGE ###\n(none yet)"
        out = ["### EVERGREEN FOUNDATIONAL KNOWLEDGE ###"]
        for i, (h, src, summ) in enumerate(rows, 1):
            out.append(f"{i}. [{(src or '?').upper()}] (id:{h[:8]}) {summ}")
        return "\n".join(out)

    # ── feedback ─────────────────────────────────────────────────────────────
    def add_feedback(self, category: str, feedback_text: str):
        with self._conn() as c:
            c.execute("INSERT INTO user_feedback (category,feedback_text) VALUES (?,?)",
                      (category, feedback_text))

    def get_unprocessed_feedback(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        with self._conn() as c:
            rows = c.execute("SELECT id,category,feedback_text FROM user_feedback WHERE processed=0").fetchall()
            for _id, cat, text in rows:
                out.setdefault(cat, []).append(text)
                c.execute("UPDATE user_feedback SET processed=1 WHERE id=?", (_id,))
        return out
