"""
detector.py — Workspace detection engine.

Philosophy: the application thinks in Workspaces, not PIDs or windows.
All implementation details (tty, lsof, AppleScript IDs) stay inside
this module. Everything above gets clean Workspace objects.

Detection pipeline:
  1. AppleScript → enumerate Terminal tabs + their tty paths + tab indices
  2. ps          → find the shell PID for each tty
  3. lsof        → resolve shell CWD (single batched call)
  4. path match  → compare CWD variants against configured project paths
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
    window_id: str    # Terminal window ID — used only inside focus()
    tab_index: int    # 1-based index of the tab within its window
    tty: str = ""     # terminal device path at detection time
    cwd: str = ""     # actual shell cwd at detection time
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
# Step 1 — enumerate Terminal tabs (window_id + tty + tab_index)
# ---------------------------------------------------------------------------

def _terminal_tabs() -> list[dict]:
    """
    Return [{window_id, tty, tab_index}] for every open Terminal.app tab.
    tab_index is 1-based and matches the AppleScript tab ordinal within
    its parent window — required for accurate tab-level focus.
    """
    script = """
    tell application "System Events"
        if not (exists process "Terminal") then return ""
    end tell
    tell application "Terminal"
        set rows to {}
        repeat with w in windows
            set wId to id of w
            set tabIdx to 0
            repeat with t in tabs of w
                set tabIdx to tabIdx + 1
                try
                    set ttyPath to tty of t
                    set end of rows to (wId as string) & "|||" & ttyPath & "|||" & (tabIdx as string)
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
        parts = line.split("|||", 2)
        if len(parts) < 2:
            continue
        wid = parts[0].strip()
        tty = parts[1].strip()
        tab_index = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 1
        tabs.append({"window_id": wid, "tty": tty, "tab_index": tab_index})
    return tabs


# ---------------------------------------------------------------------------
# Step 2 — find shell PID for a tty
# ---------------------------------------------------------------------------

_SHELLS = {"zsh", "bash", "sh", "fish", "tcsh", "csh", "ksh"}


def _shell_pids(tabs: list[dict]) -> dict[str, str]:
    """
    Map tty (full /dev/ttysNNN path) → shell PID using a single ps call.

    Runs `ps -A -o pid,tty,comm` once and filters in Python, rather than
    spawning one subprocess per tab. Only considers ttys belonging to the
    Terminal tabs already enumerated by AppleScript; ignores everything else.
    """
    known_ttys = {tab["tty"] for tab in tabs}
    if not known_ttys:
        return {}

    raw = _run(["ps", "-A", "-o", "pid,tty,comm"])
    result: dict[str, str] = {}

    for line in raw.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, tty_short, comm = parts

        try:
            int(pid)  # skip header row
        except ValueError:
            continue

        if tty_short == "??":  # no controlling terminal
            continue

        # ps reports e.g. ttys003; prepend /dev/ to get full path
        tty_full = f"/dev/{tty_short}"
        if tty_full not in known_ttys:
            continue

        base = comm.lstrip("-").split("/")[-1]
        if base in _SHELLS and tty_full not in result:
            result[tty_full] = pid

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
    Projects are configured by path; matching is prefix-based and
    symlink-tolerant so subdirectories and path aliases are recognised.
    """

    def __init__(self, projects: list[dict]) -> None:
        # Store both realpath and abspath variants for each project so
        # _match() can compare against whichever form the OS returns.
        self._projects = [
            {
                "name": p["name"],
                "path":     os.path.realpath(os.path.expanduser(p["path"])),
                "path_abs": os.path.abspath(os.path.expanduser(p["path"])),
            }
            for p in projects
        ]
        # Preserve config.yaml order for HUD display.
        self._order = {p["name"]: i for i, p in enumerate(self._projects)}

    def detect(self) -> list[Workspace]:
        """
        Scan Terminal sessions and return one Workspace per active project.
        Projects without a matching terminal tab are omitted.
        """
        tabs = _terminal_tabs()
        if not tabs:
            return []

        tty_to_pid = _shell_pids(tabs)
        if not tty_to_pid:
            return []

        tty_to_window    = {tab["tty"]: tab["window_id"]  for tab in tabs}
        tty_to_tab_index = {tab["tty"]: tab["tab_index"]  for tab in tabs}

        pid_to_tty = {pid: tty for tty, pid in tty_to_pid.items()}
        cwds = _batch_cwds(list(tty_to_pid.values()))

        if not cwds:
            return []

        # Build a name → Workspace map so that later matches overwrite earlier
        # ones for the same project. "Latest tab returned by AppleScript wins"
        # is the tie-break rule — predictable, simple, no activity tracking.
        workspace_map: dict[str, Workspace] = {}

        for pid, cwd in cwds.items():
            project = self._match(cwd)
            if not project:
                continue

            tty = pid_to_tty.get(pid, "")
            workspace_map[project["name"]] = Workspace(
                name=project["name"],
                path=project["path"],
                window_id=tty_to_window.get(tty, ""),
                tab_index=tty_to_tab_index.get(tty, 1),
                tty=tty,
                cwd=cwd,
            )

        # Return workspaces in config.yaml order, not detection order.
        # last-match-wins dedup is preserved; only the final sort changes.
        return sorted(workspace_map.values(),
                      key=lambda ws: self._order.get(ws.name, len(self._projects)))

    def focus(self, workspace: Workspace) -> None:
        """
        Bring the Terminal window (and correct tab) for this workspace to front.

        Order of operations:
          1. Activate Terminal.app
          2. Find the window by window_id
          3. Un-minimise if needed
          4. Select the correct tab (graceful fallback to window-level if it fails)
          5. Set frontmost
        """
        if not workspace.window_id:
            return

        tab_idx = workspace.tab_index or 1

        _applescript(f"""
        tell application "Terminal"
            activate
            repeat with w in windows
                if (id of w as string) is "{workspace.window_id}" then
                    if miniaturized of w then set miniaturized of w to false
                    try
                        set selected tab of w to tab {tab_idx} of w
                    end try
                    set frontmost of w to true
                    exit repeat
                end if
            end repeat
        end tell
        """)

    def _match(self, cwd: str) -> Optional[dict]:
        """
        Match a CWD against configured project paths.

        Generates multiple normalised variants of the incoming CWD (realpath,
        abspath, original) and compares each against both the realpath and
        abspath variants stored for each project. This handles macOS path
        aliases such as /tmp → /private/tmp and symlinked project directories.
        """
        cwd_variants = {
            os.path.realpath(cwd),
            os.path.abspath(cwd),
            cwd,
        }

        for project in self._projects:
            for proj_path in (project["path"], project["path_abs"]):
                for v in cwd_variants:
                    if v == proj_path or v.startswith(proj_path + os.sep):
                        return project

        return None
