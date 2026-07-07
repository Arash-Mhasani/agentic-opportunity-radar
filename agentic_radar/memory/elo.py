"""
Deterministic Elo — the arithmetic the v5 migration wrongly handed to an LLM.

"Shift intelligence left" (Day-3 sl.41): subjective judgment (which idea is better)
is the LLM's job; the *math* (rating updates, expected scores, ordering) is pure,
testable code. This module is fully unit-tested and never calls a model.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Tuple


def expected_score(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def update_pair(ra: float, rb: float, a_won: bool, k: float = 32.0) -> Tuple[float, float]:
    ea = expected_score(ra, rb)
    sa = 1.0 if a_won else 0.0
    ra2 = ra + k * (sa - ea)
    rb2 = rb + k * ((1.0 - sa) - (1.0 - ea))
    return ra2, rb2


def run_tournament(
    ideas: List[Dict],
    judge: Callable[[Dict, Dict], bool],
    *,
    k: float = 32.0,
    default_elo: float = 1200.0,
    rounds: int = 1,
) -> List[Dict]:
    """
    ideas: list of dicts each with at least 'id'; optional existing 'elo_score'.
    judge(a, b) -> True if a beats b. Called by the orchestrator with a swapped-position
    LLM judge to neutralize ordering bias.
    Returns the same list (copies) with updated 'elo_score', sorted desc.
    """
    pool = []
    for it in ideas:
        c = dict(it)
        c.setdefault("elo_score", default_elo)
        c["_wins"] = 0
        c["_matches"] = 0
        pool.append(c)

    n = len(pool)
    for _ in range(max(1, rounds)):
        for i in range(n):
            for j in range(i + 1, n):
                a, b = pool[i], pool[j]
                a_won = judge(a, b)
                ra, rb = update_pair(a["elo_score"], b["elo_score"], a_won, k=k)
                a["elo_score"], b["elo_score"] = ra, rb
                a["_matches"] += 1
                b["_matches"] += 1
                a["_wins"] += 1 if a_won else 0
                b["_wins"] += 0 if a_won else 1

    pool.sort(key=lambda x: x["elo_score"], reverse=True)
    return pool
