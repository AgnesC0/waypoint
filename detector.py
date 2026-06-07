"""
detector.py — Browser tab title scanner using AppleScript.

Queries running instances of Chrome, Arc, and Safari for all open tab titles,
then matches them against the project keyword list from config.yaml.
"""

import subprocess
from typing import Optional


# AppleScript for each supported browser.
# Safari uses `name of t` (not `title`) per its scripting dictionary.
_BROWSER_SCRIPTS: dict[str, str] = {
    "Google Chrome": """
        tell application "Google Chrome"
            set result to {}
            repeat with w in windows
                repeat with t in tabs of w
                    set end of result to title of t
                end repeat
            end repeat
            return result
        end tell
    """,
    "Arc": """
        tell application "Arc"
            set result to {}
            repeat with w in windows
                repeat with t in tabs of w
                    set end of result to title of t
                end repeat
            end repeat
            return result
        end tell
    """,
    "Safari": """
        tell application "Safari"
            set result to {}
            repeat with w in windows
                repeat with t in tabs of w
                    set end of result to name of t
                end repeat
            end repeat
            return result
        end tell
    """,
}


def _running_apps() -> set[str]:
    """Return the set of application names currently running on macOS."""
    script = """
        tell application "System Events"
            return name of every process whose background only is false
        end tell
    """
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return {s.strip() for s in out.stdout.split(",")}
    except Exception:
        pass
    return set()


def _applescript(script: str) -> list[str]:
    """
    Run an AppleScript and return the result as a list of strings.
    AppleScript lists are returned as comma-separated text on stdout.
    Returns an empty list on any error or timeout.
    """
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            return [t.strip() for t in out.stdout.strip().split(",") if t.strip()]
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return []


class Detector:
    """Detects which configured project is currently active in the browser."""

    def __init__(self, projects: list[dict]) -> None:
        # projects is the list loaded directly from config.yaml
        self.projects = projects

    def get_tab_titles(self) -> list[str]:
        """
        Return all open tab titles across every supported browser that is
        currently running. Skips browsers that are not open to avoid delays.
        """
        running = _running_apps()
        titles: list[str] = []

        for browser, script in _BROWSER_SCRIPTS.items():
            if browser not in running:
                continue
            titles.extend(_applescript(script))

        return titles

    def detect(self) -> Optional[dict]:
        """
        Scan open tabs and return the first project whose keywords appear in
        any tab title, or None if no match is found.

        Matching is case-insensitive and checks substring containment, so a
        keyword "alpha" matches a tab titled "Project Alpha — Claude".
        """
        titles = self.get_tab_titles()
        if not titles:
            return None

        haystack = " ".join(titles).lower()

        for project in self.projects:
            for keyword in project.get("keywords", []):
                if keyword.lower() in haystack:
                    return project

        return None
