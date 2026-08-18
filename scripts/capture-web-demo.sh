#!/usr/bin/env bash
# Produce the public 90-second walkthrough from deterministic no-token demo state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$REPOSITORY_ROOT/docs/demo}"
PORT="${ODYSSEUS_VIDEO_PORT:-8751}"
FPS="${ODYSSEUS_VIDEO_FPS:-6}"
DURATION_SCALE="${ODYSSEUS_VIDEO_DURATION_SCALE:-1}"

port_is_free() {
  python3 -c 'import socket,sys
s=socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    s.close()' "$1"
}
while ! port_is_free "$PORT"; do PORT="$((PORT + 1))"; done

BROWSER=''
for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$candidate" >/dev/null 2>&1; then BROWSER="$(command -v "$candidate")"; break; fi
done
if [ -z "$BROWSER" ] && [ -x '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' ]; then
  BROWSER='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
fi
if [ -z "$BROWSER" ]; then printf '%s\n' 'Chrome or Chromium is required.' >&2; exit 1; fi
if ! command -v node >/dev/null 2>&1; then printf '%s\n' 'Node.js is required.' >&2; exit 1; fi
if ! command -v ffmpeg >/dev/null 2>&1; then printf '%s\n' 'ffmpeg is required.' >&2; exit 1; fi

STATE_DIR="$(mktemp -d)"
FRAMES_DIR="$(mktemp -d)"
PROFILE_DIR="$(mktemp -d)"
SERVER_PID=''
cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" >/dev/null 2>&1 || true; fi
  rm -rf "$STATE_DIR" "$FRAMES_DIR" "$PROFILE_DIR"
}
trap cleanup EXIT INT TERM

mkdir -p "$OUTPUT_DIR"
"$REPOSITORY_ROOT/scripts/demo.py" --state-dir "$STATE_DIR" --serve --port "$PORT" >/dev/null 2>&1 &
SERVER_PID="$!"
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null

RUNS_JSON="$($REPOSITORY_ROOT/bin/odysseus --state-dir "$STATE_DIR" runs --json)"
PROJECT_ID="$(printf '%s' "$RUNS_JSON" | python3 -c 'import json,sys; print(next(run["project_id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Stabilize checkout retry flow"))')"
REVIEW_RUN_ID="$(printf '%s' "$RUNS_JSON" | python3 -c 'import json,sys; print(next(run["id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Guard the factor pipeline against look-ahead bias"))')"
ACCEPTED_RUN_ID="$(printf '%s' "$RUNS_JSON" | python3 -c 'import json,sys; print(next(run["id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Make webhook delivery idempotent"))')"

FRAME_COUNT="$(node "$REPOSITORY_ROOT/scripts/capture-web-demo.mjs" \
  --base-url "http://127.0.0.1:$PORT" \
  --project-id "$PROJECT_ID" \
  --review-run-id "$REVIEW_RUN_ID" \
  --accepted-run-id "$ACCEPTED_RUN_ID" \
  --frames-dir "$FRAMES_DIR" \
  --profile-dir "$PROFILE_DIR" \
  --chrome "$BROWSER" \
  --fps "$FPS" \
  --duration-scale "$DURATION_SCALE")"

ffmpeg -hide_banner -loglevel error -y \
  -framerate "$FPS" -i "$FRAMES_DIR/frame-%05d.jpg" \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p -movflags +faststart \
  "$OUTPUT_DIR/odysseus-90s.mp4"
ffmpeg -hide_banner -loglevel error -y \
  -i "$OUTPUT_DIR/odysseus-90s.mp4" \
  -ss "$(python3 -c "print(max(0.0, 4.0 * float('$DURATION_SCALE')))")" -frames:v 1 \
  "$OUTPUT_DIR/odysseus-90s-poster.png"

printf 'Odysseus walkthrough: %s frames → %s\n' "$FRAME_COUNT" "$OUTPUT_DIR/odysseus-90s.mp4"
