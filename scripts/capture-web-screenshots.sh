#!/usr/bin/env bash
# Reproduce the public web screenshots from deterministic no-token demo state.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$REPOSITORY_ROOT/docs/screenshots}"
PORT="${ODYSSEUS_SCREENSHOT_PORT:-8743}"
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
while ! port_is_free "$PORT" || ! port_is_free "$((PORT + 1))"; do
  PORT="$((PORT + 2))"
done
STATE_DIR="$(mktemp -d)"
FIRST_RUN_STATE_DIR="$(mktemp -d)"
FIRST_RUN_PORT="$((PORT + 1))"
SERVER_PID=''
FIRST_RUN_SERVER_PID=''

cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" >/dev/null 2>&1 || true; fi
  if [ -n "$FIRST_RUN_SERVER_PID" ]; then kill "$FIRST_RUN_SERVER_PID" >/dev/null 2>&1 || true; fi
  rm -rf "$STATE_DIR"
  rm -rf "$FIRST_RUN_STATE_DIR"
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
"$REPOSITORY_ROOT/bin/odysseus" --state-dir "$FIRST_RUN_STATE_DIR" serve --port "$FIRST_RUN_PORT" >/dev/null 2>&1 &
FIRST_RUN_SERVER_PID="$!"
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$FIRST_RUN_PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$FIRST_RUN_PORT/api/health" >/dev/null

RUN_ID="$($REPOSITORY_ROOT/bin/odysseus --state-dir "$STATE_DIR" runs --json | python3 -c 'import json,sys; print(next(run["id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Stabilize checkout retry flow"))')"
PROJECT_ID="$($REPOSITORY_ROOT/bin/odysseus --state-dir "$STATE_DIR" runs --json | python3 -c 'import json,sys; print(next(run["project_id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Stabilize checkout retry flow"))')"
REVIEW_RUN_ID="$($REPOSITORY_ROOT/bin/odysseus --state-dir "$STATE_DIR" runs --json | python3 -c 'import json,sys; print(next(run["id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Guard the factor pipeline against look-ahead bias"))')"
ACCEPTED_RUN_ID="$($REPOSITORY_ROOT/bin/odysseus --state-dir "$STATE_DIR" runs --json | python3 -c 'import json,sys; print(next(run["id"] for run in json.load(sys.stdin)["runs"] if run["title"] == "Make webhook delivery idempotent"))')"
BASE_URL="http://127.0.0.1:$PORT"
COMMON=(--headless=new --disable-gpu --no-sandbox --hide-scrollbars --force-device-scale-factor=1 --window-size=1440,1000)

"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-first-run.png" "http://127.0.0.1:$FIRST_RUN_PORT/"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-portfolio.png" "$BASE_URL/?view=portfolio"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-workspace.png" "$BASE_URL/?view=work"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-project.png" "$BASE_URL/#project/$PROJECT_ID"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-attention.png" "$BASE_URL/?view=attention"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-task-review.png" "$BASE_URL/#task/$REVIEW_RUN_ID"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-task-delivery.png" "$BASE_URL/#task/$ACCEPTED_RUN_ID"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-integration.png" "$BASE_URL/?tab=integration#task/$RUN_ID"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-ci-repair.png" "$BASE_URL/?tab=ci#task/$RUN_ID"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-context-receipt.png" "$BASE_URL/?tab=context#task/$RUN_ID"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-new-task.png" "$BASE_URL/?view=work&dialog=task&prompt=Review%20authentication%20security"
"$BROWSER" "${COMMON[@]}" --screenshot="$OUTPUT_DIR/web-settings.png" "$BASE_URL/?view=settings"
printf 'Twelve real screenshots written to %s\n' "$OUTPUT_DIR"
