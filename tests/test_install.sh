#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT INT TERM

"$REPOSITORY_ROOT/install.sh" --bin-dir "$TEMP_ROOT/bin" --no-doctor >/dev/null
test -L "$TEMP_ROOT/bin/odysseus"
test "$(readlink "$TEMP_ROOT/bin/odysseus")" = "$REPOSITORY_ROOT/bin/odysseus"
"$TEMP_ROOT/bin/odysseus" --version | grep -q 'Odysseus 0.6.0'

REMOTE_INSTALL="$TEMP_ROOT/remote-install"
REMOTE_BIN="$TEMP_ROOT/remote-bin"
CURRENT_REF="$(git -C "$REPOSITORY_ROOT" branch --show-current)"
ODYSSEUS_INSTALL_REPOSITORY="$REPOSITORY_ROOT" ODYSSEUS_INSTALL_REF="$CURRENT_REF" \
  bash -s -- --install-dir "$REMOTE_INSTALL" --bin-dir "$REMOTE_BIN" --no-doctor < "$REPOSITORY_ROOT/install.sh" >/dev/null
test -d "$REMOTE_INSTALL/.git"
test "$(readlink "$REMOTE_BIN/odysseus")" = "$REMOTE_INSTALL/bin/odysseus"
