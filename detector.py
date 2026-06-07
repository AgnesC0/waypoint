"""
detector.py — Workspace detection engine.

Philosophy: the application thinks in Workspaces, not PIDs or windows.
All implementation details (tty, lsof, AppleScript IDs) stay inside
this module. Everything above gets clean Workspace objects.

Detection pipeline:
  1. AppleScript → enumerate Terminal tabs + their tty paths
  2. ps          → find the shell PID for each tty
  3. lsof        → resolve shell CWD (single batched call)
  4. path match  → compare CWD against configured project paths
  5. yield       → Workspace objects, one per matched project
"""

import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Workspace — the only type the rest of the application touches
# ---------------------------------------------------------------------------

@dataclass
class Workspace:
    name: str         # display name from config
    path: str         # absolute real path from config
    window_id: str    # Terminal window ID — used only for focus()
    last_seen: float = field(default_factory=time.time)

    @property
    def display_path(self) -> str:
        """Return a ~ abbreviated path suitable for display."""
        home = os.path.expanduser("~")
        return "~" + self.path[len(home):] if self.path.startswith(home) else self.path


# ---------------------------------------------------------------------------
# Low-level helpers (private to this module)
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 3) -> str:
    """Run a subprocess, return stdout; silently return '' on any error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _applescript(script: str) -> str:
    return _run(["osascript", "-e", script])


# ---------------------------------------------------------------------------
# Step 1 — enumerate Terminal tabs
# ---------------------------------------------------------------------------

def _terminal_tabs() -> list[dict]:
    """
    Return [{window_id, tty}] for every open Terminal.app tab.
    Each tty is a device path like /dev/ttys003.
    """
    script = """
    tell application "System Events"
        if not (exists process "Terminal") then return ""
    end tell
    tell application "Terminal"
        set rows to {}
        repeat with w in windows
            set wId to id of w
            repeat with t in tabs of w
                try
                    set ttyPath to tty of t
                    set end of rows to (wId as string) & "|||" & ttyPath
                end try
            end repeat
        end repeat
        set AppleScript's text item delimiters to linefeed
        set rows to rows as string
        set AppleScript's text item delimiters to ""
        return rows
    end tell
    """
    raw = _applescript(script)
    if not raw:
        return []

    tabs = []
    for line in raw.splitlines():
        line = line.strip()
        if "|||" not in line:
            continue
        wid, tty = line.split("|||", 1)
        tabs.append({"window_id": wid.strip(), "tty": tty.strip()})
    return tabs


# ---------------------------------------------------------------------------
# Step 2 — find shell PID for a tty
# ---------------------------------------------------------------------------

_SHELLS = {"zsh", "bash", "sh", "fish", "tcsh", "csh", "ksh"}


def _shell_pids(tabs: list[dict]) -> dict[str, str]:
    """
    Map tty → shell PID for each tab.
    Uses a single `ps` call per tty to find the shell process.
    Returns only entries where a shell was found.
    """
    result: dict[str, str] = {}

    for tab in tabs:
        tty = tab["tty"].replace("/dev/", "")
        raw = _run(["ps", "-t", tty, "-o", "pid,comm"])

        for line in raw.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            pid, comm = parts
            try:
                int(pid)  # skip header row
            except ValueError:
                continue

            # Normalize: strip leading dash (-zsh → zsh) and directory prefix
            base = comm.lstrip("-").split("/")[-1]
            if base in _SHELLS:
                result[tab["tty"]] = pid
                break

    return result


# ---------------------------------------------------------------------------
# Step 3 — batch CWD resolution via lsof
# ---------------------------------------------------------------------------

def _batch_cwds(pids: list[str]) -> dict[str, str]:
    """
    Resolve working directories for multiple PIDs in a single lsof call.
    Returns {pid: cwd_path}.
    """
    if not pids:
        return {}

    raw = _run(
        ["lsof", "-a", "-p", ",".join(pids), "-d", "cwd", "-Fn"],
        timeout=4,
    )

    cwds: dict[str, str] = {}
    current_pid: Optional[str] = None

    for line in raw.splitlines():
        if line.startswith("p"):
            current_pid = line[1:]
        elif line.startswith("n") and current_pid:
            cwds[current_pid] = line[1:]

    return cwds


# ---------------------------------------------------------------------------
# Detector — public API
# ---------------------------------------------------------------------------

class Detector:
    """
    Produces Workspace objects from the current terminal state.
    Projects are configured by path (not keyword); matching is prefix-based
    so subfolders within a project are also recognised.
    """

    def __init__(self, projects: list[dict]) -> None:
        # Expand and resolve all project paths once at init time
        self._projects = [
            {
                "name": p["name"],
                "path": os.path.realpath(os.path.expanduser(p["path"])),
            }
            for p in projects
        ]

    def detect(self) -> list[Workspace]:
        """
        Scan Terminal sessions and return one Workspace per active project.
        Projects without a matching terminal tab are omitted.
        """
        tabs = _terminal_tabs()
        if not tabs:
            return []

        # tty → shell pid
        tty_to_pid = _shell_pids(tabs)
        if not tty_to_pid:
            return []

        # tty → window_id (for focus)
        tty_to_window = {tab["tty"]: tab["window_id"] for tab in tabs}

        # Batch CWD lookup
        pid_to_tty = {pid: tty for tty, pid in tty_to_pid.items()}
        cwds = _batch_cwds(list(tty_to_pid.values()))

        workspaces: list[Workspace] = []
        seen: set[str] = set()

        for pid, cwd in cwds.items():
            project = self._match(cwd)
            if not project or project["name"] in seen:
                continue

            seen.add(project["name"])
            tty = pid_to_tty.get(pid, "")
            workspaces.append(Workspace(
                name=project["name"],
                path=project["path"],
                window_id=tty_to_window.get(tty, ""),
            ))

        return workspaces

    def focus(self, workspace: Workspace) -> None:
        """Bring the Terminal window for this workspace to the front."""
        if not workspace.window_id:
            return
        _applescript(f"""
        tell application "Terminal"
            activate
            repeat with w in windows
                if (id of w as string) is "{workspace.window_id}" then
                    set frontmost of w to true
                    exit repeat
                end if
            end repeat
        end tell
        """)

    def _match(self, cwd: str) -> Optional[dict]:
        """
        Match a CWD against configured project paths.
        Accepts exact matches and subdirectories.
        """
        real = os.path.realpath(cwd)
        for project in self._projects:
            p = project["path"]
            if real == p or real.startswith(p + os.sep):
                return project
        return None
