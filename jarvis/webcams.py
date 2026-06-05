"""Public webcam directory — free & keyless.

IMPORTANT — scope and ethics
============================
This module surfaces ONLY webcams that are *intentionally public*: official
government traffic cameras and well-known published live streams. It deliberately
does **not** scan, probe, or brute-force the internet for "open"/unsecured/private
cameras, and provides no access to any device its owner has not chosen to make
public. Accessing someone else's camera without authorisation is unlawful; this
is an aggregator of public feeds, nothing more.

Live source: **TfL JamCams** — Transport for London's public traffic cameras,
exposed via the keyless TfL Unified API (https://api.tfl.gov.uk). Each camera is
geolocated and serves a regularly-refreshed public JPEG, so cams plot on the
globe and display live in-terminal. No API key required. A curated set of other
public live cams worldwide supplements the map.
"""
from __future__ import annotations

from typing import Dict, List

import requests

from config import config
from jarvis.cache import cache

TFL_JAMCAM_URL = "https://api.tfl.gov.uk/Place/Type/JamCam"
TFL_MAX = 60  # cap so the globe isn't swamped by ~900 London cameras

# Curated, openly-public live cams worldwide (link-outs) — gives the globe global
# spread alongside the live TfL feed.
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


def _prop(place: Dict, key: str) -> str | None:
    for p in place.get("additionalProperties", []) or []:
        if p.get("key") == key:
            return p.get("value")
    return None


def _fetch_tfl() -> List[Dict]:
    resp = requests.get(
        TFL_JAMCAM_URL,
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": "JARVIS-Terminal/1.0"},
    )
    resp.raise_for_status()
    cams: List[Dict] = []
    for place in resp.json():
        lat, lon = place.get("lat"), place.get("lon")
        if lat is None or lon is None:
            continue
        if (_prop(place, "available") or "true").lower() == "false":
            continue
        image = _prop(place, "imageUrl")
        if not image:
            continue
        cams.append({
            "id": place.get("id") or place.get("naptanId") or image,
            "title": place.get("commonName", "London traffic camera"),
            "lat": lat, "lon": lon,
            "city": "London", "country": "GB", "category": "Traffic",
            "image": image,
            "video": _prop(place, "videoUrl"),
            "status": "active", "public": True,
        })
        if len(cams) >= TFL_MAX:
            break
    return cams


def get_webcams() -> Dict:
    """Return the public webcam directory — free keyless TfL live + curated."""
    try:
        live = cache.get_or_set("webcams:tfl", config.CACHE_TTL, _fetch_tfl)
    except Exception as exc:
        return {"source": "curated", "live": False, "sample": True,
                "count": len(CURATED), "webcams": CURATED, "error": str(exc)[:140],
                "note": "Live TfL feed unreachable — showing curated public cams."}

    if not live:
        return {"source": "curated", "live": False, "sample": True,
                "count": len(CURATED), "webcams": CURATED,
                "note": "Curated public webcams (live TfL feed returned none)."}

    webcams = live + CURATED
    return {"source": "tfl+curated", "live": True, "sample": False,
            "count": len(webcams), "webcams": webcams,
            "note": "Live London traffic cameras (TfL, keyless public feed) + "
                    "curated public cams worldwide."}
