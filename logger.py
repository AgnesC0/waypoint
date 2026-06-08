"""
logger.py — Workspace session event logger.

Writes workspace-level behavioral signals to ~/.waypoint/activity_log.jsonl.
Only records workspace presence, timing, and inferred task context.
Never records commands, keystrokes, terminal output, or file contents.

Event types
-----------
workspace_start  — a workspace appears for the first time (or after absence)
workspace_switch — exactly one workspace ends and one begins in the same cycle
workspace_end    — a workspace disappears with no simultaneous replacement

For a clean A→B transition only workspace_switch is emitted. For independent
appearances and disappearances, workspace_start / workspace_end are used.
"""

import json
import os
import re
import subprocess
import time
from typing import Optional

from detector import Workspace

_LOG_DIR  = os.path.expanduser("~/.waypoint")
_LOG_PATH = os.path.join(_LOG_DIR, "activity_log.jsonl")

# Branches too generic to carry task signal
_SKIP_BRANCHES = {
    "main", "master", "develop", "dev",
    "staging", "production", "release", "hotfix", "feature",
}

# Branch prefixes that scope a task name (e.g. "feature/terminal-detection")
_SKIP_PREFIXES = {"feature", "fix", "bugfix", "feat", "chore", "refactor", "hotfix", "release"}

# Tokens too generic to use as a keyword
_SKIP_TOKENS = {"app", "web", "api", "lib", "src", "new", "old", "test", "light", "dark"}


