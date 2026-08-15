#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT INT TERM

INSTALL_ROOT="$TEMP_ROOT/install"
BIN_ROOT="$TEMP_ROOT/bin"
STATE_ROOT="$TEMP_ROOT/state"
CURRENT_REF="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
CURRENT_VERSION="$(cd "$REPOSITORY_ROOT" && python3 -c 'from odysseus import __version__; print(__version__)')"

run_installer() {
  ODYSSEUS_INSTALL_REPOSITORY="$REPOSITORY_ROOT" bash -s -- \
    --install-dir "$INSTALL_ROOT" --bin-dir "$BIN_ROOT" --state-dir "$STATE_ROOT" --no-doctor "$@" \
    < "$REPOSITORY_ROOT/install.sh"
}

run_installer --version 0.6.1 >/dev/null
"$BIN_ROOT/odysseus" --version | grep -q 'Odysseus 0.6.1'
"$BIN_ROOT/odysseus" --state-dir "$STATE_ROOT" doctor --json >/dev/null
test ! -L "$INSTALL_ROOT/managed/previous"

# A live server lease and a live worker both close the maintenance race.
mkdir -p "$STATE_ROOT/runtime/server.lock"
python3 - "$STATE_ROOT/runtime/server.lock/owner.json" "$$" <<'PY'
import json, sys
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"pid": int(sys.argv[2]), "token": "test"}))
PY
if run_installer --update --ref "$CURRENT_REF" >"$TEMP_ROOT/live-server.log" 2>&1; then
  printf '%s\n' 'Installer accepted a live server lease.' >&2
  exit 1
fi
grep -q 'server is still running' "$TEMP_ROOT/live-server.log"
rm -rf "$STATE_ROOT/runtime/server.lock"
test ! -d "$STATE_ROOT/runtime/maintenance.lock"

mkdir -p "$STATE_ROOT/runs"
python3 - "$STATE_ROOT/runs/live-run.json" "$$" <<'PY'
import json, sys
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({
    "id": "live-run", "schema_version": 8, "status": "running", "worker_pid": int(sys.argv[2])
}))
PY
if run_installer --update --ref "$CURRENT_REF" >"$TEMP_ROOT/live-run.log" 2>&1; then
  printf '%s\n' 'Installer accepted a live agent worker.' >&2
  exit 1
fi
grep -q 'Active agent runs' "$TEMP_ROOT/live-run.log"
python3 - "$STATE_ROOT/runs/live-run.json" <<'PY'
import json, sys
path = sys.argv[1]
value = json.load(open(path, encoding="utf-8"))
value.update(status="attention", worker_pid=None)
open(path, "w", encoding="utf-8").write(json.dumps(value))
PY
cat >"$STATE_ROOT/inbox.json" <<'EOF'
{"release-note":{"id":"release-note","title":"before update","status":"open"}}
EOF

run_installer --update --ref "$CURRENT_REF" >/dev/null
"$BIN_ROOT/odysseus" --version | grep -q "Odysseus $CURRENT_VERSION"
test -L "$INSTALL_ROOT/managed/previous"
MATCHING_BACKUP="$(python3 - "$INSTALL_ROOT/managed/install.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["state_backup"])
PY
)"
test -f "$MATCHING_BACKUP"
test -f "$MATCHING_BACKUP.json"

# `update` is never an alias for a state-destructive downgrade.
if run_installer --update --version 0.5.4 >"$TEMP_ROOT/downgrade.log" 2>&1; then
  printf '%s\n' 'Installer accepted an update across a schema downgrade.' >&2
  exit 1
fi
grep -q 'refuses schema downgrade' "$TEMP_ROOT/downgrade.log"
"$BIN_ROOT/odysseus" --version | grep -q "Odysseus $CURRENT_VERSION"

CHECK_OUTPUT="$(ODYSSEUS_INSTALL_REPOSITORY="$REPOSITORY_ROOT" ODYSSEUS_INSTALL_LATEST_REF="$CURRENT_REF" \
  bash -s -- --check --ref "$CURRENT_REF" --install-dir "$INSTALL_ROOT" --bin-dir "$BIN_ROOT" --state-dir "$STATE_ROOT" \
  < "$REPOSITORY_ROOT/install.sh")"
