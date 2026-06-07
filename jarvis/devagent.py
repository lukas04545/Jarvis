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
import threading
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

# Last applied change-set (relpath -> original text, or None if it was new), kept
# so a change can be rolled back even after it passed.
_CPLOCK = threading.Lock()
_LAST_CHECKPOINT: Dict[str, str | None] = {}


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


def _read_raw(p: str) -> str | None:
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _restore(checkpoint: Dict[str, str | None]) -> List[str]:
    """Restore files from a checkpoint: rewrite originals, delete new files."""
    restored = []
    for rel, original in checkpoint.items():
        p = os.path.join(REPO_ROOT, rel)
        try:
            if original is None:
                if os.path.exists(p):
                    os.remove(p)
            else:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(original)
            restored.append(rel)
        except OSError:
            continue
    return restored


def rollback_last() -> Dict:
    """Undo the most recently applied change-set."""
    with _CPLOCK:
        cp = dict(_LAST_CHECKPOINT)
        _LAST_CHECKPOINT.clear()
    if not cp:
        return {"restored": [], "note": "nothing to roll back"}
    return {"restored": _restore(cp)}


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
    {"type": "function", "function": {
        "name": "revert_all",
        "description": "Undo all of this session's file changes, restoring the previous versions. "
                       "Use if your changes broke things and you want a clean slate.",
        "parameters": {"type": "object", "properties": {}}}},
]

_SYSTEM = (
    "You are the J.A.R.V.I.S. DEV agent — an autonomous software engineer working "
    "ON the Jarvis codebase itself. Implement the Operator's task with minimal, "
    "correct, idiomatic changes that match the surrounding code. Workflow: explore "
    "with list_files/read_file FIRST, then write_file your changes, then run_tests "
    "and fix any failures, iterating until green. If you get stuck or break the "
    "build, call revert_all to roll back and start over. Keep everything inside the "
    "project; never touch secrets or .git. When done, reply with a concise summary "
    "of what you changed and why (no tool call). NOTE: if the suite is still failing "
    "at the end, your changes will be automatically rolled back."
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
    # Checkpoint: first time a path is touched, remember its prior state so the
    # change-set can be rolled back if the tests fail.
    checkpoint: Dict[str, str | None] = {}

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
        rel = os.path.relpath(p, REPO_ROOT)
        if rel not in checkpoint:                     # snapshot before first write
            checkpoint[rel] = _read_raw(p) if os.path.exists(p) else None
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content)
        changed.add(rel)
        rec("write_file", rel)
        return {"written": rel, "bytes": len(content)}

    def run_tests():
        rec("run_tests")
        return _run_tests()

    def git_diff():
        rec("git_diff")
        return _git_diff()

    def revert_all():
        restored = _restore(checkpoint)
        checkpoint.clear()
        changed.clear()
        rec("revert_all", f"{len(restored)} files")
        return {"reverted": restored}

    impls = {"list_files": list_files, "read_file": read_file, "write_file": write_file,
             "run_tests": run_tests, "git_diff": git_diff, "revert_all": revert_all}

    messages = [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": "TASK: " + task}]
    try:
        result = deepseek.complete_with_tools(messages, SCHEMA, impls,
                                              temperature=0.2, max_tokens=1600, max_rounds=max_rounds)
    except deepseek.DeepSeekError as exc:
        return {"error": str(exc), "actions": actions, "files_changed": sorted(changed)}

    changed_list = sorted(changed)
    tests = _run_tests() if changed else None
    rolled_back = False
    tests_after_rollback = None
    if changed and tests and not tests.get("passed"):
        # The change-set is broken — restore the previous working versions.
        _restore(checkpoint)
        rec("auto_rollback", f"{len(checkpoint)} files restored")
        rolled_back = True
        tests_after_rollback = _run_tests()
        with _CPLOCK:
            _LAST_CHECKPOINT.clear()
    else:
        # Keep the change, but remember how to undo it on request.
        with _CPLOCK:
            _LAST_CHECKPOINT.clear()
            _LAST_CHECKPOINT.update(checkpoint)

    return {
        "task": task,
        "summary": result["text"],
        "actions": actions,
        "files_changed": changed_list,
        "diff": _git_diff(),
        "tests": tests,
        "rolled_back": rolled_back,
        "tests_after_rollback": tests_after_rollback,
        "can_rollback": bool(changed_list) and not rolled_back,
        "generated": datetime.now(tz=timezone.utc).isoformat(),
    }
