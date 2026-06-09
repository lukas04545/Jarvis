"""Shared, resilient HTTP session for outbound feed requests.

One pooled :class:`requests.Session` for all the live data modules: connection
reuse (faster), a consistent User-Agent, a default timeout, and automatic
retries with backoff on *transient* errors only (connection drops, 429, 5xx) —
never on 4xx like 403/404, so blocked hosts fail fast instead of retry-storming.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter

from config import config

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - urllib3 always present with requests
    Retry = None

USER_AGENT = "JARVIS-Terminal/1.0 (+intelligence-feed)"


def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    if Retry is not None:
        retry = Retry(
            total=2, connect=2, read=1, backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    return s


session = _build_session()


def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT)
    return session.get(url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", config.HTTP_TIMEOUT)
    return session.post(url, **kwargs)
