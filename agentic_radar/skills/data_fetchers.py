"""
Niche data fetchers.

After the reuse audit, GitHub / HuggingFace / YouTube / Notion are *consumed* via MCP
or vetted connectors (see connectors/). What remains here are the genuinely-niche,
keyless/free pollers with no good first-party MCP equivalent:
arXiv, Semantic Scholar, Grants.gov, HackerNews, Reddit, SEC.

(X/Twitter has no compliant first-party MCP and is the acknowledged weak link; the
stub returns nothing unless you wire your own compliant source.)
"""
from __future__ import annotations

import os
import time
import random
import re
import urllib.parse
import datetime
import logging
from typing import List, Dict, Any, Optional

import requests
try:
    import feedparser
except ImportError:
    feedparser = None

log = logging.getLogger("radar.fetch")


def request_with_backoff(method: str, url: str, *, headers=None, params=None,
                         json_body=None, timeout: int = 15, max_attempts: int = 4,
                         base_sleep: float = 1.5) -> requests.Response:
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "agentic-radar/1.0 python-requests")
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(method, url, headers=hdrs, params=params,
                                    json=json_body, timeout=timeout)
            if resp.status_code == 429:
                ra = resp.headers.get("Retry-After")
                sleep_s = float(ra) if ra else base_sleep * (2 ** (attempt - 1))
                time.sleep(min(sleep_s * random.uniform(0.9, 1.1), 60)); continue
            if 500 <= resp.status_code < 600:
                time.sleep(base_sleep * (2 ** (attempt - 1)) * random.uniform(0.9, 1.1)); continue
            resp.raise_for_status()
            return resp
        except Exception:
            if attempt >= max_attempts:
                raise
            time.sleep(base_sleep * (2 ** (attempt - 1)))
    raise RuntimeError("request_with_backoff exhausted")


def parse_feed(url: str):
    resp = request_with_backoff("GET", url, timeout=15, max_attempts=2)
    return feedparser.parse(resp.content)


