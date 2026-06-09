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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List

import feedparser
import requests

from config import config
from jarvis import http
from jarvis.cache import cache

def _g(query: str) -> str:
    """Build a Google-News RSS search URL (last 24h, English)."""
    return ("https://news.google.com/rss/search?q="
            + query.replace(" ", "+") + "+when:1d&hl=en-US&gl=US&ceid=US:en")


# (label, region, url) — a deliberately broad, multi-pole, multi-domain source
# set. Outlets give breadth; Google-News topic queries give depth on the
# domains the ORACLE forecasts over (conflict, markets, cyber, space, disease…).
FEEDS = [
    # ── International wires / broadcasters ────────────────────────────────
    ("BBC World", "Global", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Al Jazeera", "MENA", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("Guardian World", "Global", "https://www.theguardian.com/world/rss"),
    ("Reuters World", "Global", _g("world")),
    ("AP Top", "Americas", _g("source:Associated Press")),
    ("NPR World", "Americas", "https://feeds.npr.org/1004/rss.xml"),
    ("DW Europe", "Europe", "https://rss.dw.com/rdf/rss-en-eu"),
    ("France24", "Europe", "https://www.france24.com/en/rss"),
    ("Euronews", "Europe", "https://www.euronews.com/rss?level=theme&name=news"),
    ("NHK World", "Asia", "https://www3.nhk.or.jp/nhkworld/en/news/feeds/rss/all.xml"),
    ("CNA Asia", "Asia", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml"),
    ("Times of India", "Asia", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
    ("AllAfrica", "Africa", "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf"),
    # ── Markets / economy ─────────────────────────────────────────────────
    ("CNBC Markets", "Global", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("Economy Wire", "Global", _g("central bank OR inflation OR recession OR markets")),
    ("Energy/Oil", "Global", _g("oil prices OR OPEC OR energy crisis")),
    # ── Conflict / security / geopolitics ─────────────────────────────────
    ("Conflict Wire", "Global", _g("military conflict OR offensive OR ceasefire OR strikes")),
    ("Sanctions/Diplo", "Global", _g("sanctions OR summit OR diplomatic OR treaty")),
    ("Cyber Wire", "Global", _g("cyberattack OR data breach OR ransomware")),
    # ── Science / space / tech / health ───────────────────────────────────
    ("Ars Technica", "Global", "https://feeds.arstechnica.com/arstechnica/index"),
    ("The Verge", "Global", "https://www.theverge.com/rss/index.xml"),
    ("NASA Breaking", "Global", "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
    ("ScienceDaily", "Global", "https://www.sciencedaily.com/rss/top/science.xml"),
    ("Outbreak Wire", "Global", _g("outbreak OR epidemic OR virus OR public health emergency")),
]

# Lightweight keyword → topic tagging for the terminal's topic filter / heatmap
# and the ORACLE's per-domain signal volumes.
TOPIC_KEYWORDS = {
    "CONFLICT": ["war", "strike", "military", "missile", "troops", "ceasefire", "attack",
                 "clash", "border", "offensive", "shelling", "insurgent", "airstrike"],
    "MARKETS": ["market", "stocks", "economy", "inflation", "rate", "trade", "tariff", "oil",
                "gdp", "bond", "recession", "central bank", "yields", "currency", "default"],
    "POLITICS": ["election", "president", "minister", "parliament", "vote", "summit", "sanction",
                 "diplomat", "coup", "protest", "referendum", "treaty"],
    "DISASTER": ["earthquake", "flood", "storm", "wildfire", "hurricane", "cyclone", "evacuat",
                 "drought", "volcano", "tsunami", "landslide"],
    "CYBER": ["cyberattack", "ransomware", "data breach", "hack", "malware", "ddos", "exploit"],
    "TECH": ["ai", "chip", "semiconductor", "robot", "quantum", "startup", "software"],
    "SPACE": ["satellite", "rocket", "launch", "orbit", "nasa", "spacex", "asteroid", "space"],
    "HEALTH": ["virus", "outbreak", "disease", "pandemic", "vaccine", "epidemic", "health emergency"],
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
    resp = http.get(
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
    # Fetch all feeds concurrently so a couple of slow sources can't bottleneck
    # the wire — important now that we poll ~24 feeds for maximum coverage.
    items: List[Dict] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            pool.submit(_fetch_feed, label, region, url): label
            for label, region, url in FEEDS
        }
        for fut in as_completed(futures):
            try:
                items.extend(fut.result())
            except Exception:
                continue  # one dead feed must not blank the whole wire

    # Dedupe on a normalised title prefix (wires often re-run the same story).
    seen: set[str] = set()
    deduped: List[Dict] = []
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped[:150]


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
