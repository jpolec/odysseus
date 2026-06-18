#!/usr/bin/env bash
# Interactive picker for running Codex sessions.
#
#   picker.sh           fzf picker; on enter, switches the parent client to the
#                       chosen session's origin window and resumes it in popup.
#   picker.sh --list    print the rows only (used by fzf's ctrl-x reload).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

prefix="$(get_tmux_option @codex_session_prefix 'codex-')"

emit_rows() {
  local now s state at path label rank ago
  now="$(date +%s)"
  tmux list-sessions -F '#{session_name}' 2>/dev/null | while IFS= read -r s; do
    case "$s" in
    "$prefix"*) ;;
    *) continue ;;
    esac

    state="$(tmux show-options -qv -t "$s" @codex_state 2>/dev/null || true)"
    at="$(tmux show-options -qv -t "$s" @codex_state_at 2>/dev/null || true)"
    path="$(tmux display-message -p -t "$s" '#{pane_current_path}' 2>/dev/null || true)"

    case "$state" in
    waiting) label=$'\033[33mWAIT\033[0m' rank=0 ;;
    idle) label=$'\033[32mIDLE\033[0m' rank=1 ;;
    working) label=$'\033[31mWORK\033[0m' rank=3 ;;
    *) label=$'\033[90m????\033[0m' rank=2 ;;
    esac

    if [[ "$at" =~ ^[0-9]+$ ]]; then
      ago="$(((now - at) / 60))m"
    else
      ago='-'
    fi

    printf '%s\t%s\t%s\t%5s\t%s\n' \
      "$rank" "$s" "$label" "$ago" "${path/#$HOME/~}"
  done | sort -t$'\t' -k1,1n -k4,4n
}

[ "${1:-}" = '--list' ] && {
  emit_rows
  exit 0
}

if ! command -v fzf >/dev/null 2>&1; then
  tmux display-message "tmux-codex-session-manager: fzf is required for the picker"
  exit 0
fi

rows="$(emit_rows)"
if [ -z "$rows" ]; then
  tmux display-message 'tmux-codex-session-manager: no Codex sessions'
  exit 0
fi

self="${BASH_SOURCE[0]}"
self_quoted="$(shell_quote "$self")"
export FZF_DEFAULT_OPTS=''
sel=$(printf '%s\n' "$rows" | fzf --ansi --delimiter='\t' --with-nth=3,4,5 \
  --reverse --cycle --header='Codex sessions - enter: jump - ctrl-x: kill' \
  --preview='tmux capture-pane -ept {2}' --preview-window='right,62%,wrap' \
  --bind="ctrl-x:execute-silent(tmux kill-session -t {2})+reload($self_quoted --list)")

[ -z "$sel" ] && exit 0
target="$(printf '%s' "$sel" | cut -f2)"

# Move the underlying parent client to the session's origin window, then resume
# the session in this popup over it. Falls back to the current window.
origin="$(tmux show-options -qv -t "$target" @codex_origin 2>/dev/null || true)"
parent="$(tmux show-options -gqv @codex_parent 2>/dev/null || true)"
[ -n "$origin" ] && [ -n "$parent" ] &&
  tmux switch-client -c "$parent" -t "$origin" 2>/dev/null

tmux attach-session -t "$target"
