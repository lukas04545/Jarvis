"""Unified multi-provider LLM client for J.A.R.V.I.S.

Supports all free-tier providers from https://github.com/cheahjs/free-llm-api-resources.
Providers are tried in the configured priority order with automatic fallback on
rate limits (HTTP 429) or transient errors.

Public API mirrors the old deepseek.py interface so existing callers work unchanged:
    complete()            — blocking full reply
    stream()              — token-by-token SSE generator
    complete_with_tools() — agentic tool-calling loop
    build_messages()      — assemble the message list with the JARVIS persona
"""
from __future__ import annotations

import json
import os
from typing import Dict, Iterator, List, Optional

import requests

from config import LLM_PROVIDERS, LLM_PROVIDER_ORDER

SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the AI core "
    "of a global intelligence terminal. You speak with calm, precise, British "
    "concision — like a senior intelligence analyst briefing a principal. "
    "You favour signal over noise: lead with the assessment, then the evidence. "
    "When given news or surveillance data, synthesise it into actionable "
    "situational awareness. Use terminal-friendly plain text; no markdown "
    "headers. Be candid about uncertainty. Address the operator as 'Operator'. "
    "You have a persistent neural memory you can use via tools: recall_memory to "
    "look up what you know, save_memory to remember important new facts, and "
    "brain_stats. Recall before answering when prior context would help, and save "
    "durable conclusions so you build continuity across sessions."
)


class LLMError(RuntimeError):
    pass


def _get_key(provider_id: str) -> str:
    """API key: UI override > env var."""
    from jarvis import runtime
    return runtime.get_provider_key(provider_id)


def _get_model(provider_id: str) -> str:
    """Active model for a provider (env override or registry default)."""
    p = LLM_PROVIDERS[provider_id]
    env_override = p["env_key"].replace("_API_KEY", "_MODEL")
    return os.environ.get(env_override, "") or p["default_model"]


def get_active_provider() -> Optional[str]:
    """ID of the first configured provider in priority order, or None."""
    for pid in LLM_PROVIDER_ORDER:
        if _get_key(pid):
            return pid
    return None


def get_active_model() -> Optional[str]:
    """Model string for the active provider, or None when offline."""
    pid = get_active_provider()
    return _get_model(pid) if pid else None


def _ordered_providers(require_tools: bool = False) -> List[str]:
    """Configured provider IDs in priority order."""
    out = []
    for pid in LLM_PROVIDER_ORDER:
        if not _get_key(pid):
            continue
        if require_tools and not LLM_PROVIDERS[pid].get("supports_tools"):
            continue
        out.append(pid)
    return out


def _headers(provider_id: str) -> Dict[str, str]:
    p = LLM_PROVIDERS[provider_id]
    h: Dict[str, str] = {
        "Authorization": f"Bearer {_get_key(provider_id)}",
        "Content-Type": "application/json",
    }
    h.update(p.get("extra_headers", {}))
    return h


def _offline_reply(messages: List[Dict]) -> str:
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    return (
        "[OFFLINE MODE] No LLM provider is configured, Operator. "
        "Open SETTINGS (⚙) and paste a free API key — "
        "Google AI Studio, Groq, Cerebras, OpenRouter, Mistral, Cohere, HuggingFace, or DeepSeek. "
        f'Last transmission logged: "{last[:160]}".'
    )


def complete(
    messages: List[Dict],
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
    provider: Optional[str] = None,
) -> str:
    """Return the full assistant reply. Tries providers in priority order."""
    providers = [provider] if provider else _ordered_providers()
    if not providers:
        return _offline_reply(messages)

    last_exc: Optional[Exception] = None
    for pid in providers:
        p = LLM_PROVIDERS[pid]
        payload = {
            "model": _get_model(pid),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            resp = requests.post(
                f"{p['base_url']}/chat/completions",
                headers=_headers(pid),
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"].get("content", "") or ""
        except requests.HTTPError as exc:
            last_exc = exc
            code = exc.response.status_code if exc.response is not None else 0
            if code in (429, 401, 403, 503):
                continue
            detail = exc.response.text[:200] if exc.response is not None else str(exc)
            raise LLMError(f"{p['name']} HTTP {code}: {detail}")
        except (requests.RequestException, KeyError, ValueError) as exc:
            last_exc = exc
            continue

    if last_exc:
        raise LLMError(f"All providers failed. Last error: {last_exc}")
    return _offline_reply(messages)


def stream(
    messages: List[Dict],
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
    provider: Optional[str] = None,
) -> Iterator[str]:
    """Yield assistant text deltas. Falls back between providers on failure."""
    providers = [provider] if provider else _ordered_providers()
    if not providers:
        for word in _offline_reply(messages).split(" "):
            yield word + " "
        return

    for pid in providers:
        p = LLM_PROVIDERS[pid]
        payload = {
            "model": _get_model(pid),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        try:
            with requests.post(
                f"{p['base_url']}/chat/completions",
                headers=_headers(pid),
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
                        return
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    piece = delta.get("content")
                    if piece:
                        yield piece
            return
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if code in (429, 401, 403, 503):
                continue
            raise LLMError(f"{p['name']} stream failed: {exc}")
        except requests.RequestException:
            continue

    for word in _offline_reply(messages).split(" "):
        yield word + " "


def complete_with_tools(
    messages: List[Dict],
    tools: List[Dict],
    impls: Dict,
    *,
    temperature: float = 0.4,
    max_tokens: int = 900,
    max_rounds: int = 4,
    provider: Optional[str] = None,
) -> Dict:
    """Run an agentic tool-calling loop.

    Falls back to plain completion when no provider supports tools.
    Returns {"text": str, "tools_used": list}.
    """
    if not _ordered_providers():
        return {"text": _offline_reply(messages), "tools_used": []}

    tool_providers = [provider] if provider else _ordered_providers(require_tools=True)
    if not tool_providers:
        return {"text": complete(messages, temperature=temperature, max_tokens=max_tokens), "tools_used": []}

    pid = tool_providers[0]
    p = LLM_PROVIDERS[pid]
    msgs = list(messages)
    used: List[Dict] = []

    for _ in range(max_rounds):
        payload = {
            "model": _get_model(pid),
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "tool_choice": "auto",
            "stream": False,
        }
        try:
            resp = requests.post(
                f"{p['base_url']}/chat/completions",
                headers=_headers(pid),
                json=payload,
                timeout=90,
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise LLMError(f"{p['name']} tool call failed: {exc}") from exc

        calls = msg.get("tool_calls")
        if not calls:
            return {"text": msg.get("content", "") or "", "tools_used": used}

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
            used.append({"name": name, "args": args})
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id"),
                "content": json.dumps(result)[:2500],
            })

    try:
        text = complete(msgs, temperature=temperature, max_tokens=max_tokens, provider=pid)
    except LLMError:
        text = "I gathered context from memory but couldn't finalise a reply."
    return {"text": text, "tools_used": used}


def build_messages(user_prompt: str, context: Optional[str] = None) -> List[Dict]:
    """Assemble the message list with the JARVIS persona and optional context."""
    msgs: List[Dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        msgs.append({"role": "system", "content": "Live terminal context follows.\n" + context})
    msgs.append({"role": "user", "content": user_prompt})
    return msgs
