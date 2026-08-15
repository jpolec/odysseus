#!/usr/bin/env bash
# Run and measure Odysseus work using Odysseus itself.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_DIR="${ODYSSEUS_DOGFOOD_STATE:-${ODYSSEUS_HOME:-$HOME/.odysseus}}"
VERSION="$(cd "$REPOSITORY_ROOT" && python3 -c 'from odysseus import __version__; print(__version__)')"
COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
  start)
    exec "$REPOSITORY_ROOT/bin/odysseus" --state-dir "$STATE_DIR" start --open "$@"
    ;;
  run)
    if [ "$#" -eq 0 ]; then
      printf '%s\n' 'Usage: scripts/dogfood.sh run "finished outcome"' >&2
      exit 2
    fi
    exec "$REPOSITORY_ROOT/bin/odysseus" --state-dir "$STATE_DIR" run \
      --project "$REPOSITORY_ROOT" --release "$VERSION" "$*"
    ;;
  proof)
    mkdir -p "$REPOSITORY_ROOT/proofs"
    "$REPOSITORY_ROOT/bin/odysseus" --state-dir "$STATE_DIR" proof \
      --release "$VERSION" --json --output "$REPOSITORY_ROOT/proofs/v$VERSION.json"
    "$REPOSITORY_ROOT/bin/odysseus" --state-dir "$STATE_DIR" proof \
      --release "$VERSION" --output "$REPOSITORY_ROOT/proofs/v$VERSION.md"
    printf 'Wrote public summary proofs/v%s.md and local ignored JSON proofs/v%s.json\n' "$VERSION" "$VERSION"
    ;;
  status)
    "$REPOSITORY_ROOT/bin/odysseus" --state-dir "$STATE_DIR" stats
    "$REPOSITORY_ROOT/bin/odysseus" --state-dir "$STATE_DIR" proof --release "$VERSION"
    ;;
  *)
    cat <<'EOF'
Usage: scripts/dogfood.sh COMMAND

  start                 open Odysseus on its normal durable state
  run "finished outcome" queue work on the Odysseus repository itself
  status                show all-state stats and observed current-release proof
  proof                 write a public Markdown summary and ignored local JSON receipt

Set ODYSSEUS_DOGFOOD_STATE to use a state directory other than ~/.odysseus.
EOF
    ;;
esac
