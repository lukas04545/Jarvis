"""Offline / SIMULATED fallback datasets.

When every live feed is unreachable (e.g. a locked-down network with no egress),
the terminal would otherwise go blank.  To keep J.A.R.V.I.S. demonstrable, we
serve a small curated sample set — always flagged ``simulated: True`` so the UI
can badge it as SIM and never passes synthetic data off as live intelligence.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List


def _t(mins_ago: int) -> Dict[str, float | str]:
    ts = time.time() - mins_ago * 60
    return {"ts": ts, "time": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")}


_SAMPLE_HEADLINES = [
    ("Diplomats convene for emergency summit as ceasefire talks stall", "Reuters World", "Global", "CONFLICT", 7),
    ("Central banks signal coordinated stance amid inflation data", "BBC World", "Global", "MARKETS", 14),
    ("Parliament passes contested reform after marathon session", "DW Europe", "Europe", "POLITICS", 22),
    ("Magnitude 5.8 quake reported offshore; no tsunami warning issued", "NHK World", "Asia", "DISASTER", 31),
    ("New semiconductor export controls reshape supply chains", "CNA Asia", "Asia", "TECH", 38),
    ("Health agency monitors regional outbreak, urges caution", "Al Jazeera", "MENA", "HEALTH", 46),
    ("Energy markets steady as pipeline maintenance concludes", "France24", "Europe", "MARKETS", 53),
    ("Border tensions ease following back-channel negotiations", "AP Top", "Americas", "CONFLICT", 61),
]


def news() -> Dict:
    items: List[Dict] = []
    for title, source, region, topic, mins in _SAMPLE_HEADLINES:
        t = _t(mins)
        items.append(
            {
                "title": title,
                "summary": "Simulated wire item — live feeds unreachable from this network.",
                "link": "",
                "source": source,
                "region": region,
                "topic": topic,
                "ts": t["ts"],
                "time": t["time"],
            }
        )
    topics: Dict[str, int] = {}
    regions: Dict[str, int] = {}
    for it in items:
        topics[it["topic"]] = topics.get(it["topic"], 0) + 1
        regions[it["region"]] = regions.get(it["region"], 0) + 1
    return {
        "count": len(items),
        "items": items,
        "topics": topics,
        "regions": regions,
        "simulated": True,
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def surveillance() -> Dict:
    quakes = [
        ("M5.8 offshore Honshu, Japan", 5.8, "ELEVATED", 12, 38.3, 142.4),
        ("M4.9 near Antofagasta, Chile", 4.9, "NOMINAL", 34, -23.65, -70.4),
        ("M4.3 Aegean Sea region", 4.3, "NOMINAL", 58, 38.5, 25.0),
    ]
    events = []
    for place, mag, level, mins, lat, lon in quakes:
        t = _t(mins)
        events.append(
            {"mag": mag, "place": place, "lat": lat, "lon": lon, "depth": 10,
             "level": level, "ts": t["ts"], "time": t["time"], "url": ""}
        )
    return {
        "posture": "ELEVATED",
        "sensors_online": 0,
        "sensors_total": 3,
        "simulated": True,
        "seismic": {"status": "SIMULATED", "count": len(events), "events": events,
                    "peak_mag": events[0]["mag"]},
        "orbital": {"status": "SIMULATED", "lat": 12.4, "lon": -53.1,
                    "alt_km": 421.3, "velocity_kmh": 27600, "visibility": "daylight"},
        "solar": {"status": "SIMULATED", "count": 1,
                  "alerts": [{"issued": "", "summary": "G1 (Minor) geomagnetic storm watch — simulated sample."}]},
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def markets() -> Dict:
    instruments = [
        {"symbol": "S&P 500", "name": "S&P 500", "class": "index", "price": 5430.2, "chg": -0.8},
        {"symbol": "Nasdaq", "name": "Nasdaq", "class": "index", "price": 17220.5, "chg": -1.1},
        {"symbol": "Nikkei 225", "name": "Nikkei 225", "class": "index", "price": 38900.0, "chg": 0.4},
        {"symbol": "Crude Oil", "name": "Crude Oil", "class": "commodity", "price": 82.4, "chg": 2.3},
        {"symbol": "Gold", "name": "Gold", "class": "commodity", "price": 2380.0, "chg": 0.9},
        {"symbol": "BTC", "name": "BTC", "class": "crypto", "price": 64200.0, "chg": -2.6},
        {"symbol": "ETH", "name": "ETH", "class": "crypto", "price": 3380.0, "chg": -3.1},
    ]
    risk = [i["chg"] for i in instruments if i["class"] in ("index", "crypto")]
    risk_avg = round(sum(risk) / len(risk), 2)
    return {
        "simulated": True, "sources_online": 0, "instruments": instruments,
        "risk_index": risk_avg, "sentiment": "RISK-OFF",
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def gdelt() -> Dict:
    return {
        "simulated": True, "themes_online": 0,
        "themes": {
            "conflict": {"latest": 4.1, "mean": 3.2, "trend_pct": 28.1, "points": 56, "tone": -5.4},
            "economy": {"latest": 2.8, "mean": 2.9, "trend_pct": -3.4, "points": 56, "tone": -1.8},
            "unrest": {"latest": 1.6, "mean": 1.1, "trend_pct": 45.5, "points": 56, "tone": -3.9},
        },
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def satellite() -> Dict:
    samples = [
        ("Wildfire complex — California", "Wildfires", "FIRE", 38.6, -121.9),
        ("Eruptive activity — Mt Etna", "Volcanoes", "VOLCANO", 37.75, 14.99),
        ("Tropical storm — W Pacific", "Severe Storms", "STORM", 14.2, 138.6),
        ("Iceberg drift — Weddell Sea", "Icebergs", "ICEBERG", -73.0, -45.0),
        ("Seasonal flooding — Bangladesh", "Floods", "FLOOD", 24.0, 90.4),
    ]
    events = [
        {"id": f"sim-{i}", "title": t, "category": c, "tag": g,
         "lat": lat, "lon": lon, "date": "", "link": ""}
        for i, (t, c, g, lat, lon) in enumerate(samples)
    ]
    return {
        "simulated": True,
        "sources_online": 0,
        "events": {"status": "SIMULATED", "count": len(events), "events": events},
        "earth_image": {"status": "SIMULATED", "image": None,
                        "caption": "EPIC full-disc image unavailable on this network.",
                        "date": "", "centroid": {"lat": 0, "lon": 0}},
        "catalog": {"status": "SIMULATED", "active_satellites": 11000},
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }
