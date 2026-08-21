#!/usr/bin/env bash
# Reproduce the local proof gate used before an Odysseus release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROOF_STATE="$(mktemp -d)"
PROOF_HTTP_STATE="$(mktemp -d)"
PROOF_CREDENTIAL_STATE="$(mktemp -d)"
SERVER_PID=''

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$PROOF_STATE" "$PROOF_HTTP_STATE" "$PROOF_CREDENTIAL_STATE"
}
trap cleanup EXIT INT TERM

cd "$REPOSITORY_ROOT"
printf '%s\n' '[1/9] Static, shell, browser prerequisite, and repository checks'
node --check web/app.js
python3 -m py_compile odysseus/*.py scripts/*.py
bash -n install.sh scripts/*.sh tests/test_install.sh tests/test_package.sh tests/test_upgrade.sh
python3 scripts/verify-release-consistency.py >/dev/null
git diff --check
BROWSER=''
for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$candidate" >/dev/null 2>&1; then BROWSER="$(command -v "$candidate")"; break; fi
done
if [ -z "$BROWSER" ] && [ -x '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' ]; then
  BROWSER='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
fi
if [ -z "$BROWSER" ]; then
  printf '%s\n' 'Chrome or Chromium is required for release browser smoke proof.' >&2
  exit 1
fi

printf '%s\n' '[2/9] Checkout and exact-commit installer smoke tests'
./tests/test_install.sh
./tests/test_upgrade.sh

printf '%s\n' '[3/9] Targeted recovery, integration, lifecycle, browser, and credential slices'
python3 -m unittest -v \
  tests.test_environments.EnvironmentTests.test_host_credentials_require_explicit_allow_env \
  tests.test_environments.EnvironmentTests.test_docker_wrapper_scopes_mounts_resources_network_ports_and_credentials \
  tests.test_worktrees.WorktreeTests.test_accepted_artifacts_are_composed_into_a_downstream_worktree \
  tests.test_worktrees.WorktreeTests.test_apply_to_repository_refuses_dirty_checkout_and_aborts_conflict \
  tests.test_worktrees.WorktreeTests.test_conflicting_artifacts_stop_on_the_isolated_integration_branch \
  tests.test_lifecycle.LifecycleLeaseTests.test_reclaim_removes_delivered_worktree_and_runtime_but_keeps_branch \
  tests.test_lifecycle.LifecycleLeaseTests.test_reclaim_keeps_failed_worktree_for_recovery \
  tests.test_browser_regression.BrowserRegressionTests.test_artifact_integration_and_sidebar_recovery_flow_in_real_browser

if bin/odysseus --state-dir "$PROOF_CREDENTIAL_STATE" run --project "$REPOSITORY_ROOT" \
  --env OPENAI_API_KEY=secret-value 'credential persistence probe' \
  >"$PROOF_CREDENTIAL_STATE/secret-env.out" 2>"$PROOF_CREDENTIAL_STATE/secret-env.err"; then
  printf '%s\n' 'Secret-looking environment value was accepted into a run request.' >&2
  exit 1
fi
grep -q 'looks secret' "$PROOF_CREDENTIAL_STATE/secret-env.err"
bin/odysseus --state-dir "$PROOF_CREDENTIAL_STATE" run --project "$REPOSITORY_ROOT" \
  --allow-env OPENAI_API_KEY 'name-only credential probe' --json >"$PROOF_CREDENTIAL_STATE/name-only-run.json"
python3 - "$PROOF_CREDENTIAL_STATE/name-only-run.json" <<'PY'
import json
import sys
run = json.load(open(sys.argv[1], encoding="utf-8"))
assert run["environment_request"]["allow_env"] == ["OPENAI_API_KEY"], run
assert "secret-value" not in json.dumps(run), run
PY

printf '%s\n' '[4/9] Complete automated suite'
python3 -m unittest discover -s tests -v

printf '%s\n' '[5/9] Build, uvx, packaged assets, and packaged HTTP boot'
./tests/test_package.sh

printf '%s\n' '[6/9] Reproducible Odysseus-on-Odysseus product state'
scripts/demo.py --state-dir "$PROOF_STATE" --project "$REPOSITORY_ROOT" >/dev/null
bin/odysseus --state-dir "$PROOF_STATE" runs --json >/dev/null
bin/odysseus --state-dir "$PROOF_STATE" stats >/dev/null
bin/odysseus --state-dir "$PROOF_STATE" resources --json >"$PROOF_STATE/resources.json"
bin/odysseus --state-dir "$PROOF_STATE" proof --json --output "$PROOF_STATE/production-proof.json" >/dev/null
python3 - "$PROOF_STATE/production-proof.json" "$PROOF_STATE/resources.json" <<'PY'
import json
import sys
proof = json.load(open(sys.argv[1], encoding="utf-8"))
resources = json.load(open(sys.argv[2], encoding="utf-8"))
assert proof["metrics"]["autonomous_tasks"] == 0, proof
assert proof["classifications"]["demo"] >= 1, proof
assert proof["classifications"]["demo"] == sum(proof["classifications"].values()), proof
assert proof["metrics"]["observed_tasks"] == 0, proof
assert len(proof["proof_sha256"]) == 64, proof
assert resources["format"] == "odysseus-resources-v1", resources
assert resources["totals"]["worktrees"] >= 0, resources
assert resources["totals"]["runtime_directories"] >= 0, resources
PY

printf '%s\n' '[7/9] Screenshot route smoke test'
SCREENSHOT_PROOF_DIR="$PROOF_STATE/screenshots"
ODYSSEUS_SCREENSHOT_PORT="${ODYSSEUS_RELEASE_SCREENSHOT_PORT:-8875}" \
  scripts/capture-web-screenshots.sh "$SCREENSHOT_PROOF_DIR" >/dev/null
python3 - "$SCREENSHOT_PROOF_DIR" <<'PY'
import pathlib
import sys
expected = {
    "web-first-run.png",
    "web-home.png",
    "web-portfolio.png",
    "web-workspace.png",
    "web-project.png",
    "web-plans.png",
    "web-attention.png",
    "web-task-review.png",
    "web-task-activity.png",
    "web-task-delivery.png",
    "web-integration.png",
    "web-ci-repair.png",
    "web-context-receipt.png",
    "web-new-task.png",
    "web-settings.png",
}
root = pathlib.Path(sys.argv[1])
actual = {path.name for path in root.glob("*.png")}
assert actual == expected, sorted(actual)
for path in root.glob("*.png"):
    assert path.stat().st_size > 10_000, path
PY

printf '%s\n' '[8/9] Checkout HTTP health, bootstrap, and shutdown smoke test'
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

printf '%s\n' '[9/9] Remote-access guardrail smoke test'
if bin/odysseus --state-dir "$PROOF_HTTP_STATE/remote" serve --host 0.0.0.0 --allow-remote --port 0 \
  >"$PROOF_HTTP_STATE/remote.out" 2>"$PROOF_HTTP_STATE/remote.err"; then
  printf '%s\n' 'Remote bind without authentication was accepted.' >&2
  exit 1
fi
grep -q -- '--allow-remote requires --auth-password-file' "$PROOF_HTTP_STATE/remote.err"

printf '%s\n' 'Odysseus release proof passed.'
