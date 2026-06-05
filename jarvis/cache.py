"""A tiny thread-safe TTL cache.

External feeds (news, seismic data, orbital tracking) are polled by every
connected terminal.  Rather than hammer upstream sources, results are memoised
for a short window.  Stale-on-error: if a refresh fails, the last good value is
returned so the terminal degrades gracefully instead of going dark.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Tuple


class TTLCache:
    def __init__(self) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, ttl: int, producer: Callable[[], Any]) -> Any:
        """Return a cached value, refreshing it via ``producer`` when stale.

        If ``producer`` raises and a previous value exists, that previous value
        is served (stale-on-error).  If there is nothing cached, the exception
        propagates so the caller can surface the failure.
        """
        now = time.time()
        with self._lock:
            hit = self._store.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]

        try:
            value = producer()
        except Exception:
            with self._lock:
                hit = self._store.get(key)
            if hit is not None:
                return hit[1]
            raise

        with self._lock:
            self._store[key] = (now, value)
        return value

    def age(self, key: str) -> float | None:
        """Seconds since ``key`` was last refreshed, or None if absent."""
        with self._lock:
            hit = self._store.get(key)
        return None if hit is None else time.time() - hit[0]


cache = TTLCache()
