#!/usr/bin/env bash
# Launch (or re-attach to) a Codex session for a directory, shown in a popup.
# Args: <dir> [origin-window-id]   (both expanded by run-shell in the binding)
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

path="${1:-$PWD}"
window="${2:-}"

prefix="$(get_tmux_option @codex_session_prefix 'codex-')"
cmd="$(get_tmux_option @codex_command 'codex')"
w="$(get_tmux_option @codex_popup_width '90%')"
h="$(get_tmux_option @codex_popup_height '90%')"

if [ ! -d "$path" ]; then
  tmux display-message "tmux-codex-session-manager: directory not found: $path"
  exit 0
fi

path="$(cd "$path" && pwd -P)" || exit 0
session="${prefix}$(session_hash "$path")"

current_session="$(tmux display-message -p '#S' 2>/dev/null || true)"
case "$current_session" in
"$prefix"*)
  tmux display-message 'Codex popup already open'
  exit 0
  ;;
esac

if ! tmux has-session -t "$session" 2>/dev/null; then
  tmux new-session -d -s "$session" -c "$path" "$cmd"
  tmux set-option -t "$session" @codex_state idle >/dev/null
  tmux set-option -t "$session" @codex_state_at "$(date +%s)" >/dev/null
fi

# Record which window launched it, so the picker can jump back here later.
[ -n "$window" ] && tmux set-option -t "$session" @codex_origin "$window" >/dev/null

tmux display-popup -w "$w" -h "$h" -E "tmux attach-session -t $(shell_quote "$session")"
