"""Live market data — keyless feeds.

Two open sources:
  * CoinGecko  — crypto spot + 24h change (no key).
  * Stooq      — global equity indices, commodities, FX via a CSV endpoint.

Markets are a leading indicator for the ORACLE: risk-off moves, oil spikes and
crypto volatility often precede or confirm geopolitical events.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Dict, List

import requests

from config import config
from jarvis.cache import cache

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
STOOQ_URL = "https://stooq.com/q/l/"

# Stooq symbol → display name. ^ = index, .F = futures/commodity, fx pairs.
STOOQ_SYMBOLS = {
    "^spx": "S&P 500", "^ndq": "Nasdaq", "^dji": "Dow Jones",
    "^dax": "DAX", "^n225": "Nikkei 225", "^hsi": "Hang Seng",
    "cl.f": "Crude Oil", "gc.f": "Gold", "ng.f": "Nat Gas",
    "eurusd": "EUR/USD", "dx.f": "Dollar Index",
}

CRYPTO_IDS = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL"}


def _crypto() -> List[Dict]:
    resp = requests.get(
        COINGECKO_URL,
        params={"ids": ",".join(CRYPTO_IDS), "vs_currencies": "usd",
                "include_24hr_change": "true"},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    out: List[Dict] = []
    for cid, sym in CRYPTO_IDS.items():
        row = data.get(cid) or {}
        if "usd" not in row:
            continue
        out.append({
            "symbol": sym, "name": sym, "class": "crypto",
            "price": round(row["usd"], 2),
            "chg": round(row.get("usd_24h_change", 0.0), 2),
        })
    return out


def _stooq() -> List[Dict]:
    syms = ",".join(STOOQ_SYMBOLS)
    resp = requests.get(
        STOOQ_URL,
        params={"s": syms, "f": "sd2t2ohlcvn", "h": "", "e": "csv"},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    out: List[Dict] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        sym = (row.get("Symbol") or "").lower()
        try:
            close = float(row.get("Close"))
            open_ = float(row.get("Open"))
        except (TypeError, ValueError):
            continue
        chg = ((close - open_) / open_ * 100) if open_ else 0.0
        out.append({
            "symbol": STOOQ_SYMBOLS.get(sym, sym.upper()),
            "name": STOOQ_SYMBOLS.get(sym, sym.upper()),
            "class": "commodity" if sym.endswith(".f") else ("fx" if "usd" in sym else "index"),
            "price": round(close, 2),
            "chg": round(chg, 2),
        })
    return out


def _gather() -> Dict:
    instruments: List[Dict] = []
    online = 0
    for fn in (_crypto, _stooq):
        try:
            instruments.extend(fn())
            online += 1
        except Exception:
            continue

    if not instruments:
        from jarvis import fallback
        return fallback.markets()

    # A coarse risk gauge: average move across risk assets (equities + crypto).
    risk = [i["chg"] for i in instruments if i["class"] in ("index", "crypto")]
    risk_avg = round(sum(risk) / len(risk), 2) if risk else 0.0
    return {
        "simulated": False,
        "sources_online": online,
        "instruments": instruments,
        "risk_index": risk_avg,
        "sentiment": "RISK-OFF" if risk_avg < -0.6 else ("RISK-ON" if risk_avg > 0.6 else "NEUTRAL"),
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }


def get_markets() -> Dict:
    data = cache.get_or_set("markets", config.CACHE_TTL, _gather)
    return {**data, "age": cache.age("markets")}
