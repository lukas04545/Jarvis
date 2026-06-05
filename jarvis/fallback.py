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
        ("M5.8 offshore Honshu, Japan", 5.8, "ELEVATED", 12),
        ("M4.9 near Antofagasta, Chile", 4.9, "NOMINAL", 34),
        ("M4.3 Aegean Sea region", 4.3, "NOMINAL", 58),
    ]
    events = []
    for place, mag, level, mins in quakes:
        t = _t(mins)
        events.append(
            {"mag": mag, "place": place, "lat": 0, "lon": 0, "depth": 10,
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
