"""
main.py — Waypoint entry point.

    python main.py
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
        sys.exit(f"[Waypoint] config.yaml not found at {path}")
    with open(path) as fh:
        return yaml.safe_load(fh)


def main() -> None:
    config = load_config()
    projects = config.get("projects", [])
    if not projects:
        sys.exit("[Waypoint] No projects defined in config.yaml")

    root = tk.Tk()
    root.title("Waypoint")
    HUD(root, config, Detector(projects))
    root.mainloop()


if __name__ == "__main__":
    main()
