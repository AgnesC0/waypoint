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

# ---------------------------------------------------------------------------
# Step 0 — detect the focused Terminal.app tab
# ---------------------------------------------------------------------------

def _focused_tty() -> str:
    """Return the tty of the currently selected Terminal.app tab.

    Returns '' when Terminal is not frontmost or no tab is selected,
    so callers can distinguish "Terminal focused, known tab" from
    "user is in another app" without changing the stored active workspace.
    """
    script = """
    tell application "System Events"
        if not (exists process "Terminal") then return ""
    end tell
    tell application "Terminal"
        if not frontmost then return ""
        try
            return tty of selected tab of front window
        end try
        return ""
    end tell
    """
    return _applescript(script)


# ---------------------------------------------------------------------------
# MacOSDetector
# ---------------------------------------------------------------------------

class MacOSDetector(BaseDetector):

    def focused_tty(self) -> str:
        """Return the tty of the focused Terminal tab, or '' if Terminal is not frontmost."""
        return _focused_tty()

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
            project  = self._match(cwd)
            excluded = self._is_excluded(cwd)

            if self._debug:
                tty_dbg = pid_to_tty.get(pid, "?")
                resolved = os.path.realpath(cwd)
                if excluded:
                    match_label = "excluded"
                elif project:
                    match_label = f"configured: {project['name']}"
                elif cwd == _home or os.path.dirname(cwd) == cwd:
                    match_label = "skipped (home)"
                else:
                    match_label = "untracked"
                print(f"[poll] tab:          {tty_dbg}")
                print(f"[poll] raw cwd:      {cwd}")
                print(f"[poll] resolved cwd: {resolved}")
                print(f"[poll] matched:      {match_label}")
                print(flush=True)

            if excluded:
                continue

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
                pid=pid,
            )

        if self._debug:
            detected = sorted(workspace_map.keys())
            print(f"[poll] result: {detected if detected else '(none)'}", flush=True)

        return sorted(workspace_map.values(),
                      key=lambda ws: self._order.get(ws.name, len(self._projects)))

    def focus(self, workspace: Workspace) -> None:
        if not workspace.window_id:
            return
        if not str(workspace.window_id).isdigit():
            return
        tab_idx = workspace.tab_index or 1
        if not isinstance(tab_idx, int):
            return
        # Terminal's scripting API and System Events walk windows in the same
        # z-order, so the index found in the Terminal tell-block is valid in the
        # System Events tell-block with no translation.
        # AXRaise raises only the target window without activating Terminal.app,
        # so other Terminal windows stay where they are.
        # Avoided: `activate` (activates whole app) and `set index of w to 1`
        # (modifying a background app's window order triggers implicit activation
        # on macOS, same effect as activate).
        if self._debug:
            self._focus_debug(workspace, tab_idx)
            return
        _applescript(f"""
        set targetIdx to 0
        tell application "Terminal"
            set allWins to windows
            repeat with i from 1 to count of allWins
                set w to item i of allWins
                if (id of w as string) is "{workspace.window_id}" then
                    if miniaturized of w then set miniaturized of w to false
                    try
                        set selected tab of w to tab {tab_idx} of w
                    end try
                    set targetIdx to i
                    exit repeat
                end if
            end repeat
        end tell
        if targetIdx > 0 then
            tell application "System Events"
                tell process "Terminal"
                    perform action "AXRaise" of window targetIdx
                end tell
            end tell
        end if
        """)

    # ── Debug-mode focus ──────────────────────────────────────────────────────

    def _focus_debug(self, workspace: Workspace, tab_idx: int) -> None:
        """focus() with full before/after state logging to stderr."""
        import sys

        def _state() -> str:
            return _applescript("""
            tell application "System Events"
                set fa to name of first application process whose frontmost is true
                try
                    tell process "Terminal"
                        set tf to frontmost as string
                        set wnames to {}
                        set allW to windows
                        repeat with i from 1 to count of allW
                            set end of wnames to (i as string) & ":" & (name of item i of allW)
                        end repeat
                        set AppleScript's text item delimiters to "  |  "
                        set ws to wnames as string
                        set AppleScript's text item delimiters to ""
                    end tell
                on error
                    set tf to "no-terminal-process"
                    set ws to ""
                end try
                return "frontmost=" & fa & "  term_front=" & tf & "  term_wins=[" & ws & "]"
            end tell
            """)

        print(
            f"\n[focus-debug] ── {workspace.name!r} ──────────────────────",
            file=sys.stderr, flush=True,
        )
        print(
            f"[focus-debug]  target window_id={workspace.window_id!r}"
            f"  tab_index={tab_idx}"
            f"  tty={workspace.tty!r}",
            file=sys.stderr, flush=True,
        )
        print(
            f"[focus-debug]  commands: AXRaise=YES  activate=NO  set_index=NO",
            file=sys.stderr, flush=True,
        )
        print(f"[focus-debug]  BEFORE: {_state()}", file=sys.stderr, flush=True)

        # Run the identical script used in normal mode
        _applescript(f"""
        set targetIdx to 0
        tell application "Terminal"
            set allWins to windows
            repeat with i from 1 to count of allWins
                set w to item i of allWins
                if (id of w as string) is "{workspace.window_id}" then
                    if miniaturized of w then set miniaturized of w to false
                    try
                        set selected tab of w to tab {tab_idx} of w
                    end try
                    set targetIdx to i
                    exit repeat
                end if
            end repeat
        end tell
        if targetIdx > 0 then
            tell application "System Events"
                tell process "Terminal"
                    perform action "AXRaise" of window targetIdx
                end tell
            end tell
        end if
        """)

        print(f"[focus-debug]  AFTER:  {_state()}", file=sys.stderr, flush=True)
