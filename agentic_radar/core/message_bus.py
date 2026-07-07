"""
File message bus.

Honest framing (correcting v5_plan_2's "flush the agent's memory" claim): the
Anthropic Messages API is already stateless per call — there is no persistent agent
memory to flush. The real win is *summarize-before-synthesize*:

  * On ingest we write the RAW signal to the bus and hand the agent only a URI.
  * The source agent reads the raw record, writes back a COMPRESSED structured record.
  * Downstream nodes (curation, business) read only the compressed records.

So a 50k-token transcript never re-enters context after it has been distilled to a
~80-token record. That is what keeps the context window small (Chroma context-rot,
ref 13) — not memory-flushing magic.
"""
from __future__ import annotations

import json
import os
import hashlib
from typing import Any, Dict, List, Optional


class MessageBus:
    def __init__(self, bus_dir: str):
        self.bus_dir = bus_dir
        os.makedirs(self.bus_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        return os.path.join(self.bus_dir, f"{key}.json")

    def write_raw(self, signal: Dict[str, Any]) -> str:
        """Persist a raw signal, return a stable file:// URI keyed by content hash."""
        blob = json.dumps(signal, sort_keys=True, default=str)
        key = "raw_" + hashlib.sha256(blob.encode()).hexdigest()[:16]
        with open(self._path(key), "w", encoding="utf-8") as f:
            f.write(blob)
        return f"file://{os.path.abspath(self._path(key))}"

    def read(self, uri: str) -> Dict[str, Any]:
        path = uri[len("file://"):] if uri.startswith("file://") else uri
        # confine reads to the bus directory (no path traversal)
        path = os.path.abspath(path)
        if not path.startswith(os.path.abspath(self.bus_dir)):
            raise ValueError("refusing to read outside the message bus")
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())

    def read_text(self, uri: str) -> str:
        """Tool-facing: return the raw record as text for the model to process."""
        try:
            return json.dumps(self.read(uri), indent=2, default=str)
        except Exception as e:
            return f"ERROR reading bus record: {e}"

    def write_compressed(self, source_uri: str, record: Dict[str, Any]) -> str:
        key = "rec_" + hashlib.sha256(source_uri.encode()).hexdigest()[:16]
        record = dict(record)
        record["_source_uri"] = source_uri
        with open(self._path(key), "w", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str))
        return f"file://{os.path.abspath(self._path(key))}"

    def list_compressed(self) -> List[Dict[str, Any]]:
        out = []
        for fn in sorted(os.listdir(self.bus_dir)):
            if fn.startswith("rec_"):
                try:
                    with open(os.path.join(self.bus_dir, fn), encoding="utf-8") as f:
                        out.append(json.loads(f.read()))
                except Exception:
                    continue
        return out
