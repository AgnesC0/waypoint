"""
detector_windows.py — Windows terminal detection via psutil + pywin32.

Detection pipeline:
  1. psutil.process_iter  → enumerate all running shell processes
  2. psutil.Process.cwd() → resolve working directory per process
  3. _wt_parent()         → walk up to find a Windows Terminal host, if any
  4. _hwnd_for_pid()      → map PID → visible top-level HWND (needs pywin32)
  5. _match()             → compare CWD against configured project paths

Supported terminals
  Windows Terminal  (wt.exe)      tabs detected via child shell processes
  PowerShell 5      (powershell.exe)
  PowerShell 7      (pwsh.exe)
  Command Prompt    (cmd.exe)

Field behaviour on Windows
  tty        → always ""  (no Unix tty concept)
  tab_index  → always 1   (WT tab enumeration requires UI Automation; deferred)
  window_id  → HWND as decimal string, or str(pid) when pywin32 is absent

Dependencies
  psutil>=5.9     required — install via requirements-windows.txt
  pywin32>=306    optional — window focus will silently no-op without it
"""

import os
from typing import Optional

from detector import BaseDetector, Workspace

_SHELL_NAMES = {"powershell.exe", "pwsh.exe", "cmd.exe"}
_WT_HOST     = "windowsterminal.exe"


# ---------------------------------------------------------------------------
# psutil helpers
# ---------------------------------------------------------------------------

def _iter_shell_procs():
    """
    Yield psutil.Process objects for every running shell process.
    Silently skips processes that have exited or denied access.
    Yields nothing (and does not raise) if psutil is not installed.
    """
    try:
        import psutil
    except ImportError:
        return

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() in _SHELL_NAMES:
                yield proc
        except Exception:
            pass


def _cwd_for_proc(proc) -> str:
    try:
        return proc.cwd()
    except Exception:
        return ""


def _wt_parent(proc):
    """
    Walk up the parent chain (up to 4 levels) looking for WindowsTerminal.exe.
    Returns the WT process object if found, None otherwise.

    The depth limit handles both the direct-child layout used in recent WT
    versions and the older layout where conhost.exe / OpenConsole.exe sits
    between WT and the shell.
    """
    try:
        p = proc
        for _ in range(4):
            p = p.parent()
            if p is None:
                break
            if p.name().lower() == _WT_HOST:
                return p
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Win32 HWND helpers (require pywin32)
# ---------------------------------------------------------------------------

def _hwnd_for_pid(pid: int) -> int:
    """
    Return the first visible top-level HWND owned by pid, or 0.
    Silently returns 0 if pywin32 is not installed.
    """
    try:
        import win32gui
        import win32process
    except ImportError:
        return 0

    found: list[int] = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                if wpid == pid:
                    found.append(hwnd)
            except Exception:
                pass

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass

    return found[0] if found else 0


# ---------------------------------------------------------------------------
# WindowsDetector
# ---------------------------------------------------------------------------

class WindowsDetector(BaseDetector):

    def detect(self) -> list[Workspace]:
        workspace_map: dict[str, Workspace] = {}
        _home = os.path.expanduser("~")

        for proc in _iter_shell_procs():
            cwd = _cwd_for_proc(proc)
            if not cwd:
                continue

            project = self._match(cwd)
            if project:
                name = project["name"]
                path = project["path"]
            else:
                if cwd == _home or os.path.dirname(cwd) == cwd:
                    continue
                name = os.path.basename(cwd) or cwd
                path = cwd

            # Prefer the Windows Terminal window handle when the shell is a
            # WT tab; fall back to the shell's own console HWND; then to
            # str(pid) when pywin32 is absent.
            hwnd = 0
            wt = _wt_parent(proc)
            if wt is not None:
                hwnd = _hwnd_for_pid(wt.pid)
            if not hwnd:
                hwnd = _hwnd_for_pid(proc.pid)
            window_id = str(hwnd) if hwnd else str(proc.pid)

            workspace_map[name] = Workspace(
                name=name,
                path=path,
                window_id=window_id,
                tab_index=1,
                tty="",
                cwd=cwd,
            )

        return sorted(workspace_map.values(),
                      key=lambda ws: self._order.get(ws.name, len(self._projects)))

    def focus(self, workspace: Workspace) -> None:
        """
        Bring the terminal window to the foreground via SetForegroundWindow.
        Silently no-ops when pywin32 is absent or window_id is not a valid HWND.
        """
        try:
            import win32gui
            import win32con
            hwnd = int(workspace.window_id)
            if not hwnd or not win32gui.IsWindow(hwnd):
                return
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
