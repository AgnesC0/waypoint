"""
detector.py — Detect running Claude Code sessions via AppleScript + ps aux.

Two-layer detection strategy:
  1. ps aux  — find all claude processes and resolve their working directories
               via a single batched lsof call
  2. AppleScript — enumerate Terminal.app windows to get IDs and titles so
                   the HUD can focus the right window on click

The two sources are cross-referenced: a process CWD is matched against project
keywords, then the Terminal window whose title best matches that path is
associated with the result.
"""

import subprocess
from typing import Optional


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 3) -> str:
    """Run a subprocess and return stdout; return '' on any error."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _applescript(script: str) -> str:
    """Execute an AppleScript snippet and return its stdout."""
    return _run(["osascript", "-e", script])


# ---------------------------------------------------------------------------
# Process detection (ps aux + lsof)
# ---------------------------------------------------------------------------

def get_claude_pids() -> list[str]:
    """
    Return PIDs of all running processes whose command line contains 'claude'.
    Excludes grep, waypoint itself, and Python to avoid false positives.
    """
    raw = _run(["ps", "aux"])
    pids = []
    for line in raw.splitlines():
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        cmd = parts[10].lower()
        if (
            "claude" in cmd
            and "grep" not in cmd
            and "waypoint" not in cmd
            and "detector" not in cmd
        ):
            pids.append(parts[1])  # PID is column 2
    return pids


def get_cwds(pids: list[str]) -> dict[str, str]:
    """
    Resolve working directories for a list of PIDs in a single lsof call.
    Returns a dict mapping pid → absolute path.
    """
    if not pids:
        return {}

    raw = _run(["lsof", "-a", "-p", ",".join(pids), "-d", "cwd", "-Fn"], timeout=4)
    result: dict[str, str] = {}
    current_pid: Optional[str] = None

    for line in raw.splitlines():
        if line.startswith("p"):
            current_pid = line[1:]
        elif line.startswith("n") and current_pid:
            result[current_pid] = line[1:]

    return result


# ---------------------------------------------------------------------------
# Terminal window enumeration (AppleScript)
# ---------------------------------------------------------------------------

def get_terminal_windows() -> list[dict]:
    """
    Return all Terminal.app windows as [{"id": str, "title": str}].
    Uses a "|||" separator so commas inside titles are preserved.
    Returns [] if Terminal is not running.
    """
    script = """
    tell application "System Events"
        if not (exists process "Terminal") then return ""
    end tell
    tell application "Terminal"
        set result to {}
        repeat with w in windows
            set wId to id of w
            set wName to name of w
            set end of result to (wId as string) & "|||" & wName
        end repeat
        -- join with newlines so commas inside titles are safe
        set AppleScript's text item delimiters to linefeed
        set result to result as string
        set AppleScript's text item delimiters to ""
        return result
    end tell
    """
    raw = _applescript(script)
    if not raw:
        return []

    windows = []
    for line in raw.splitlines():
        line = line.strip()
        if "|||" in line:
            wid, title = line.split("|||", 1)
            windows.append({"id": wid.strip(), "title": title.strip()})
    return windows


# ---------------------------------------------------------------------------
# Detector class
# ---------------------------------------------------------------------------

class Detector:
    """
    Combines process and window data to produce a list of active Claude
    sessions, each enriched with the matched project and a Terminal window
    ID for click-to-focus.
    """

    def __init__(self, projects: list[dict]) -> None:
        self.projects = projects

    # -- matching -----------------------------------------------------------

    def _match_project(self, text: str) -> Optional[dict]:
        """Return the first project whose keywords appear in text (case-insensitive)."""
        lower = text.lower()
        for project in self.projects:
            for kw in project.get("keywords", []):
                if kw.lower() in lower:
                    return project
        return None

    def _find_window_for_path(
        self, cwd: str, windows: list[dict]
    ) -> Optional[str]:
        """
        Heuristic: check the last two path components of cwd against each
        window title. Returns the window ID of the best match, or None.
        """
        parts = [p for p in cwd.strip("/").split("/") if p]
        candidates = parts[-2:] if len(parts) >= 2 else parts

        for win in windows:
            title_lower = win["title"].lower()
            if any(c.lower() in title_lower for c in candidates):
                return win["id"]
        return None

    # -- public API ---------------------------------------------------------

    def detect(self) -> list[dict]:
        """
        Return a list of active Claude sessions:
          [{"project": {...}, "window_id": str|None, "path": str}]

        Each entry represents one running claude process matched to a project.
        Deduplicated by project name (first match wins).
        """
        pids = get_claude_pids()
        cwd_map = get_cwds(pids)       # pid → cwd
        windows = get_terminal_windows()

        results: list[dict] = []
        seen: set[str] = set()

        for pid, cwd in cwd_map.items():
            project = self._match_project(cwd)
            if not project or project["name"] in seen:
                continue

            seen.add(project["name"])
            results.append({
                "project": project,
                "window_id": self._find_window_for_path(cwd, windows),
                "path": cwd,
            })

        return results

    def focus_window(self, window_id: str) -> None:
        """Bring the Terminal window with the given ID to the front."""
        script = f"""
        tell application "Terminal"
            activate
            repeat with w in windows
                if (id of w as string) is "{window_id}" then
                    set frontmost of w to true
                    exit repeat
                end if
            end repeat
        end tell
        """
        _applescript(script)
