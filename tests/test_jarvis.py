"""Smoke + unit tests for J.A.R.V.I.S.

These avoid hitting the network: external feeds are monkeypatched so the API
surface, caching, and offline AI fallback are all exercised deterministically.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from jarvis import (  # noqa: E402
    agents, braintools, deepseek, devagent, device, fallback, forecast, ingest, memory,
    news, osint, runtime, signals, stocks, surveillance, webcams,
)


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p
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
    """Keep the runtime key store + brain confined to temp; reset rate limiter."""
    monkeypatch.setattr(runtime, "_SECRETS_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setattr(runtime, "_overrides", {})
    monkeypatch.setattr(memory, "_PATH", str(tmp_path / "brain.json"))
    monkeypatch.setattr(memory, "_neurons", {})
    osint._HITS.clear()
    # Never spawn the background ingest loop or hit the network during tests.
    monkeypatch.setenv("JARVIS_AUTO_INGEST", "0")
    monkeypatch.setenv("JARVIS_SCRAPE_ARTICLES", "0")
    monkeypatch.setattr(ingest, "_STARTED", False)
    monkeypatch.setattr(ingest, "_THREAD", None)


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


# ── Agent harness ──────────────────────────────────────────────────────────
def test_agent_routing_picks_specialists_and_core():
    geo = [a.name for a in agents.route("assess military escalation on the border")]
    assert "GEOINT" in geo
    econ = [a.name for a in agents.route("inflation and oil market outlook")]
    assert "ECONINT" in econ and "ORACLE" in econ          # 'outlook' → ORACLE
    fallback_route = [a.name for a in agents.route("zxqw nonsense")]
    assert fallback_route == agents.CORE                    # core desk fallback


def test_agent_tool_digests_do_not_crash(offline_data):
    for name, fn in agents.TOOLS.items():
        out = fn()
        assert isinstance(out, str) and out


def test_agent_run_offline_returns_data_briefing(offline_data, monkeypatch):
    monkeypatch.setattr(agents.runtime.config, "DEEPSEEK_API_KEY", "")
    res = agents.AGENTS_BY_NAME["GEOINT"].run("conflict risk?")
    assert res["name"] == "GEOINT" and res["mode"] == "offline"
    assert "OFFLINE" in res["findings"] and res["tools"]


def test_run_taskforce_offline_full_shape(offline_data, monkeypatch):
    monkeypatch.setattr(agents.runtime.config, "DEEPSEEK_API_KEY", "")
    out = agents.run_taskforce("what is likely to escalate next week?")
    assert out["online"] is False
    assert out["plan"] and len(out["agents"]) == len(out["plan"])
    assert all(a["findings"] for a in out["agents"])
    assert "text" in out["synthesis"]


def test_agents_endpoint_requires_query(client):
    assert client.post("/api/agents", json={"query": "  "}).status_code == 400


def test_agents_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        app_module.agents, "run_taskforce",
        lambda q: {"query": q, "plan": ["GEOINT"], "agents": [
            {"name": "GEOINT", "role": "r", "tools": [], "mode": "offline", "findings": "x"}],
            "synthesis": {"text": "ok", "mode": "offline"}, "online": False})
    d = client.post("/api/agents", json={"query": "test"}).get_json()
    assert d["plan"] == ["GEOINT"] and d["agents"][0]["name"] == "GEOINT"


# ── Device telemetry (memory / screen / input) ─────────────────────────────
def test_device_store_sanitises_and_roundtrips():
    device.reset()
    stored = device.set_device({
        "memory": {"deviceMemoryGB": 8, "jsHeapMB": 42, "evil": "rm -rf"},
        "hardware": {"cores": 12, "ua": "x" * 500},
        "screen": {"width": 1920, "height": 1080},
        "capture": {"screenSharing": True, "micListening": False},
        "secret_section": {"password": "hunter2"},   # must be dropped
    })
    assert "secret_section" not in stored
    assert "evil" not in stored["memory"]              # unknown key dropped
    assert len(stored["hardware"]["ua"]) <= 160        # value capped
    got = device.get_device()
    assert got["memory"]["deviceMemoryGB"] == 8 and got["screen"]["width"] == 1920
    assert got["capture"]["screenSharing"] is True


def test_device_endpoints(client):
    device.reset()
    r = client.post("/api/device", json={"hardware": {"cores": 4}})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    got = client.get("/api/device").get_json()
    assert got["hardware"]["cores"] == 4


def test_sentinel_agent_reads_device_telemetry():
    device.reset()
    assert "no device telemetry" in agents.TOOLS["device"]()  # empty case
    device.set_device({"hardware": {"cores": 16, "platform": "Linux"},
                       "screen": {"width": 2560, "height": 1440}})
    digest = agents.TOOLS["device"]()
    assert "16 cores" in digest and "2560x1440" in digest


def test_expanded_agent_roster_and_routing():
    names = set(agents.AGENTS_BY_NAME)
    assert {"OSINT", "MEDINT", "ENERGY", "CLIMATE", "SENTINEL", "REDCELL"} <= names
    assert len(agents.AGENTS) >= 11
    # Device wording routes to SENTINEL; routing is capped.
    assert "SENTINEL" in [a.name for a in agents.route("check my device memory and screen")]
    assert len(agents.route("health energy climate cyber market conflict device weather")) <= agents.MAX_AGENTS


# ── Persistent memory / brain ──────────────────────────────────────────────
def test_memory_add_recall_and_edges():
    a = memory.add("Tensions rising on the eastern border", kind="intel")
    memory.add("Border ceasefire talks collapse", kind="intel")
    memory.add("Bitcoin rallies on ETF inflows", kind="markets")
    assert a
    g = memory.graph()
    assert g["count"] == 3
    # The two border memories share keywords → at least one synapse.
    assert g["synapses"] >= 1
    hits = memory.recall("border ceasefire", k=2)
    assert hits and any("border" in h["text"].lower() for h in hits)


def test_memory_weight_is_clamped_and_strengthens():
    nid = memory.add("Critical: nuclear test detected", kind="intel", weight=10)
    memory.add("trivial note", weight=99)        # clamps to 10
    memory.add("trivial note", weight=2)         # dedup keeps the higher weight
    g = {n["text"]: n for n in memory.graph()["neurons"]}
    assert g["Critical: nuclear test detected"]["weight"] == 10
    assert g["trivial note"]["weight"] == 10     # max kept on dedup
    # default importance when unspecified
    memory.add("plain memory")
    assert {n["text"]: n for n in memory.graph()["neurons"]}["plain memory"]["weight"] == 5


def test_ingest_heuristic_weight_for_hot_news(monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")   # raw path
    monkeypatch.setattr(ingest.news, "get_news", lambda: {"items": [
        {"title": "Missile attack kills dozens near capital", "topic": "CONFLICT", "region": "Global"},
        {"title": "Local museum reopens after renovation", "topic": "GENERAL", "region": "Europe"},
    ]})
    ingest.ingest_once()
    by = {n["text"].split(" —")[0]: n for n in memory.graph()["neurons"]}
    hot = by["Missile attack kills dozens near capital"]["weight"]
    mild = by["Local museum reopens after renovation"]["weight"]
    assert hot >= 9 and hot > mild      # conflict + global + hot keywords → high


def test_memory_persists_to_disk(tmp_path, monkeypatch):
    path = str(tmp_path / "b.json")
    monkeypatch.setattr(memory, "_PATH", path)
    monkeypatch.setattr(memory, "_neurons", {})
    memory.add("Persistent neuron")
    assert os.path.exists(path)


def test_memory_endpoints(client):
    assert client.post("/api/memory", json={"text": "Remember the Alamo"}).get_json()["ok"]
    g = client.get("/api/memory").get_json()
    assert g["count"] == 1
    rec = client.post("/api/memory", json={"recall": "alamo"}).get_json()
    assert rec["memories"] and "Alamo" in rec["memories"][0]["text"]


def test_chat_context_includes_memory(client, monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")
    memory.add("Operator prefers terse briefings")
    # Offline reply still proves the route works; memory recall must not error.
    r = client.post("/api/chat", json={"message": "give me a briefing"})
    assert r.status_code == 200


# ── OSINT / email exposure (holehe + breach metadata) ──────────────────────
def test_osint_requires_authorization(client):
    r = client.post("/api/osint", json={"email": "test@example.com", "authorized": False})
    assert r.status_code == 403
    assert "authoriz" in r.get_json()["error"].lower()


def test_osint_rejects_invalid_email(client):
    r = client.post("/api/osint", json={"email": "not-an-email", "authorized": True})
    assert r.status_code == 400


def test_osint_returns_metadata_never_passwords():
    res = osint.check_email("user@example.com", authorized=True)
    assert res["email"] == "user@example.com"
    assert res["accounts_checked"] == len(osint.SITES)
    assert "accounts_found" in res and isinstance(res["breaches"], list)
    # Breach entries are metadata only (data-class *labels*, no leaked values).
    for b in res["breaches"]:
        assert set(b) <= {"name", "domain", "date", "pwnCount", "dataClasses"}
        assert all(isinstance(c, str) for c in b["dataClasses"])
    # Hard guarantee: no field anywhere leaks credentials/plaintext records.
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k.lower(); yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    bad = {"password", "passwd", "credential", "credentials", "plaintext", "hash", "secret"}
    assert not (set(keys(res)) & bad)


def test_osint_rate_limit():
    for _ in range(osint._MAX_PER_MIN):
        osint.check_email("a@b.co", authorized=True)
    blocked = osint.check_email("a@b.co", authorized=True)
    assert "rate limit" in blocked.get("error", "")


# ── Expanded harness: RECON + CORTEX desks ─────────────────────────────────
def test_recon_agent_runs_osint_from_task():
    out = agents.TOOLS  # base tools unchanged
    assert "device" in out
    digest = agents.CONTEXT_TOOLS["osint"]("check exposure for jane@example.com please")
    assert "jane@example.com" in digest and "accounts found" in digest


def test_cortex_rides_along_when_memory_exists():
    memory.add("Prior assessment: supply-chain stress elevated")
    names = [a.name for a in agents.route("supply-chain assessment")]
    assert "CORTEX" in names


def test_full_roster_has_recon_and_cortex():
    assert {"RECON", "CORTEX"} <= set(agents.AGENTS_BY_NAME)
    assert len(agents.AGENTS) >= 13


# ── News → brain ingestion (continuous learning) ───────────────────────────
def test_ingest_offline_stores_headlines_as_neurons(monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")  # offline → raw path
    sample = {"items": [
        {"title": "Border clashes intensify in the east", "topic": "CONFLICT", "region": "MENA"},
        {"title": "Markets fall on rate fears", "topic": "MARKETS", "region": "Global"},
    ]}
    monkeypatch.setattr(ingest.news, "get_news", lambda: sample)
    st = ingest.ingest_once()
    assert st["processor"] == "raw" and st["last_count"] == 2
    assert memory.stats()["neurons"] == 2
    # stored as 'news' neurons that can be recalled
    assert memory.recall("border clashes", k=1)


def test_ingest_neuron_carries_context_not_just_headline(monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")  # offline → raw path
    monkeypatch.setattr(ingest.news, "get_news", lambda: {"items": [{
        "title": "Coup attempt reported in capital",
        "summary": "Soldiers seized the state broadcaster overnight; the president's whereabouts are unknown.",
        "source": "Reuters", "region": "Africa", "topic": "POLITICS",
        "link": "https://example.com/a", "time": "08:12",
    }]})
    ingest.ingest_once()
    g = memory.graph()
    n = g["neurons"][0]
    assert "—" in n["text"] and "broadcaster" in n["text"].lower()   # more than headline
    assert n["meta"]["source"] == "Reuters" and n["meta"]["region"] == "Africa"
    assert n["meta"]["link"] == "https://example.com/a"


def test_ensure_started_respects_env(monkeypatch):
    monkeypatch.setenv("JARVIS_AUTO_INGEST", "0")
    monkeypatch.setattr(ingest, "_STARTED", False)
    monkeypatch.setattr(ingest, "_THREAD", None)
    ingest.ensure_started()
    assert ingest._THREAD is None      # did not start


def test_import_does_not_autostart_under_pytest():
    # The import-time auto-start must be skipped while testing.
    assert ingest._THREAD is None


def test_ingest_status_exposes_auto_and_interval(client, monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(app_module.ingest.news, "get_news",
                        lambda: {"items": [{"title": "T", "topic": "TECH", "region": "Global"}]})
    client.post("/api/ingest")
    s = client.get("/api/ingest").get_json()
    assert "auto" in s and "interval" in s and s["interval"] >= 60
    assert s["age"] >= 0 and "next_in" in s


def test_ingest_distills_with_deepseek(monkeypatch):
    monkeypatch.setattr(ingest.runtime, "ai_online", lambda: True)
    monkeypatch.setattr(ingest.news, "get_news", lambda: {"items": [
        {"title": "X", "topic": "TECH", "region": "Global"}]})
    monkeypatch.setattr(ingest.deepseek, "complete",
                        lambda *a, **k: '```json\n[{"fact":"Chip export curbs widen","tags":["chips","trade"],"domain":"TECH"}]\n```')
    st = ingest.ingest_once()
    assert st["processor"] == "deepseek" and st["last_count"] == 1
    assert memory.recall("chip export", k=1)
    # distilled neuron is tagged with its topic/domain (drives the colour map)
    assert memory.graph()["neurons"][0]["meta"]["topic"] == "TECH"


# ── DeepSeek full brain access (tool calling) ──────────────────────────────
def test_braintools_impls_read_write():
    assert braintools._save(text="Operator prefers terse briefings")["saved"]
    hits = braintools._recall(query="terse briefings")
    assert hits and "terse" in hits[0]["text"].lower()
    assert braintools._stats()["neurons"] >= 1


def test_complete_with_tools_offline_returns_stub(monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")
    out = deepseek.complete_with_tools([{"role": "user", "content": "hi"}],
                                       braintools.SCHEMA, braintools.IMPLS)
    assert "OFFLINE MODE" in out["text"] and out["tools_used"] == []


def test_complete_with_tools_executes_and_saves(monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "sk-x")   # online
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:   # first round: model asks to save a memory
            return _FakeResp({"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "save_memory",
                    "arguments": '{"text":"Operator likes terse briefings","tags":["pref"]}'}}]}}]})
        return _FakeResp({"choices": [{"message": {"role": "assistant", "content": "Noted, Operator."}}]})

    monkeypatch.setattr(deepseek.requests, "post", fake_post)
    out = deepseek.complete_with_tools([{"role": "user", "content": "remember I like terse"}],
                                       braintools.SCHEMA, braintools.IMPLS)
    assert out["text"] == "Noted, Operator."
    assert any(t["name"] == "save_memory" for t in out["tools_used"])
    assert memory.recall("terse briefings", k=1)   # DeepSeek actually wrote to the brain


def test_chat_endpoint_returns_tools_used(client, monkeypatch):
    monkeypatch.setattr(app_module.deepseek, "complete_with_tools",
                        lambda *a, **k: {"text": "ok", "tools_used": [{"name": "recall_memory", "args": {}}]})
    d = client.post("/api/chat", json={"message": "hello"}).get_json()
    assert d["reply"] == "ok" and d["tools_used"][0]["name"] == "recall_memory"


def test_ingest_endpoint(client, monkeypatch):
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(app_module.ingest.news, "get_news",
                        lambda: {"items": [{"title": "Quake hits coast", "topic": "DISASTER", "region": "Asia"}]})
    d = client.post("/api/ingest").get_json()
    assert d["last_count"] == 1 and d["count"] == 1   # graph() count merged in


def test_forecast_feeds_brain_memory_into_prompt(monkeypatch):
    memory.add("Eastern border tensions have been escalating for weeks", kind="news")
    captured = {}
    monkeypatch.setattr(forecast.deepseek, "complete",
                        lambda msgs, **k: captured.setdefault("p", msgs[-1]["content"]) and None or "[]")
    sig = {"domains": {}, "regions": {}, "gdelt": {}, "markets": {}, "geophysical": {},
           "satellite": {}, "anomalies": ["border tensions escalating"],
           "top_headlines": ["Eastern border tensions rise"]}
    forecast.ai_forecast(sig)
    assert "PRIOR INTELLIGENCE" in captured.get("p", "")


# ── DEV agent (self-coding harness) ────────────────────────────────────────
def test_devagent_path_safety(tmp_path, monkeypatch):
    monkeypatch.setattr(devagent, "REPO_ROOT", str(tmp_path))
    (tmp_path / "ok.py").write_text("x = 1")
    assert devagent._safe("ok.py").endswith("ok.py")
    for bad in ["../escape.txt", "../../etc/passwd", ".git/config", ".env",
                ".jarvis_secrets.json", "jarvis/../../x"]:
        with pytest.raises(ValueError):
            devagent._safe(bad)


def test_devagent_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("JARVIS_ENABLE_DEVAGENT", raising=False)
    assert devagent.enabled() is False
    r = client.post("/api/dev", json={"task": "do something"})
    assert r.status_code == 403 and "disabled" in r.get_json()["error"].lower()
    assert devagent.status()["enabled"] is False


def test_devagent_writes_and_iterates(tmp_path, monkeypatch):
    # Enable + confine to a temp repo; drive a fake DeepSeek tool loop.
    monkeypatch.setenv("JARVIS_ENABLE_DEVAGENT", "1")
    monkeypatch.setattr(devagent, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "sk-x")   # AI core online
    monkeypatch.setattr(devagent, "_run_tests", lambda: {"passed": True, "output": "ok"})
    monkeypatch.setattr(devagent, "_git_diff", lambda: "module.py | 1 +")
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:        # round 1: agent writes a file
            return _FakeResp({"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "write_file",
                    "arguments": '{"path":"module.py","content":"def ping():\\n    return True\\n"}'}}]}}]})
        return _FakeResp({"choices": [{"message": {"role": "assistant",
            "content": "Added module.py with a ping() function."}}]})

    monkeypatch.setattr(deepseek.requests, "post", fake_post)
    out = devagent.develop("add a ping function")
    assert (tmp_path / "module.py").read_text().startswith("def ping")
    assert "module.py" in out["files_changed"]
    assert any(a["tool"] == "write_file" for a in out["actions"])
    assert out["tests"]["passed"] is True


def test_devagent_write_blocks_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(devagent, "REPO_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        devagent._safe("../../evil.py")


def test_devagent_extra_workspace_roots(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; repo.mkdir()
    ws = tmp_path / "workspace"; ws.mkdir()
    outside = tmp_path / "private"; outside.mkdir()
    monkeypatch.setattr(devagent, "REPO_ROOT", str(repo))
    monkeypatch.setenv("JARVIS_DEV_ROOTS", str(ws))

    (ws / "a.py").write_text("x")
    assert devagent._safe(str(ws / "a.py")).endswith("a.py")   # granted workspace OK
    with pytest.raises(ValueError):                            # not granted → rejected
        devagent._safe(str(outside / "secret.txt"))
    # .git and secret files are blocked even inside a granted workspace
    with pytest.raises(ValueError):
        devagent._safe(str(ws / ".git" / "config"))
    with pytest.raises(ValueError):
        devagent._safe(str(ws / ".env"))
    assert str(ws) in devagent.status()["extra_roots"]
    assert devagent.status()["workspace_count"] == 2


def test_devagent_refuses_filesystem_root(monkeypatch):
    monkeypatch.setenv("JARVIS_DEV_ROOTS", "/")
    assert devagent._extra_roots() == []      # '/' is never accepted


def test_devagent_make_dir_confined(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; repo.mkdir()
    ws = tmp_path / "ws"; ws.mkdir()
    monkeypatch.setattr(devagent, "REPO_ROOT", str(repo))
    monkeypatch.setenv("JARVIS_DEV_ROOTS", str(ws))
    made = devagent._make_dir(str(ws / "newproj" / "src"))
    assert os.path.isdir(made)
    with pytest.raises(ValueError):                       # outside granted roots
        devagent._make_dir(str(tmp_path / "elsewhere"))


def test_devagent_external_project_not_gated_by_jarvis_tests(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; repo.mkdir()
    ws = tmp_path / "ws"; ws.mkdir()
    monkeypatch.setenv("JARVIS_ENABLE_DEVAGENT", "1")
    monkeypatch.setattr(devagent, "REPO_ROOT", str(repo))
    monkeypatch.setenv("JARVIS_DEV_ROOTS", str(ws))
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "sk-x")

    def boom():
        raise AssertionError("Jarvis tests must not run for external-only changes")
    monkeypatch.setattr(devagent, "_run_tests", boom)

    proj = str(ws / "newapp")
    js = __import__("json")
    seq = iter([("make_dir", {"path": proj}),
                ("write_file", {"path": proj + "/main.py", "content": "print('hi')\n"})])

    def fake_post(url, headers=None, json=None, timeout=None):
        try:
            name, args = next(seq)
            return _FakeResp({"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c", "type": "function",
                                "function": {"name": name, "arguments": js.dumps(args)}}]}}]})
        except StopIteration:
            return _FakeResp({"choices": [{"message": {"role": "assistant", "content": "scaffolded newapp"}}]})
    monkeypatch.setattr(deepseek.requests, "post", fake_post)

    out = devagent.develop("create a new app in the workspace")
    assert out["tests_gated"] is False and out["rolled_back"] is False and out["tests"] is None
    assert os.path.isfile(proj + "/main.py")
    assert any("main.py" in f for f in out["files_changed"])
    assert any("newapp" in d for d in out["dirs_created"])


def _drive_write(content, tmp_path):
    """Build a fake DeepSeek that writes module.py then finishes."""
    state = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            args = '{"path":"module.py","content":' + __import__("json").dumps(content) + '}'
            return _FakeResp({"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "write_file", "arguments": args}}]}}]})
        return _FakeResp({"choices": [{"message": {"role": "assistant", "content": "done"}}]})
    return fake_post


def test_devagent_autorolls_back_on_test_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_DEVAGENT", "1")
    monkeypatch.setattr(devagent, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "sk-x")
    monkeypatch.setattr(devagent, "_git_diff", lambda: "")
    # Tests fail after the write, then pass once it's rolled back.
    seq = iter([{"passed": False, "output": "boom"}, {"passed": True, "output": "ok"}])
    monkeypatch.setattr(devagent, "_run_tests", lambda: next(seq))
    monkeypatch.setattr(deepseek.requests, "post", _drive_write("def broken(:\n", tmp_path))

    out = devagent.develop("write a broken file")
    assert out["rolled_back"] is True
    assert out["tests_after_rollback"]["passed"] is True
    assert not (tmp_path / "module.py").exists()   # new file removed on rollback


def test_devagent_manual_rollback_restores_original(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_DEVAGENT", "1")
    monkeypatch.setattr(devagent, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(deepseek.config, "DEEPSEEK_API_KEY", "sk-x")
    monkeypatch.setattr(devagent, "_git_diff", lambda: "")
    monkeypatch.setattr(devagent, "_run_tests", lambda: {"passed": True, "output": "ok"})
    (tmp_path / "module.py").write_text("ORIGINAL\n")          # pre-existing file
    monkeypatch.setattr(deepseek.requests, "post", _drive_write("CHANGED\n", tmp_path))

    out = devagent.develop("change module.py")
    assert out["rolled_back"] is False and out["can_rollback"] is True
    assert (tmp_path / "module.py").read_text() == "CHANGED\n"
    # Manual rollback restores the previous version.
    res = devagent.rollback_last()
    assert "module.py" in res["restored"]
    assert (tmp_path / "module.py").read_text() == "ORIGINAL\n"


# ── Stocks (tracking + TimesFM/statistical forecast) ───────────────────────
def test_stooq_symbol_mapping():
    assert stocks._stooq_symbol("AAPL") == "aapl.us"
    assert stocks._stooq_symbol("^SPX") == "^spx"
    assert stocks._stooq_symbol("cl.f") == "cl.f"


def test_gbm_forecast_shape_and_bands():
    import math
    closes = [100.0]
    for i in range(1, 80):                       # realistic volatility
        closes.append(closes[-1] * math.exp(0.001 + (0.02 if i % 2 else -0.017)))
    fc = stocks._gbm_forecast(closes, 15)
    assert len(fc) == 15
    for p in fc:
        assert p["lo"] <= p["yhat"] <= p["hi"]
    # the confidence cone widens with horizon
    assert (fc[-1]["hi"] - fc[-1]["lo"]) > (fc[0]["hi"] - fc[0]["lo"])


def test_get_forecast_falls_back_to_simulated(monkeypatch):
    # Force the live history fetch to fail → deterministic simulated series.
    monkeypatch.setattr(stocks, "_fetch_history", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(stocks.config, "CACHE_TTL", 0)
    d = stocks.get_forecast("AAPL", horizon=20)
    assert d["simulated"] is True and d["ticker"] == "AAPL"
    assert d["method"] == "statistical" and len(d["forecast"]) == 20
    assert d["history"] and "predicted" in d


def test_stocks_endpoint(client, monkeypatch):
    monkeypatch.setattr(stocks, "_fetch_history", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(stocks.config, "CACHE_TTL", 0)
    r = client.get("/api/stocks/MSFT?horizon=10")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ticker"] == "MSFT" and len(d["forecast"]) == 10


def test_stocks_invalid_ticker(client):
    assert client.get("/api/stocks/%20%20").status_code in (400, 404)


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
