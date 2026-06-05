"""Runtime-mutable settings — API keys pasted into the terminal UI.

Keys can come from two places, in priority order:

  1. Pasted in the Settings panel  → stored server-side in a gitignored
     ``.jarvis_secrets.json`` (chmod 600) so they survive a restart.
  2. Environment / ``.env``        → the original static configuration.

Keys are *never* sent back to the browser; the API only exposes whether each
provider is configured and where the value came from.
"""
from __future__ import annotations

import json
import os
import threading

from config import config

_SECRETS_PATH = os.environ.get(
    "JARVIS_SECRETS_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".jarvis_secrets.json",
    ),
)

_lock = threading.Lock()
_overrides: dict[str, str] = {}


def _load() -> None:
    global _overrides
    try:
        with open(_SECRETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _overrides = {k: str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        _overrides = {}


def _persist() -> None:
    try:
        with open(_SECRETS_PATH, "w", encoding="utf-8") as f:
            json.dump(_overrides, f)
        os.chmod(_SECRETS_PATH, 0o600)
    except OSError:
        pass


_load()


def deepseek_key() -> str:
    with _lock:
        return _overrides.get("deepseek_api_key") or config.DEEPSEEK_API_KEY


def windy_key() -> str:
    with _lock:
        return _overrides.get("windy_api_key") or os.environ.get("WINDY_WEBCAMS_API_KEY", "")


def ai_online() -> bool:
    return bool(deepseek_key())


def set_keys(deepseek_api_key: str | None = None, windy_api_key: str | None = None) -> None:
    """Update keys. Pass an empty string to clear one; ``None`` leaves it as-is."""
    with _lock:
        for field, value in (
            ("deepseek_api_key", deepseek_api_key),
            ("windy_api_key", windy_api_key),
        ):
            if value is None:
                continue
            value = value.strip()
            if value:
                _overrides[field] = value
            else:
                _overrides.pop(field, None)
        _persist()


def status() -> dict:
    """Non-sensitive view of which providers are configured."""
    # Read configured-state first (each helper takes _lock), then snapshot which
    # keys came from the UI under a single lock. Never hold _lock across a call
    # that re-acquires it — _lock is non-reentrant.
    ds_configured = bool(deepseek_key())
    wd_configured = bool(windy_key())
    with _lock:
        ds_from_ui = bool(_overrides.get("deepseek_api_key"))
        wd_from_ui = bool(_overrides.get("windy_api_key"))

    def src(from_ui: bool, env_present: bool) -> str:
        return "ui" if from_ui else ("env" if env_present else "none")

    return {
        "deepseek": {
            "configured": ds_configured,
            "source": src(ds_from_ui, bool(config.DEEPSEEK_API_KEY)),
        },
        "windy": {
            "configured": wd_configured,
            "source": src(wd_from_ui, bool(os.environ.get("WINDY_WEBCAMS_API_KEY"))),
        },
    }
