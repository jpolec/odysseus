#!/usr/bin/env bash
# Install, update, or roll back a versioned Odysseus checkout.
set -euo pipefail

REPOSITORY="${ODYSSEUS_INSTALL_REPOSITORY:-https://github.com/jpolec/odysseus.git}"
RELEASE_API="${ODYSSEUS_INSTALL_RELEASE_API:-https://api.github.com/repos/jpolec/odysseus/releases/latest}"
INSTALL_DIR="${ODYSSEUS_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/odysseus}"
BIN_DIR="${ODYSSEUS_BIN_DIR:-$HOME/.local/bin}"
STATE_DIR="${ODYSSEUS_HOME:-$HOME/.odysseus}"
REF="${ODYSSEUS_INSTALL_REF:-}"
CHANNEL="${ODYSSEUS_INSTALL_CHANNEL:-stable}"
MODE='install'
RUN_DOCTOR=1
RESTORE_STATE=0
EXPLICIT_SOURCE=0
STAGE_DIR=''
VALIDATION_DIR=''
LOCK_DIR=''
LOCK_OWNER="$$-$(date +%s)-$RANDOM"
STATE_MAINTENANCE_LOCK=''

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  --version VERSION    install one stable version (for example 0.6.2)
  --edge               install/update from main
  --ref REF            install an exact branch, tag, or commit
  --update             update the managed installation
  --check              report whether an update is available
  --rollback           atomically switch to the previous installed version
  --restore-state      with --rollback, restore its matching state backup
  --install-dir PATH   managed installation root
  --bin-dir PATH       command-link directory
  --state-dir PATH     state directory to back up and validate
  --no-doctor          skip the human-readable doctor report
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) REF="v${2#v}"; CHANNEL='stable'; EXPLICIT_SOURCE=1; shift 2 ;;
    --edge) REF='main'; CHANNEL='edge'; EXPLICIT_SOURCE=1; shift ;;
    --ref) REF="$2"; CHANNEL='custom'; EXPLICIT_SOURCE=1; shift 2 ;;
    --update) MODE='update'; shift ;;
    --check) MODE='check'; shift ;;
    --rollback) MODE='rollback'; shift ;;
    --restore-state) RESTORE_STATE=1; shift ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --no-doctor) RUN_DOCTOR=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

cleanup() {
  if [ -n "$STAGE_DIR" ] && [ -d "$STAGE_DIR" ]; then rm -rf "$STAGE_DIR"; fi
  if [ -n "$VALIDATION_DIR" ] && [ -d "$VALIDATION_DIR" ]; then rm -rf "$VALIDATION_DIR"; fi
  if [ -n "$STATE_MAINTENANCE_LOCK" ] && [ -d "$STATE_MAINTENANCE_LOCK" ] && \
     [ "$(sed -n '2p' "$STATE_MAINTENANCE_LOCK/owner" 2>/dev/null || true)" = "$LOCK_OWNER" ]; then
    rm -f "$STATE_MAINTENANCE_LOCK/owner" "$STATE_MAINTENANCE_LOCK/owner.json"
    rmdir "$STATE_MAINTENANCE_LOCK" >/dev/null 2>&1 || true
  fi
  if [ -n "$LOCK_DIR" ] && [ -d "$LOCK_DIR" ]; then
    if [ "$(sed -n '2p' "$LOCK_DIR/owner" 2>/dev/null || true)" = "$LOCK_OWNER" ]; then
      rm -f "$LOCK_DIR/owner"
      rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
    fi
  fi
}
trap cleanup EXIT INT TERM

if ! command -v git >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Git and Python 3.10+ are required to install Odysseus.' >&2
  exit 1
fi

