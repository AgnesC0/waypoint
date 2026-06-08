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
        task_keyword, confidence = self._infer_task(ws)
        self._sessions[ws.name] = {
            "start_time":   now,
            "ws":           ws,
            "task_keyword": task_keyword,
            "confidence":   confidence,
        }
        self._write({
            "event_type":        "workspace_start",
            "timestamp":         now,
            "start_time":        now,
            "end_time":          None,
            "duration_seconds":  None,
            "workspace":         ws.name,
            "cwd":               ws.cwd,
            "tty":               ws.tty,
            "window_id":         ws.window_id,
            "tab_id":            ws.tab_index,
            "previous_workspace": None,
            "current_workspace": ws.name,
            "end_reason":        None,
            "task_keyword":      task_keyword,
            "confidence":        confidence,
        })

    def _emit_end(self, name: str, end_reason: str, now: float) -> None:
        session = self._sessions.pop(name)
        ws = session["ws"]
        self._write({
            "event_type":        "workspace_end",
            "timestamp":         now,
            "start_time":        session["start_time"],
            "end_time":          now,
            "duration_seconds":  round(now - session["start_time"], 2),
            "workspace":         name,
            "cwd":               ws.cwd,
            "tty":               ws.tty,
            "window_id":         ws.window_id,
            "tab_id":            ws.tab_index,
            "previous_workspace": name,
            "current_workspace": None,
            "end_reason":        end_reason,
            "task_keyword":      session["task_keyword"],
            "confidence":        session["confidence"],
        })

    def _emit_switch(
        self, ended_name: str, started_name: str, current: dict, now: float
    ) -> None:
        session = self._sessions.pop(ended_name)
        new_ws  = current[started_name]
        task_keyword, confidence = self._infer_task(new_ws)

        self._write({
            "event_type":        "workspace_switch",
            "timestamp":         now,
            "start_time":        session["start_time"],
            "end_time":          now,
            "duration_seconds":  round(now - session["start_time"], 2),
            "workspace":         ended_name,
            "cwd":               session["ws"].cwd,
            "tty":               session["ws"].tty,
            "window_id":         session["ws"].window_id,
            "tab_id":            session["ws"].tab_index,
            "previous_workspace": ended_name,
            "current_workspace": started_name,
            "end_reason":        "switch_workspace",
            "task_keyword":      session["task_keyword"],
            "confidence":        session["confidence"],
        })

        self._sessions[started_name] = {
            "start_time":   now,
            "ws":           new_ws,
            "task_keyword": task_keyword,
            "confidence":   confidence,
        }

    # ── JSONL writer ─────────────────────────────────────────────────────────

    def _write(self, event: dict) -> None:
        try:
            with open(self._log_path, "a") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            pass

    # ── Task inference ────────────────────────────────────────────────────────

    def _infer_task(self, ws: Workspace) -> tuple[str, float]:
        """
        Infer a task keyword conservatively from three sources, in order:
          1. git branch  — strongest signal; user-chosen, task-specific
          2. folder name — moderate signal; reflects project intent
          3. display name — weakest; last resort
        Returns ("", 0.0) when no meaningful keyword can be extracted.
        """
        branch = self._git_branch(ws.path)
        if branch and branch not in _SKIP_BRANCHES:
            kw = _clean_token(branch)
            if kw:
                return kw, 0.8

        folder = os.path.basename(ws.path.rstrip("/"))
        kw = _clean_token(folder)
        if kw and kw not in _SKIP_TOKENS:
            return kw, 0.5

        kw = _clean_token(ws.name)
        if kw:
            return kw, 0.3

        return "", 0.0

    def _git_branch(self, path: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", path, "branch", "--show-current"],
                capture_output=True, text=True, timeout=2,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""


# ── Module-level helper ───────────────────────────────────────────────────────

def _clean_token(raw: str) -> str:
    """Return the first meaningful lowercase token from a name or branch path."""
    tokens = re.split(r"[^a-z0-9]+", raw.lower())
    tokens = [t for t in tokens if len(t) > 2 and t not in _SKIP_TOKENS]
    return tokens[0] if tokens else ""
