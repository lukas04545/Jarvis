"""Public webcam directory.

IMPORTANT — scope and ethics
============================
This module surfaces ONLY webcams whose owners have *intentionally published*
them for public viewing (e.g. tourism, traffic and weather cams listed on the
Windy Webcams public registry, plus a small curated set of well-known public
live streams).

It deliberately does **not** scan, probe, or brute-force the internet for
"open"/unsecured/private cameras, and provides no access to any device its
owner has not chosen to make public. Accessing someone else's camera without
authorisation is unlawful; this is an aggregator of public feeds, nothing more.

Live data source: the Windy Webcams API (https://api.windy.com/webcams), which
requires a free API key. Paste one in the terminal's SETTINGS panel to unlock
live public webcams; without a key, a clearly-labelled curated sample is served.
"""
from __future__ import annotations

from typing import Dict, List

import requests

from config import config
from jarvis import runtime
from jarvis.cache import cache

WINDY_URL = "https://api.windy.com/webcams/api/v3/webcams"

# Curated, openly-public live cams (owner-published). Used when no Windy key is
# configured so the feature is demonstrable; flagged sample=True and link-only.
CURATED: List[Dict] = [
    {"id": "s-nyc", "title": "Times Square, New York", "lat": 40.7580, "lon": -73.9855,
     "city": "New York", "country": "US", "category": "City",
     "link": "https://www.earthcam.com/usa/newyork/timessquare/"},
    {"id": "s-shibuya", "title": "Shibuya Crossing, Tokyo", "lat": 35.6595, "lon": 139.7005,
     "city": "Tokyo", "country": "JP", "category": "City",
     "link": "https://www.youtube.com/watch?v=Ab8AdLwOhq8"},
    {"id": "s-venice", "title": "Grand Canal, Venice", "lat": 45.4408, "lon": 12.3155,
     "city": "Venice", "country": "IT", "category": "Landmark",
     "link": "https://www.skylinewebcams.com/en/webcam/italia/veneto/venezia/canal-grande.html"},
    {"id": "s-abbey", "title": "Abbey Road Crossing, London", "lat": 51.5320, "lon": -0.1779,
     "city": "London", "country": "GB", "category": "City",
     "link": "https://www.abbeyroad.com/crossing"},
    {"id": "s-sydney", "title": "Sydney Harbour", "lat": -33.8568, "lon": 151.2153,
     "city": "Sydney", "country": "AU", "category": "Harbour",
     "link": "https://www.portauthoritynsw.com.au/sydney-harbour/sydney-harbour-webcam/"},
    {"id": "s-kona", "title": "Kona Coast, Hawaii", "lat": 19.6400, "lon": -155.9969,
     "city": "Kailua-Kona", "country": "US", "category": "Coast",
     "link": "https://www.konaweb.com/cam/"},
    {"id": "s-table", "title": "Table Mountain, Cape Town", "lat": -33.9628, "lon": 18.4098,
     "city": "Cape Town", "country": "ZA", "category": "Landmark",
     "link": "https://www.tablemountain.net/content/page/webcam"},
    {"id": "s-rio", "title": "Copacabana Beach, Rio", "lat": -22.9711, "lon": -43.1822,
     "city": "Rio de Janeiro", "country": "BR", "category": "Beach",
     "link": "https://www.skylinewebcams.com/en/webcam/brasil/rio-de-janeiro/rio-de-janeiro/copacabana.html"},
]


def _fetch_windy(key: str, limit: int = 50) -> List[Dict]:
    resp = requests.get(
        WINDY_URL,
        headers={"x-windy-api-key": key},
        params={"limit": limit, "include": "categories,images,location,player", "lang": "en"},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    cams: List[Dict] = []
    for w in resp.json().get("webcams", []):
        loc = w.get("location", {}) or {}
        images = w.get("images", {}) or {}
        current = images.get("current", {}) or {}
        player = w.get("player", {}) or {}
        embed = (player.get("day") or {}).get("embed") or (player.get("lifetime") or {}).get("embed")
        cats = w.get("categories", []) or []
        cams.append(
            {
                "id": str(w.get("webcamId") or w.get("id") or ""),
                "title": w.get("title", "Public webcam"),
                "lat": loc.get("latitude"),
                "lon": loc.get("longitude"),
                "city": loc.get("city"),
                "country": loc.get("country"),
                "category": cats[0]["name"] if cats and isinstance(cats[0], dict) else "General",
                "image": current.get("preview") or current.get("thumbnail"),
                "embed": embed,
                "status": w.get("status", "active"),
                "public": True,
            }
        )
    # Only cams with usable coordinates can be plotted on the globe.
    return [c for c in cams if c["lat"] is not None and c["lon"] is not None]


def get_webcams() -> Dict:
    """Return the public webcam directory (live via Windy if keyed, else sample)."""
    key = runtime.windy_key()
    if key:
        try:
            cams = cache.get_or_set(f"webcams:{key[:6]}", config.CACHE_TTL, lambda: _fetch_windy(key))
            return {"source": "windy", "live": True, "sample": False,
                    "count": len(cams), "webcams": cams,
                    "note": "Live public webcams via the Windy Webcams registry (owner-published)."}
        except Exception as exc:  # fall back to sample, surface the reason
            return {"source": "windy", "live": False, "sample": True,
                    "count": len(CURATED), "webcams": CURATED,
                    "error": str(exc)[:140],
                    "note": "Windy fetch failed — showing curated public sample."}
    return {"source": "curated", "live": False, "sample": True,
            "count": len(CURATED), "webcams": CURATED,
            "note": "Curated public webcams. Add a free Windy Webcams API key in "
                    "SETTINGS to load live public webcams worldwide."}
