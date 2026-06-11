"""
detector.py — Workspace type and platform dispatcher.

Exports Workspace and the correct Detector class for the current OS.
All code that does `from detector import Detector, Workspace` continues
to work without any changes.

Platform implementations:
  detector_macos.py   → MacOSDetector   (AppleScript + ps + lsof)
  detector_windows.py → WindowsDetector (psutil + optional pywin32)
"""

import os
import sys
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
    window_id: str    # platform window identifier (AppleScript ID / HWND / PID)
    tab_index: int    # 1-based tab index; 1 when tabs are unsupported
    tty: str = ""     # terminal device path; "" on Windows
    cwd: str = ""     # actual shell cwd at detection time
    pid: str = ""     # shell process PID; used for foreground-command detection
    last_seen: float = field(default_factory=time.time)

    @property
    def display_path(self) -> str:
        home = os.path.expanduser("~")
        return "~" + self.path[len(home):] if self.path.startswith(home) else self.path


# ---------------------------------------------------------------------------
# BaseDetector — shared path normalisation and matching
# ---------------------------------------------------------------------------

class BaseDetector:
    """
    Shared project-path setup and CWD matching.
    Platform subclasses implement detect() and focus().
    """

    def __init__(self, projects: list[dict], debug: bool = False) -> None:
        self._projects = [
            {
                "name":     p["name"],
                "path":     os.path.realpath(os.path.expanduser(p["path"])),
                "path_abs": os.path.abspath(os.path.expanduser(p["path"])),
            }
            for p in projects
        ]
        self._order = {p["name"]: i for i, p in enumerate(self._projects)}
        self._debug = debug

    def detect(self) -> list[Workspace]:
        raise NotImplementedError

    def focus(self, workspace: Workspace) -> None:
        raise NotImplementedError

    def _match(self, cwd: str) -> Optional[dict]:
        """
        Match a CWD against configured project paths.

        Uses os.path.normcase so matching is case-insensitive on Windows
        (normcase is a no-op on macOS/Linux). Generates realpath, abspath,
        and raw variants of the CWD to tolerate symlinks and path aliases.
        """
        nc = os.path.normcase
        cwd_variants = {
            nc(os.path.realpath(cwd)),
            nc(os.path.abspath(cwd)),
            nc(cwd),
        }
        for project in self._projects:
            for proj_path in (project["path"], project["path_abs"]):
                norm = nc(proj_path)
                for v in cwd_variants:
                    if v == norm or v.startswith(norm + os.sep):
                        return project
        return None


# ---------------------------------------------------------------------------
# Platform dispatch — must come after Workspace and BaseDetector are defined
# so that the platform modules can safely import from this module.
# ---------------------------------------------------------------------------

if sys.platform == "darwin":
    from detector_macos import MacOSDetector as Detector
elif sys.platform == "win32":
    from detector_windows import WindowsDetector as Detector
else:
    raise RuntimeError(f"[Waypoint] Unsupported platform: {sys.platform}")
