"""Central configuration for J.A.R.V.I.S.

All tunables are read from the environment (optionally via a local `.env`
file) so the same code runs locally, in CI, or in a container without edits.
"""
from __future__ import annotations

import os

try:  # python-dotenv is optional at runtime; only needed for local .env files
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv missing is non-fatal
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    # ── DeepSeek (OpenAI-compatible chat completions) ──────────────────────
    DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL: str = os.environ.get(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    ).rstrip("/")
    DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    # ── Server ─────────────────────────────────────────────────────────────
    HOST: str = os.environ.get("JARVIS_HOST", "0.0.0.0")
    PORT: int = _int("JARVIS_PORT", 8765)

    # ── Feeds ──────────────────────────────────────────────────────────────
    CACHE_TTL: int = _int("JARVIS_CACHE_TTL", 180)
    HTTP_TIMEOUT: int = _int("JARVIS_HTTP_TIMEOUT", 12)

    @classmethod
    def ai_online(cls) -> bool:
        """True when a DeepSeek key is configured."""
        return bool(cls.DEEPSEEK_API_KEY)


config = Config()
