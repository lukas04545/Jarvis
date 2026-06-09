"""Global surveillance — open-source intelligence feeds.

This module pulls live, public sensor data that together form a real-time
"global situational picture" for the terminal:

* SEISMIC   — USGS significant/notable earthquakes (geophysical activity).
* ORBITAL   — current position of the International Space Station.
* SOLAR     — NOAA space-weather / geomagnetic storm alerts.

All endpoints are open and keyless.  Each source fails independently; a dead
sensor is reported as DEGRADED rather than taking the board down.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import requests

from config import config
from jarvis import http
from jarvis.cache import cache

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
ISS_URL = "https://api.wheretheiss.at/v1/satellites/25544"
NOAA_ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"


def _threat_level(magnitude: float) -> str:
    if magnitude >= 7.0:
        return "CRITICAL"
    if magnitude >= 6.0:
        return "SEVERE"
    if magnitude >= 5.0:
        return "ELEVATED"
    return "NOMINAL"


def _seismic() -> Dict:
    resp = http.get(USGS_URL, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    feats = resp.json().get("features", [])
    events: List[Dict] = []
    for f in feats:
        p = f.get("properties", {})
        g = f.get("geometry", {}) or {}
        coords = g.get("coordinates", [None, None, None])
        mag = p.get("mag") or 0.0
        events.append(
            {
                "mag": round(float(mag), 1),
                "place": p.get("place", "Unknown"),
                "lon": coords[0],
                "lat": coords[1],
                "depth": coords[2],
                "level": _threat_level(float(mag)),
                "ts": (p.get("time") or 0) / 1000.0,
                "time": datetime.fromtimestamp(
                    (p.get("time") or 0) / 1000.0, tz=timezone.utc
                ).strftime("%H:%M"),
                "url": p.get("url", ""),
            }
        )
    events.sort(key=lambda e: e["mag"], reverse=True)
    return {
        "status": "ONLINE",
        "count": len(events),
        "events": events[:12],
        "peak_mag": events[0]["mag"] if events else 0.0,
    }


def _orbital() -> Dict:
    resp = http.get(ISS_URL, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    d = resp.json()
    return {
        "status": "ONLINE",
        "lat": round(d.get("latitude", 0.0), 2),
        "lon": round(d.get("longitude", 0.0), 2),
        "alt_km": round(d.get("altitude", 0.0), 1),
        "velocity_kmh": round(d.get("velocity", 0.0), 0),
        "visibility": d.get("visibility", "unknown"),
    }


def _solar() -> Dict:
    resp = http.get(NOAA_ALERTS_URL, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    rows = resp.json()
    alerts: List[Dict] = []
    for row in rows[:6]:
        msg = (row.get("message") or "").replace("\r\n", " ").strip()
        alerts.append(
            {
                "issued": row.get("issue_datetime", ""),
                "summary": msg[:160],
            }
        )
    return {"status": "ONLINE", "count": len(alerts), "alerts": alerts}


def _gather() -> Dict:
    sensors: Dict[str, Dict] = {}
    for name, fn in (("seismic", _seismic), ("orbital", _orbital), ("solar", _solar)):
        try:
            sensors[name] = fn()
        except Exception as exc:  # one sensor down != board down
            sensors[name] = {"status": "DEGRADED", "error": str(exc)[:120]}

    # Headline DEFCON-style posture derived from live seismic peak.
    peak = sensors.get("seismic", {}).get("peak_mag", 0.0) or 0.0
    posture = _threat_level(peak)
    online = sum(1 for s in sensors.values() if s.get("status") == "ONLINE")

    return {
        "posture": posture,
        "sensors_online": online,
        "sensors_total": len(sensors),
        "seismic": sensors["seismic"],
        "orbital": sensors["orbital"],
        "solar": sensors["solar"],
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_surveillance() -> Dict:
    """Return the cached global surveillance picture.

    When no sensor is reachable, a clearly-flagged SIMULATED picture is served
    so the board never goes dark.
    """
    data = cache.get_or_set("surveillance", config.CACHE_TTL, _gather)
    if data.get("sensors_online", 0) == 0:
        from jarvis import fallback

        sim = fallback.surveillance()
        return {**sim, "age": cache.age("surveillance")}
    return {**data, "simulated": False, "age": cache.age("surveillance")}
