#!/usr/bin/env bash
# Merge tmux-codex-session-manager hooks into a Codex hooks.json file.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${1:-${CODEX_HOOKS_FILE:-$HOME/.codex/hooks.json}}"

if ! command -v python3 >/dev/null 2>&1; then
  printf 'tmux-codex-session-manager: python3 is required to merge hooks\n' >&2
  exit 1
fi

mkdir -p "$(dirname "$target")"

python3 - "$target" "$DIR/print-hooks.sh" <<'PY'
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path


target = Path(sys.argv[1]).expanduser()
print_hooks = Path(sys.argv[2])
snippet = json.loads(subprocess.check_output([str(print_hooks)], text=True))

if target.exists() and target.stat().st_size:
    try:
        data = json.loads(target.read_text())
    except json.JSONDecodeError as exc:
        print(f"tmux-codex-session-manager: invalid JSON in {target}: {exc}", file=sys.stderr)
        sys.exit(1)
else:
    data = {}

if not isinstance(data, dict):
    print(f"tmux-codex-session-manager: {target} must contain a JSON object", file=sys.stderr)
    sys.exit(1)

hooks = data.setdefault("hooks", {})
if not isinstance(hooks, dict):
    print(f"tmux-codex-session-manager: {target}.hooks must be a JSON object", file=sys.stderr)
    sys.exit(1)

added = 0
skipped = 0
for event, entries in snippet.get("hooks", {}).items():
    dest_entries = hooks.setdefault(event, [])
    if not isinstance(dest_entries, list):
        print(f"tmux-codex-session-manager: hooks.{event} must be an array", file=sys.stderr)
        sys.exit(1)

    existing_commands = {
        hook.get("command")
        for entry in dest_entries
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    }

    for entry in entries:
        new_hooks = []
        for hook in entry.get("hooks", []):
            command = hook.get("command")
            if command in existing_commands:
                skipped += 1
                continue
            new_hooks.append(hook)
            existing_commands.add(command)

        if new_hooks:
            merged = dict(entry)
            merged["hooks"] = new_hooks
            dest_entries.append(merged)
            added += len(new_hooks)

if target.exists():
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = target.with_name(f"{target.name}.bak-{stamp}")
    shutil.copy2(target, backup)
else:
    backup = None

tmp = target.with_name(f".{target.name}.tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
tmp.replace(target)

print(f"tmux-codex-session-manager: hooks file: {target}")
if backup:
    print(f"tmux-codex-session-manager: backup: {backup}")
print(f"tmux-codex-session-manager: added {added}, skipped {skipped}")
PY
