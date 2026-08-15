#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT INT TERM

"$REPOSITORY_ROOT/install.sh" --bin-dir "$TEMP_ROOT/bin" --state-dir "$TEMP_ROOT/state" --no-doctor >/dev/null
test -L "$TEMP_ROOT/bin/odysseus"
test "$(readlink "$TEMP_ROOT/bin/odysseus")" = "$REPOSITORY_ROOT/bin/odysseus"
EXPECTED_VERSION="$(python3 -c 'from odysseus import __version__; print(__version__)')"
"$TEMP_ROOT/bin/odysseus" --version | grep -q "Odysseus $EXPECTED_VERSION"

REMOTE_INSTALL="$TEMP_ROOT/remote-install"
REMOTE_BIN="$TEMP_ROOT/remote-bin"
REMOTE_INSTALL_RESOLVED="$(python3 -c 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).resolve())' "$REMOTE_INSTALL")"
CURRENT_REF="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
ODYSSEUS_INSTALL_REPOSITORY="$REPOSITORY_ROOT" \
  bash -s -- --ref "$CURRENT_REF" --install-dir "$REMOTE_INSTALL" --bin-dir "$REMOTE_BIN" \
  --state-dir "$TEMP_ROOT/remote-state" --no-doctor < "$REPOSITORY_ROOT/install.sh" >/dev/null
test -L "$REMOTE_INSTALL/managed/current"
test -d "$REMOTE_INSTALL/managed/current/.git"
test -f "$REMOTE_INSTALL/managed/install.json"
test "$(readlink "$REMOTE_BIN/odysseus")" = "$REMOTE_INSTALL_RESOLVED/managed/current/bin/odysseus"
test "$(git -C "$REMOTE_INSTALL/managed/current" rev-parse HEAD)" = "$(git -C "$REPOSITORY_ROOT" rev-parse "$CURRENT_REF^{commit}")"
