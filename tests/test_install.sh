#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT INT TERM

"$REPOSITORY_ROOT/install.sh" --bin-dir "$TEMP_ROOT/bin" --no-doctor >/dev/null
test -L "$TEMP_ROOT/bin/odysseus"
test "$(readlink "$TEMP_ROOT/bin/odysseus")" = "$REPOSITORY_ROOT/bin/odysseus"
EXPECTED_VERSION="$(python3 -c 'from odysseus import __version__; print(__version__)')"
"$TEMP_ROOT/bin/odysseus" --version | grep -q "Odysseus $EXPECTED_VERSION"

REMOTE_INSTALL="$TEMP_ROOT/remote-install"
REMOTE_BIN="$TEMP_ROOT/remote-bin"
CURRENT_REF="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
ODYSSEUS_INSTALL_REPOSITORY="$REPOSITORY_ROOT" ODYSSEUS_INSTALL_REF="$CURRENT_REF" \
  bash -s -- --install-dir "$REMOTE_INSTALL" --bin-dir "$REMOTE_BIN" --no-doctor < "$REPOSITORY_ROOT/install.sh" >/dev/null
test -d "$REMOTE_INSTALL/.git"
test "$(readlink "$REMOTE_BIN/odysseus")" = "$REMOTE_INSTALL/bin/odysseus"
test "$(git -C "$REMOTE_INSTALL" rev-parse HEAD)" = "$(git -C "$REPOSITORY_ROOT" rev-parse "$CURRENT_REF^{commit}")"
