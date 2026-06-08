"""
detector_macos.py — macOS terminal detection via AppleScript + ps + lsof.

Detection pipeline:
  1. AppleScript → enumerate Terminal.app tabs: window_id, tty, tab_index
  2. ps          → find shell PID for each tty (single call, filter in Python)
  3. lsof        → resolve CWD for all shell PIDs (single batched call)
  4. _match()    → compare CWD variants against configured project paths
"""

import os
import subprocess
from typing import Optional

from detector import BaseDetector, Workspace


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 3) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _applescript(script: str) -> str:
    return _run(["osascript", "-e", script])


# ---------------------------------------------------------------------------
# Step 1 — enumerate Terminal.app tabs
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
        wid       = parts[0].strip()
        tty       = parts[1].strip()
        tab_index = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 1
        tabs.append({"window_id": wid, "tty": tty, "tab_index": tab_index})
    return tabs


# ---------------------------------------------------------------------------
# Step 2 — find shell PID for each tty
# ---------------------------------------------------------------------------

_SHELLS = {"zsh", "bash", "sh", "fish", "tcsh", "csh", "ksh"}


def _shell_pids(tabs: list[dict]) -> dict[str, str]:
    """
    Map tty → shell PID using a single ps call, filtered in Python.
    Only considers ttys belonging to the tabs enumerated by AppleScript.
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
            int(pid)
        except ValueError:
            continue
        if tty_short == "??":
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
    """Resolve working directories for multiple PIDs in a single lsof call."""
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
# MacOSDetector
# ---------------------------------------------------------------------------

class MacOSDetector(BaseDetector):

    def detect(self) -> list[Workspace]:
        tabs = _terminal_tabs()
        if not tabs:
            return []

        tty_to_pid = _shell_pids(tabs)
        if not tty_to_pid:
            return []

        tty_to_window    = {tab["tty"]: tab["window_id"]  for tab in tabs}
        tty_to_tab_index = {tab["tty"]: tab["tab_index"]  for tab in tabs}
        pid_to_tty       = {pid: tty for tty, pid in tty_to_pid.items()}

        cwds = _batch_cwds(list(tty_to_pid.values()))
        if not cwds:
            return []

        # last-match-wins: later AppleScript tab order overwrites earlier
        # entries for the same project (predictable, no activity tracking).
        workspace_map: dict[str, Workspace] = {}

        _home = os.path.expanduser("~")
        for pid, cwd in cwds.items():
            project = self._match(cwd)
            if project:
                name = project["name"]
                path = project["path"]
            else:
                if cwd == _home or os.path.dirname(cwd) == cwd:
                    continue
                name = os.path.basename(cwd) or cwd
                path = cwd
            tty = pid_to_tty.get(pid, "")
            workspace_map[name] = Workspace(
                name=name,
                path=path,
                window_id=tty_to_window.get(tty, ""),
                tab_index=tty_to_tab_index.get(tty, 1),
                tty=tty,
                cwd=cwd,
            )

        return sorted(workspace_map.values(),
                      key=lambda ws: self._order.get(ws.name, len(self._projects)))

    def focus(self, workspace: Workspace) -> None:
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
