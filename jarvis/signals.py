"""Signals layer — turn raw data into quantitative forecasting indicators.

Pulls every live source (news, GDELT, markets, surveillance, satellite) and
distils them into a compact, numeric signal vector: per-domain and per-region
coverage volumes, *momentum* (vs a rolling in-memory baseline), media tone,
market risk, geophysical posture and satellite-event tallies — plus a list of
detected anomalies.

The momentum baseline accumulates as the server runs: each snapshot is appended
to an in-memory ring buffer, so trends sharpen over time. This is what gives the
ORACLE something predictive to reason over, rather than a static headline dump.
"""
from __future__ import annotations

import statistics
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List

from jarvis import gdelt, markets, news, satellite, surveillance

# Rolling history of per-domain volumes for momentum. Survives across requests
# (module-level), capped so memory is bounded.
_HISTORY: Deque[Dict[str, float]] = deque(maxlen=60)
_LOCK = threading.Lock()

DOMAINS = ["CONFLICT", "MARKETS", "POLITICS", "DISASTER", "CYBER", "TECH", "SPACE", "HEALTH"]


def _zscore(value: float, series: List[float]) -> float:
    if len(series) < 3:
        return 0.0
    mean = statistics.fmean(series)
    sd = statistics.pstdev(series)
    return round((value - mean) / sd, 2) if sd > 1e-9 else 0.0


def _level(z: float) -> str:
    if z >= 2.0:
        return "SURGING"
    if z >= 1.0:
        return "RISING"
    if z <= -1.0:
        return "FALLING"
    return "STEADY"


def build_signals() -> Dict:
    n = news.get_news()
    surv = surveillance.get_surveillance()
    sat = satellite.get_satellite()
    mk = markets.get_markets()
    gd = gdelt.get_gdelt()

    # ── per-domain + per-region news volumes ──────────────────────────────
    domain_vol: Dict[str, int] = {d: 0 for d in DOMAINS}
    region_vol: Dict[str, int] = {}
    for it in n.get("items", []):
        domain_vol[it["topic"]] = domain_vol.get(it["topic"], 0) + 1
        region_vol[it["region"]] = region_vol.get(it["region"], 0) + 1

    # Append current volumes to history, then compute momentum vs the baseline.
    with _LOCK:
        history = list(_HISTORY)
        _HISTORY.append({d: float(domain_vol.get(d, 0)) for d in DOMAINS})

    domains: Dict[str, Dict] = {}
    anomalies: List[str] = []
    for d in DOMAINS:
        vol = domain_vol.get(d, 0)
        past = [h.get(d, 0.0) for h in history]
        z = _zscore(vol, past)
        baseline = round(statistics.fmean(past), 1) if past else float(vol)
        domains[d] = {"volume": vol, "baseline": baseline, "momentum": z, "level": _level(z)}
        if z >= 1.5 and vol >= 3:
            anomalies.append(f"{d} coverage {_level(z)} (z={z}, {vol} vs {baseline} baseline)")

    # ── GDELT tone/volume ─────────────────────────────────────────────────
    gd_themes = gd.get("themes", {})
    for theme, t in gd_themes.items():
        if t.get("trend_pct", 0) >= 25:
            anomalies.append(f"GDELT '{theme}' coverage +{t['trend_pct']}% vs week mean")
        if t.get("tone", 0) <= -4:
            anomalies.append(f"GDELT '{theme}' tone strongly negative ({t['tone']})")

    # ── markets ───────────────────────────────────────────────────────────
    mk_summary = {
        "risk_index": mk.get("risk_index", 0.0),
        "sentiment": mk.get("sentiment", "NEUTRAL"),
        "movers": sorted(mk.get("instruments", []),
                         key=lambda x: abs(x.get("chg", 0)), reverse=True)[:5],
    }
    if abs(mk.get("risk_index", 0.0)) >= 1.5:
        anomalies.append(f"Markets {mk_summary['sentiment']} (risk index {mk_summary['risk_index']})")

    # ── geophysical + satellite ───────────────────────────────────────────
    geo = {
        "posture": surv.get("posture", "NOMINAL"),
        "peak_mag": (surv.get("seismic") or {}).get("peak_mag", 0.0),
    }
    if geo["peak_mag"] and geo["peak_mag"] >= 6.0:
        anomalies.append(f"Major seismic event M{geo['peak_mag']}")

    sat_events = (sat.get("events") or {}).get("events", [])
    sat_tags: Dict[str, int] = {}
    for e in sat_events:
        sat_tags[e["tag"]] = sat_tags.get(e["tag"], 0) + 1
    if sat_tags.get("VOLCANO", 0) >= 1:
        anomalies.append(f"{sat_tags['VOLCANO']} active volcanic event(s) (NASA EONET)")

    simulated = any(x.get("simulated") for x in (n, mk, gd, sat)) or bool(surv.get("simulated"))

    return {
        "generated": datetime.now(tz=timezone.utc).isoformat(),
        "simulated": simulated,
        "samples_in_baseline": len(history),
        "domains": domains,
        "regions": dict(sorted(region_vol.items(), key=lambda x: -x[1])),
        "gdelt": gd_themes,
        "markets": mk_summary,
        "geophysical": geo,
        "satellite": {"total": len(sat_events), "by_tag": sat_tags},
        "anomalies": anomalies,
        "top_headlines": [it["title"] for it in n.get("items", [])[:15]],
    }
