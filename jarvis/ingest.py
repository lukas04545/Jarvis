"""News → brain ingestion pipeline (continuous web learning).

Each cycle:
  1. pull the aggregated global news feed (links included);
  2. **scrape the article web pages** and extract the body text;
  3. **distil each batch with DeepSeek** into concise intelligence facts (entities,
     events, assessments) — or store the headline+snippet raw when offline;
  4. imprint them as 'news' neurons in the persistent brain, where shared
     keywords/entities automatically wire them together.

The ORACLE then reads this accumulated, connected knowledge when forecasting
(see :mod:`jarvis.forecast`), so predictions sharpen as the brain learns.

Runs automatically: the loop is started the first time the app serves a page
(:func:`ensure_started`) and on launch, so it works however the server is run.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List

import requests

from config import config
from jarvis import deepseek, memory, news, runtime

_STATUS: Dict = {"last_run": None, "runs": 0, "last_count": 0,
                 "processor": "—", "scraped": 0, "neurons": 0}
_THREAD = None
_STARTED = False
_LOCK = threading.Lock()

_UA = "Mozilla/5.0 (compatible; JARVIS-Terminal/1.0; +intelligence)"
_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_PARA = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")


# ── web scraping ───────────────────────────────────────────────────────────
def _clean_html(raw: str) -> str:
    raw = _SCRIPT.sub(" ", raw)
    paras = _PARA.findall(raw)
    body = " ".join(paras) if paras else raw
    body = _html.unescape(_TAGS.sub(" ", body))
    return re.sub(r"\s+", " ", body).strip()


def _fetch_article(url: str) -> str:
    if not url or os.environ.get("JARVIS_SCRAPE_ARTICLES", "1") == "0":
        return ""
    try:
        r = requests.get(url, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": _UA})
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
            return ""
        return _clean_html(r.text)[:800]
    except Exception:
        return ""


def _scrape(items: List[Dict]) -> int:
    """Fetch + attach article body text to each item (concurrent). Returns hits."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        bodies = list(pool.map(lambda it: _fetch_article(it.get("link", "")), items))
    hits = 0
    for it, body in zip(items, bodies):
        it["body"] = body
        if body:
            hits += 1
    return hits


# ── DeepSeek distillation ──────────────────────────────────────────────────
def _parse_json_array(text: str) -> List[Dict]:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    a, b = text.find("["), text.rfind("]")
    if a == -1 or b == -1:
        raise ValueError("no JSON array")
    return json.loads(text[a:b + 1])


def _distill(items: List[Dict]) -> List[Dict]:
    lines = []
    for it in items:
        body = (it.get("body") or "")[:300]
        lines.append(f"- [{it['region']}/{it['topic']}] {it['title']}." + (f" {body}" if body else ""))
    prompt = (
        "You are an intelligence analyst. From these scraped news items, extract the "
        "key, durable intelligence as a JSON array (no prose) of objects "
        '{"fact","tags"} where fact is one concise factual statement (<140 chars) '
        "and tags is 2-5 lowercase keyword tags (entities, places, themes). Merge "
        "duplicates; keep only substantive items.\n\nNEWS:\n" + "\n".join(lines)
    )
    raw = deepseek.complete(
        [{"role": "system", "content": "You output only valid JSON arrays."},
         {"role": "user", "content": prompt}],
        temperature=0.3, max_tokens=1200,
    )
    out = []
    for o in _parse_json_array(raw):
        fact = str(o.get("fact", "")).strip()
        if fact:
            out.append({"text": fact, "tags": [str(t).lower() for t in (o.get("tags") or [])][:6]})
    return out


# ── ingest cycle ───────────────────────────────────────────────────────────
def ingest_once(limit: int = 24) -> Dict:
    items = [dict(it) for it in news.get_news().get("items", [])[:limit]]
    scraped = _scrape(items)

    count = 0
    processor = "raw"
    facts = None
    if runtime.ai_online():
        try:
            facts = _distill(items)
            processor = "deepseek"
        except Exception:
            facts = None

    if facts:
        for f in facts:
            if memory.add(f["text"], kind="news", tags=f["tags"],
                          meta={"source": "DeepSeek synthesis", "processor": "deepseek"}):
                count += 1
    else:
        for it in items:
            # Store more than the headline: headline + a context snippet, plus
            # source/region/topic/link metadata for inspection and recall.
            snippet = (it.get("body") or it.get("summary") or "").strip()
            snippet = re.sub(r"\s+", " ", snippet)[:240]
            text = f"{it['title']} — {snippet}" if snippet else it["title"]
            kws = re.findall(r"[a-z0-9]{4,}", snippet.lower())[:6]
            tags = [it["topic"].lower(), it["region"].lower()] + kws[:4]
            meta = {"source": it.get("source", ""), "region": it.get("region", ""),
                    "topic": it.get("topic", ""), "link": it.get("link", ""),
                    "time": it.get("time", "")}
            if memory.add(text, kind="news", tags=tags, meta=meta):
                count += 1

    neurons = memory.stats()["neurons"]
    with _LOCK:
        _STATUS.update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "runs": _STATUS["runs"] + 1, "last_count": count,
            "processor": processor, "scraped": scraped, "neurons": neurons,
        })
    print(f"  [ingest] +{count} neurons via {processor} "
          f"(scraped {scraped}/{len(items)} articles) → {neurons} total", flush=True)
    return dict(_STATUS)


def get_status() -> Dict:
    with _LOCK:
        return {**_STATUS, "auto": _THREAD is not None, "neurons": memory.stats()["neurons"]}


def start_background(interval: int = 300) -> None:
    global _THREAD
    with _LOCK:
        if _THREAD is not None:
            return
        _THREAD = True  # placeholder claims the slot, prevents a double-start race

    def loop():
        while True:
            try:
                ingest_once()
            except Exception as exc:
                print(f"  [ingest] cycle failed: {exc}", flush=True)
            time.sleep(max(60, interval))

    t = threading.Thread(target=loop, daemon=True, name="jarvis-ingest")
    _THREAD = t
    t.start()
    print(f"  [ingest] continuous learning ON (every {max(60, interval)}s)", flush=True)


def ensure_started() -> None:
    """Start the loop on first use, however the app was launched (idempotent)."""
    global _STARTED
    if _STARTED or os.environ.get("JARVIS_AUTO_INGEST", "1") == "0":
        return
    _STARTED = True
    start_background(int(os.environ.get("JARVIS_INGEST_INTERVAL", "300")))