printf '%s' "$CHECK_OUTPUT" | grep -q 'Update available\|up to date'

# A damaged archive is rejected before live state or the active version moves.
CORRUPT_BACKUP="$TEMP_ROOT/corrupt.tar.gz"
cp "$MATCHING_BACKUP" "$CORRUPT_BACKUP"
cp "$MATCHING_BACKUP.json" "$CORRUPT_BACKUP.json"
printf 'damage' >>"$CORRUPT_BACKUP"
python3 - "$INSTALL_ROOT/managed/install.json" "$CORRUPT_BACKUP" <<'PY'
import json, sys
path = sys.argv[1]
value = json.load(open(path, encoding="utf-8"))
value["state_backup"] = sys.argv[2]
open(path, "w", encoding="utf-8").write(json.dumps(value))
PY
cat >"$STATE_ROOT/inbox.json" <<'EOF'
{"release-note":{"id":"release-note","title":"after update","status":"open"}}
EOF
if run_installer --rollback --restore-state >"$TEMP_ROOT/corrupt-restore.log" 2>&1; then
  printf '%s\n' 'Rollback accepted a corrupt state archive.' >&2
  exit 1
fi
grep -q 'checksum does not match' "$TEMP_ROOT/corrupt-restore.log"
"$BIN_ROOT/odysseus" --version | grep -q "Odysseus $CURRENT_VERSION"
grep -q 'after update' "$STATE_ROOT/inbox.json"
python3 - "$INSTALL_ROOT/managed/install.json" "$MATCHING_BACKUP" <<'PY'
import json, sys
path = sys.argv[1]
value = json.load(open(path, encoding="utf-8"))
value["state_backup"] = sys.argv[2]
open(path, "w", encoding="utf-8").write(json.dumps(value))
PY

run_installer --rollback --restore-state >/dev/null
"$BIN_ROOT/odysseus" --version | grep -q 'Odysseus 0.6.1'
test "$(readlink "$INSTALL_ROOT/managed/previous")" != "$(readlink "$INSTALL_ROOT/managed/current")"
grep -q 'before update' "$STATE_ROOT/inbox.json"

# Existing unmanaged state is snapshotted even on the first managed install.
FIRST_ROOT="$TEMP_ROOT/first-managed"
mkdir -p "$FIRST_ROOT/state"
printf '%s\n' '{"max_parallel":1}' >"$FIRST_ROOT/state/config.json"
ODYSSEUS_INSTALL_REPOSITORY="$REPOSITORY_ROOT" bash -s -- \
  --install-dir "$FIRST_ROOT/install" --bin-dir "$FIRST_ROOT/bin" --state-dir "$FIRST_ROOT/state" \
  --no-doctor --version 0.6.1 < "$REPOSITORY_ROOT/install.sh" >/dev/null
FIRST_BACKUP="$(find "$FIRST_ROOT/install/managed/state-backups" -name '*.tar.gz' -print -quit)"
test -f "$FIRST_BACKUP"
test -f "$FIRST_BACKUP.json"

# An unrelated command is rejected before any release is activated.
PREFLIGHT_ROOT="$TEMP_ROOT/preflight"
mkdir -p "$PREFLIGHT_ROOT/bin"
printf '%s\n' 'reserved' >"$PREFLIGHT_ROOT/bin/odysseus"
if ODYSSEUS_INSTALL_REPOSITORY="$REPOSITORY_ROOT" bash -s -- \
  --install-dir "$PREFLIGHT_ROOT/install" --bin-dir "$PREFLIGHT_ROOT/bin" --state-dir "$PREFLIGHT_ROOT/state" \
  --no-doctor --version 0.6.1 < "$REPOSITORY_ROOT/install.sh" >"$TEMP_ROOT/preflight.log" 2>&1; then
  printf '%s\n' 'Installer replaced an unrelated command.' >&2
  exit 1
fi
grep -q 'Refusing to replace an existing file' "$TEMP_ROOT/preflight.log"
test ! -L "$PREFLIGHT_ROOT/install/managed/current"

printf 'Upgrade 0.6.1 -> %s and atomic rollback passed.\n' "$CURRENT_VERSION"
