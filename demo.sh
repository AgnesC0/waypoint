#!/usr/bin/env bash
# demo.sh — Prepare Waypoint GIF demo environment.
#
# Sets demo hints and opens two Terminal windows in the configured project
# directories. Run this first, then run record_gif.sh while the HUD is visible.

set -e

WAYPOINT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── 1. Write demo hints ───────────────────────────────────────────────────────
python3 - <<'EOF'
import json, os

path = os.path.expanduser("~/.waypoint/hints.json")
os.makedirs(os.path.dirname(path), exist_ok=True)

try:
    with open(path) as f:
        hints = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    hints = {}

hints["CogPass Light"] = {"hint": "update light neuro",  "manual": True}
hints["Waypoint"]      = {"hint": "fix HUD resume hint", "manual": True}

with open(path, "w") as f:
    json.dump(hints, f, indent=2)

print(f"  hints written → {path}")
EOF

# ── 2. Open two Terminal windows in the project dirs ─────────────────────────
osascript <<EOF
tell application "Terminal"
    activate
    -- CogPass Light window
    set w1 to do script "cd ~/CogPass-Light && clear && echo '[ CogPass Light ]'"
    delay 0.4
    -- Waypoint window
    set w2 to do script "cd $WAYPOINT_DIR && clear && echo '[ Waypoint ]'"
    delay 0.4
end tell
EOF

echo ""
echo "Done. Two terminal windows are open."
echo "Now start the HUD and record:"
echo ""
echo "  python main.py          # in one tab"
echo "  ./record_gif.sh         # in another tab, once HUD is visible"
