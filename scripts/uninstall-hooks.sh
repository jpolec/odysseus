#!/usr/bin/env bash
# Remove Odysseus tmux hooks from a Codex hooks.json file.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${1:-${CODEX_HOOKS_FILE:-$HOME/.codex/hooks.json}}"

if ! command -v python3 >/dev/null 2>&1; then
  printf 'odysseus: python3 is required to merge hooks\n' >&2
  exit 1
fi

if [ ! -f "$target" ]; then
  printf 'odysseus: hooks file not found: %s\n' "$target" >&2
  exit 1
fi

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

try:
    data = json.loads(target.read_text())
except json.JSONDecodeError as exc:
    print(f"odysseus: invalid JSON in {target}: {exc}", file=sys.stderr)
    sys.exit(1)

plugin_commands = {
    hook.get("command")
    for entries in snippet.get("hooks", {}).values()
    for entry in entries
    for hook in entry.get("hooks", [])
    if isinstance(hook, dict)
}

hooks = data.get("hooks")
if not isinstance(hooks, dict):
    print(f"odysseus: no hooks object found in {target}")
    sys.exit(0)

removed = 0
for event in list(hooks.keys()):
    entries = hooks.get(event)
    if not isinstance(entries, list):
        continue
    kept_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            kept_entries.append(entry)
            continue
        hook_list = entry.get("hooks")
        if not isinstance(hook_list, list):
            kept_entries.append(entry)
            continue
        kept_hooks = []
        for hook in hook_list:
            if isinstance(hook, dict) and hook.get("command") in plugin_commands:
                removed += 1
            else:
                kept_hooks.append(hook)
        if kept_hooks:
            updated = dict(entry)
            updated["hooks"] = kept_hooks
            kept_entries.append(updated)
    if kept_entries:
        hooks[event] = kept_entries
    else:
        hooks.pop(event, None)

if removed == 0:
    print(f"odysseus: no matching hooks found in {target}")
    sys.exit(0)

stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
backup = target.with_name(f"{target.name}.bak-{stamp}")
shutil.copy2(target, backup)

tmp = target.with_name(f".{target.name}.tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
tmp.replace(target)

print(f"odysseus: hooks file: {target}")
print(f"odysseus: backup: {backup}")
print(f"odysseus: removed {removed}")
PY
