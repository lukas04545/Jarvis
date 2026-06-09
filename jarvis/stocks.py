"""Stock tracking + price forecasting.

* History — daily close prices from Stooq's keyless CSV endpoint.
* Forecast — Google **TimesFM** (time-series foundation model) when available,
  otherwise a solid statistical fallback (geometric-Brownian drift/volatility
  with widening confidence bands). Both return a point path + lo/hi band.

TimesFM is heavy (JAX/PyTorch + a downloaded checkpoint), so it is OPTIONAL and
opt-in: install `timesfm` and set ``JARVIS_ENABLE_TIMESFM=1``. Without it the
statistical model is used and clearly labelled. When the network is unreachable,
a deterministic SIMULATED series is returned so the chart stays demonstrable.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests

from config import config
from jarvis import http
from jarvis.cache import cache

STOOQ_CSV = "https://stooq.com/q/d/l/"
WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "TSLA", "META"]

_TFM = None  # cached TimesFM model instance


def _clean(ticker: str) -> str:
    t = "".join(c for c in (ticker or "").strip() if c.isalnum() or c in ".^-_").lower()
    return t[:16]


def _stooq_symbol(ticker: str) -> str:
    t = _clean(ticker)
    if not t:
        return ""
    return t if ("." in t or t.startswith("^")) else t + ".us"


def _fetch_history(ticker: str, limit: int = 260) -> Tuple[List[float], List[str]]:
    sym = _stooq_symbol(ticker)
    resp = http.get(STOOQ_CSV, params={"s": sym, "i": "d"}, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    closes: List[float] = []
    dates: List[str] = []
    for row in csv.DictReader(io.StringIO(resp.text)):
        try:
            closes.append(float(row["Close"]))
            dates.append(row["Date"])
        except (KeyError, TypeError, ValueError):
            continue
    return closes[-limit:], dates[-limit:]


def _simulated_history(ticker: str, n: int = 160) -> Tuple[List[float], List[str]]:
    h = hashlib.sha256(_clean(ticker).encode()).digest()
    price = 40 + (h[0] << 8 | h[1]) % 400          # stable base price per ticker
    drift = ((h[2] / 255) - 0.45) * 0.0025
    vol = 0.008 + (h[3] / 255) * 0.02
    closes, dates = [], []
    start = datetime.now(tz=timezone.utc) - timedelta(days=n)
    seed = h[4] << 8 | h[5]
    for i in range(n):
        # deterministic pseudo-random walk
        seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
        shock = ((seed / 0x7FFFFFFF) - 0.5) * 2 * vol
        price = max(1.0, price * math.exp(drift + shock))
        closes.append(round(price, 2))
        dates.append((start + timedelta(days=i)).strftime("%Y-%m-%d"))
    return closes, dates


def _future_dates(last_date: str, horizon: int) -> List[str]:
    try:
        d = datetime.strptime(last_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        d = datetime.now(tz=timezone.utc)
    out, added = [], 0
    while added < horizon:
        d += timedelta(days=1)
        if d.weekday() < 5:                          # business days only
            out.append(d.strftime("%Y-%m-%d"))
            added += 1
    return out


def _gbm_forecast(closes: List[float], horizon: int, z: float = 1.2816) -> List[Dict]:
    """Geometric-Brownian forecast: drift + vol with ~80% confidence bands."""
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes)) if closes[i - 1] > 0]
    last = closes[-1]
    if len(rets) < 2:
        return [{"yhat": round(last, 2), "lo": round(last, 2), "hi": round(last, 2)} for _ in range(horizon)]
    window = rets[-120:]
    mu = statistics.fmean(window)
    sd = statistics.pstdev(window) or 1e-6
    out = []
    for t in range(1, horizon + 1):
        yhat = last * math.exp(mu * t)
        spread = z * sd * math.sqrt(t)
        out.append({"yhat": round(yhat, 2),
                    "lo": round(last * math.exp(mu * t - spread), 2),
                    "hi": round(last * math.exp(mu * t + spread), 2)})
    return out


def _timesfm_forecast(closes: List[float], horizon: int) -> List[Dict] | None:
    """Google TimesFM forecast (opt-in). Returns None if unavailable."""
    if os.environ.get("JARVIS_ENABLE_TIMESFM") != "1":
        return None
    try:
        global _TFM
        import timesfm  # type: ignore

        if _TFM is None:
            _TFM = timesfm.TimesFm(
                hparams=timesfm.TimesFmHparams(backend="cpu", per_core_batch_size=32,
                                               horizon_len=max(64, horizon), context_len=512),
                checkpoint=timesfm.TimesFmCheckpoint(
                    huggingface_repo_id="google/timesfm-1.0-200m-pytorch"),
            )
        series = [float(c) for c in closes[-512:]]
        point, quantiles = _TFM.forecast([series], freq=[0])
        pf = list(point[0])[:horizon]
        qf = quantiles[0] if quantiles is not None else None
        out = []
        for t in range(horizon):
            yhat = float(pf[t])
            if qf is not None and len(qf) > t and len(qf[t]) >= 3:
                lo, hi = float(qf[t][1]), float(qf[t][-2])
            else:
                lo = hi = yhat
            out.append({"yhat": round(yhat, 2),
                        "lo": round(min(lo, yhat), 2), "hi": round(max(hi, yhat), 2)})
        return out
    except Exception:
        return None


def get_forecast(ticker: str, horizon: int = 20) -> Dict:
    horizon = max(5, min(90, int(horizon or 20)))
    sym = _clean(ticker)
    if not sym:
        return {"error": "invalid ticker"}

    simulated = False
    try:
        closes, dates = cache.get_or_set(f"stk:{sym}", config.CACHE_TTL, lambda: _fetch_history(sym))
        if not closes:
            raise ValueError("no data")
    except Exception:
        closes, dates = _simulated_history(sym)
        simulated = True

    fc = _timesfm_forecast(closes, horizon)
    method = "timesfm"
    if fc is None:
        fc = _gbm_forecast(closes, horizon)
        method = "statistical"

    fdates = _future_dates(dates[-1] if dates else "", horizon)
    forecast = [{**fc[i], "date": fdates[i] if i < len(fdates) else f"+{i+1}"} for i in range(len(fc))]

    last = closes[-1]
    prev = closes[-2] if len(closes) > 1 else last
    predicted = forecast[-1]["yhat"] if forecast else last
    return {
        "ticker": ticker.upper().strip(),
        "symbol": _stooq_symbol(sym),
        "method": method,
        "simulated": simulated,
        "last": round(last, 2),
        "change_pct": round((last - prev) / prev * 100, 2) if prev else 0.0,
        "predicted": round(predicted, 2),
        "predicted_change_pct": round((predicted - last) / last * 100, 2) if last else 0.0,
        "horizon": horizon,
        "history": [{"date": dates[i], "close": closes[i]} for i in range(len(closes))],
        "forecast": forecast,
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def _quote(ticker: str) -> Dict:
    try:
        closes, _ = cache.get_or_set(f"stk:{_clean(ticker)}", config.CACHE_TTL, lambda: _fetch_history(ticker))
        if not closes:
            raise ValueError
        sim = False
    except Exception:
        closes, _ = _simulated_history(ticker)
        sim = True
    last, prev = closes[-1], (closes[-2] if len(closes) > 1 else closes[-1])
    return {"ticker": ticker.upper(), "last": round(last, 2),
            "change_pct": round((last - prev) / prev * 100, 2) if prev else 0.0, "simulated": sim}


def get_watchlist() -> Dict:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=7) as pool:
        quotes = list(pool.map(_quote, WATCHLIST))
    return {"quotes": quotes, "simulated": any(q["simulated"] for q in quotes)}
