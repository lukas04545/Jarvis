"""Global news tracking.

Aggregates headlines from a spread of international wire services and public
broadcasters via their RSS feeds, normalises them into a single stream, dedupes,
and tags each item with a coarse region + topic so the terminal can filter.

No API keys required — all sources are public RSS.
"""
from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from typing import Dict, List

import feedparser
import requests

from config import config
from jarvis.cache import cache

# (label, region, url) — a deliberately diverse, multi-pole source set.
FEEDS = [
    ("BBC World", "Global", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "MENA", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Reuters World", "Global", "https://news.google.com/rss/search?q=when:24h+world&hl=en-US&gl=US&ceid=US:en"),
    ("AP Top", "Americas", "https://news.google.com/rss/search?q=when:24h+source:Associated+Press&hl=en-US&gl=US&ceid=US:en"),
    ("DW Europe", "Europe", "https://rss.dw.com/rdf/rss-en-eu"),
    ("NHK World", "Asia", "https://www3.nhk.or.jp/nhkworld/en/news/feeds/rss/all.xml"),
    ("France24", "Europe", "https://www.france24.com/en/rss"),
    ("CNA Asia", "Asia", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml"),
]

# Lightweight keyword → topic tagging for the terminal's topic filter / heatmap.
TOPIC_KEYWORDS = {
    "CONFLICT": ["war", "strike", "military", "missile", "troops", "ceasefire", "attack", "clash", "border"],
    "MARKETS": ["market", "stocks", "economy", "inflation", "rate", "trade", "tariff", "oil", "gdp", "bond"],
    "POLITICS": ["election", "president", "minister", "parliament", "vote", "summit", "sanction", "diplomat"],
    "DISASTER": ["earthquake", "flood", "storm", "wildfire", "hurricane", "cyclone", "evacuat", "drought"],
    "TECH": ["ai", "chip", "cyber", "hack", "satellite", "space", "semiconductor", "data breach"],
    "HEALTH": ["virus", "outbreak", "disease", "pandemic", "vaccine", "health"],
}

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text or "")).strip()


def _topic_for(text: str) -> str:
    low = text.lower()
    best, score = "GENERAL", 0
    for topic, words in TOPIC_KEYWORDS.items():
        hits = sum(1 for w in words if w in low)
        if hits > score:
            best, score = topic, hits
    return best


def _entry_time(entry) -> float:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return time.mktime(t)
    return time.time()


def _fetch_feed(label: str, region: str, url: str) -> List[Dict]:
    # feedparser can fetch directly, but going through requests lets us enforce
    # a timeout and a UA that some CDNs require.
    resp = requests.get(
        url,
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": "JARVIS-Terminal/1.0 (+intelligence-feed)"},
    )
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    out: List[Dict] = []
    for entry in parsed.entries[:20]:
        title = _clean(getattr(entry, "title", ""))
        if not title:
            continue
        summary = _clean(getattr(entry, "summary", ""))[:280]
        ts = _entry_time(entry)
        out.append(
            {
                "title": title,
                "summary": summary,
                "link": getattr(entry, "link", ""),
                "source": label,
                "region": region,
                "topic": _topic_for(f"{title} {summary}"),
                "ts": ts,
                "time": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M"),
            }
        )
    return out


def _aggregate() -> List[Dict]:
    items: List[Dict] = []
    for label, region, url in FEEDS:
        try:
            items.extend(_fetch_feed(label, region, url))
        except Exception:
            # One dead feed must not blank the whole wire.
            continue

    # Dedupe on a normalised title prefix (wires often re-run the same story).
    seen: set[str] = set()
    deduped: List[Dict] = []
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped[:80]


def get_news() -> Dict:
    """Return the aggregated, cached global news stream + light analytics.

    If every live feed is unreachable we serve a clearly-flagged SIMULATED
    sample so the terminal stays demonstrable instead of going blank.
    """
    items = cache.get_or_set("news", config.CACHE_TTL, _aggregate)

    if not items:
        from jarvis import fallback

        data = fallback.news()
        data["age"] = cache.age("news")
        return data

    topic_counts: Dict[str, int] = {}
    region_counts: Dict[str, int] = {}
    for it in items:
        topic_counts[it["topic"]] = topic_counts.get(it["topic"], 0) + 1
        region_counts[it["region"]] = region_counts.get(it["region"], 0) + 1

    return {
        "count": len(items),
        "items": items,
        "topics": topic_counts,
        "regions": region_counts,
        "simulated": False,
        "age": cache.age("news"),
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }
