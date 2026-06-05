"""Intelligence briefing synthesis.

Pulls the live news stream and surveillance picture, packs them into a compact
context block, and asks DeepSeek (in the JARVIS persona) to produce a single,
analyst-grade situational briefing.
"""
from __future__ import annotations

from typing import Dict

from jarvis import deepseek, news, surveillance


def _context_block() -> str:
    n = news.get_news()
    s = surveillance.get_surveillance()

    lines = [f"GLOBAL THREAT POSTURE: {s['posture']}",
             f"SENSORS ONLINE: {s['sensors_online']}/{s['sensors_total']}"]

    seismic = s.get("seismic", {})
    if seismic.get("events"):
        top = seismic["events"][0]
        lines.append(
            f"PEAK SEISMIC: M{top['mag']} {top['place']} ({top['level']})"
        )

    lines.append("\nTOP HEADLINES (most recent first):")
    for it in n["items"][:18]:
        lines.append(f"- [{it['time']} {it['region']}/{it['topic']}] {it['title']}")

    lines.append("\nTOPIC VOLUME: " + ", ".join(
        f"{k}={v}" for k, v in sorted(n["topics"].items(), key=lambda x: -x[1])
    ))
    return "\n".join(lines)


def generate_briefing() -> Dict:
    """Return an AI-synthesised situational briefing + the raw context used."""
    context = _context_block()
    prompt = (
        "Produce the global situational briefing for the Operator. Structure it "
        "as: (1) BLUF — one-line bottom line up front; (2) KEY DEVELOPMENTS — "
        "3-5 terse bullets, each with a one-clause 'so what'; (3) WATCH ITEMS — "
        "what to monitor next 24h. Keep it under 220 words. Plain text only."
    )
    text = deepseek.complete(
        deepseek.build_messages(prompt, context=context),
        temperature=0.3,
        max_tokens=700,
    )
    return {"briefing": text, "context": context}
