"""DeepSeek API client.

DeepSeek exposes an OpenAI-compatible ``/chat/completions`` endpoint, so this
is a thin wrapper around it with two entry points:

* :func:`complete`  — blocking, returns the full assistant message.
* :func:`stream`    — generator yielding text deltas for live, token-by-token
  rendering in the terminal console.

When no API key is configured the client operates in OFFLINE mode and returns a
clearly-labelled canned response so the rest of the system stays demonstrable
without credentials.
"""
from __future__ import annotations

import json
from typing import Dict, Iterator, List

import requests

from config import config

# JARVIS persona — terse, analytical, situational-awareness oriented.
SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI core "
    "of a global intelligence terminal. You speak with calm, precise, British "
    "concision — like a senior intelligence analyst briefing a principal. You "
    "favour signal over noise: lead with the assessment, then the evidence. "
    "When given news or surveillance data, synthesise it into actionable "
    "situational awareness. Use terminal-friendly plain text; no markdown "
    "headers. Be candid about uncertainty. Address the operator as 'Operator'."
)


class DeepSeekError(RuntimeError):
    pass


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }


def _offline_reply(messages: List[Dict[str, str]]) -> str:
    last = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    return (
        "[OFFLINE MODE] DeepSeek credentials are not configured, Operator. "
        "Set DEEPSEEK_API_KEY to bring the AI core online. "
        f'Your last transmission was logged: "{last[:160]}".'
    )


def complete(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
) -> str:
    """Return the full assistant reply for ``messages``."""
    if not config.ai_online():
        return _offline_reply(messages)

    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        resp = requests.post(
            f"{config.DEEPSEEK_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except requests.HTTPError as exc:  # pragma: no cover - network dependent
        detail = exc.response.text[:200] if exc.response is not None else str(exc)
        raise DeepSeekError(f"DeepSeek HTTP {exc.response.status_code}: {detail}")
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise DeepSeekError(f"DeepSeek request failed: {exc}") from exc


def stream(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
) -> Iterator[str]:
    """Yield assistant text deltas as they arrive (SSE streaming)."""
    if not config.ai_online():
        # Emit the offline notice in word-sized chunks so the UI still animates.
        for word in _offline_reply(messages).split(" "):
            yield word + " "
        return

    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    try:
        with requests.post(
            f"{config.DEEPSEEK_BASE_URL}/chat/completions",
            headers=_headers(),
            json=payload,
            timeout=90,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                chunk = raw[len("data:"):].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0]["delta"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                piece = delta.get("content")
                if piece:
                    yield piece
    except requests.RequestException as exc:
        raise DeepSeekError(f"DeepSeek stream failed: {exc}") from exc


def build_messages(user_prompt: str, context: str | None = None) -> List[Dict[str, str]]:
    """Assemble a message list with the JARVIS persona and optional context."""
    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append(
            {
                "role": "system",
                "content": "Live terminal context follows.\n" + context,
            }
        )
    messages.append({"role": "user", "content": user_prompt})
    return messages
