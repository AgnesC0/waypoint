"""
main.py — Waypoint entry point.

Loads config.yaml, wires up the detector and the HUD, then starts the
tkinter event loop. Run this file directly:

    python main.py
"""

import os
import sys
import tkinter as tk

import yaml

from detector import Detector
from hud import HUD


def load_config() -> dict:
    """
    Load and return the YAML configuration file located in the same
    directory as this script. Exits with a clear message if not found.
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(config_path):
        print(
            f"[Waypoint] config.yaml not found at: {config_path}\n"
            "Copy config.yaml from the repo root and edit it to get started.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(config_path, "r") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    config = load_config()
    projects = config.get("projects", [])

    if not projects:
        print("[Waypoint] No projects defined in config.yaml — add at least one.", file=sys.stderr)
        sys.exit(1)

    detector = Detector(projects)

    root = tk.Tk()
    root.title("Waypoint")

    HUD(root, config, detector)
    root.mainloop()


if __name__ == "__main__":
    main()
