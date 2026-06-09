"""Runtime-mutable settings — API keys pasted into the terminal UI.

Keys can come from two places, in priority order:
  1. Pasted in the Settings panel → stored in .jarvis_secrets.json (chmod 600)
  2. Environment / .env → static configuration.

Keys are never sent back to the browser; the API only exposes whether each
provider is configured and where the value came from.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

from config import config, LLM_PROVIDERS, LLM_PROVIDER_ORDER

_SECRETS_PATH = os.environ.get(
    "JARVIS_SECRETS_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".jarvis_secrets.json",
    ),
)

_lock = threading.Lock()
_overrides: dict = {}


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


def get_secret(key_name: str) -> str:
    """Retrieve any stored secret by its storage key name."""
    with _lock:
        return _overrides.get(key_name, "")


def get_provider_key(provider_id: str) -> str:
    """Effective API key for a provider (UI override > env var)."""
    p = LLM_PROVIDERS.get(provider_id, {})
    runtime_key = p.get("runtime_key", "")
    env_key = p.get("env_key", "")
    return get_secret(runtime_key) or os.environ.get(env_key, "")


def deepseek_key() -> str:
    return get_provider_key("deepseek")


def hibp_key() -> str:
    return get_secret("hibp_api_key") or os.environ.get("HIBP_API_KEY", "")


def ai_online() -> bool:
    """True when any LLM provider key is configured."""
    for pid in LLM_PROVIDER_ORDER:
        if get_provider_key(pid):
            return True
    return False


def active_provider() -> Optional[str]:
    """ID of the first configured provider in priority order, or None."""
    for pid in LLM_PROVIDER_ORDER:
        if get_provider_key(pid):
            return pid
    return None


def set_keys(**kwargs: Optional[str]) -> None:
    """Update any stored keys. Pass empty string to clear; None to leave unchanged."""
    with _lock:
        for key_name, value in kwargs.items():
            if value is None:
                continue
            value = str(value).strip()
            if value:
                _overrides[key_name] = value
            else:
                _overrides.pop(key_name, None)
        _persist()


def status() -> dict:
    """Non-sensitive view of which providers are configured."""
    result: dict = {}
    for pid, pinfo in LLM_PROVIDERS.items():
        key_name = pinfo["runtime_key"]
        env_var = pinfo["env_key"]
        from_ui = bool(get_secret(key_name))
        env_present = bool(os.environ.get(env_var))
        configured = bool(from_ui or env_present)
        result[pid] = {
            "name": pinfo["name"],
            "configured": configured,
            "source": "ui" if from_ui else ("env" if env_present else "none"),
            "limits": pinfo["limits"],
            "signup": pinfo["signup"],
        }
    hibp_ui = bool(get_secret("hibp_api_key"))
    hibp_env = bool(os.environ.get("HIBP_API_KEY"))
    result["hibp"] = {
        "name": "Have I Been Pwned",
        "configured": bool(hibp_ui or hibp_env),
        "source": "ui" if hibp_ui else ("env" if hibp_env else "none"),
    }
    return result
