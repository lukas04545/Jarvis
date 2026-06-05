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
from typing import Iterator

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from config import config
from jarvis import (
    __version__,
    briefing,
    deepseek,
    news,
    runtime,
    satellite,
    surveillance,
    webcams,
)

app = Flask(__name__)


@app.route("/")
def index():
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
        windy_api_key=body.get("windy_api_key"),
    )
    return jsonify({"ok": True, "providers": runtime.status()})


@app.route("/api/webcams")
def api_webcams():
    return jsonify(webcams.get_webcams())


@app.route("/api/satellite")
def api_satellite():
    return jsonify(satellite.get_satellite())


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
    context = None
    # Optionally enrich the conversation with the live picture so JARVIS can
    # reason over current events without the operator pasting them in.
    if body.get("with_context"):
        try:
            n = news.get_news()
            s = surveillance.get_surveillance()
            heads = "; ".join(it["title"] for it in n["items"][:10])
            context = (
                f"Threat posture {s['posture']}. "
                f"Recent headlines: {heads}"
            )
        except Exception:
            context = None
    return prompt, context


@app.route("/api/chat", methods=["POST"])
def api_chat():
    prompt, context = _chat_inputs()
    if not prompt:
        return jsonify({"error": "empty message"}), 400
    try:
        reply = deepseek.complete(deepseek.build_messages(prompt, context))
        return jsonify({"reply": reply})
    except deepseek.DeepSeekError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    prompt, context = _chat_inputs()
    if not prompt:
        return jsonify({"error": "empty message"}), 400

    messages = deepseek.build_messages(prompt, context)

    def event_stream() -> Iterator[str]:
        try:
            for delta in deepseek.stream(messages):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except deepseek.DeepSeekError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    banner = (
        f"\n  J.A.R.V.I.S. v{__version__}  —  AI core "
        f"{'ONLINE' if runtime.ai_online() else 'OFFLINE (paste a key in SETTINGS or set DEEPSEEK_API_KEY)'}\n"
        f"  Terminal:  http://{config.HOST}:{config.PORT}\n"
    )
    print(banner)
    app.run(host=config.HOST, port=config.PORT, threaded=True)
