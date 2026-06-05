"""Device telemetry store.

Holds the latest *non-sensitive* device telemetry that the browser client
voluntarily reports (memory/hardware/screen/network/power/locale + input
activity counters and capture flags), so the SENTINEL agent and the DEVICE
panel can reason over the operator's local device posture.

Privacy / scope
---------------
* Only the operator's OWN browser posts here, and only the whitelisted,
  non-sensitive fields below are accepted — anything else is dropped.
* Screen-share frames and microphone audio are NEVER sent to the server; they
  stay local in the browser. Only boolean "sharing/listening" flags are stored.
* The store is in-memory and last-value-only; nothing is persisted to disk.
"""
from __future__ import annotations

import threading
import time
from typing import Dict

_lock = threading.Lock()
_latest: Dict = {}

# Whitelist: section -> allowed keys. Everything else is discarded.
_ALLOWED: Dict[str, set] = {
    "memory": {"deviceMemoryGB", "jsHeapMB", "storageQuotaMB", "storageUsageMB"},
    "hardware": {"cores", "platform", "ua", "languages"},
    "screen": {"width", "height", "availWidth", "availHeight", "colorDepth",
               "pixelRatio", "orientation"},
    "network": {"effectiveType", "downlinkMbps", "rttMs", "online"},
    "power": {"batteryLevel", "charging"},
    "input": {"keysPerMin", "pointerPerMin"},
    "locale": {"timezone"},
    "capture": {"screenSharing", "micListening"},
}


def _coerce(value):
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [str(x)[:40] for x in value[:8]]
    return str(value)[:160]


def set_device(data: Dict) -> Dict:
    """Sanitise + store an incoming telemetry blob. Returns the stored value."""
    clean: Dict = {}
    if isinstance(data, dict):
        for section, keys in _ALLOWED.items():
            src = data.get(section)
            if isinstance(src, dict):
                sub = {k: _coerce(v) for k, v in src.items() if k in keys}
                if sub:
                    clean[section] = sub
    clean["updated"] = time.time()
    global _latest
    with _lock:
        _latest = clean
    return clean


def get_device() -> Dict:
    with _lock:
        return dict(_latest)


def reset() -> None:
    """Test helper — clear stored telemetry."""
    global _latest
    with _lock:
        _latest = {}
