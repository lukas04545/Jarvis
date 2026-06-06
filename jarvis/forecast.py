"""J.A.R.V.I.S. ORACLE — predictive forecasting engine.

Consumes the quantitative signal vector (:mod:`jarvis.signals`) and produces
probabilistic forecasts of future events. Two layers:

  * heuristic_forecast() — transparent rule-based predictions derived directly
    from momentum / tone / market signals. Always available (even offline), and
    used to ground / backstop the AI.
  * ai_forecast()        — DeepSeek reasons over the full signal picture and
    returns richer, structured predictions as strict JSON.

generate_forecast() runs both and returns a merged, de-duplicated forecast.
Every prediction carries a probability, confidence, time horizon, the drivers
behind it, and confirm/deny indicators — so it is falsifiable, not vibes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Dict, List

from jarvis import deepseek, memory, signals as signals_mod


def _clamp(p: float) -> float:
    return max(0.05, min(0.95, p))


def _confidence(samples: int, z: float) -> str:
    score = min(samples, 20) / 20 + min(abs(z), 3) / 3
    return "HIGH" if score >= 1.4 else ("MEDIUM" if score >= 0.7 else "LOW")


# Domain → (event template, default horizon, confirm, deny)
_TEMPLATES = {
    "CONFLICT": ("Escalation or new kinetic action in {region}", "7d",
                 "troop movements, official mobilisation, further strikes",
                 "ceasefire or de-escalation announcement"),
    "MARKETS": ("Sharp market move / risk repricing ({region})", "7d",
                "continued volatility, central-bank action, liquidity stress",
                "stabilising prints, dovish guidance"),
    "POLITICS": ("Political rupture — election shock, coup or mass protest in {region}", "30d",
                 "snap announcements, security deployments, resignations",
                 "negotiated settlement, status quo holds"),
    "DISASTER": ("Natural disaster impact intensifies in {region}", "7d",
                 "new warnings, evacuations, rising casualty counts",
                 "conditions ease, all-clear issued"),
    "CYBER": ("Major cyber incident / breach disclosure ({region})", "7d",
              "exploit chatter, follow-on intrusions, ransom demands",
              "patch rollout, no further compromise"),
    "HEALTH": ("Public-health escalation / outbreak spread in {region}", "30d",
               "case growth, cross-border spread, emergency declarations",
               "containment confirmed, cases plateau"),
    "SPACE": ("Notable space / launch event ({region})", "30d",
              "launch manifests, anomaly reports", "nominal operations"),
}


def heuristic_forecast(sig: Dict) -> List[Dict]:
    preds: List[Dict] = []
    top_region = next(iter(sig.get("regions", {})), "Global")
    samples = sig.get("samples_in_baseline", 0)
    gd = sig.get("gdelt", {})

    for domain, tmpl in _TEMPLATES.items():
        info = sig.get("domains", {}).get(domain, {})
        z = info.get("momentum", 0.0)
        vol = info.get("volume", 0)
        if vol < 2 and z < 1.0:
            continue  # not enough signal to forecast on

        # Base probability rises with momentum; nudged by GDELT tone + markets.
        prob = 0.30 + 0.13 * z + 0.015 * vol
        if domain == "CONFLICT":
            tone = (gd.get("conflict") or {}).get("tone", 0)
            trend = (gd.get("conflict") or {}).get("trend_pct", 0)
            prob += -0.02 * tone + 0.002 * trend
        if domain == "MARKETS":
            prob += 0.05 * abs(sig.get("markets", {}).get("risk_index", 0))
        prob = _clamp(prob)

        statement, horizon, confirm, deny = tmpl
        drivers = [f"{domain} coverage {info.get('level','STEADY')} "
                   f"(z={z}, {vol} items vs {info.get('baseline',0)} baseline)"]
        if domain == "CONFLICT" and gd.get("conflict"):
            drivers.append(f"GDELT conflict tone {gd['conflict'].get('tone')}, "
                           f"volume {gd['conflict'].get('trend_pct')}% vs mean")
        if domain == "MARKETS":
            drivers.append(f"markets {sig.get('markets',{}).get('sentiment')} "
                           f"(risk {sig.get('markets',{}).get('risk_index')})")

        preds.append({
            "statement": statement.format(region=top_region),
            "domain": domain, "region": top_region,
            "probability": round(prob, 2),
            "confidence": _confidence(samples, z),
            "horizon": horizon, "drivers": drivers,
            "confirm": confirm, "deny": deny, "source": "heuristic",
        })

    preds.sort(key=lambda p: p["probability"], reverse=True)
    return preds[:6]


_AI_INSTRUCTIONS = (
    "You are the J.A.R.V.I.S. ORACLE, a forecasting analyst. Given the signal "
    "vector and headlines, output probabilistic forecasts of FUTURE events.\n"
    "Return ONLY a JSON array (no prose, no code fences) of 4-7 objects with keys:\n"
    '  statement (string, a specific falsifiable future event),\n'
    "  domain (CONFLICT|MARKETS|POLITICS|DISASTER|CYBER|TECH|SPACE|HEALTH),\n"
    "  region (string), probability (0..1 float), confidence (LOW|MEDIUM|HIGH),\n"
    "  horizon (24h|7d|30d), drivers (array of short strings),\n"
    "  confirm (string: what would confirm it), deny (string: what would refute it).\n"
    "Calibrate probabilities honestly; prefer specificity. Base everything on the "
    "provided signals — do not invent facts."
)


def _parse_json_array(text: str) -> List[Dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in model output")
    return json.loads(text[start:end + 1])


def _normalise(p: Dict) -> Dict:
    try:
        prob = float(p.get("probability", 0.3))
    except (TypeError, ValueError):
        prob = 0.3
    if prob > 1:
        prob /= 100.0
    return {
        "statement": str(p.get("statement", "")).strip()[:240],
        "domain": str(p.get("domain", "GENERAL")).upper()[:12],
        "region": str(p.get("region", "Global"))[:32],
        "probability": round(_clamp(prob), 2),
        "confidence": str(p.get("confidence", "MEDIUM")).upper()[:6],
        "horizon": str(p.get("horizon", "7d"))[:6],
        "drivers": [str(d)[:160] for d in (p.get("drivers") or [])][:5],
        "confirm": str(p.get("confirm", ""))[:200],
        "deny": str(p.get("deny", ""))[:200],
        "source": "ai",
    }


def ai_forecast(sig: Dict) -> List[Dict]:
    """DeepSeek structured predictions. Raises deepseek.DeepSeekError on failure."""
    compact = {
        "domains": sig.get("domains"), "regions": sig.get("regions"),
        "gdelt": sig.get("gdelt"), "markets": sig.get("markets"),
        "geophysical": sig.get("geophysical"), "satellite": sig.get("satellite"),
        "anomalies": sig.get("anomalies"),
    }
    # Pull the brain's accumulated, DeepSeek-distilled knowledge most related to
    # the current picture — this gives the forecaster historical continuity.
    query = " ".join(sig.get("top_headlines", [])[:8] + sig.get("anomalies", [])[:4])
    prior = memory.recall(query, k=10)
    prior_block = ("\n\nPRIOR INTELLIGENCE (accumulated brain memory):\n- "
                   + "\n- ".join(m["text"] for m in prior)) if prior else ""

    prompt = (
        _AI_INSTRUCTIONS
        + "\n\nSIGNAL VECTOR:\n" + json.dumps(compact, separators=(",", ":"))
        + "\n\nTOP HEADLINES:\n- " + "\n- ".join(sig.get("top_headlines", [])[:15])
        + prior_block
    )
    raw = deepseek.complete(
        [{"role": "system", "content": "You output only valid JSON arrays."},
         {"role": "user", "content": prompt}],
        temperature=0.5, max_tokens=1400,
    )
    return [_normalise(p) for p in _parse_json_array(raw) if p.get("statement")]


def generate_forecast() -> Dict:
    sig = signals_mod.build_signals()
    heuristic = heuristic_forecast(sig)

    predictions = heuristic
    method = "heuristic"
    ai_error = None
    try:
        ai = ai_forecast(sig)
        if ai:
            # AI leads; append any heuristic domain the AI missed for coverage.
            ai_domains = {p["domain"] for p in ai}
            extra = [h for h in heuristic if h["domain"] not in ai_domains]
            predictions = ai + extra[:2]
            method = "ai+heuristic"
    except Exception as exc:  # offline, rate-limited, or unparsable → heuristic
        ai_error = str(exc)[:160]

    predictions.sort(key=lambda p: p["probability"], reverse=True)
    return {
        "generated": datetime.now(tz=timezone.utc).isoformat(),
        "method": method,
        "ai_error": ai_error,
        "simulated": sig.get("simulated", False),
        "horizon_note": "Probabilities are model estimates over the stated horizon, not certainties.",
        "predictions": predictions,
        "signals": sig,
    }
