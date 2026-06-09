"""Central configuration for J.A.R.V.I.S."""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# All supported free-tier LLM providers (OpenAI-compatible chat completions)
# Source: https://github.com/cheahjs/free-llm-api-resources
LLM_PROVIDERS: dict = {
    "google": {
        "name": "Google AI Studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash",
        "env_key": "GOOGLE_API_KEY",
        "runtime_key": "google_api_key",
        "supports_tools": True,
        "limits": "250K tokens/min · free",
        "signup": "aistudio.google.com",
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "runtime_key": "groq_api_key",
        "supports_tools": True,
        "limits": "14.4K req/day · free",
        "signup": "console.groq.com",
    },
    "cerebras": {
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "default_model": "llama3.1-70b",
        "env_key": "CEREBRAS_API_KEY",
        "runtime_key": "cerebras_api_key",
        "supports_tools": True,
        "limits": "1M tokens/day · free",
        "signup": "cloud.cerebras.ai",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "env_key": "OPENROUTER_API_KEY",
        "runtime_key": "openrouter_api_key",
        "supports_tools": True,
        "limits": "50 req/day · free",
        "signup": "openrouter.ai",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/lukas04545/Jarvis",
            "X-Title": "J.A.R.V.I.S.",
        },
    },
    "mistral": {
        "name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "runtime_key": "mistral_api_key",
        "supports_tools": True,
        "limits": "1B tokens/month · free",
        "signup": "console.mistral.ai",
    },
    "cohere": {
        "name": "Cohere",
        "base_url": "https://api.cohere.com/compatibility/v1",
        "default_model": "command-a-03-2025",
        "env_key": "COHERE_API_KEY",
        "runtime_key": "cohere_api_key",
        "supports_tools": True,
        "limits": "1K req/month · free",
        "signup": "cohere.com",
    },
    "huggingface": {
        "name": "HuggingFace",
        "base_url": "https://api-inference.huggingface.co/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "runtime_key": "huggingface_api_key",
        "supports_tools": False,
        "limits": "$0.10/month credits · free",
        "signup": "huggingface.co",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "runtime_key": "deepseek_api_key",
        "supports_tools": True,
        "limits": "paid / trial credits",
        "signup": "platform.deepseek.com",
    },
}


def _provider_order() -> list:
    raw = os.environ.get(
        "LLM_PROVIDER_ORDER",
        "google,groq,cerebras,openrouter,mistral,cohere,huggingface,deepseek",
    )
    return [p.strip() for p in raw.split(",") if p.strip() in LLM_PROVIDERS]


LLM_PROVIDER_ORDER: list = _provider_order()


class Config:
    # ── Legacy DeepSeek fields (kept for backward compat) ──────────────
    DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL: str = os.environ.get(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
    ).rstrip("/")
    DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    # ── Server ─────────────────────────────────────────────────────────
    HOST: str = os.environ.get("JARVIS_HOST", "0.0.0.0")
    PORT: int = _int("JARVIS_PORT", 8765)

    # ── Feeds ──────────────────────────────────────────────────────────
    CACHE_TTL: int = _int("JARVIS_CACHE_TTL", 180)
    HTTP_TIMEOUT: int = _int("JARVIS_HTTP_TIMEOUT", 12)

    @classmethod
    def ai_online(cls) -> bool:
        for p in LLM_PROVIDERS.values():
            if os.environ.get(p["env_key"]):
                return True
        return False


config = Config()
