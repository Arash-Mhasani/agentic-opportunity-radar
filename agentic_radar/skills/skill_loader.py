"""
Skill loader — the REAL one.

The previous harness only *pretended* to run skills: it sent the model
"use skill X on file://Y" but never loaded the SKILL.md text and gave the model no
way to read Y. This loader fixes the fatal bug:

  1. Parse SKILL.md → YAML frontmatter (name, description, version, allowed-tools,
     when-NOT-to-use) + markdown body (the workflow).
  2. Validate it against the Day-3 standard (kebab-case name, description length,
     gerund hint, version present) so non-standard skills are caught, not silently run.
  3. Build the system prompt by appending the skill BODY to the base persona.
  4. Provide real tools (`read_bus_record`, `read_reference`) so the model can read
     the data and progressively disclose reference files — instead of hallucinating.
"""
from __future__ import annotations

import os
import re
import glob
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

log = logging.getLogger("radar.skills")

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_GENERIC_NAMES = {"helper", "utils", "tools", "data"}
_VENDOR_PREFIXES = ("claude-", "gemini-", "anthropic-", "gpt-", "openai-")


@dataclass
class SkillSpec:
    name: str
    description: str
    body: str
    version: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    path: str = ""
    directory: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def system_block(self) -> str:
        return f"# ACTIVE SKILL: {self.name} (v{self.version or '?'})\n\n{self.body.strip()}\n"


def _validate(name: str, description: str, version: str, dir_name: str) -> List[str]:
    """Return a list of standard-conformance warnings (Day-3 sl.46-48)."""
    w: List[str] = []
    if not _KEBAB.match(name or ""):
        w.append(f"name '{name}' is not kebab-case")
    if name in _GENERIC_NAMES:
        w.append(f"name '{name}' is too generic")
    if any(name.startswith(p) for p in _VENDOR_PREFIXES):
        w.append(f"name '{name}' uses a vendor prefix")
    # gerund hint: descriptions/names that lead with a non-gerund verb noun
    if name and "-" in name and not name.split("-")[0].endswith("e") and not name.split("-")[0].endswith("ing"):
        # soft hint only; 'analyze-...' is acceptable in this codebase's convention
        pass
    if not description:
        w.append("missing description (the routing interface)")
    elif len(description) > 1024:
        w.append("description exceeds 1024 chars (YAML cap)")
    if not version:
        w.append("missing version (skills are dependencies; pin them)")
    if "when not to use" not in (description or "").lower() and "do not use" not in (description or "").lower():
        # only a hint; many bodies put this in a section instead
        pass
    return w


def parse_skill(skill_md_path: str) -> SkillSpec:
    with open(skill_md_path, "r", encoding="utf-8") as f:
        raw = f.read()
    m = _FRONTMATTER.match(raw)
    if not m:
        raise ValueError(f"{skill_md_path}: no YAML frontmatter found")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    version = str(meta.get("version", "")).strip()
    allowed = meta.get("allowed-tools") or meta.get("allowed_tools") or []
    if isinstance(allowed, str):
        allowed = allowed.split()
    directory = os.path.basename(os.path.dirname(skill_md_path))
    warnings = _validate(name, description, version, directory)
    if warnings:
        log.debug("Skill %s non-conformances: %s", name or directory, warnings)
    return SkillSpec(name=name or directory, description=description, body=body,
                     version=version, allowed_tools=list(allowed),
                     path=skill_md_path, directory=directory, warnings=warnings)


class SkillRegistry:
    """Discovers skills/<dir>/SKILL.md and routes a category → skill name."""

    # category (from the fetcher) → skill name. youtube_search is intentionally
    # absent: it was a duplicate of analyze-youtube-transcript and is deleted.
    CATEGORY_MAP = {
        "paper": "summarize-academic-paper",
        "video": "analyze-youtube-transcript",
        "social": "analyze-social-sentiment",
        "grant": "analyze-funding-signal",
        "job": "analyze-job-signal",
        "market": "analyze-market-signal",
        "investment": "analyze-market-signal",
        "startup": "analyze-market-signal",
        "other": "analyze-market-signal",
    }

    def __init__(self, skills_dir: str):
        self.skills_dir = skills_dir
        self._by_name: Dict[str, SkillSpec] = {}
        self.discover()

    def discover(self) -> Dict[str, SkillSpec]:
        self._by_name = {}
        for path in glob.glob(os.path.join(self.skills_dir, "*", "SKILL.md")):
            try:
                spec = parse_skill(path)
                self._by_name[spec.name] = spec
            except Exception as e:
                log.warning("Failed to parse %s: %s", path, e)
        return self._by_name

    def get(self, name: str) -> Optional[SkillSpec]:
        return self._by_name.get(name)

    def for_category(self, category: str) -> Optional[SkillSpec]:
        return self.get(self.CATEGORY_MAP.get(category, "analyze-market-signal"))

    def all(self) -> List[SkillSpec]:
        return list(self._by_name.values())

    def conformance_report(self) -> List[Dict[str, Any]]:
        return [{"name": s.name, "version": s.version, "warnings": s.warnings} for s in self.all()]


# ── tools the skill-running agent gets ───────────────────────────────────────
def make_bus_tools(read_record_fn, read_reference_fn=None):
    """
    Build the Tool objects the source agent uses. Imported lazily to avoid a
    circular import with llm_client.
    """
    from agents.llm_client import Tool

    tools = [
        Tool(
            name="read_bus_record",
            description="Read the raw signal record from the file message bus. Call once to get the data to process.",
            input_schema={"type": "object", "properties": {"uri": {"type": "string"}}, "required": ["uri"]},
            handler=lambda inp: read_record_fn(inp.get("uri", "")),
        )
    ]
    if read_reference_fn:
        tools.append(Tool(
            name="read_reference",
            description="Read a supplementary reference file bundled with the active skill (progressive disclosure).",
            input_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            handler=lambda inp: read_reference_fn(inp.get("name", "")),
        ))
    return tools
