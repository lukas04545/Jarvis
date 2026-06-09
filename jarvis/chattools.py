"""JARVIS's full chat tool belt.

On top of the brain tools (recall/save/stats), this lets the AI core *act*: search
the web, read a page, summarise the live global situation, run the ORACLE event
forecast, and forecast a stock — orchestrating the whole platform from chat.
"""
from __future__ import annotations

from typing import Dict, List

from jarvis import braintools, forecast, news, stocks, surveillance, websearch


def _web_search(query: str = "", n: int = 6) -> Dict:
    return websearch.search(query, n)


def _open_url(url: str = "") -> Dict:
    return websearch.fetch_text(url)


def _situation() -> Dict:
    n = news.get_news()
    s = surveillance.get_surveillance()
    return {
        "threat_posture": s.get("posture"),
        "seismic_peak": (s.get("seismic") or {}).get("peak_mag"),
        "headlines": [it["title"] for it in n.get("items", [])[:12]],
        "simulated": bool(n.get("simulated") or s.get("simulated")),
    }


def _forecast_events() -> Dict:
    fc = forecast.generate_forecast()
    return {"method": fc.get("method"),
            "predictions": [{"statement": p["statement"], "probability": p["probability"],
                             "confidence": p["confidence"], "horizon": p["horizon"]}
                            for p in fc.get("predictions", [])[:6]]}


def _forecast_stock(ticker: str = "", horizon: int = 20) -> Dict:
    d = stocks.get_forecast(ticker, horizon)
    if d.get("error"):
        return d
    return {k: d[k] for k in ("ticker", "symbol", "last", "change_pct", "predicted",
                              "predicted_change_pct", "horizon", "method", "simulated")}


_EXTRA_SCHEMA: List[Dict] = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web (live) for information beyond JARVIS's own feeds.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "n": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "open_url",
        "description": "Fetch a web page and return its main text.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "situation",
        "description": "Get the current global situation: threat posture, seismic peak and top headlines.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "forecast_events",
        "description": "Run the ORACLE: probabilistic predictions of future world events.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "forecast_stock",
        "description": "Forecast a stock/index/crypto price (Stooq symbols, e.g. AAPL, ^SPX).",
        "parameters": {"type": "object", "properties": {
            "ticker": {"type": "string"}, "horizon": {"type": "integer"}}, "required": ["ticker"]}}},
]

SCHEMA: List[Dict] = braintools.SCHEMA + _EXTRA_SCHEMA
IMPLS: Dict = {**braintools.IMPLS,
               "web_search": _web_search, "open_url": _open_url, "situation": _situation,
               "forecast_events": _forecast_events, "forecast_stock": _forecast_stock}
