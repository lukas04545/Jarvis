"""J.A.R.V.I.S. DEV agent — a coding harness that can develop Jarvis itself.

DeepSeek drives a tool-using loop with **repo-confined** file tools plus the
test runner, so it can read the codebase, write changes, run the suite, and
iterate toward a working result.

SAFETY
======
* Disabled unless ``JARVIS_ENABLE_DEVAGENT=1`` — it modifies files, so it is
  off by default and intended as a LOCAL developer tool on your own machine.
* Every file path is confined to the project root; ``.git``, virtualenvs,
  caches and secret files (.env / .jarvis_secrets.json / .jarvis_brain.json)
  are off-limits. No arbitrary shell — only ``pytest`` and read-only ``git``.
"""
from __future__ import annotations

import glob as _glob
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Dict, List

from jarvis import deepseek, runtime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BLOCKED_DIRS = {".git", ".venv", "venv", "env", "__pycache__",
                 "node_modules", ".pytest_cache"}
_BLOCKED_FILES = {".env", ".jarvis_secrets.json", ".jarvis_brain.json",
                  ".jarvis_brain.json.tmp"}
MAX_WRITE = 60000
MAX_READ = 20000


def enabled() -> bool:
    return os.environ.get("JARVIS_ENABLE_DEVAGENT") == "1"


def _safe(rel: str) -> str:
    """Resolve a repo-relative path, rejecting traversal / blocked targets."""
    rel = (rel or "").strip().lstrip("/")
    p = os.path.normpath(os.path.join(REPO_ROOT, rel))
    if p != REPO_ROOT and not p.startswith(REPO_ROOT + os.sep):
        raise ValueError("path escapes project root")
    parts = set(os.path.relpath(p, REPO_ROOT).split(os.sep))
    if parts & _BLOCKED_DIRS:
        raise ValueError("blocked directory")
    if os.path.basename(p) in _BLOCKED_FILES:
        raise ValueError("blocked file")
    return p


# ── tool implementations (read-only helpers) ───────────────────────────────
def _list_files(pattern: str = "**/*.py") -> List[str]:
    out = []
    for f in _glob.glob(os.path.join(REPO_ROOT, pattern), recursive=True):
        if not os.path.isfile(f):
            continue
        try:
            rel = os.path.relpath(f, REPO_ROOT)
            _safe(rel)
        except ValueError:
            continue
        out.append(rel)
    return sorted(out)[:250]


def _read_file(path: str = "") -> str:
    with open(_safe(path), "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()[:MAX_READ]


def _run_tests() -> Dict:
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header"],
                           cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
        return {"passed": r.returncode == 0, "output": (r.stdout + r.stderr)[-1800:]}
    except Exception as exc:
        return {"passed": False, "output": str(exc)[:400]}


def _git_diff() -> str:
    try:
        r = subprocess.run(["git", "diff", "--stat"], cwd=REPO_ROOT,
                           capture_output=True, text=True, timeout=30)
        return r.stdout[-1500:]
    except Exception:
        return ""


SCHEMA: List[Dict] = [
    {"type": "function", "function": {
        "name": "list_files", "description": "List repo files matching a glob pattern.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "e.g. '**/*.py' or 'jarvis/*.py'"}}}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a file in the Jarvis project.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file in the project (confined to the repo).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_tests", "description": "Run the project's pytest suite and return the result.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "git_diff", "description": "Show a summary (git diff --stat) of pending changes.",
        "parameters": {"type": "object", "properties": {}}}},
]

_SYSTEM = (
    "You are the J.A.R.V.I.S. DEV agent — an autonomous software engineer working "
    "ON the Jarvis codebase itself. Implement the Operator's task with minimal, "
    "correct, idiomatic changes that match the surrounding code. Workflow: explore "
    "with list_files/read_file FIRST, then write_file your changes, then run_tests "
    "and fix any failures, iterating until green. Keep everything inside the "
    "project; never touch secrets or .git. When done, reply with a concise summary "
    "of what you changed and why (no tool call)."
)


def status() -> Dict:
    return {"enabled": enabled(), "ai_online": runtime.ai_online(), "root": os.path.basename(REPO_ROOT)}


def develop(task: str, max_rounds: int = 14) -> Dict:
    """Run the coding agent against a task. Returns a transcript of its work."""
    if not enabled():
        return {"error": "DEV agent is disabled. Set JARVIS_ENABLE_DEVAGENT=1 to enable "
                         "(local developer use only — it modifies project files)."}
    if not runtime.ai_online():
        return {"error": "AI core offline — paste a DeepSeek key in SETTINGS."}
    task = (task or "").strip()
    if not task:
        return {"error": "empty task"}

    actions: List[Dict] = []
    changed: set = set()

    def rec(name, detail=""):
        actions.append({"tool": name, "detail": str(detail)[:200]})

    def list_files(pattern: str = "**/*.py"):
        rec("list_files", pattern)
        return _list_files(pattern)

    def read_file(path: str = ""):
        rec("read_file", path)
        return _read_file(path)

    def write_file(path: str = "", content: str = ""):
        p = _safe(path)
        if len(content) > MAX_WRITE:
            return {"error": "content too large"}
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        rel = os.path.relpath(p, REPO_ROOT)
        changed.add(rel)
        rec("write_file", rel)
        return {"written": rel, "bytes": len(content)}

    def run_tests():
        rec("run_tests")
        return _run_tests()

    def git_diff():
        rec("git_diff")
        return _git_diff()

    impls = {"list_files": list_files, "read_file": read_file, "write_file": write_file,
             "run_tests": run_tests, "git_diff": git_diff}

    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": "TASK: " + task}]
    try:
        result = deepseek.complete_with_tools(messages, SCHEMA, impls,
                                              temperature=0.2, max_tokens=1600, max_rounds=max_rounds)
    except deepseek.DeepSeekError as exc:
        return {"error": str(exc), "actions": actions, "files_changed": sorted(changed)}

    return {
        "task": task,
        "summary": result["text"],
        "actions": actions,
        "files_changed": sorted(changed),
        "diff": _git_diff(),
        "tests": _run_tests() if changed else None,
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }
