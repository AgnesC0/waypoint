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

Print live detection state for debugging:
    python main.py status
"""

import argparse
import os
import sys
import time
import tkinter as tk
from typing import Optional

import yaml

from detector import Detector
from hud import HUD
from logger import HintStore, LastSeenStore


def load_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(path):
        sys.exit(f"[Waypoint] config.yaml not found at {path}")
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    # Always exclude Waypoint's own install directory regardless of config.yaml contents.
    own_dir  = os.path.dirname(os.path.abspath(__file__))
    own_real = os.path.realpath(own_dir)
    excludes = cfg.setdefault("exclude", [])
    if not any(os.path.realpath(os.path.expanduser(str(e))) == own_real for e in excludes):
        excludes.append(own_dir)
    return cfg


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


def _abbrev(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home) else path


def _cmd_status(config: dict) -> None:
    projects = config.get("projects", [])
    detector = Detector(projects, exclude=config.get("exclude", []))
    hint_store = HintStore()
    last_seen  = LastSeenStore()

    workspaces = detector.detect()

    # focused_tty is macOS-only; other platforms show "unsupported"
    focused_tty = ""
    focused_supported = hasattr(detector, "focused_tty")
    if focused_supported:
        try:
            focused_tty = detector.focused_tty()
        except Exception:
            focused_tty = ""

    now = time.time()

    if not workspaces:
        print("[Waypoint] No open workspaces detected.")
        print("Possible causes: Terminal not running, Automation permission not granted,")
        print("or no terminals open at configured project paths.")
        return

    print(f"Waypoint status — {len(workspaces)} workspace(s) open\n")

    for ws in workspaces:
        inferred = hint_store.update_from_workspace(ws) or "(none)"
        stored   = hint_store.get(ws.name) or "(none)"

        if focused_supported:
            if ws.tty and focused_tty and ws.tty == focused_tty:
                active_str = f"yes  (focused tty: {focused_tty})"
            elif focused_tty:
                active_str = f"no   (focused tty: {focused_tty})"
            else:
                active_str = "no   (Terminal not frontmost)"
        else:
            active_str = "unsupported"

        ts = last_seen.get(ws.name)
        if ts is not None:
            delta = now - ts
            if delta < 60:
                recency = f"{int(delta)}s ago"
            elif delta < 3600:
                recency = f"{int(delta // 60)}m ago"
            else:
                recency = f"{delta / 3600:.1f}h ago"
        else:
            recency = "(no data)"

        print(f"  Workspace:     {ws.name}")
        print(f"  Config path:   {_abbrev(ws.path)}")
        print(f"  CWD:           {_abbrev(ws.cwd)}")
        print(f"  TTY:           {ws.tty or '(none)'}")
        print(f"  PID:           {ws.pid or '(none)'}")
        print(f"  Active tab:    {active_str}")
        print(f"  Inferred hint: {inferred}")
        print(f"  Stored hint:   {stored}")
        print(f"  Last seen:     {recency}")
        print()


def _run_hud(config: dict, debug: bool = False) -> None:
    projects = config.get("projects", [])
    if not projects:
        sys.exit("[Waypoint] No projects defined in config.yaml")
    root = tk.Tk()
    root.title("Waypoint")
    HUD(root, config, Detector(projects, debug=debug, exclude=config.get("exclude", [])))
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="waypoint",
        description="Waypoint — context restoration HUD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Print live detection state for debugging")

    hint_p = sub.add_parser("hint", help="Get or set the resume hint for a workspace")
    hint_p.add_argument("text",        nargs="?", default="",
                        help="Hint text (max 40 chars). Omit to read the current hint.")
    hint_p.add_argument("--clear", "-c", action="store_true",
                        help="Clear the hint; auto-detection resumes on next poll.")
    hint_p.add_argument("--workspace", "-w", metavar="NAME",
                        help="Workspace name. Default: match current directory to config.")

    parser.add_argument("--debug", action="store_true",
                        help="Print per-tab CWD detection details to stdout on every poll tick.")

    args   = parser.parse_args()
    config = load_config()

    if args.cmd == "hint":
        _cmd_hint(args, config)
    elif args.cmd == "status":
        _cmd_status(config)
    else:
        _run_hud(config, debug=args.debug)


if __name__ == "__main__":
    main()
