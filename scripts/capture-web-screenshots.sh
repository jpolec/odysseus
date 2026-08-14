#!/usr/bin/env bash
# Reproduce the public web screenshots from deterministic no-token demo state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$REPOSITORY_ROOT/docs/screenshots}"
PORT="${ODYSSEUS_SCREENSHOT_PORT:-8743}"
STATE_DIR="$(mktemp -d)"
SERVER_PID=''

cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" >/dev/null 2>&1 || true; fi
  rm -rf "$STATE_DIR"
}
trap cleanup EXIT INT TERM

BROWSER=''
for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$candidate" >/dev/null 2>&1; then BROWSER="$(command -v "$candidate")"; break; fi
done
if [ -z "$BROWSER" ] && [ -x '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' ]; then
  BROWSER='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
fi
if [ -z "$BROWSER" ]; then
  printf '%s\n' 'Chrome or Chromium is required to capture web screenshots.' >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
"$REPOSITORY_ROOT/scripts/demo.py" --state-dir "$STATE_DIR" --serve --port "$PORT" >/dev/null 2>&1 &
SERVER_PID="$!"
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null

RUN_ID="$($REPOSITORY_ROOT/bin/odysseus --state-dir "$STATE_DIR" runs --json | python3 -c 'import json,sys; print(next(run["id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Stabilize checkout retry flow"))')"
BASE_URL="http://127.0.0.1:$PORT"
COMMON=(--headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --window-size=1440,1000)

"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-attention.png" "$BASE_URL/?view=attention"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-epic-dag.png" "$BASE_URL/?view=epics"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-integration-ci.png" "$BASE_URL/#task/$RUN_ID"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-insights.png" "$BASE_URL/?view=insights"
printf 'Screenshots written to %s\n' "$OUTPUT_DIR"
