"""
main.py — Waypoint entry point.

Usage:
    python main.py

Loads config.yaml from the same directory, creates the Detector and HUD,
and starts the tkinter event loop. The window runs until the user quits
via the right-click menu or Ctrl-C.
"""

import os
import sys
import tkinter as tk

import yaml

from detector import Detector
from hud import HUD


def load_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(path):
        print(
            f"[Waypoint] config.yaml not found at: {path}\n"
            "Copy it from the repo and edit to match your projects.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path, "r") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    config = load_config()
    projects = config.get("projects", [])

    if not projects:
        print(
            "[Waypoint] No projects defined in config.yaml — add at least one entry.",
            file=sys.stderr,
        )
        sys.exit(1)

    detector = Detector(projects)

    root = tk.Tk()
    root.title("Waypoint")

    HUD(root, config, detector)
    root.mainloop()


if __name__ == "__main__":
    main()
