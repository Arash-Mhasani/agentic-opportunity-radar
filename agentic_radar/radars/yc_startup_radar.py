"""
YC Startup Radar — robotics startups founded in the last two years.

Source: the yc-oss public dataset (https://yc-oss.github.io/api/), which mirrors the
YC company directory as JSON. We consume it rather than scraping YC.

Filters (pure, testable code — "shift intelligence left"):
  * robotics: tag/industry/one-liner mentions robotics-family terms.
  * recency: the YC batch year is >= current_year - 2. For early-stage YC companies
    the batch year is the best available proxy for "founded in the last two years";
    if an explicit founded year is present we prefer it.

Network is optional: pass `companies=[...]` to filter an in-memory list (used by tests
and by callers that already hold the dataset). Otherwise we fetch the robotics-tagged
endpoint.
"""
from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger("radar.yc")

# robotics-family detection
_ROBOTICS = re.compile(
    r"\b(robot|robotic|robotics|humanoid|manipulation|teleoperat|"
    r"actuat|end[- ]effector|gripper|legged|locomotion|embodied|"
    r"autonomous (mobile )?robot|cobot|drone|uav)\b",
    re.IGNORECASE,
)

# YC batch → year, handles "W24", "S25", "Winter 2024", "Summer 2025", "Fall 2024", "Spring 2025", "IK12"(ignore)
_BATCH_4 = re.compile(r"(20\d{2})")
_BATCH_2 = re.compile(r"\b([WSFXwsfx])(\d{2})\b")
_SEASON_2 = re.compile(r"\b(winter|summer|spring|fall|autumn)\s*'?(\d{2})\b", re.IGNORECASE)


def batch_year(batch: Optional[str]) -> Optional[int]:
    if not batch:
        return None
    b = str(batch)
    m = _BATCH_4.search(b)
    if m:
        return int(m.group(1))
    m = _SEASON_2.search(b)
    if m:
        return 2000 + int(m.group(2))
    m = _BATCH_2.search(b)
    if m:
        return 2000 + int(m.group(2))
    return None


def _founded_year(company: Dict[str, Any]) -> Optional[int]:
    for key in ("founded", "foundedYear", "founded_year", "yearFounded"):
        v = company.get(key)
        if isinstance(v, int) and 2000 <= v <= 2100:
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    return batch_year(company.get("batch"))


def _is_robotics(company: Dict[str, Any]) -> bool:
    hay = " ".join(str(company.get(k, "")) for k in ("name", "oneLiner", "one_liner",
                                                     "longDescription", "long_description",
                                                     "industry", "subindustry"))
    tags = company.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    hay += " " + " ".join(str(t) for t in tags)
    return bool(_ROBOTICS.search(hay))


def filter_robotics_recent(companies: List[Dict[str, Any]], *, years: int = 2,
                           now: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
    now = now or datetime.date.today()
    cutoff = now.year - years
    out = []
    for c in companies:
        if not _is_robotics(c):
            continue
        fy = _founded_year(c)
        if fy is None or fy < cutoff:
            continue
        out.append(c)
    return out


def to_signals(companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    sigs = []
    for c in companies:
        name = c.get("name", "?")
        fy = _founded_year(c)
        one = c.get("oneLiner") or c.get("one_liner") or ""
        sigs.append({
            "timestamp": now, "source": "YCombinator",
            "title": f"[YC {c.get('batch','?')}] {name} (founded ~{fy})",
            "url": c.get("website") or c.get("url") or f"https://www.ycombinator.com/companies/{c.get('slug','')}",
            "summary": one[:500],
            "category": "startup",
        })
    return sigs


def fetch_yc_robotics_recent(years: int = 2, companies: Optional[List[Dict[str, Any]]] = None,
                             timeout: int = 20) -> List[Dict[str, Any]]:
    """
    Return normalized signals for robotics YC startups founded in the last `years`.
    If `companies` is provided (tests/offline), filter that; else fetch yc-oss.
    """
    if companies is None:
        companies = _fetch_yc_oss(timeout=timeout)
    recent = filter_robotics_recent(companies, years=years)
    log.info("YC radar: %d robotics startups founded in last %d years (of %d).",
             len(recent), years, len(companies))
    return to_signals(recent)


def _fetch_yc_oss(timeout: int = 20) -> List[Dict[str, Any]]:  # pragma: no cover (network)
    import requests
    # robotics-tagged endpoint first; fall back to all-companies and filter.
    for url in ("https://yc-oss.github.io/api/tags/robotics.json",
                "https://yc-oss.github.io/api/industries/robotics.json",
                "https://yc-oss.github.io/api/companies/all.json"):
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "agentic-radar/1.0"})
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("companies", [])
        except Exception as e:
            log.warning("yc-oss fetch failed (%s): %s", url, e)
    return []
