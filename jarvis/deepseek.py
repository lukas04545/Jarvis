"""DeepSeek API client — compatibility shim over jarvis.llm.

All multi-provider routing now lives in jarvis/llm.py. This module exists
so that existing imports of ``from jarvis import deepseek`` (and
``deepseek.complete()``, ``deepseek.stream()``, etc.) continue to work
without any changes to callers.
"""
from __future__ import annotations

from jarvis.llm import (
    LLMError as DeepSeekError,
    SYSTEM_PROMPT,
    build_messages,
    complete,
    complete_with_tools,
    stream,
)

__all__ = [
    "DeepSeekError",
    "SYSTEM_PROMPT",
    "build_messages",
    "complete",
    "complete_with_tools",
    "stream",
]