absolute_path() {
  python3 - "$1" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

INSTALL_DIR="$(absolute_path "$INSTALL_DIR")"
BIN_DIR="$(absolute_path "$BIN_DIR")"
STATE_DIR="$(absolute_path "$STATE_DIR")"

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
CHECKOUT_ROOT=''
if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
  CANDIDATE_ROOT="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
  if [ -x "$CANDIDATE_ROOT/bin/odysseus" ]; then CHECKOUT_ROOT="$CANDIDATE_ROOT"; fi
fi

# Running ./install.sh from a clone remains the shortest development install.
if [ "$MODE" = 'install' ] && [ "$EXPLICIT_SOURCE" -eq 0 ] && [ -z "$REF" ] && [ -n "$CHECKOUT_ROOT" ]; then
  COMMAND_SOURCE="$CHECKOUT_ROOT/bin/odysseus"
  mkdir -p "$BIN_DIR"
  COMMAND_LINK="$BIN_DIR/odysseus"
  if [ -L "$COMMAND_LINK" ]; then
    EXISTING_TARGET="$(readlink "$COMMAND_LINK")"
    case "$EXISTING_TARGET" in
      "$COMMAND_SOURCE"|"$INSTALL_DIR"/*) ;;
      *) printf 'Refusing to replace an unrelated command link: %s -> %s\n' "$COMMAND_LINK" "$EXISTING_TARGET" >&2; exit 1 ;;
    esac
  elif [ -e "$COMMAND_LINK" ]; then
    printf 'Refusing to replace an existing file: %s\n' "$COMMAND_LINK" >&2
    exit 1
  fi
  ln -sfn "$COMMAND_SOURCE" "$COMMAND_LINK"
  printf 'Using checkout: %s\nInstalled: %s\n' "$CHECKOUT_ROOT" "$COMMAND_LINK"
  if [ "$RUN_DOCTOR" -eq 1 ]; then "$COMMAND_LINK" doctor; fi
  printf 'Start: %s start --open\n' "$COMMAND_LINK"
  exit 0
fi

MANAGED_DIR="$INSTALL_DIR/managed"
RELEASES_DIR="$MANAGED_DIR/releases"
CURRENT_LINK="$MANAGED_DIR/current"
PREVIOUS_LINK="$MANAGED_DIR/previous"
MANIFEST="$MANAGED_DIR/install.json"
BACKUPS_DIR="$MANAGED_DIR/state-backups"
COMMAND_LINK="$BIN_DIR/odysseus"

acquire_directory_lock() {
  LOCK_PATH="$1"
  LABEL="$2"
  for _attempt in 1 2 3; do
    if mkdir "$LOCK_PATH" 2>/dev/null; then
      printf '%s\n%s\n' "$$" "$LOCK_OWNER" >"$LOCK_PATH/owner"
      return 0
    fi
    OWNER_PID="$(sed -n '1p' "$LOCK_PATH/owner" 2>/dev/null || true)"
    if [ -n "$OWNER_PID" ] && kill -0 "$OWNER_PID" 2>/dev/null; then
      printf '%s is already active (pid %s): %s\n' "$LABEL" "$OWNER_PID" "$LOCK_PATH" >&2
      return 1
    fi
    STALE_PATH="$LOCK_PATH.stale-$$-$RANDOM"
    if mv "$LOCK_PATH" "$STALE_PATH" 2>/dev/null; then rm -rf "$STALE_PATH"; fi
  done
  printf 'Cannot acquire %s: %s\n' "$LABEL" "$LOCK_PATH" >&2
  return 1
}

server_lease_pid() {
  python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path
try:
    print(int(json.loads((Path(sys.argv[1]) / "owner.json").read_text()).get("pid") or 0))
except Exception:
    print(0)
PY
}

assert_quiescent_state() {
  SERVER_LOCK="$STATE_DIR/runtime/server.lock"
  if [ -d "$SERVER_LOCK" ]; then
    SERVER_PID="$(server_lease_pid "$SERVER_LOCK")"
    if [ "$SERVER_PID" -gt 0 ] 2>/dev/null && kill -0 "$SERVER_PID" 2>/dev/null; then
      printf 'Odysseus server is still running (pid %s). Stop it before install/update/rollback.\n' "$SERVER_PID" >&2
      return 1
    fi
    STALE_SERVER="$SERVER_LOCK.stale-$$-$RANDOM"
    if mv "$SERVER_LOCK" "$STALE_SERVER" 2>/dev/null; then rm -rf "$STALE_SERVER"; fi
  fi
  python3 - "$STATE_DIR" <<'PY'
import json
import os
import sys
from pathlib import Path

active = {"starting", "running", "checking", "reviewing", "cancelling", "publishing"}
root = Path(sys.argv[1])
live = []
for path in sorted((root / "runs").glob("*.json")):
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Cannot inspect active runs because {path} is invalid: {exc}")
    if run.get("status") not in active:
        continue
    try:
        pid = int(run.get("worker_pid") or 0)
        if pid > 0:
            os.kill(pid, 0)
            live.append(f"{run.get('id') or path.stem} (pid {pid})")
    except (OSError, TypeError, ValueError):
        continue
if live:
    raise SystemExit("Active agent runs must finish or stop before maintenance: " + ", ".join(live))
PY
}

if [ "$MODE" != 'check' ]; then
  if [ -d "$INSTALL_DIR" ] && [ ! -d "$MANAGED_DIR" ] && [ ! -d "$INSTALL_DIR/.git" ] && \
     [ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    printf 'Install path is non-empty and is not an Odysseus installation: %s\n' "$INSTALL_DIR" >&2
    exit 1
  fi
  mkdir -p "$MANAGED_DIR"
  LOCK_DIR="$MANAGED_DIR/install.lock"
  acquire_directory_lock "$LOCK_DIR" 'Another Odysseus install/update/rollback'
  mkdir -p "$STATE_DIR/runtime"
  STATE_MAINTENANCE_LOCK="$STATE_DIR/runtime/maintenance.lock"
  acquire_directory_lock "$STATE_MAINTENANCE_LOCK" 'Odysseus state maintenance'
  python3 - "$STATE_MAINTENANCE_LOCK/owner.json" "$LOCK_OWNER" <<'PY'
import json
import os
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"pid": os.getppid(), "token": sys.argv[2]}) + "\n", encoding="utf-8")
PY
  assert_quiescent_state
fi

resolve_latest_ref() {
  if [ -n "${ODYSSEUS_INSTALL_LATEST_REF:-}" ]; then
    printf '%s\n' "$ODYSSEUS_INSTALL_LATEST_REF"
    return
  fi
  python3 - "$RELEASE_API" <<'PY'
import json
import sys
import urllib.request

request = urllib.request.Request(sys.argv[1], headers={"Accept": "application/vnd.github+json", "User-Agent": "odysseus-installer"})
try:
    with urllib.request.urlopen(request, timeout=15) as response:
        value = json.load(response)
except Exception as exc:
    raise SystemExit(f"Cannot resolve the latest stable Odysseus release: {exc}")
tag = str(value.get("tag_name") or "")
if not tag.startswith("v") or value.get("draft") or value.get("prerelease"):
    raise SystemExit("The latest release response did not contain a stable v* tag.")
print(tag)
PY
}

current_target() {
  if [ -L "$CURRENT_LINK" ]; then readlink "$CURRENT_LINK"; fi
}

release_version() {
  "$1/bin/odysseus" --version | awk '{print $2}'
}

release_schema() {
  python3 - "$1/odysseus/store.py" <<'PY'
import re
import sys
from pathlib import Path

match = re.search(r"^RUN_SCHEMA_VERSION\s*=\s*(\d+)", Path(sys.argv[1]).read_text(encoding="utf-8"), re.MULTILINE)
if not match:
    raise SystemExit("Cannot read the run schema from the installed release.")
print(match.group(1))
PY
}

backup_state() {
  mkdir -p "$BACKUPS_DIR"
  SOURCE_RELEASE="${2:-}"
  SOURCE_VERSION='unmanaged'
  SOURCE_SCHEMA=0
  SOURCE_COMMIT=''
  if [ -n "$SOURCE_RELEASE" ] && [ -x "$SOURCE_RELEASE/bin/odysseus" ]; then
    SOURCE_VERSION="$(release_version "$SOURCE_RELEASE")"
    SOURCE_SCHEMA="$(release_schema "$SOURCE_RELEASE")"
    SOURCE_COMMIT="$(git -C "$SOURCE_RELEASE" rev-parse HEAD 2>/dev/null || true)"
  fi
  python3 - "$STATE_DIR" "$BACKUPS_DIR" "$1" "$SOURCE_VERSION" "$SOURCE_SCHEMA" "$SOURCE_COMMIT" <<'PY'
import datetime as dt
import fcntl
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path

root = Path(sys.argv[1]).expanduser()
destination = Path(sys.argv[2])
label = re.sub(r"[^A-Za-z0-9_.-]+", "-", sys.argv[3]).strip("-") or "unknown"
if not root.is_dir():
    print("")
    raise SystemExit(0)
items = [item for item in root.iterdir() if item.name not in {"worktrees", "runtime", ".store.lock"}]
if not items:
    print("")
    raise SystemExit(0)
stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
target = destination / f"{stamp}-{label}.tar.gz"
lock_path = root / ".store.lock"
with lock_path.open("a+") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    with tarfile.open(target, "w:gz") as archive:
        for item in items:
            archive.add(item, arcname=item.name, recursive=True)
    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
observed_schema = 0
for path in (root / "runs").glob("*.json"):
    try:
        observed_schema = max(observed_schema, int(json.loads(path.read_text()).get("schema_version") or 0))
    except Exception:
        pass
metadata = {
    "format": "odysseus-state-backup-v1",
    "archive": target.name,
    "archive_sha256": digest,
    "state_identity": hashlib.sha256(str(root.resolve()).encode()).hexdigest(),
    "source_version": sys.argv[4],
    "source_run_schema": int(sys.argv[5] or 0),
    "observed_run_schema": observed_schema,
    "source_commit": sys.argv[6],
    "created_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
target.with_suffix(target.suffix + ".json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
print(target)
PY
}

restore_state() {
  RESTORE_TARGET="$2"
  RESTORE_SCHEMA="$(release_schema "$RESTORE_TARGET")"
  python3 - "$STATE_DIR" "$1" "$RESTORE_TARGET/bin/odysseus" "$RESTORE_SCHEMA" <<'PY'
import fcntl
import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).expanduser().resolve()
archive_path = Path(sys.argv[2]).expanduser().resolve()
executable = Path(sys.argv[3]).resolve()
target_schema = int(sys.argv[4])
if len(root.parts) < 3 or root == Path.home().resolve():
    raise SystemExit(f"Refusing unsafe state restore target: {root}")
if not archive_path.is_file():
    raise SystemExit(f"State backup does not exist: {archive_path}")
metadata_path = archive_path.with_suffix(archive_path.suffix + ".json")
if not metadata_path.is_file():
    raise SystemExit(f"State backup metadata does not exist: {metadata_path}")
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
if metadata.get("format") != "odysseus-state-backup-v1":
    raise SystemExit("Unsupported state backup metadata format.")
if metadata.get("state_identity") != hashlib.sha256(str(root).encode()).hexdigest():
    raise SystemExit("State backup belongs to a different state directory.")
if metadata.get("archive_sha256") != hashlib.sha256(archive_path.read_bytes()).hexdigest():
    raise SystemExit("State backup checksum does not match its metadata.")
root.mkdir(parents=True, exist_ok=True)
staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.restore-", dir=root.parent))
recovery = Path(tempfile.mkdtemp(prefix=f".{root.name}.recovery-", dir=root.parent))
preserved = {"worktrees", "runtime", ".store.lock"}

def interrupted(_signum, _frame):
    raise InterruptedError("state restore interrupted")

signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGTERM, interrupted)
try:
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise SystemExit("Unsafe path in state backup.")
            if member.issym() or member.islnk() or member.isdev():
                raise SystemExit("Links and device files are not allowed in state backups.")
        archive.extractall(staging)

    # Strict compatibility check before touching live state. Newer releases
    # provide the exhaustive verifier; the inline scan protects older targets.
    for path in (staging / "runs").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or int(value.get("schema_version") or 0) > target_schema:
            raise SystemExit(f"Backup run is incompatible with target schema {target_schema}: {path}")
    for directory in ("runs", "epics", "project_profiles", "project_knowledge", "project_skill_policies"):
        for path in (staging / directory).glob("*.json"):
            if not isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
                raise SystemExit(f"Invalid JSON object: {path}")
    for path in (staging / "events").glob("*.ndjson"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() and not isinstance(json.loads(line), dict):
                raise SystemExit(f"Invalid NDJSON object: {path}:{number}")
    help_result = subprocess.run([str(executable), "state", "--help"], text=True, capture_output=True, check=False)
    if help_result.returncode == 0:
        verified = subprocess.run(
            [str(executable), "--state-dir", str(staging), "state", "verify", "--migrate", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
    else:
        verified = subprocess.run(
            [str(executable), "--state-dir", str(staging), "doctor", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
    if verified.returncode:
        raise SystemExit(f"Target release rejected restored state: {verified.stderr or verified.stdout}")

    installed: list[Path] = []
    moved_old: list[tuple[Path, Path]] = []
    with (root / ".store.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            for item in list(root.iterdir()):
                if item.name in preserved:
                    continue
                destination = recovery / item.name
                os.replace(item, destination)
                moved_old.append((item, destination))
            for item in list(staging.iterdir()):
                destination = root / item.name
                os.replace(item, destination)
                installed.append(destination)
        except BaseException:
            for item in reversed(installed):
                if item.is_dir() and not item.is_symlink():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            for destination, saved in reversed(moved_old):
                if saved.exists() or saved.is_symlink():
                    os.replace(saved, destination)
            raise
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
finally:
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(recovery, ignore_errors=True)
PY
}

atomic_link() {
  TARGET="$1"
  LINK="$2"
  TEMP_LINK="$LINK.next.$$"
  ln -s "$TARGET" "$TEMP_LINK"
  # `mv temp current` follows a destination symlink to a directory on macOS,
  # leaving `current` unchanged. os.replace swaps the symlink itself on both
  # macOS and Linux and keeps activation atomic.
  python3 - "$TEMP_LINK" "$LINK" <<'PY'
import os
import sys

os.replace(sys.argv[1], sys.argv[2])
PY
}

write_manifest() {
  python3 - "$MANIFEST" "$REPOSITORY" "$CHANNEL" "$REF" "$1" "$2" "$3" "$4" "$5" <<'PY'
import datetime as dt
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
value = {
    "format": "odysseus-install-v1",
    "repository": sys.argv[2],
    "channel": sys.argv[3],
    "ref": sys.argv[4],
    "version": sys.argv[5],
    "commit": sys.argv[6],
    "current": sys.argv[7],
    "previous": sys.argv[8],
    "state_backup": sys.argv[9],
    "updated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
temporary = path.with_name(f".{path.name}.{os.getpid()}")
temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
}

manifest_backup() {
  if [ ! -f "$MANIFEST" ]; then return; fi
  python3 - "$MANIFEST" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("state_backup") or "")
PY
}

activate_release() {
  NEW_TARGET="$1"
  OLD_TARGET="$2"
  NEW_VERSION="$3"
  NEW_COMMIT="$4"
  STATE_BACKUP_PATH="$5"
  OLD_PREVIOUS=''
  [ -L "$PREVIOUS_LINK" ] && OLD_PREVIOUS="$(readlink "$PREVIOUS_LINK")"
  SAVED_MANIFEST="$MANAGED_DIR/.install.json.before.$$"
  SAVED_MANAGER="$MANAGED_DIR/.install.sh.before.$$"
  [ -f "$MANIFEST" ] && cp "$MANIFEST" "$SAVED_MANIFEST"
  [ -f "$MANAGED_DIR/install.sh" ] && cp "$MANAGED_DIR/install.sh" "$SAVED_MANAGER"

  cp "$NEW_TARGET/install.sh" "$MANAGED_DIR/install.sh.next"
  chmod +x "$MANAGED_DIR/install.sh.next"
  if ! python3 - "$MANAGED_DIR/install.sh.next" "$MANAGED_DIR/install.sh" <<'PY'
import os, sys
os.replace(sys.argv[1], sys.argv[2])
PY
  then
    return 1
  fi
  if [ -n "$OLD_TARGET" ]; then atomic_link "$OLD_TARGET" "$PREVIOUS_LINK"; fi
  atomic_link "$NEW_TARGET" "$CURRENT_LINK"
  if write_manifest "$NEW_VERSION" "$NEW_COMMIT" "$NEW_TARGET" "$OLD_TARGET" "$STATE_BACKUP_PATH"; then
    rm -f "$SAVED_MANIFEST" "$SAVED_MANAGER"
    return 0
  fi

  printf '%s\n' 'Activation metadata failed; restoring the previous installation.' >&2
  if [ -n "$OLD_TARGET" ]; then atomic_link "$OLD_TARGET" "$CURRENT_LINK"; else rm -f "$CURRENT_LINK"; fi
  if [ -n "$OLD_PREVIOUS" ]; then atomic_link "$OLD_PREVIOUS" "$PREVIOUS_LINK"; else rm -f "$PREVIOUS_LINK"; fi
  if [ -f "$SAVED_MANIFEST" ]; then mv -f "$SAVED_MANIFEST" "$MANIFEST"; else rm -f "$MANIFEST"; fi
  if [ -f "$SAVED_MANAGER" ]; then mv -f "$SAVED_MANAGER" "$MANAGED_DIR/install.sh"; fi
  return 1
}

preflight_command_link() {
  mkdir -p "$BIN_DIR"
  if [ ! -w "$BIN_DIR" ]; then
    printf 'Command directory is not writable: %s\n' "$BIN_DIR" >&2
    return 1
  fi
  if [ -L "$COMMAND_LINK" ]; then
    EXISTING_TARGET="$(readlink "$COMMAND_LINK")"
    case "$EXISTING_TARGET" in
      "$CURRENT_LINK/bin/odysseus"|"$INSTALL_DIR"/*) ;;
      *)
        if [ ! -x "$EXISTING_TARGET" ] || ! "$EXISTING_TARGET" --version 2>/dev/null | grep -q '^Odysseus '; then
          printf 'Refusing to replace an unrelated command link: %s -> %s\n' "$COMMAND_LINK" "$EXISTING_TARGET" >&2
          return 1
        fi
        ;;
    esac
  elif [ -e "$COMMAND_LINK" ]; then
    printf 'Refusing to replace an existing file: %s\n' "$COMMAND_LINK" >&2
    return 1
  fi
}

validate_state_for_release() {
  RELEASE="$1"
  ARCHIVE="${2:-}"
  RELEASE_SCHEMA="$(release_schema "$RELEASE")"
  VALIDATION_DIR="$(mktemp -d "$MANAGED_DIR/.validation.XXXXXX")"
  if [ -n "$ARCHIVE" ]; then tar -xzf "$ARCHIVE" -C "$VALIDATION_DIR"; fi
  python3 - "$VALIDATION_DIR" "$RELEASE_SCHEMA" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
maximum = int(sys.argv[2])
for path in (root / "runs").glob("*.json"):
    value = json.loads(path.read_text(encoding="utf-8"))
    version = int(value.get("schema_version") or 0) if isinstance(value, dict) else maximum + 1
    if version > maximum:
        raise SystemExit(f"State uses run schema {version}, but target release supports {maximum}: {path}")
PY
  if "$RELEASE/bin/odysseus" state --help >/dev/null 2>&1; then
    if ! "$RELEASE/bin/odysseus" --state-dir "$VALIDATION_DIR" state verify --migrate --json >/dev/null; then
      printf 'Target release rejected the state snapshot: %s\n' "$RELEASE" >&2
      return 1
    fi
  else
    if ! "$RELEASE/bin/odysseus" --state-dir "$VALIDATION_DIR" doctor --json >/dev/null; then
      printf 'Target release rejected the state snapshot: %s\n' "$RELEASE" >&2
      return 1
    fi
  fi
  rm -rf "$VALIDATION_DIR"
  VALIDATION_DIR=''
}

if [ "$MODE" != 'check' ]; then preflight_command_link; fi

if [ "$MODE" = 'rollback' ]; then
  if [ ! -L "$CURRENT_LINK" ] || [ ! -L "$PREVIOUS_LINK" ]; then
    printf '%s\n' 'No managed previous Odysseus release is available.' >&2
    exit 1
  fi
  CURRENT_TARGET="$(readlink "$CURRENT_LINK")"
  ROLLBACK_TARGET="$(readlink "$PREVIOUS_LINK")"
  CURRENT_VERSION="$(release_version "$CURRENT_TARGET")"
  ROLLBACK_VERSION="$(release_version "$ROLLBACK_TARGET")"
  CURRENT_SCHEMA="$(release_schema "$CURRENT_TARGET")"
  ROLLBACK_SCHEMA="$(release_schema "$ROLLBACK_TARGET")"
  MATCHING_BACKUP="$(manifest_backup)"
  if [ "$ROLLBACK_SCHEMA" -lt "$CURRENT_SCHEMA" ] && [ "$RESTORE_STATE" -ne 1 ]; then
    printf 'Rollback %s -> %s crosses run schema %s -> %s. Re-run with --restore-state.\n' \
      "$CURRENT_VERSION" "$ROLLBACK_VERSION" "$CURRENT_SCHEMA" "$ROLLBACK_SCHEMA" >&2
    exit 1
  fi
  ROLLBACK_BACKUP="$(backup_state "$CURRENT_VERSION-before-rollback" "$CURRENT_TARGET")"
  if [ "$RESTORE_STATE" -eq 1 ]; then
    if [ -z "$MATCHING_BACKUP" ]; then printf '%s\n' 'No matching pre-update state backup is available.' >&2; exit 1; fi
    restore_state "$MATCHING_BACKUP" "$ROLLBACK_TARGET"
  else
    validate_state_for_release "$ROLLBACK_TARGET" "$ROLLBACK_BACKUP"
  fi
  REF="rollback:$ROLLBACK_VERSION"
  activate_release "$ROLLBACK_TARGET" "$CURRENT_TARGET" "$ROLLBACK_VERSION" \
    "$(git -C "$ROLLBACK_TARGET" rev-parse HEAD)" "$ROLLBACK_BACKUP"
  printf 'Rolled back Odysseus %s -> %s.\n' "$CURRENT_VERSION" "$ROLLBACK_VERSION"
  if [ "$RESTORE_STATE" -eq 1 ]; then printf 'Restored state: %s\n' "$MATCHING_BACKUP"; fi
  exit 0
fi

if [ -z "$REF" ]; then REF="$(resolve_latest_ref)"; CHANNEL='stable'; fi
if [ "$CHANNEL" = 'stable' ] && [[ "$REF" != v* ]]; then
  printf 'Stable installs require a v* release tag, got: %s\n' "$REF" >&2
  exit 1
fi

CURRENT_TARGET="$(current_target)"
CURRENT_VERSION=''
if [ -n "$CURRENT_TARGET" ] && [ -x "$CURRENT_TARGET/bin/odysseus" ]; then
  CURRENT_VERSION="$(release_version "$CURRENT_TARGET")"
fi

if [ "$MODE" = 'check' ]; then
  TARGET_VERSION="${REF#v}"
  TARGET_COMMIT_CHECK=''
  case "$REF" in
    ????????????????????????????????????????) TARGET_COMMIT_CHECK="$REF" ;;
    main) TARGET_COMMIT_CHECK="$(git ls-remote "$REPOSITORY" refs/heads/main | awk 'NR == 1 {print $1}')" ;;
    *) TARGET_COMMIT_CHECK="$(git ls-remote "$REPOSITORY" "$REF" "refs/tags/$REF^{}" | awk 'END {print $1}')" ;;
  esac
  CURRENT_COMMIT_CHECK=''
  if [ -n "$CURRENT_TARGET" ]; then CURRENT_COMMIT_CHECK="$(git -C "$CURRENT_TARGET" rev-parse HEAD)"; fi
  if { [ "$CHANNEL" = 'stable' ] && [ "$CURRENT_VERSION" = "$TARGET_VERSION" ]; } || \
     { [ -n "$TARGET_COMMIT_CHECK" ] && [ "$CURRENT_COMMIT_CHECK" = "$TARGET_COMMIT_CHECK" ]; }; then
    printf 'Odysseus %s is up to date on the stable channel.\n' "$CURRENT_VERSION"
    exit 0
  fi
  if [ -n "$CURRENT_VERSION" ]; then
    printf 'Update available: %s -> %s (%s).\n' "$CURRENT_VERSION" "$TARGET_VERSION" "$CHANNEL"
  else
    printf 'Odysseus is not managed here; available target: %s (%s).\n' "$TARGET_VERSION" "$CHANNEL"
  fi
  exit 0
fi

mkdir -p "$RELEASES_DIR" "$BACKUPS_DIR" "$BIN_DIR"
STAGE_DIR="$(mktemp -d "$MANAGED_DIR/.stage.XXXXXX")"
git init -q "$STAGE_DIR"
git -C "$STAGE_DIR" remote add origin "$REPOSITORY"
if [ "$CHANNEL" = 'stable' ]; then
  git -C "$STAGE_DIR" fetch --quiet --depth 1 origin "refs/tags/$REF"
else
  git -C "$STAGE_DIR" fetch --quiet --depth 1 origin "$REF"
fi
git -C "$STAGE_DIR" checkout --quiet --detach FETCH_HEAD
TARGET_COMMIT="$(git -C "$STAGE_DIR" rev-parse HEAD)"
TARGET_VERSION="$(release_version "$STAGE_DIR")"
TARGET_SCHEMA="$(release_schema "$STAGE_DIR")"
if [ "$CHANNEL" = 'stable' ] && [ "$TARGET_VERSION" != "${REF#v}" ]; then
  printf 'Release tag %s reports application version %s.\n' "$REF" "$TARGET_VERSION" >&2
  exit 1
fi
RELEASE_DIR="$RELEASES_DIR/$TARGET_VERSION-${TARGET_COMMIT%${TARGET_COMMIT#????????????}}"
if [ -d "$RELEASE_DIR" ]; then
  rm -rf "$STAGE_DIR"
  STAGE_DIR=''
else
  mv "$STAGE_DIR" "$RELEASE_DIR"
  STAGE_DIR=''
fi

if [ "$CURRENT_TARGET" = "$RELEASE_DIR" ]; then
  printf 'Odysseus %s is already installed (%s).\n' "$TARGET_VERSION" "$CHANNEL"
else
  STATE_BACKUP=''
  if [ -n "$CURRENT_TARGET" ]; then
    CURRENT_SCHEMA="$(release_schema "$CURRENT_TARGET")"
    if [ "$TARGET_SCHEMA" -lt "$CURRENT_SCHEMA" ]; then
      printf 'Update refuses schema downgrade %s -> %s (run schema %s -> %s). Use rollback --restore-state for a matching previous release.\n' \
        "$CURRENT_VERSION" "$TARGET_VERSION" "$CURRENT_SCHEMA" "$TARGET_SCHEMA" >&2
      exit 1
    fi
  fi
  STATE_BACKUP="$(backup_state "${CURRENT_VERSION:-unmanaged}-before-$TARGET_VERSION" "$CURRENT_TARGET")"
  validate_state_for_release "$RELEASE_DIR" "$STATE_BACKUP"
  activate_release "$RELEASE_DIR" "$CURRENT_TARGET" "$TARGET_VERSION" "$TARGET_COMMIT" "$STATE_BACKUP"
  printf 'Installed Odysseus %s from %s (%s).\n' "$TARGET_VERSION" "$REF" "$CHANNEL"
fi

COMMAND_SOURCE="$CURRENT_LINK/bin/odysseus"
ln -sfn "$COMMAND_SOURCE" "$COMMAND_LINK"

printf 'Command: %s\n' "$COMMAND_LINK"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) printf 'Add this directory to PATH: %s\n' "$BIN_DIR" ;; esac
if [ "$RUN_DOCTOR" -eq 1 ]; then "$COMMAND_LINK" doctor; else printf 'Next: %s doctor\n' "$COMMAND_LINK"; fi
printf 'Start: %s start --open\n' "$COMMAND_LINK"
