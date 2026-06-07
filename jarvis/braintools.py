"""Brain tools exposed to DeepSeek (function calling).

These give the AI core *full access* to the persistent memory: it can search and
recall what JARVIS knows, and persist new facts — deciding for itself when to do
so during a conversation.
"""
from __future__ import annotations

from typing import Dict, List

from jarvis import memory

# OpenAI-compatible tool schemas advertised to DeepSeek.
SCHEMA: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Search J.A.R.V.I.S. long-term memory (the neural brain) "
                           "for facts, prior assessments and news related to a query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up."},
                    "k": {"type": "integer", "description": "Max results (default 8)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Persist an important fact or conclusion to long-term "
                           "memory so it is remembered in future sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The fact to remember."},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "2-5 keyword tags."},
                    "importance": {"type": "integer",
                                   "description": "Significance 1-10 (10 = critical)."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brain_stats",
            "description": "Summarise what JARVIS currently remembers (neuron counts by kind).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _recall(query: str = "", k: int = 8) -> List[Dict]:
    return memory.recall(query, k=min(int(k or 8), 15))


def _save(text: str = "", tags: List[str] | None = None, importance: int = 5) -> Dict:
    nid = memory.add(text, kind="chat", tags=tags, weight=importance, meta={"source": "JARVIS (AI)"})
    return {"saved": bool(nid), "id": nid}


def _stats() -> Dict:
    return memory.stats()


IMPLS = {"recall_memory": _recall, "save_memory": _save, "brain_stats": _stats}
