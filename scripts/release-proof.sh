#!/usr/bin/env bash
# Reproduce the local proof gate used before an Odysseus release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROOF_STATE="$(mktemp -d)"
PROOF_HTTP_STATE="$(mktemp -d)"
SERVER_PID=''

cleanup() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" >/dev/null 2>&1 || true; fi
  rm -rf "$PROOF_STATE" "$PROOF_HTTP_STATE"
}
trap cleanup EXIT INT TERM

cd "$REPOSITORY_ROOT"
printf '%s\n' '[1/6] Static, shell, and repository checks'
node --check web/app.js
python3 -m py_compile odysseus/*.py scripts/demo.py
bash -n install.sh scripts/*.sh tests/test_install.sh tests/test_package.sh
git diff --check

printf '%s\n' '[2/6] Checkout and exact-commit installer smoke tests'
./tests/test_install.sh

printf '%s\n' '[3/6] Complete automated suite'
python3 -m unittest discover -s tests -v

printf '%s\n' '[4/6] Build, uvx, packaged assets, and packaged HTTP boot'
./tests/test_package.sh

printf '%s\n' '[5/6] Reproducible Odysseus-on-Odysseus product state'
scripts/demo.py --state-dir "$PROOF_STATE" --project "$REPOSITORY_ROOT" >/dev/null
bin/odysseus --state-dir "$PROOF_STATE" runs --json >/dev/null
bin/odysseus --state-dir "$PROOF_STATE" stats >/dev/null

printf '%s\n' '[6/6] Checkout HTTP health, bootstrap, and shutdown smoke test'
PORT="${ODYSSEUS_RELEASE_PROOF_PORT:-8873}"
bin/odysseus --state-dir "$PROOF_HTTP_STATE" serve --port "$PORT" >"$PROOF_HTTP_STATE/server.log" 2>&1 &
SERVER_PID="$!"
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/api/health" >"$PROOF_HTTP_STATE/health.json"
curl -fsS "http://127.0.0.1:$PORT/api/bootstrap" >"$PROOF_HTTP_STATE/bootstrap.json"
python3 - "$PROOF_HTTP_STATE/health.json" "$PROOF_HTTP_STATE/bootstrap.json" <<'PY'
import json
import sys
from odysseus import __version__

health = json.load(open(sys.argv[1], encoding="utf-8"))
bootstrap = json.load(open(sys.argv[2], encoding="utf-8"))
assert health["ok"] is True, health
assert health["sse_connection_limit"] >= 1, health
assert bootstrap["version"] == __version__, bootstrap
PY
kill "$SERVER_PID"
wait "$SERVER_PID" || true
SERVER_PID=''

printf '%s\n' 'Odysseus release proof passed.'
