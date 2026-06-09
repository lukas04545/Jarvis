"""J.A.R.V.I.S. — Flask application entrypoint.

Serves the terminal UI and a small JSON/SSE API:

    GET  /                     terminal UI
    GET  /api/status           system + AI core status
    GET  /api/news             aggregated global news stream
    GET  /api/surveillance     global surveillance picture
    GET  /api/briefing         AI-synthesised situational briefing
    POST /api/chat             JARVIS console reply (blocking JSON)
    POST /api/chat/stream      JARVIS console reply (SSE token stream)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Iterator

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from config import config
from jarvis import (
    __version__,
    agents,
    braintools,
    briefing,
    deepseek,
    device,
    devagent,
    forecast,
    gdelt,
    ingest,
    markets,
    memory,
    news,
    osint,
    runtime,
    satellite,
    signals,
    stocks,
    surveillance,
    webcams,
)

app = Flask(__name__)


@app.route("/")
def index():
    ingest.ensure_started()      # kick off continuous learning on first page load
    return render_template("index.html", version=__version__)


@app.route("/sw.js")
def service_worker():
    # Served from root so the worker's scope covers the entire app, not /static.
    resp = send_from_directory(app.static_folder + "/js", "sw.js")
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/api/status")
def api_status():
    online = runtime.ai_online()
    return jsonify(
        {
            "system": "JARVIS",
            "version": __version__,
            "ai_core": "ONLINE" if online else "OFFLINE",
            "model": config.DEEPSEEK_MODEL if online else None,
            "cache_ttl": config.CACHE_TTL,
            "providers": runtime.status(),
        }
    )


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    # Never returns key material — only configured/source flags.
    return jsonify(runtime.status())


@app.route("/api/settings", methods=["POST"])
def api_set_settings():
    body = request.get_json(silent=True) or {}
    runtime.set_keys(
        deepseek_api_key=body.get("deepseek_api_key"),
        hibp_api_key=body.get("hibp_api_key"),
    )
    return jsonify({"ok": True, "providers": runtime.status()})


@app.route("/api/osint", methods=["POST"])
def api_osint():
    body = request.get_json(silent=True) or {}
    result = osint.check_email(body.get("email", ""), authorized=bool(body.get("authorized")))
    code = 200
    if result.get("error") == "authorization required":
        code = 403
    elif result.get("error"):
        code = 400
    return jsonify(result), code


@app.route("/api/memory", methods=["GET"])
def api_memory():
    brain = memory.get(request.args.get("brain", "main"))
    return jsonify({**brain.graph(), "stats": brain.stats()})


@app.route("/api/memory", methods=["POST"])
def api_memory_add():
    body = request.get_json(silent=True) or {}
    brain = memory.get(body.get("brain", "main"))
    if body.get("recall"):
        return jsonify({"memories": brain.recall(str(body["recall"]), k=int(body.get("k", 6)))})
    nid = brain.add(str(body.get("text", "")), kind=str(body.get("kind", "note")),
                    tags=body.get("tags"), body=body.get("body"))
    return jsonify({"ok": bool(nid), "id": nid, **brain.graph()})


@app.route("/api/memory/<nid>", methods=["DELETE"])
def api_memory_forget(nid):
    brain = memory.get(request.args.get("brain", "main"))
    return jsonify({"ok": brain.forget(nid)})


@app.route("/api/ingest", methods=["GET"])
def api_ingest_status():
    return jsonify(ingest.get_status())


@app.route("/api/ingest", methods=["POST"])
def api_ingest_run():
    # Scrape news → distil with DeepSeek → imprint connected neurons.
    return jsonify({**ingest.ingest_once(), **memory.graph()})


@app.route("/api/webcams")
def api_webcams():
    return jsonify(webcams.get_webcams())


@app.route("/api/satellite")
def api_satellite():
    return jsonify(satellite.get_satellite())


@app.route("/api/markets")
def api_markets():
    return jsonify(markets.get_markets())


@app.route("/api/stocks")
def api_stocks_watchlist():
    return jsonify(stocks.get_watchlist())


@app.route("/api/stocks/<ticker>")
def api_stocks(ticker):
    horizon = request.args.get("horizon", 20)
    result = stocks.get_forecast(ticker, horizon)
    return jsonify(result), (400 if result.get("error") else 200)


@app.route("/api/gdelt")
def api_gdelt():
    return jsonify(gdelt.get_gdelt())


@app.route("/api/signals")
def api_signals():
    return jsonify(signals.build_signals())


@app.route("/api/forecast")
def api_forecast():
    # The ORACLE: quantitative signals + heuristic + DeepSeek predictions.
    return jsonify(forecast.generate_forecast())


@app.route("/api/device", methods=["GET"])
def api_get_device():
    return jsonify(device.get_device())


@app.route("/api/device", methods=["POST"])
def api_set_device():
    # The operator's own browser reports non-sensitive device telemetry here so
    # the SENTINEL agent can read it. Screen/audio are never sent (see device.py).
    body = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "stored": device.set_device(body)})


@app.route("/api/dev", methods=["GET"])
def api_dev_status():
    return jsonify(devagent.status())


@app.route("/api/dev", methods=["POST"])
def api_dev_run():
    task = ((request.get_json(silent=True) or {}).get("task") or "").strip()
    if not task:
        return jsonify({"error": "empty task"}), 400
    result = devagent.develop(task)
    code = 403 if result.get("error", "").startswith("DEV agent is disabled") else 200
    return jsonify(result), code


@app.route("/api/dev/rollback", methods=["POST"])
def api_dev_rollback():
    if not devagent.enabled():
        return jsonify({"error": "DEV agent is disabled"}), 403
    return jsonify(devagent.rollback_last())


@app.route("/api/agents", methods=["POST"])
def api_agents():
    query = ((request.get_json(silent=True) or {}).get("query") or "").strip()
    if not query:
        return jsonify({"error": "empty query"}), 400
    return jsonify(agents.run_taskforce(query))


@app.route("/api/agents/stream", methods=["POST"])
def api_agents_stream():
    query = ((request.get_json(silent=True) or {}).get("query") or "").strip()
    if not query:
        return jsonify({"error": "empty query"}), 400

    def event_stream() -> Iterator[str]:
        try:
            for event in agents.stream_taskforce(query):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # pragma: no cover - defensive
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/news")
def api_news():
    region = request.args.get("region")
    topic = request.args.get("topic")
    data = news.get_news()
    if region or topic:
        data = {
            **data,
            "items": [
                it
                for it in data["items"]
                if (not region or it["region"] == region)
                and (not topic or it["topic"] == topic)
            ],
        }
    return jsonify(data)


@app.route("/api/surveillance")
def api_surveillance():
    return jsonify(surveillance.get_surveillance())


@app.route("/api/briefing")
def api_briefing():
    try:
        return jsonify(briefing.generate_briefing())
    except deepseek.DeepSeekError as exc:
        return jsonify({"error": str(exc)}), 502


def _chat_inputs() -> tuple[str, str | None]:
    body = request.get_json(silent=True) or {}
    prompt = (body.get("message") or "").strip()
    parts = []
    # Persistent memory: recall related neurons so JARVIS has continuity.
    try:
        mem = memory.recall(prompt, k=5)
        if mem:
            parts.append("Relevant long-term memory:\n" +
                         "\n".join(f"- {m['text']}" for m in mem))
    except Exception:
        pass
    # Optionally enrich with the live picture so JARVIS can reason over events.
    if body.get("with_context"):
        try:
            n = news.get_news()
            s = surveillance.get_surveillance()
            heads = "; ".join(it["title"] for it in n["items"][:10])
            parts.append(f"Threat posture {s['posture']}. Recent headlines: {heads}")
        except Exception:
            pass
    return prompt, ("\n\n".join(parts) or None)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    prompt, context = _chat_inputs()
    if not prompt:
        return jsonify({"error": "empty message"}), 400
    try:
        # Full brain access: DeepSeek can recall / search / save memory via tools.
        result = deepseek.complete_with_tools(
            deepseek.build_messages(prompt, context),
            braintools.SCHEMA, braintools.IMPLS)
        return jsonify({"reply": result["text"], "tools_used": result["tools_used"]})
    except deepseek.DeepSeekError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    prompt, context = _chat_inputs()
    if not prompt:
        return jsonify({"error": "empty message"}), 400

    messages = deepseek.build_messages(prompt, context)

    def event_stream() -> Iterator[str]:
        # Streamed + full brain access: tool events, then the answer streams in.
        for ev in deepseek.stream_with_tools(messages, braintools.SCHEMA, braintools.IMPLS):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Start continuous learning as soon as the app is imported — so it runs however
# the server is launched (python app.py, gunicorn, etc.) and even when the PWA
# service worker serves the page from cache and never hits the index route.
# Skipped under pytest so the test suite never spawns the loop / touches the net.
if "pytest" not in sys.modules:
    ingest.ensure_started()


if __name__ == "__main__":
    banner = (
        f"\n  J.A.R.V.I.S. v{__version__}  —  AI core "
        f"{'ONLINE' if runtime.ai_online() else 'OFFLINE (paste a key in SETTINGS or set DEEPSEEK_API_KEY)'}\n"
        f"  Terminal:  http://{config.HOST}:{config.PORT}\n"
    )
    print(banner)
    # Continuous learning: scrape news → distil → connected neurons → forecasts.
    ingest.ensure_started()
    app.run(host=config.HOST, port=config.PORT, threaded=True)
