"""
The 7 evaluation dimensions (Day-4 sl.30), adapted from vibe-coding to this radar.

User-facing (outside):
  1. Intent satisfaction      — do the opportunities respect the founder's actual
                                 intent/constraints (solo, <=20h, low-capital, robotics)?
  2. Functional correctness   — is the output valid JSON with every required field?
  3. Visual/behavioral        — does the rendered report build without error?
  4. Cost & efficiency        — model calls, tool iterations, est USD, signal floor.
Internal (inside):
  5. Quality & conventions    — are ideas specific and non-generic (named technique +
                                 named bottleneck), not boilerplate?
  6. Trajectory quality       — right skill picked per source; right sources read.
  7. Self-repair              — on a bad fetch / malformed JSON, does the system recover
                                 rather than fabricate or crash?
Transversal: Safety & RAI    — no fabricated competitor claims, no hardcoded creds,
                                 writes gated, IP-safe.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

REQUIRED_IDEA_FIELDS = ["id", "title", "description", "revenue_path", "adjacent_tech_transfer"]
_GENERIC = re.compile(r"\b(synerg|leverage ai|revolutioniz|cutting[- ]edge|next[- ]gen|disrupt)\b", re.I)
# Founder hard-constraints encoded as a rejection filter: no building robot HARDWARE
# and no building a foundation model. (Software *for* robots is allowed and is the point.)
_BANNED = re.compile(
    r"(foundation model"
    r"|humanoid robot|robot arm|legged robot|robotic arm"
    r"|build (a |an |the |your )?(new )?(robot|humanoid|drone)\b"
    r"|\bhardware (units?|startup|company|product|business|device)\b"
    r"|sell hardware|manufacture)",
    re.I,
)


# ── dimension 2: functional correctness (deterministic) ──────────────────────
def score_functional_correctness(ideas: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(ideas, list) or not ideas:
        return {"pass": False, "score": 0.0, "detail": "no ideas / not a list"}
    ok = 0
    for idea in ideas:
        if isinstance(idea, dict) and all(idea.get(f) for f in REQUIRED_IDEA_FIELDS):
            ok += 1
    return {"pass": ok == len(ideas), "score": ok / len(ideas),
            "detail": f"{ok}/{len(ideas)} ideas have all required fields"}


# ── dimension 1 + RAI: intent / constraint compliance (deterministic) ────────
def score_constraint_compliance(ideas: List[Dict[str, Any]]) -> Dict[str, Any]:
    violations = []
    for idea in ideas or []:
        blob = json.dumps(idea, default=str).lower()
        if _BANNED.search(blob):
            violations.append(idea.get("id") or idea.get("title"))
    return {"pass": not violations, "score": 0.0 if violations else 1.0,
            "detail": f"banned-pattern violations: {violations}" if violations else "no constraint violations"}


# ── dimension 5: quality & conventions (deterministic heuristic) ─────────────
def score_quality(ideas: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not ideas:
        return {"pass": False, "score": 0.0, "detail": "no ideas"}
    good = 0
    for idea in ideas:
        blob = (idea.get("description", "") + " " + idea.get("adjacent_tech_transfer", ""))
        specific = len(blob.split()) >= 8 and bool(idea.get("adjacent_tech_transfer"))
        generic = bool(_GENERIC.search(blob))
        if specific and not generic:
            good += 1
    return {"pass": good >= max(1, len(ideas) // 2), "score": good / len(ideas),
            "detail": f"{good}/{len(ideas)} ideas specific & non-generic"}


# ── dimension 6: trajectory quality (routing correctness) ────────────────────
def score_trajectory(registry, cases: List[Dict[str, str]]) -> Dict[str, Any]:
    ok = 0
    detail = []
    for case in cases:
        skill = registry.for_category(case["category"])
        got = skill.name if skill else None
        if got == case["expected_skill"]:
            ok += 1
        else:
            detail.append(f"{case['category']}→{got} (want {case['expected_skill']})")
    return {"pass": ok == len(cases), "score": ok / max(1, len(cases)),
            "detail": "; ".join(detail) or "all categories routed correctly"}


# ── the LLM-as-judge rubric for dimensions that need judgment (online) ────────
JUDGE_RUBRIC = """\
Score this opportunity on three dimensions, 1-5 each. Return JSON only:
{"intent_fit": n, "specificity": n, "feasibility_solo": n, "notes": "..."}
- intent_fit: respects solo / <=20h-week / low-capital / robotics, ranked by opportunity.
- specificity: names a concrete adjacent technique AND a concrete bottleneck.
- feasibility_solo: a single low-capital founder could start the first motion in <=2 weeks.
"""
