#!/usr/bin/env bash
# Build the fast hero film and four focused workflow films from disposable demo data.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$REPOSITORY_ROOT/docs/demo}"
FULL_FILM="$OUTPUT_DIR/odysseus-90s.mp4"

mkdir -p "$OUTPUT_DIR"

if [ ! -f "$FULL_FILM" ]; then
  "$SCRIPT_DIR/capture-web-demo.sh" "$OUTPUT_DIR"
fi

# Preserve every original frame while presenting the full tour in half the time.
ffmpeg -hide_banner -loglevel error -y \
  -i "$FULL_FILM" -vf 'setpts=0.5*PTS,fps=12' \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p -movflags +faststart \
  "$OUTPUT_DIR/odysseus-45s.mp4"
ffmpeg -hide_banner -loglevel error -y \
  -ss 4 -i "$OUTPUT_DIR/odysseus-45s.mp4" -frames:v 1 \
  "$OUTPUT_DIR/odysseus-45s-poster.png"

for story in task plan recovery delivery; do
  ODYSSEUS_VIDEO_STORY="$story" \
  ODYSSEUS_VIDEO_BASENAME="odysseus-$story" \
  ODYSSEUS_VIDEO_FPS="${ODYSSEUS_WORKFLOW_FPS:-3}" \
    "$SCRIPT_DIR/capture-web-demo.sh" "$OUTPUT_DIR"
done

printf 'Odysseus video suite written to %s\n' "$OUTPUT_DIR"
