"""News → brain ingestion pipeline (continuous learning).

Periodically: scrape the aggregated global news, **distil each batch with
DeepSeek** into concise intelligence facts (entities, events, assessments), and
imprint them as neurons in the persistent memory. Shared keywords automatically
wire the new neurons into the existing graph, so the brain accumulates a
connected model of world events over time — which the ORACLE then reads when
forecasting (see :mod:`jarvis.forecast`).

Degrades gracefully: with no DeepSeek key (or if distillation fails) it stores
the raw headlines as neurons instead, so the pipeline keeps learning offline.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List

from jarvis import deepseek, memory, news, runtime

_STATUS: Dict = {"last_run": None, "runs": 0, "last_count": 0,
                 "processor": "—", "neurons": 0}
_THREAD = None
_LOCK = threading.Lock()


def _parse_json_array(text: str) -> List[Dict]:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    a, b = text.find("["), text.rfind("]")
    if a == -1 or b == -1:
        raise ValueError("no JSON array")
    return json.loads(text[a:b + 1])


def _distill(items: List[Dict]) -> List[Dict]:
    """DeepSeek → list of {text, tags} intelligence facts extracted from news."""
    lines = [f"- [{it['region']}/{it['topic']}] {it['title']}" for it in items]
    prompt = (
        "You are an intelligence analyst. From these news headlines, extract the "
        "key, durable intelligence as a JSON array (no prose) of objects "
        '{"fact","tags"} where fact is one concise factual statement (<140 chars) '
        "and tags is 2-5 lowercase keyword tags (entities, places, themes). Merge "
        "duplicates; keep only substantive items.\n\nHEADLINES:\n" + "\n".join(lines)
    )
    raw = deepseek.complete(
        [{"role": "system", "content": "You output only valid JSON arrays."},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=1100,
    )
    out = []
    for o in _parse_json_array(raw):
        fact = str(o.get("fact", "")).strip()
        if fact:
            tags = [str(t).lower() for t in (o.get("tags") or [])][:6]
            out.append({"text": fact, "tags": tags})
    return out


def ingest_once(limit: int = 30) -> Dict:
    """Run one ingestion cycle: news → (DeepSeek distil) → neurons."""
    items = news.get_news().get("items", [])[:limit]
    count = 0
    processor = "raw"

    facts = None
    if runtime.ai_online():
        try:
            facts = _distill(items)
            processor = "deepseek"
        except Exception:
            facts = None  # fall back to raw headlines

    if facts:
        for f in facts:
            if memory.add(f["text"], kind="news", tags=f["tags"]):
                count += 1
    else:
        for it in items:
            tags = [it["topic"].lower(), it["region"].lower()]
            if memory.add(it["title"], kind="news", tags=tags):
                count += 1

    with _LOCK:
        _STATUS.update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "runs": _STATUS["runs"] + 1,
            "last_count": count,
            "processor": processor,
            "neurons": memory.stats()["neurons"],
        })
    return dict(_STATUS)


def get_status() -> Dict:
    with _LOCK:
        return {**_STATUS, "auto": _THREAD is not None, "neurons": memory.stats()["neurons"]}


def start_background(interval: int = 600) -> None:
    """Start the auto-ingestion loop (idempotent, daemon)."""
    global _THREAD
    with _LOCK:
        if _THREAD is not None:
            return

    def loop():
        while True:
            try:
                ingest_once()
            except Exception:
                pass
            time.sleep(max(60, interval))

    _THREAD = threading.Thread(target=loop, daemon=True, name="jarvis-ingest")
    _THREAD.start()
