#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
SERVER_PID=''

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT INT TERM

command -v uv >/dev/null 2>&1 || { printf '%s\n' 'uv is required for the package proof.' >&2; exit 1; }
EXPECTED_VERSION="$(cd "$REPOSITORY_ROOT" && python3 -c 'from odysseus import __version__; print(__version__)')"
if ! UV_CACHE_DIR="$TEMP_ROOT/uv-cache" uv build "$REPOSITORY_ROOT" --out-dir "$TEMP_ROOT/dist" >"$TEMP_ROOT/uv-build.log" 2>&1; then
  if grep -Eq 'Failed to fetch|No solution found when resolving|operation timed out|offline' "$TEMP_ROOT/uv-build.log"; then
    printf '%s\n' 'uv could not fetch isolated build requirements; using offline package proof fallback.' >&2
    ODYSSEUS_OFFLINE_DIST="$TEMP_ROOT/dist" python3 "$REPOSITORY_ROOT/scripts/build-offline-package.py" >/dev/null
  else
    cat "$TEMP_ROOT/uv-build.log" >&2
    exit 1
  fi
fi
WHEEL="$(find "$TEMP_ROOT/dist" -name '*.whl' -print -quit)"
test -n "$WHEEL"

export UV_CACHE_DIR="$TEMP_ROOT/uv-cache"
export UV_TOOL_DIR="$TEMP_ROOT/uv-tools"
uvx --from "$WHEEL" odysseus --version | grep -q "Odysseus $EXPECTED_VERSION"
uvx --from "$WHEEL" odysseus --state-dir "$TEMP_ROOT/state" doctor --json >"$TEMP_ROOT/doctor.json"
python3 - "$TEMP_ROOT/doctor.json" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["web_assets"], value
assert value["bundled_skills"] >= 9, value
PY

PORT="${ODYSSEUS_PACKAGE_TEST_PORT:-8874}"
uvx --from "$WHEEL" odysseus --state-dir "$TEMP_ROOT/web-state" serve --port "$PORT" >"$TEMP_ROOT/server.log" 2>&1 &
SERVER_PID="$!"
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/" | grep -q 'ODYSSEUS'
curl -fsS "http://127.0.0.1:$PORT/api/bootstrap" >"$TEMP_ROOT/bootstrap.json"
python3 - "$TEMP_ROOT/bootstrap.json" "$EXPECTED_VERSION" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["version"] == sys.argv[2], value
PY

printf 'Wheel, uvx entry point, bundled assets, Skills, and HTTP boot passed for %s.\n' "$EXPECTED_VERSION"
