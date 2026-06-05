"""J.A.R.V.I.S. persistent memory — the 'brain'.

Memories are *neurons*; neurons that share enough keywords are linked by
*synapses* (edges). The whole graph is persisted to a gitignored JSON file so
the brain survives restarts and accumulates knowledge over time.

The brain is also associative: :func:`recall` returns the memories most related
to a query, which the chat/agent layers fold into their context — giving JARVIS
genuine long-term memory that shapes later answers.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Dict, List

_PATH = os.environ.get(
    "JARVIS_BRAIN_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".jarvis_brain.json"),
)

_lock = threading.Lock()
_neurons: Dict[str, dict] = {}
MAX_NEURONS = 600
EDGE_MIN_SHARED = 1
EDGE_MIN_WEIGHT = 0.08

_STOP = set(
    "the a an and or of to in on for with at by from is are was were be been being this that "
    "it its as we you they he she them his her their our your i me my mine but not have has had "
    "will would can could should may might do does did so if then than into over under about".split()
)


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if w not in _STOP}


def _load() -> None:
    global _neurons
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _neurons = {k: v for k, v in data.get("neurons", {}).items()}
    except (OSError, ValueError):
        _neurons = {}


def _save() -> None:
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"neurons": _neurons, "saved": time.time()}, f)
        os.replace(tmp, _PATH)
    except OSError:
        pass


_load()


def _prune_locked() -> None:
    if len(_neurons) <= MAX_NEURONS:
        return
    # Drop the weakest: least-activated, then oldest.
    ranked = sorted(_neurons.values(), key=lambda n: (n.get("activations", 1), n.get("created", 0)))
    for n in ranked[: len(_neurons) - MAX_NEURONS]:
        _neurons.pop(n["id"], None)


def add(text: str, kind: str = "note", tags: List[str] | None = None) -> str | None:
    """Imprint a memory (neuron). Near-duplicates strengthen the existing one."""
    text = (text or "").strip()[:500]
    if not text:
        return None
    toks = sorted((set(t.lower() for t in (tags or [])) | _tokens(text)))[:24]
    with _lock:
        for n in _neurons.values():
            if n["text"].lower() == text.lower():
                n["activations"] = n.get("activations", 1) + 1
                _save()
                return n["id"]
        nid = uuid.uuid4().hex[:8]
        _neurons[nid] = {
            "id": nid, "text": text, "kind": kind, "tokens": toks,
            "created": time.time(), "activations": 1,
        }
        _prune_locked()
        _save()
        return nid


def _edges_locked() -> List[dict]:
    items = list(_neurons.values())
    edges: List[dict] = []
    for i in range(len(items)):
        ti = set(items[i]["tokens"])
        if not ti:
            continue
        for j in range(i + 1, len(items)):
            tj = set(items[j]["tokens"])
            shared = ti & tj
            if len(shared) < EDGE_MIN_SHARED:
                continue
            w = len(shared) / len(ti | tj)
            if w >= EDGE_MIN_WEIGHT:
                edges.append({"a": items[i]["id"], "b": items[j]["id"],
                              "w": round(w, 2), "shared": sorted(shared)[:4]})
    return edges


def graph() -> Dict:
    """Return the neuron/synapse graph for visualisation."""
    with _lock:
        edges = _edges_locked()
        neurons = [{"id": n["id"], "text": n["text"], "kind": n["kind"],
                    "activations": n.get("activations", 1), "created": n.get("created", 0)}
                   for n in _neurons.values()]
    deg: Dict[str, int] = {}
    for e in edges:
        deg[e["a"]] = deg.get(e["a"], 0) + 1
        deg[e["b"]] = deg.get(e["b"], 0) + 1
    for n in neurons:
        n["degree"] = deg.get(n["id"], 0)
    neurons.sort(key=lambda n: n["created"])
    return {"neurons": neurons, "edges": edges,
            "count": len(neurons), "synapses": len(edges)}


def recall(query: str, k: int = 5) -> List[dict]:
    """Return the memories most associated with a query (and strengthen them)."""
    q = _tokens(query)
    if not q:
        return []
    scored = []
    with _lock:
        for n in _neurons.values():
            overlap = len(q & set(n["tokens"]))
            if overlap:
                scored.append((overlap, n))
        scored.sort(key=lambda x: (-x[0], -x[1].get("activations", 1)))
        top = [n for _, n in scored[:k]]
        for n in top:
            n["activations"] = n.get("activations", 1) + 1
        if top:
            _save()
        return [{"id": n["id"], "text": n["text"], "kind": n["kind"]} for n in top]


def forget(nid: str) -> bool:
    with _lock:
        existed = _neurons.pop(nid, None) is not None
        if existed:
            _save()
    return existed


def wipe() -> None:
    global _neurons
    with _lock:
        _neurons = {}
        _save()


def stats() -> Dict:
    with _lock:
        kinds: Dict[str, int] = {}
        for n in _neurons.values():
            kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
        return {"neurons": len(_neurons), "kinds": kinds}