class DataFetcher:
    """Niche pollers only. Each method returns normalized signal dicts and degrades to []."""

    def fetch_arxiv_papers(self, categories: List[str], queries: List[str]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        if not feedparser:
            return signals
        def _pull(url, cat_label):
            try:
                for e in parse_feed(url).entries:
                    signals.append({"timestamp": e.get("updated", datetime.datetime.now(datetime.timezone.utc).isoformat()),
                                    "source": "arXiv", "title": e.get("title", "").replace("\n", " "),
                                    "url": e.get("link", ""),
                                    "summary": e.get("summary", "").replace("\n", " ")[:500],
                                    "category": "paper"})
            except Exception as ex:
                log.warning("arXiv %s: %s", cat_label, ex)
        for cat in categories:
            _pull(f"https://export.arxiv.org/api/query?search_query=cat:{cat}&sortBy=lastUpdatedDate&sortOrder=descending&max_results=15", cat)
            time.sleep(0.4)
        for q in queries:
            _pull(f"https://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(q)}&sortBy=submittedDate&sortOrder=descending&max_results=8", q)
            time.sleep(0.4)
        return signals

    def fetch_semantic_scholar(self, queries: List[str]) -> List[Dict[str, Any]]:
        signals = []
        for q in queries:
            try:
                resp = request_with_backoff("GET", "https://api.semanticscholar.org/graph/v1/paper/search",
                                            params={"query": q, "limit": 10,
                                                    "fields": "title,url,abstract,year,citationCount,publicationDate",
                                                    "year": "2024-2026"}, timeout=10, max_attempts=2)
                for p in resp.json().get("data", []):
                    cites = p.get("citationCount", 0) or 0
                    signals.append({"timestamp": p.get("publicationDate") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                    "source": "SemanticScholar",
                                    "title": f"{p.get('title','')} (cited:{cites})",
                                    "url": p.get("url", ""), "summary": (p.get("abstract") or "")[:500],
                                    "category": "paper"})
            except Exception as e:
                log.warning("SemanticScholar '%s': %s", q, e)
            time.sleep(1)
        return signals

    def fetch_grant_solicitations(self, keywords: List[str]) -> List[Dict[str, Any]]:
        signals, seen = [], set()
        for kw in keywords:
            try:
                resp = request_with_backoff("POST", "https://api.grants.gov/v1/api/search2",
                                            json_body={"keyword": kw, "oppStatuses": "posted", "rows": 12},
                                            timeout=20, max_attempts=2)
                for h in (resp.json().get("data") or {}).get("oppHits") or []:
                    if not isinstance(h, dict):
                        continue
                    title = (h.get("title") or "").strip()
                    num = h.get("number") or title
                    if not title or num in seen:
                        continue
                    seen.add(num)
                    agency = h.get("agencyName") or h.get("agencyCode") or "Federal"
                    close = (h.get("closeDate") or "").strip()
                    oid = h.get("id", "")
                    signals.append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "source": "GrantsGov",
                                    "title": f"[{agency}] {title}" + (f" (closes {close})" if close else ""),
                                    "url": f"https://www.grants.gov/search-results-detail/{oid}" if oid else "https://www.grants.gov/search-grants",
                                    "summary": f"Open federal funding {num}. Matched: {kw}.", "category": "grant"})
            except Exception as e:
                log.warning("Grants.gov '%s': %s", kw, e)
        return signals

    def fetch_hackernews(self, queries: List[str]) -> List[Dict[str, Any]]:
        signals = []
        for q in queries:
            try:
                resp = request_with_backoff("GET", "https://hn.algolia.com/api/v1/search_by_date",
                                            params={"query": q, "tags": "story", "hitsPerPage": 5,
                                                    "numericFilters": "points>5"}, timeout=10, max_attempts=2)
                for hit in resp.json().get("hits", []):
                    title = hit.get("title") or ""
                    if not title:
                        continue
                    url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"
                    signals.append({"timestamp": hit.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
                                    "source": "HackerNews",
                                    "title": f"{title} ({hit.get('points',0)}pts)", "url": url,
                                    "summary": f"HN: https://news.ycombinator.com/item?id={hit.get('objectID','')}",
                                    "category": "market"})
            except Exception as e:
                log.warning("HackerNews '%s': %s", q, e)
            time.sleep(0.3)
        return signals

    def fetch_reddit_posts(self, keywords: List[str]) -> List[Dict[str, Any]]:
        signals = []
        for kw in keywords:
            try:
                resp = request_with_backoff("GET", "https://www.reddit.com/search.json",
                                            params={"q": kw, "sort": "new", "limit": 5, "t": "month"},
                                            headers={"User-Agent": "agentic-radar/1.0"}, timeout=10, max_attempts=2)
                for child in resp.json().get("data", {}).get("children", []):
                    d = child.get("data", {})
                    signals.append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "source": "Reddit",
                                    "title": d.get("title", ""),
                                    "url": "https://www.reddit.com" + d.get("permalink", ""),
                                    "summary": (d.get("selftext") or "")[:400], "category": "social"})
            except Exception as e:
                log.warning("Reddit '%s': %s", kw, e)
            time.sleep(0.5)
        return signals

    def fetch_sec_filings_robotics(self) -> List[Dict[str, Any]]:
        signals = []
        try:
            resp = request_with_backoff("GET", "https://efts.sec.gov/LATEST/search-index?q=%22humanoid%20robot%22&forms=8-K",
                                        timeout=12, max_attempts=2)
            # SEC EDGAR full-text endpoint shape varies; best-effort, degrade quietly.
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            for hit in (data.get("hits", {}) or {}).get("hits", [])[:8]:
                src = hit.get("_source", {})
                signals.append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "source": "SEC",
                                "title": f"SEC filing: {src.get('display_names',['?'])[0]}",
                                "url": "https://www.sec.gov/cgi-bin/browse-edgar",
                                "summary": "8-K mentioning humanoid robotics.", "category": "market"})
        except Exception as e:
            log.warning("SEC: %s", e)
        return signals

    def fetch_twitter_sentiment(self, handles: List[str], keywords: List[str]) -> List[Dict[str, Any]]:
        # X/Twitter has no compliant first-party MCP; intentionally returns nothing
        # unless you wire a compliant source. Do not scrape.
        log.info("X/Twitter source not configured (no compliant MCP); skipping.")
        return []
