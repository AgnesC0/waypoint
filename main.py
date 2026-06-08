"""
main.py — Waypoint entry point.

Run the HUD:
    python main.py

Set a resume hint for the current project:
    python main.py hint "fix HUD resume hint"

Clear a hint:
    python main.py hint --clear

Read the current hint without changing it:
    python main.py hint

Target a specific workspace by name:
    python main.py hint "RSA analysis" --workspace SalzLab
"""

import argparse
import os
import sys
import tkinter as tk
from typing import Optional

import yaml

from detector import Detector
from hud import HUD
from logger import HintStore


def load_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(path):
        sys.exit(f"[Waypoint] config.yaml not found at {path}")
    with open(path) as fh:
        return yaml.safe_load(fh)


def _cwd_workspace(projects: list[dict]) -> Optional[str]:
    """Return the name of the project whose path contains the current directory."""
    cwd = os.path.realpath(os.getcwd())
    for p in projects:
        path = os.path.realpath(os.path.expanduser(p["path"]))
        if cwd == path or cwd.startswith(path + os.sep):
            return p["name"]
    return None


def _cmd_hint(args: argparse.Namespace, config: dict) -> None:
    projects = config.get("projects", [])
    store    = HintStore()

    if args.workspace:
        known = {p["name"] for p in projects}
        if args.workspace not in known:
            sys.exit(f"[Waypoint] Unknown workspace: {args.workspace!r}. "
                     f"Known: {sorted(known)}")
        name = args.workspace
    else:
        name = _cwd_workspace(projects)
        if not name:
            sys.exit("[Waypoint] Current directory does not match any configured workspace.\n"
                     "Use --workspace NAME to target one explicitly.")

    if args.clear:
        store.clear(name)
        print(f"Cleared resume hint for '{name}'.")
        return

    if not args.text:
        hint = store.get(name)
        print(f"'{name}': {hint!r}" if hint else f"'{name}': (no hint set)")
        return

    store.set_manual(name, args.text)
    print(f"'{name}' → {store.get(name)!r}")


def _run_hud(config: dict) -> None:
    projects = config.get("projects", [])
    if not projects:
        sys.exit("[Waypoint] No projects defined in config.yaml")
    root = tk.Tk()
    root.title("Waypoint")
    HUD(root, config, Detector(projects))
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="waypoint",
        description="Waypoint — context restoration HUD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    hint_p = sub.add_parser("hint", help="Get or set the resume hint for a workspace")
    hint_p.add_argument("text",        nargs="?", default="",
                        help="Hint text (max 40 chars). Omit to read the current hint.")
    hint_p.add_argument("--clear", "-c", action="store_true",
                        help="Clear the hint; auto-detection resumes on next poll.")
    hint_p.add_argument("--workspace", "-w", metavar="NAME",
                        help="Workspace name. Default: match current directory to config.")

    args   = parser.parse_args()
    config = load_config()

    if args.cmd == "hint":
        _cmd_hint(args, config)
    else:
        _run_hud(config)


if __name__ == "__main__":
    main()