class WorkspaceLogger:
    """Records workspace session start / switch / end events to a JSONL log."""

    def __init__(self, log_path: str = _LOG_PATH) -> None:
        self._log_path = log_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        # name → {start_time, ws, task_keyword, confidence}
        self._sessions: dict[str, dict] = {}

    def update(self, workspaces: list[Workspace]) -> None:
        """Diff current workspace set against previous; emit events for changes."""
        now = time.time()
        current        = {ws.name: ws for ws in workspaces}
        previous_names = set(self._sessions)
        current_names  = set(current)

        ended   = previous_names - current_names
        started = current_names  - previous_names

        if len(ended) == 1 and len(started) == 1:
            self._emit_switch(next(iter(ended)), next(iter(started)), current, now)
        else:
            for name in ended:
                self._emit_end(name, "terminal_closed", now)
            for name in started:
                self._emit_start(current[name], now)

        # Keep cwd/tty current for continuing sessions
        for name in current_names & previous_names:
            self._sessions[name]["ws"] = current[name]

    def shutdown(self) -> None:
        """Flush all open sessions with end_reason=app_quit."""
        now = time.time()
        for name in list(self._sessions):
            self._emit_end(name, "app_quit", now)

    # ── Event emitters ────────────────────────────────────────────────────────

    def _emit_start(self, ws: Workspace, now: float) -> None:
        context = self._infer_task(ws)
        self._sessions[ws.name] = {
            "start_time": now,
            "ws":         ws,
            "context":    context,
        }
        self._write({
            "event_type":         "workspace_start",
            "timestamp":          now,
            "start_time":         now,
            "end_time":           None,
            "duration_seconds":   None,
            "workspace":          ws.name,
            "context":            context,
            "cwd":                ws.cwd,
            "tty":                ws.tty,
            "window_id":          ws.window_id,
            "tab_id":             ws.tab_index,
            "previous_workspace": None,
            "current_workspace":  ws.name,
            "end_reason":         None,
        })

    def _emit_end(self, name: str, end_reason: str, now: float) -> None:
        session = self._sessions.pop(name)
        ws = session["ws"]
        self._write({
            "event_type":         "workspace_end",
            "timestamp":          now,
            "start_time":         session["start_time"],
            "end_time":           now,
            "duration_seconds":   round(now - session["start_time"], 2),
            "workspace":          name,
            "context":            session["context"],
            "cwd":                ws.cwd,
            "tty":                ws.tty,
            "window_id":          ws.window_id,
            "tab_id":             ws.tab_index,
            "previous_workspace": name,
            "current_workspace":  None,
            "end_reason":         end_reason,
        })

    def _emit_switch(
        self, ended_name: str, started_name: str, current: dict, now: float
    ) -> None:
        session  = self._sessions.pop(ended_name)
        new_ws   = current[started_name]
        context  = self._infer_task(new_ws)

        self._write({
            "event_type":         "workspace_switch",
            "timestamp":          now,
            "start_time":         session["start_time"],
            "end_time":           now,
            "duration_seconds":   round(now - session["start_time"], 2),
            "workspace":          ended_name,
            "context":            session["context"],
            "cwd":                session["ws"].cwd,
            "tty":                session["ws"].tty,
            "window_id":          session["ws"].window_id,
            "tab_id":             session["ws"].tab_index,
            "previous_workspace": ended_name,
            "current_workspace":  started_name,
            "end_reason":         "switch_workspace",
        })

        self._sessions[started_name] = {
            "start_time": now,
            "ws":         new_ws,
            "context":    context,
        }

    # ── JSONL writer ─────────────────────────────────────────────────────────

    def _write(self, event: dict) -> None:
        try:
            with open(self._log_path, "a") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            pass

    # ── Task inference ────────────────────────────────────────────────────────

    def _infer_task(self, ws: Workspace) -> str:
        return infer_context(ws)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _git_branch(path: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _to_display_hint(raw: str) -> str:
    """Split on word separators and join with spaces: 'my-feature' → 'my feature'."""
    tokens = re.split(r"[-_/\s]+", raw.lower())
    return " ".join(t for t in tokens if t)


def infer_context(ws: Workspace) -> str:
    """
    Return a human-readable context string for log events.
    Uses git branch only; returns empty string when on main/master or no branch.
    Never reads commands, keystrokes, terminal output, or file contents.
    """
    branch = _git_branch(ws.path)
    if branch and branch not in _SKIP_BRANCHES:
        parts = branch.split("/")
        if parts[0].lower() in _SKIP_PREFIXES | _SKIP_BRANCHES:
            branch = "/".join(parts[1:])
        if branch and branch not in _SKIP_BRANCHES:
            return _to_display_hint(branch)
    return ""


_HINTS_PATH = os.path.join(_LOG_DIR, "hints.json")


class HintStore:
    """
    Persists one resume_hint per workspace to ~/.waypoint/hints.json.

    Each entry is stored as {"hint": str, "manual": bool}.
    Manual hints (set via the CLI) take priority over git-branch auto-detection
    and are never overwritten by the poll loop.

    Storage format:
        {
          "Waypoint":     {"hint": "fix HUD resume hint", "manual": true},
          "CogPass Light": {"hint": "execution cost model", "manual": false}
        }
    """

    def __init__(self, path: str = _HINTS_PATH) -> None:
        self._path  = path
        self._mtime: float = 0.0
        self._hints: dict[str, dict] = self._load()

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[str]:
        self._maybe_reload()
        entry = self._hints.get(name)
        return entry["hint"] if isinstance(entry, dict) else None

    def set_manual(self, name: str, raw: str) -> None:
        """Validate and store a user-provided hint; marks it as manual."""
        hint = raw.strip().split("\n")[0].strip()[:40]
        if not hint:
            return
        entry = self._hints.get(name, {})
        if isinstance(entry, dict) and entry.get("manual") and entry.get("hint") == hint:
            return
        self._hints[name] = {"hint": hint, "manual": True}
        self._persist()

    def clear(self, name: str) -> None:
        """Remove the hint for a workspace; auto-detection resumes next poll."""
        if name in self._hints:
            del self._hints[name]
            self._persist()

    def update_from_workspace(self, ws: Workspace) -> Optional[str]:
        """
        If the workspace has a meaningful git branch, persist it as the hint
        — unless a manual hint already exists for this workspace.
        Returns the currently stored hint (None when on main/master with no
        prior hint; the ↳ line is omitted in that case).
        """
        self._maybe_reload()
        entry = self._hints.get(ws.name)
        if isinstance(entry, dict) and entry.get("manual"):
            return entry["hint"]

        branch = _git_branch(ws.path)
        if branch and branch not in _SKIP_BRANCHES:
            parts = branch.split("/")
            if parts[0].lower() in _SKIP_PREFIXES | _SKIP_BRANCHES:
                branch = "/".join(parts[1:])
            if branch and branch not in _SKIP_BRANCHES:
                hint = _to_display_hint(branch)
                if hint:
                    self._set_auto(ws.name, hint)

        return self.get(ws.name)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _maybe_reload(self) -> None:
        """Reload from disk if hints.json has been modified since last read."""
        try:
            mtime = os.path.getmtime(self._path)
            if mtime != self._mtime:
                self._hints = self._load()
                self._mtime = mtime
        except OSError:
            pass

    def _set_auto(self, name: str, hint: str) -> None:
        entry = self._hints.get(name)
        if isinstance(entry, dict) and entry.get("hint") == hint:
            return
        self._hints[name] = {"hint": hint, "manual": False}
        self._persist()

    def _load(self) -> dict[str, dict]:
        try:
            self._mtime = os.path.getmtime(self._path)
            with open(self._path) as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            # Only accept entries in the current dict format {hint, manual}.
            # Flat-string values from older versions (folder-name seeds) are
            # discarded — they were never meaningful resume hints.
            return {
                k: v
                for k, v in data.items()
                if isinstance(v, dict) and "hint" in v and "manual" in v
            }
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as fh:
                json.dump(self._hints, fh, indent=2)
        except OSError:
            pass


_LAST_SEEN_PATH = os.path.join(_LOG_DIR, "last_seen.json")


class LastSeenStore:
    """
    Tracks the last Unix timestamp each workspace was seen by the detector.
    Persists to ~/.waypoint/last_seen.json so recency survives restarts.

    touch() is called every poll for open workspaces; writes to disk at most
    once per minute per workspace to keep I/O minimal.
    """

    def __init__(self, path: str = _LAST_SEEN_PATH) -> None:
        self._path  = path
        self._mtime: float = 0.0
        self._data: dict[str, float] = self._load()

    def touch(self, name: str) -> None:
        """Record that this workspace was just seen; persist if minute rolled over."""
        now  = time.time()
        prev = self._data.get(name, 0.0)
        self._data[name] = now
        if int(now // 60) != int(prev // 60):
            self._persist()

    def get(self, name: str) -> Optional[float]:
        self._maybe_reload()
        return self._data.get(name)

    def _maybe_reload(self) -> None:
        try:
            mtime = os.path.getmtime(self._path)
            if mtime != self._mtime:
                self._data  = self._load()
                self._mtime = mtime
        except OSError:
            pass

    def _load(self) -> dict[str, float]:
        try:
            self._mtime = os.path.getmtime(self._path)
            with open(self._path) as fh:
                data = json.load(fh)
            return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as fh:
                json.dump(self._data, fh, indent=2)
        except OSError:
            pass
