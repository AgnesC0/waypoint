#!/usr/bin/env bash
# record_gif.sh — Record the full screen as an animated GIF.
#
# Requirements:
#   brew install ffmpeg          # required
#   brew install gifsicle        # optional — smaller output file
#
# Usage:
#   ./record_gif.sh              # 12-second recording, outputs waypoint_demo.gif
#   ./record_gif.sh 15           # custom duration in seconds
#
# Arrange your windows before running: Waypoint HUD in corner, terminal(s)
# with Claude Code visible. This script captures whatever is on screen.

set -e

DURATION="${1:-12}"
OUTPUT="waypoint_demo.gif"
FPS=10

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

# ── Capture frames ────────────────────────────────────────────────────────────
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

INTERVAL=$(python3 -c "print(1/$FPS)")
echo "Recording ${DURATION}s at ${FPS}fps → ${OUTPUT}"
echo "Interact with the screen now..."
echo ""

FRAME=0
END_TS=$(python3 -c "import time; print(time.time() + $DURATION)")

while python3 -c "import time,sys; sys.exit(0 if time.time() < $END_TS else 1)" 2>/dev/null; do
    screencapture -x "$TMPDIR/frame_$(printf '%04d' "$FRAME").png" 2>/dev/null
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
