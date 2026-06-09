"""Persistent associative memory — the JARVIS 'brain(s)'.

Each brain is a **directory of Markdown files**, one per neuron: a JSON
frontmatter block holds the metadata, and the markdown body holds the rich
content ("more info"). Neurons that share enough keywords are linked by
*synapses* (computed on read).

Two brains:
  * ``main`` — intelligence / news / conversation memory (the default; the
    module-level functions delegate here for backward compatibility).
  * ``code`` — coding knowledge the DEV agent accumulates across sessions.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import threading
import time
import uuid
from typing import Dict, List

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_NEURONS = 1500
EDGE_MIN_SHARED = 1
EDGE_MIN_WEIGHT = 0.1

_STOP = set(
    "the a an and or of to in on for with at by from is are was were be been being this that "
    "it its as we you they he she them his her their our your i me my mine but not have has had "
    "will would can could should may might do does did so if then than into over under about".split()
)


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if w not in _STOP}


class Brain:
    """A named memory store persisted as a directory of Markdown neuron files."""

    def __init__(self, name: str, directory: str):
        self.name = name
        self.dir = directory
        self._lock = threading.Lock()
        self._neurons: Dict[str, dict] = {}
        self._load()

    # ── persistence (Markdown files) ──────────────────────────────────────
    def _file(self, nid: str) -> str:
        return os.path.join(self.dir, f"{nid}.md")

    def _serialise(self, n: dict) -> str:
        front = {k: n[k] for k in ("id", "kind", "weight", "created", "activations")}
        front["tags"] = n.get("tags", [])
        front["meta"] = n.get("meta", {})
        front["text"] = n["text"]
        body = n.get("body") or ""
        return f"---\n{json.dumps(front, ensure_ascii=False)}\n---\n{body}\n"

    def _parse(self, path: str) -> dict | None:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            return None
        m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
        if not m:
            return None
        try:
            front = json.loads(m.group(1))
        except ValueError:
            return None
        body = m.group(2).strip()
        text = front.get("text") or (body.splitlines()[0] if body else "")
        tags = front.get("tags", [])
        return {
            "id": front.get("id") or os.path.splitext(os.path.basename(path))[0],
            "text": text, "body": body, "kind": front.get("kind", "note"),
            "tags": tags, "tokens": self._compute_tokens(text, body, tags),
            "created": front.get("created", 0), "activations": front.get("activations", 1),
            "weight": front.get("weight", 5), "meta": front.get("meta", {}),
        }

    @staticmethod
    def _compute_tokens(text: str, body: str, tags: List[str]) -> List[str]:
        toks = _tokens(text + " " + (body or "")) | {t.lower() for t in (tags or [])}
        return sorted(toks)[:30]

    def _load(self) -> None:
        self._neurons = {}
        try:
            files = [f for f in os.listdir(self.dir) if f.endswith(".md")]
        except OSError:
            files = []
        for f in files:
            n = self._parse(os.path.join(self.dir, f))
            if n:
                self._neurons[n["id"]] = n

    def _write(self, n: dict) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self._file(n["id"]), "w", encoding="utf-8") as fh:
                fh.write(self._serialise(n))
        except OSError:
            pass

    def _delete_file(self, nid: str) -> None:
        try:
            os.remove(self._file(nid))
        except OSError:
            pass

    def _prune_locked(self) -> None:
        if len(self._neurons) <= MAX_NEURONS:
            return
        ranked = sorted(self._neurons.values(),
                        key=lambda n: (n.get("weight", 5), n.get("activations", 1), n.get("created", 0)))
        for n in ranked[: len(self._neurons) - MAX_NEURONS]:
            self._neurons.pop(n["id"], None)
            self._delete_file(n["id"])

    # ── operations ────────────────────────────────────────────────────────
    def add(self, text: str, kind: str = "note", tags: List[str] | None = None,
            meta: dict | None = None, weight: int | None = None, body: str | None = None) -> str | None:
        text = (text or "").strip()[:500]
        if not text:
            return None
        try:
            w = max(1, min(10, int(weight))) if weight is not None else 5
        except (TypeError, ValueError):
            w = 5
        tags = [str(t).lower() for t in (tags or [])][:12]
        body = (body or "").strip()[:4000]
        clean_meta = {k: str(v)[:300] for k, v in (meta or {}).items() if v}
        with self._lock:
            for n in self._neurons.values():
                if n["text"].lower() == text.lower():
                    n["activations"] = n.get("activations", 1) + 1
                    n["weight"] = max(n.get("weight", 5), w)
                    if body and not n.get("body"):
                        n["body"] = body
                        n["tokens"] = self._compute_tokens(text, body, n.get("tags", []))
                    if clean_meta and not n.get("meta"):
                        n["meta"] = clean_meta
                    self._write(n)
                    return n["id"]
            nid = uuid.uuid4().hex[:8]
            self._neurons[nid] = {
                "id": nid, "text": text, "body": body, "kind": kind, "tags": tags,
                "tokens": self._compute_tokens(text, body, tags),
                "created": time.time(), "activations": 1, "weight": w, "meta": clean_meta,
            }
            self._write(self._neurons[nid])
            self._prune_locked()
            return nid

    def _edges_locked(self) -> List[dict]:
        items = list(self._neurons.values())
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
                w = len(shared) / min(len(ti), len(tj))
                if w >= EDGE_MIN_WEIGHT:
                    edges.append({"a": items[i]["id"], "b": items[j]["id"],
                                  "w": round(w, 2), "shared": sorted(shared)[:4]})
        return edges

    def graph(self) -> Dict:
        with self._lock:
            edges = self._edges_locked()
            neurons = [{"id": n["id"], "text": n["text"], "body": (n.get("body") or "")[:600],
                        "kind": n["kind"], "activations": n.get("activations", 1),
                        "created": n.get("created", 0), "weight": n.get("weight", 5),
                        "meta": n.get("meta", {})}
                       for n in self._neurons.values()]
        deg: Dict[str, int] = {}
        for e in edges:
            deg[e["a"]] = deg.get(e["a"], 0) + 1
            deg[e["b"]] = deg.get(e["b"], 0) + 1
        for n in neurons:
            n["degree"] = deg.get(n["id"], 0)
        neurons.sort(key=lambda n: n["created"])
        return {"brain": self.name, "neurons": neurons, "edges": edges,
                "count": len(neurons), "synapses": len(edges)}

    def recall(self, query: str, k: int = 5) -> List[dict]:
        q = _tokens(query)
        if not q:
            return []
        scored = []
        with self._lock:
            for n in self._neurons.values():
                overlap = len(q & set(n["tokens"]))
                if overlap:
                    scored.append((overlap, n))
            scored.sort(key=lambda x: (-x[0], -x[1].get("activations", 1)))
            top = [n for _, n in scored[:k]]
            for n in top:
                n["activations"] = n.get("activations", 1) + 1
                self._write(n)
            return [{"id": n["id"], "text": n["text"], "kind": n["kind"],
                     "body": (n.get("body") or "")[:600]} for n in top]

    def forget(self, nid: str) -> bool:
        with self._lock:
            existed = self._neurons.pop(nid, None) is not None
        if existed:
            self._delete_file(nid)
        return existed

    def wipe(self) -> None:
        with self._lock:
            ids = list(self._neurons)
            self._neurons = {}
        for nid in ids:
            self._delete_file(nid)

    def stats(self) -> Dict:
        with self._lock:
            kinds: Dict[str, int] = {}
            for n in self._neurons.values():
                kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
            return {"neurons": len(self._neurons), "kinds": kinds, "brain": self.name}


def _dir(env: str, default: str) -> str:
    return os.environ.get(env) or os.path.join(_BASE, default)


main = Brain("main", _dir("JARVIS_BRAIN_DIR", ".jarvis_brain"))
code = Brain("code", _dir("JARVIS_CODEBRAIN_DIR", ".jarvis_codebrain"))
_BRAINS = {"main": main, "code": code}


def get(name: str = "main") -> Brain:
    return _BRAINS.get(name, main)


# Migrate the legacy single-file brain (.jarvis_brain.json) into the main brain.
def _migrate_legacy() -> None:
    legacy = os.environ.get("JARVIS_BRAIN_PATH") or os.path.join(_BASE, ".jarvis_brain.json")
    if main._neurons or not os.path.exists(legacy):
        return
    try:
        with open(legacy, "r", encoding="utf-8") as fh:
            data = json.load(fh).get("neurons", {})
        for n in data.values():
            main.add(n.get("text", ""), kind=n.get("kind", "note"),
                     tags=n.get("tokens", []), meta=n.get("meta", {}), weight=n.get("weight", 5))
    except (OSError, ValueError, AttributeError):
        pass


_migrate_legacy()


# ── module-level API (delegates to the main brain) ──────────────────────────
def add(text, kind="note", tags=None, meta=None, weight=None, body=None):
    return main.add(text, kind=kind, tags=tags, meta=meta, weight=weight, body=body)


def recall(query, k=5):
    return main.recall(query, k=k)


def graph():
    return main.graph()


def stats():
    return main.stats()


def forget(nid):
    return main.forget(nid)


def wipe():
    return main.wipe()
