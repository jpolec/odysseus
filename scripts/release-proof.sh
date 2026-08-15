#!/usr/bin/env bash
# Reproduce the local proof gate used before an Odysseus release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROOF_STATE="$(mktemp -d)"
trap 'rm -rf "$PROOF_STATE"' EXIT INT TERM

cd "$REPOSITORY_ROOT"
printf '%s\n' '[1/4] Static and shell checks'
node --check web/app.js
python3 -m py_compile odysseus/*.py scripts/demo.py
bash -n install.sh scripts/*.sh tests/test_install.sh

printf '%s\n' '[2/4] Checkout and piped installer smoke tests'
./tests/test_install.sh

printf '%s\n' '[3/4] Complete automated suite'
python3 -m unittest discover -s tests -v

printf '%s\n' '[4/4] Reproducible Odysseus-on-Odysseus product state'
scripts/demo.py --state-dir "$PROOF_STATE" --project "$REPOSITORY_ROOT" >/dev/null
bin/odysseus --state-dir "$PROOF_STATE" runs --json >/dev/null
bin/odysseus --state-dir "$PROOF_STATE" stats >/dev/null

printf '%s\n' 'Odysseus release proof passed.'
