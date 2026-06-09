"""Keyless web search + page reader — extends JARVIS's reach beyond its feeds.

Search uses DuckDuckGo's HTML endpoint (no API key); page reading fetches a URL
and extracts the main text. Both are bounded and degrade gracefully (a clear
"unavailable" result) when the network is blocked.
"""
from __future__ import annotations

import html as _html
import re
from urllib.parse import unquote

from config import config
from jarvis import http
from jarvis.cache import cache

DDG_URL = "https://html.duckduckgo.com/html/"
_TAGS = re.compile(r"<[^>]+>")
_RESULT_A = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_SNIPPET = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.S | re.I)
_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_PARA = re.compile(r"<p[^>]*>(.*?)</p>", re.S | re.I)


def _clean(s: str) -> str:
    return _html.unescape(_TAGS.sub("", s or "")).strip()


def _real_url(href: str) -> str:
    m = re.search(r"uddg=([^&]+)", href)
    return unquote(m.group(1)) if m else href


def _do_search(query: str, n: int):
    resp = http.post(DDG_URL, data={"q": query, "kl": "us-en"},
                     timeout=config.HTTP_TIMEOUT,
                     headers={"User-Agent": "Mozilla/5.0 (JARVIS)"})
    resp.raise_for_status()
    body = resp.text
    links = _RESULT_A.findall(body)
    snips = _SNIPPET.findall(body)
    out = []
    for i, (href, title) in enumerate(links[:n]):
        out.append({"title": _clean(title), "url": _real_url(href),
                    "snippet": _clean(snips[i]) if i < len(snips) else ""})
    return out


def search(query: str, n: int = 6) -> dict:
    query = (query or "").strip()
    if not query:
        return {"query": query, "results": [], "error": "empty query"}
    n = max(1, min(10, int(n or 6)))
    try:
        results = cache.get_or_set(f"ws:{query[:64]}:{n}", 300, lambda: _do_search(query, n))
        return {"query": query, "count": len(results), "results": results}
    except Exception as exc:
        return {"query": query, "results": [],
                "error": f"web search unavailable: {exc}"[:140]}


def fetch_text(url: str, limit: int = 2500) -> dict:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"error": "invalid url (must be http/https)"}
    try:
        r = http.get(url, timeout=config.HTTP_TIMEOUT,
                     headers={"User-Agent": "Mozilla/5.0 (JARVIS)"})
        r.raise_for_status()
        if "html" not in r.headers.get("content-type", "").lower():
            return {"url": url, "text": r.text[:limit]}
        raw = _SCRIPT.sub(" ", r.text)
        paras = _PARA.findall(raw)
        body = " ".join(paras) if paras else raw
        text = re.sub(r"\s+", " ", _html.unescape(_TAGS.sub(" ", body))).strip()
        return {"url": url, "text": text[:limit]}
    except Exception as exc:
        return {"error": f"fetch failed: {exc}"[:140]}
