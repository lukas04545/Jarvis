"""GDELT global-event signals — keyless.

GDELT monitors the world's news media in near-real-time. Its DOC 2.0 API
exposes, for any query, the *volume* of coverage over time and the emotional
*tone* of that coverage. Rising volume + falling tone on conflict/economic
queries is one of the most useful leading signals for the ORACLE.

API: https://api.gdeltproject.org/api/v2/doc/doc  (no key required)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

import requests

from config import config
from jarvis.cache import cache

DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Theme queries the ORACLE tracks. Kept broad so volume is statistically stable.
QUERIES = {
    "conflict": "(conflict OR war OR military OR attack OR crisis)",
    "economy": "(inflation OR recession OR \"central bank\" OR markets OR sanctions)",
    "unrest": "(protest OR coup OR \"civil unrest\" OR uprising)",
}


def _timeline_trend(query: str) -> Dict:
    """Return latest coverage volume and its trend vs the recent mean."""
    resp = requests.get(
        DOC_URL,
        params={"query": query, "mode": "timelinevol", "format": "json", "timespan": "7d"},
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": "JARVIS-Terminal/1.0"},
    )
    resp.raise_for_status()
    series = (resp.json().get("timeline") or [{}])[0].get("data", [])
    values = [float(p.get("value", 0)) for p in series if "value" in p]
    if not values:
        return {"latest": 0.0, "mean": 0.0, "trend_pct": 0.0, "points": 0}
    latest = values[-1]
    mean = sum(values) / len(values)
    trend = ((latest - mean) / mean * 100) if mean else 0.0
    return {"latest": round(latest, 3), "mean": round(mean, 3),
            "trend_pct": round(trend, 1), "points": len(values)}


def _tone(query: str) -> float:
    resp = requests.get(
        DOC_URL,
        params={"query": query, "mode": "tonechart", "format": "json", "timespan": "3d"},
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": "JARVIS-Terminal/1.0"},
    )
    resp.raise_for_status()
    bins = resp.json().get("tonechart", [])
    total = sum(b.get("count", 0) for b in bins)
    if not total:
        return 0.0
    weighted = sum(b.get("bin", 0) * b.get("count", 0) for b in bins)
    return round(weighted / total, 2)


def _gather() -> Dict:
    themes: Dict[str, Dict] = {}
    online = 0
    for name, query in QUERIES.items():
        try:
            trend = _timeline_trend(query)
            tone = _tone(query)
            themes[name] = {**trend, "tone": tone}
            online += 1
        except Exception as exc:
            themes[name] = {"error": str(exc)[:100]}

    if online == 0:
        from jarvis import fallback
        return fallback.gdelt()

    return {
        "simulated": False,
        "themes_online": online,
        "themes": themes,
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_gdelt() -> Dict:
    data = cache.get_or_set("gdelt", config.CACHE_TTL, _gather)
    return {**data, "age": cache.age("gdelt")}
