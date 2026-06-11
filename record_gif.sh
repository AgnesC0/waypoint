#!/usr/bin/env bash
# record_gif.sh — Record the Waypoint HUD as an animated GIF.
#
# Requirements:
#   brew install ffmpeg          # required
#   brew install gifsicle        # optional — smaller output file
#
# Usage:
#   ./record_gif.sh              # 10-second recording, outputs waypoint_demo.gif
#   ./record_gif.sh 15           # custom duration in seconds

set -e

DURATION="${1:-10}"
OUTPUT="waypoint_demo.gif"
FPS=10
WAYPOINT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Dependency check ──────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "ERROR: ffmpeg is required to convert frames → GIF."
    echo ""
    echo "Install it with:"
    echo "  brew install ffmpeg"
    echo ""
    echo "Optionally also install gifsicle for a smaller output file:"
    echo "  brew install gifsicle"
    exit 1
fi

# ── Locate the Waypoint HUD window ───────────────────────────────────────────
# The HUD uses overrideredirect so it has no title bar, but macOS accessibility
# still exposes it as a window of the Python process.
get_hud_region() {
    osascript 2>/dev/null <<'EOF'
tell application "System Events"
    set pyProcs to every process whose name is "Python"
    repeat with proc in pyProcs
        try
            set wins to every window of proc
            repeat with w in wins
                set pos  to position of w
                set sz   to size of w
                set wx to item 1 of pos
                set wy to item 2 of pos
                set ww to item 1 of sz
                set wh to item 2 of sz
                -- HUD is narrow (~180px wide); skip any wider windows (terminals, etc.)
                if ww < 300 then
                    return (wx as string) & "," & (wy as string) & "," & (ww as string) & "," & (wh as string)
                end if
            end repeat
        end try
    end repeat
    return ""
end tell
EOF
}

echo "Locating HUD window..."
BOUNDS="$(get_hud_region)"

PADDING=24
if [ -n "$BOUNDS" ]; then
    IFS=',' read -r WX WY WW WH <<< "$BOUNDS"
    RX=$(( WX - PADDING ))
    RY=$(( WY - PADDING ))
    RW=$(( WW + PADDING * 2 ))
    RH=$(( WH + PADDING * 2 ))
    # screencapture -R requires non-negative coordinates
    [ "$RX" -lt 0 ] && RX=0
    [ "$RY" -lt 0 ] && RY=0
    REGION_FLAG="-R ${RX},${RY},${RW},${RH}"
    echo "  HUD found at ${WX},${WY}  size ${WW}×${WH}"
    echo "  Capture region: ${RX},${RY}  ${RW}×${RH}"
else
    REGION_FLAG=""
    echo "  HUD window not found — capturing full screen."
    echo "  (Make sure Waypoint is running before recording.)"
fi

# ── Capture frames ────────────────────────────────────────────────────────────
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

INTERVAL=$(python3 -c "print(1/$FPS)")
echo ""
echo "Recording ${DURATION}s at ${FPS}fps → ${OUTPUT}"
echo "Interact with the HUD now (click a project, hover rows, etc.)"
echo ""

FRAME=0
END_TS=$(python3 -c "import time; print(time.time() + $DURATION)")

while python3 -c "import time,sys; sys.exit(0 if time.time() < $END_TS else 1)" 2>/dev/null; do
    # shellcheck disable=SC2086
    screencapture -x $REGION_FLAG "$TMPDIR/frame_$(printf '%04d' "$FRAME").png" 2>/dev/null
    FRAME=$(( FRAME + 1 ))
    sleep "$INTERVAL"
done

echo "Captured $FRAME frames."

# ── Convert to GIF ────────────────────────────────────────────────────────────
echo "Converting to GIF..."

# Two-pass palette generation for best quality
ffmpeg -y \
    -framerate "$FPS" \
    -i "$TMPDIR/frame_%04d.png" \
    -vf "fps=${FPS},scale=400:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer" \
    "$OUTPUT" \
    -loglevel warning

# ── Optional gifsicle optimisation ───────────────────────────────────────────
if command -v gifsicle &>/dev/null; then
    echo "Optimising with gifsicle..."
    gifsicle -O3 --colors 128 --lossy=80 "$OUTPUT" -o "$OUTPUT"
fi

SIZE=$(du -sh "$OUTPUT" | cut -f1)
echo ""
echo "Done!  $OUTPUT  ($SIZE)"
