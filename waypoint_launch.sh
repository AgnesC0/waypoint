#!/usr/bin/env bash
# waypoint_launch.sh — Auto-launch the Waypoint HUD when a new terminal opens.
#
# Add this line to your ~/.zshrc (or ~/.bashrc):
#   source ~/waypoint/waypoint_launch.sh
#
# The script does nothing if Waypoint is already running, so opening multiple
# terminal tabs will not spawn duplicate windows.

# Resolve the directory containing this script, even when sourced
_WAYPOINT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"

# Skip if already running (match on the absolute path to main.py)
if pgrep -f "${_WAYPOINT_DIR}/main\.py" > /dev/null 2>&1; then
    unset _WAYPOINT_DIR
    return 0
fi

# Launch detached: nohup keeps it alive after the shell exits; disown removes
# it from job control so it doesn't print "[1]+ Done" later
nohup python "${_WAYPOINT_DIR}/main.py" > /dev/null 2>&1 &
disown

unset _WAYPOINT_DIR
