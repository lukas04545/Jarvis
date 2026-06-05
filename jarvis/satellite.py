"""Live open satellite data — keyless, public NASA / CelesTrak feeds.

Three open sources, none requiring an API key:

* EONET   — NASA's Earth Observatory Natural Event Tracker. Natural events
            (wildfires, volcanoes, severe storms, icebergs…) detected largely
            from satellites, geolocated → plotted on the globe + listed.
* EPIC    — NASA DSCOVR/EPIC latest natural-colour full-disc image of Earth
            (the "live" view of the whole planet from L1).
* CelesTrak — count of currently-tracked active satellites (orbital catalog).

Each source fails independently; a dead feed is reported DEGRADED and, if the
whole module is unreachable, a clearly-flagged SIMULATED sample is served.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import requests

from config import config
from jarvis.cache import cache

EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
EPIC_URL = "https://epic.gsfc.nasa.gov/api/natural"
EPIC_ARCHIVE = "https://epic.gsfc.nasa.gov/archive/natural"
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json"

# Map EONET category titles → terminal-friendly short tags.
_CAT_TAG = {
    "Wildfires": "FIRE", "Volcanoes": "VOLCANO", "Severe Storms": "STORM",
    "Sea and Lake Ice": "ICE", "Icebergs": "ICEBERG", "Floods": "FLOOD",
    "Earthquakes": "QUAKE", "Drought": "DROUGHT", "Dust and Haze": "DUST",
    "Snow": "SNOW", "Temperature Extremes": "TEMP", "Landslides": "LANDSLIDE",
    "Water Color": "WATER", "Manmade": "MANMADE",
}


def _eonet(limit: int = 40) -> Dict:
    resp = requests.get(EONET_URL, params={"status": "open", "limit": limit}, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    events: List[Dict] = []
    for ev in resp.json().get("events", []):
        cats = ev.get("categories", []) or []
        cat_title = cats[0]["title"] if cats else "Event"
        geoms = ev.get("geometry", []) or []
        if not geoms:
            continue
        last = geoms[-1]  # most recent track point
        coords = last.get("coordinates")
        if not coords or last.get("type") != "Point":
            # Polygon/track → use first coordinate pair as a representative point.
            flat = coords
            while isinstance(flat, list) and flat and isinstance(flat[0], list):
                flat = flat[0]
            if not (isinstance(flat, list) and len(flat) >= 2):
                continue
            lon, lat = flat[0], flat[1]
        else:
            lon, lat = coords[0], coords[1]
        events.append(
            {
                "id": ev.get("id"),
                "title": ev.get("title", "Event"),
                "category": cat_title,
                "tag": _CAT_TAG.get(cat_title, "EVENT"),
                "lat": lat,
                "lon": lon,
                "date": last.get("date", ""),
                "link": (ev.get("sources", [{}])[0] or {}).get("url", ""),
            }
        )
    return {"status": "ONLINE", "count": len(events), "events": events}


def _epic() -> Dict:
    resp = requests.get(EPIC_URL, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {"status": "ONLINE", "image": None}
    latest = rows[0]
    name = latest.get("image")
    # EPIC archive path is keyed by capture date: /archive/natural/YYYY/MM/DD/png/NAME.png
    date = (latest.get("date") or "").split(" ")[0].replace("-", "/")
    image_url = f"{EPIC_ARCHIVE}/{date}/png/{name}.png" if name and date else None
    cpos = latest.get("centroid_coordinates", {}) or {}
    return {
        "status": "ONLINE",
        "image": image_url,
        "caption": latest.get("caption", ""),
        "date": latest.get("date", ""),
        "centroid": {"lat": cpos.get("lat"), "lon": cpos.get("lon")},
    }


def _catalog() -> Dict:
    resp = requests.get(CELESTRAK_URL, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    rows = resp.json()
    return {"status": "ONLINE", "active_satellites": len(rows)}


def _gather() -> Dict:
    out: Dict[str, Dict] = {}
    for name, fn in (("events", _eonet), ("earth_image", _epic), ("catalog", _catalog)):
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = {"status": "DEGRADED", "error": str(exc)[:120]}

    online = sum(1 for s in out.values() if s.get("status") == "ONLINE")
    if online == 0:
        from jarvis import fallback

        return fallback.satellite()

    return {
        "simulated": False,
        "sources_online": online,
        "events": out["events"],
        "earth_image": out["earth_image"],
        "catalog": out["catalog"],
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_satellite() -> Dict:
    """Return the cached live satellite picture (EONET + EPIC + catalog)."""
    data = cache.get_or_set("satellite", config.CACHE_TTL, _gather)
    return {**data, "age": cache.age("satellite")}
