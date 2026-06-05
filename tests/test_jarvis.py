"""Smoke + unit tests for J.A.R.V.I.S.

These avoid hitting the network: external feeds are monkeypatched so the API
surface, caching, and offline AI fallback are all exercised deterministically.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from jarvis import (  # noqa: E402
    deepseek, fallback, forecast, news, runtime, signals, surveillance, webcams,
)
from jarvis.cache import TTLCache  # noqa: E402
import app as app_module  # noqa: E402


@pytest.fixture
def offline_data(monkeypatch):
    """Point every network-backed getter at its SIMULATED fallback."""
    monkeypatch.setattr(news, "get_news", fallback.news)
    monkeypatch.setattr(surveillance, "get_surveillance", fallback.surveillance)
    monkeypatch.setattr(signals.satellite, "get_satellite", fallback.satellite)
    monkeypatch.setattr(signals.markets, "get_markets", fallback.markets)
    monkeypatch.setattr(signals.gdelt, "get_gdelt", fallback.gdelt)
    monkeypatch.setattr(signals.news, "get_news", fallback.news)
    monkeypatch.setattr(signals.surveillance, "get_surveillance", fallback.surveillance)


@pytest.fixture(autouse=True)
def isolate_runtime(tmp_path, monkeypatch):
    """Keep the runtime key store empty + writes confined to a temp file."""
    monkeypatch.setattr(runtime, "_SECRETS_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setattr(runtime, "_overrides", {})


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


# ── cache ────────────────────────────────────────────────────────────────
def test_cache_memoises_and_serves_stale_on_error():
    c = TTLCache()
    calls = {"n": 0}

    def produce():
        calls["n"] += 1
        return calls["n"]

    assert c.get_or_set("k", 60, produce) == 1
    assert c.get_or_set("k", 60, produce) == 1  # cached, producer not re-run
    assert calls["n"] == 1

    def boom():
        raise RuntimeError("upstream down")

    # stale-on-error: previous good value is returned
    assert c.get_or_set("k", 0, boom) == 1


def test_cache_propagates_error_when_empty():
    c = TTLCache()
    with pytest.raises(RuntimeError):
        c.get_or_set("missing", 0, lambda: (_ for _ in ()).throw(RuntimeError("x")))


# ── deepseek offline fallback ──────────────────────────────────────────────
def test_offline_complete_is_labelled(monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")
    out = deepseek.complete(deepseek.build_messages("status report"))
    assert "OFFLINE MODE" in out
    assert "status report" in out


def test_offline_stream_yields_chunks(monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")
    chunks = list(deepseek.stream(deepseek.build_messages("hello")))
    assert "".join(chunks).strip().startswith("[OFFLINE MODE]")


def test_build_messages_includes_persona_and_context():
    msgs = deepseek.build_messages("q", context="CTX")
    assert msgs[0]["role"] == "system" and "J.A.R.V.I.S." in msgs[0]["content"]
    assert any("CTX" in m["content"] for m in msgs)
    assert msgs[-1] == {"role": "user", "content": "q"}


# ── news tagging ───────────────────────────────────────────────────────────
def test_topic_tagging():
    assert news._topic_for("Missile strike near the border") == "CONFLICT"
    assert news._topic_for("Inflation and stocks rattle markets") == "MARKETS"
    assert news._topic_for("A quiet day in the village") == "GENERAL"


def test_clean_strips_html_entities():
    assert news._clean("<b>Hello</b> &amp; welcome") == "Hello & welcome"


# ── surveillance threat levels ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "mag,level",
    [(7.2, "CRITICAL"), (6.1, "SEVERE"), (5.3, "ELEVATED"), (3.0, "NOMINAL")],
)
def test_threat_level(mag, level):
    assert surveillance._threat_level(mag) == level


# ── API surface (network-free) ─────────────────────────────────────────────
def test_status_endpoint(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.get_json()["system"] == "JARVIS"


def test_news_endpoint(client, monkeypatch):
    sample = {
        "count": 1,
        "items": [
            {"title": "T", "summary": "", "link": "", "source": "S",
             "region": "Global", "topic": "TECH", "ts": 0, "time": "00:00"}
        ],
        "topics": {"TECH": 1}, "regions": {"Global": 1}, "age": 0,
        "generated": "now",
    }
    monkeypatch.setattr(app_module.news, "get_news", lambda: sample)
    r = client.get("/api/news?topic=TECH")
    assert r.status_code == 200
    assert r.get_json()["items"][0]["topic"] == "TECH"


def test_chat_requires_message(client):
    r = client.post("/api/chat", json={"message": "   "})
    assert r.status_code == 400


def test_chat_offline_reply(client, monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")
    r = client.post("/api/chat", json={"message": "sitrep", "with_context": False})
    assert r.status_code == 200
    assert "OFFLINE MODE" in r.get_json()["reply"]


def test_index_serves_terminal(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"J.A.R.V.I.S" in r.data


# ── Android / PWA surface ──────────────────────────────────────────────────
def test_service_worker_served_at_root_scope(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["Content-Type"]
    # Root scope is required for the worker to control the whole app.
    assert r.headers.get("Service-Worker-Allowed") == "/"


def test_manifest_is_valid_and_installable(client):
    import json

    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200
    manifest = json.loads(r.data)
    # Chrome's install criteria: name, start_url, standalone, 192 + 512 icons.
    assert manifest["name"] and manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    sizes = {ic["sizes"] for ic in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes


def test_index_links_pwa_assets(client):
    body = client.get("/").data
    assert b"manifest.webmanifest" in body
    assert b'name="theme-color"' in body
    assert b"/sw.js" in body


# ── Settings / runtime API keys ────────────────────────────────────────────
def test_paste_api_key_brings_ai_core_online(client, monkeypatch):
    monkeypatch.setattr(runtime.config, "DEEPSEEK_API_KEY", "")
    assert client.get("/api/status").get_json()["ai_core"] == "OFFLINE"

    r = client.post("/api/settings", json={"deepseek_api_key": "sk-live-key"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert client.get("/api/status").get_json()["ai_core"] == "ONLINE"

    # Clearing the key takes the core back offline.
    client.post("/api/settings", json={"deepseek_api_key": ""})
    assert client.get("/api/status").get_json()["ai_core"] == "OFFLINE"


def test_settings_never_leak_key_material(client):
    client.post("/api/settings", json={"deepseek_api_key": "sk-secret"})
    blob = client.get("/api/settings").get_data(as_text=True)
    assert "sk-secret" not in blob
    providers = client.get("/api/settings").get_json()
    assert providers["deepseek"]["configured"] is True
    assert providers["deepseek"]["source"] == "ui"


# ── Public webcams (free, keyless) ─────────────────────────────────────────
def test_webcams_fall_back_to_curated_when_live_unavailable(client, monkeypatch):
    # Force the live TfL fetch to fail → keyless curated fallback.
    monkeypatch.setattr(webcams.config, "CACHE_TTL", 0)  # bypass shared cache
    monkeypatch.setattr(webcams, "_fetch_tfl", lambda: (_ for _ in ()).throw(RuntimeError("blocked")))
    data = client.get("/api/webcams").get_json()
    assert data["source"] == "curated" and data["live"] is False
    assert data["count"] == len(webcams.CURATED)
    # Every entry is geolocatable (needed to plot on the globe).
    assert all(c["lat"] is not None and c["lon"] is not None for c in data["webcams"])


def test_webcams_live_tfl_merges_curated(client, monkeypatch):
    monkeypatch.setattr(webcams.config, "CACHE_TTL", 0)  # bypass shared cache
    monkeypatch.setattr(webcams, "_fetch_tfl", lambda: [
        {"id": "JamCams_1", "title": "A40 Cam", "lat": 51.5, "lon": -0.1,
         "city": "London", "country": "GB", "category": "Traffic",
         "image": "https://example/cam.jpg", "video": None,
         "status": "active", "public": True}])
    data = client.get("/api/webcams").get_json()
    assert data["live"] is True and data["source"] == "tfl+curated"
    assert data["count"] == 1 + len(webcams.CURATED)
    assert data["webcams"][0]["image"].startswith("https://")


# ── Live satellite data ────────────────────────────────────────────────────
def test_satellite_endpoint(client, monkeypatch):
    sample = {
        "simulated": False, "sources_online": 3,
        "events": {"status": "ONLINE", "count": 1,
                   "events": [{"id": "x", "title": "Wildfire", "category": "Wildfires",
                               "tag": "FIRE", "lat": 1.0, "lon": 2.0, "date": "", "link": ""}]},
        "earth_image": {"status": "ONLINE", "image": "http://x/img.png"},
        "catalog": {"status": "ONLINE", "active_satellites": 9000},
        "age": 0,
    }
    monkeypatch.setattr(app_module.satellite, "get_satellite", lambda: sample)
    d = client.get("/api/satellite").get_json()
    assert d["catalog"]["active_satellites"] == 9000
    assert d["events"]["events"][0]["tag"] == "FIRE"


def test_satellite_fallback_is_flagged_simulated():
    sat = fallback.satellite()
    assert sat["simulated"] is True
    assert sat["events"]["count"] >= 1
    assert all(e["lat"] is not None for e in sat["events"]["events"])


# ── Data expansion (markets / gdelt fallbacks) ─────────────────────────────
def test_markets_fallback_has_instruments_and_sentiment():
    mk = fallback.markets()
    assert mk["simulated"] is True and len(mk["instruments"]) >= 5
    assert mk["sentiment"] in ("RISK-OFF", "RISK-ON", "NEUTRAL")


def test_gdelt_fallback_themes():
    gd = fallback.gdelt()
    assert "conflict" in gd["themes"] and "tone" in gd["themes"]["conflict"]


# ── Signals layer ──────────────────────────────────────────────────────────
def test_build_signals_aggregates_and_flags_anomalies(offline_data):
    sig = signals.build_signals()
    assert sig["simulated"] is True
    assert set(["CONFLICT", "MARKETS"]).issubset(sig["domains"].keys())
    assert isinstance(sig["anomalies"], list) and sig["anomalies"]
    assert "sentiment" in sig["markets"]


# ── ORACLE forecast engine ─────────────────────────────────────────────────
def test_heuristic_forecast_scales_with_momentum():
    sig = {
        "regions": {"MENA": 12}, "samples_in_baseline": 20,
        "gdelt": {"conflict": {"tone": -7, "trend_pct": 40}},
        "markets": {"risk_index": -2.0, "sentiment": "RISK-OFF"},
        "domains": {
            "CONFLICT": {"volume": 14, "baseline": 4, "momentum": 2.6, "level": "SURGING"},
            "MARKETS": {"volume": 9, "baseline": 5, "momentum": 1.4, "level": "RISING"},
        },
    }
    preds = forecast.heuristic_forecast(sig)
    assert preds, "expected predictions for high-momentum signals"
    conflict = next(p for p in preds if p["domain"] == "CONFLICT")
    assert 0.05 <= conflict["probability"] <= 0.95
    assert conflict["confidence"] in ("LOW", "MEDIUM", "HIGH")
    assert conflict["horizon"] in ("24h", "7d", "30d")
    assert conflict["confirm"] and conflict["deny"]


def test_forecast_json_parser_handles_code_fences():
    raw = '```json\n[{"statement":"x","probability":0.6}]\n```'
    out = forecast._parse_json_array(raw)
    assert out[0]["statement"] == "x"


def test_forecast_normalise_clamps_and_scales_probability():
    p = forecast._normalise({"statement": "Y", "probability": 140, "domain": "cyber"})
    assert p["probability"] <= 0.95 and p["domain"] == "CYBER" and p["source"] == "ai"


def test_generate_forecast_falls_back_to_heuristic_offline(offline_data, monkeypatch):
    # No AI key → ai_forecast raises/returns offline → heuristic path.
    monkeypatch.setattr(forecast.deepseek.config, "DEEPSEEK_API_KEY", "")
    fc = forecast.generate_forecast()
    assert fc["method"] in ("heuristic", "ai+heuristic")
    assert "predictions" in fc and "signals" in fc
    assert all(0.05 <= p["probability"] <= 0.95 for p in fc["predictions"])


def test_forecast_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        app_module.forecast, "generate_forecast",
        lambda: {"method": "heuristic", "predictions": [
            {"statement": "T", "domain": "CONFLICT", "region": "MENA",
             "probability": 0.6, "confidence": "MEDIUM", "horizon": "7d",
             "drivers": [], "confirm": "", "deny": "", "source": "heuristic"}],
            "signals": {}, "simulated": True})
    d = client.get("/api/forecast").get_json()
    assert d["predictions"][0]["domain"] == "CONFLICT"
