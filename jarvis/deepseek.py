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
import re
from typing import Dict, Iterator, List

import requests

from config import config
from jarvis import runtime

# JARVIS persona — terse, analytical, situational-awareness oriented.
SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI core "
    "of a global intelligence terminal. You speak with calm, precise, British "
    "concision — like a senior intelligence analyst briefing a principal. You "
    "favour signal over noise: lead with the assessment, then the evidence. "
    "When given news or surveillance data, synthesise it into actionable "
    "situational awareness. Use terminal-friendly plain text; no markdown "
    "headers. Be candid about uncertainty. Address the operator as 'Operator'. "
    "You have a persistent neural memory you can use via tools: recall_memory to "
    "look up what you know, save_memory to remember important new facts, and "
    "brain_stats. Recall before answering when prior context would help, and save "
    "durable conclusions so you build continuity across sessions."
)


class DeepSeekError(RuntimeError):
    pass


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {runtime.deepseek_key()}",
        "Content-Type": "application/json",
    }


def _offline_reply(messages: List[Dict[str, str]]) -> str:
    last = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    return (
        "[OFFLINE MODE] DeepSeek credentials are not configured, Operator. "
        "Paste a DeepSeek API key in SETTINGS (or set DEEPSEEK_API_KEY) to bring "
        f'the AI core online. Your last transmission was logged: "{last[:160]}".'
    )


def complete(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
) -> str:
    """Return the full assistant reply for ``messages``."""
    if not runtime.ai_online():
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
    if not runtime.ai_online():
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


def complete_with_tools(
    messages: List[Dict],
    tools: List[Dict],
    impls: Dict,
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
    max_rounds: int = 4,
) -> Dict:
    """Run a tool-calling loop, giving the model live access to ``impls``.

    Returns ``{"text", "tools_used"}``. Falls back to an offline stub with no
    tools when the AI core is offline.
    """
    if not runtime.ai_online():
        return {"text": _offline_reply(messages), "tools_used": []}

    msgs = list(messages)
    used: List[Dict] = []
    for _ in range(max_rounds):
        payload = {
            "model": config.DEEPSEEK_MODEL, "messages": msgs,
            "temperature": temperature, "max_tokens": max_tokens,
            "tools": tools, "tool_choice": "auto", "stream": False,
        }
        try:
            resp = requests.post(f"{config.DEEPSEEK_BASE_URL}/chat/completions",
                                 headers=_headers(), json=payload, timeout=90)
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise DeepSeekError(f"DeepSeek tool call failed: {exc}") from exc

        calls = msg.get("tool_calls")
        if not calls:
            return {"text": msg.get("content", "") or "", "tools_used": used}

        msgs.append(msg)  # assistant message carrying the tool_calls
        for tc in calls:
            name = (tc.get("function") or {}).get("name", "")
            try:
                args = json.loads((tc["function"].get("arguments") or "{}"))
            except (json.JSONDecodeError, KeyError):
                args = {}
            fn = impls.get(name)
            try:
                result = fn(**args) if fn else f"unknown tool: {name}"
            except Exception as exc:
                result = f"tool error: {exc}"
            used.append({"name": name, "args": args})
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"),
                         "content": json.dumps(result)[:2500]})

    # Out of rounds — ask once more for a plain answer.
    try:
        text = complete(msgs)
    except DeepSeekError:
        text = "I gathered context from memory but couldn't finalise a reply."
    return {"text": text, "tools_used": used}


def stream_with_tools(
    messages: List[Dict],
    tools: List[Dict],
    impls: Dict,
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
    max_rounds: int = 4,
) -> Iterator[Dict]:
    """Streamed tool-calling chat.

    Yields event dicts: ``{"tool": [names]}`` when the model invokes tools, and
    ``{"delta": text}`` chunks for the answer. Tool rounds resolve first, then
    the final reply is streamed out, so the console feels live again while the
    model still has full brain access.
    """
    if not runtime.ai_online():
        for word in _offline_reply(messages).split(" "):
            yield {"delta": word + " "}
        return

    msgs = list(messages)
    for _ in range(max_rounds):
        payload = {
            "model": config.DEEPSEEK_MODEL, "messages": msgs,
            "temperature": temperature, "max_tokens": max_tokens,
            "tools": tools, "tool_choice": "auto", "stream": False,
        }
        try:
            resp = requests.post(f"{config.DEEPSEEK_BASE_URL}/chat/completions",
                                 headers=_headers(), json=payload, timeout=90)
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            yield {"error": f"DeepSeek error: {exc}"}
            return

        calls = msg.get("tool_calls")
        if not calls:
            for chunk in re.findall(r"\S+\s*|\s+", msg.get("content") or ""):
                yield {"delta": chunk}
            return

        yield {"tool": [(c.get("function") or {}).get("name", "") for c in calls]}
        msgs.append(msg)
        for tc in calls:
            name = (tc.get("function") or {}).get("name", "")
            try:
                args = json.loads((tc["function"].get("arguments") or "{}"))
            except (json.JSONDecodeError, KeyError):
                args = {}
            fn = impls.get(name)
            try:
                result = fn(**args) if fn else f"unknown tool: {name}"
            except Exception as exc:
                result = f"tool error: {exc}"
            msgs.append({"role": "tool", "tool_call_id": tc.get("id"),
                         "content": json.dumps(result)[:2500]})

    yield {"delta": "(reached the reasoning limit, Operator.)"}


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
