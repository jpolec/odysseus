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
include_existing="$(get_tmux_option @codex_include_existing_panes 'on')"

pane_has_codex() {
  local root="$1"
  [ -n "$root" ] || return 1

  ps -axo pid=,ppid=,command= 2>/dev/null |
    awk -v root="$root" '
      {
        pid = $1
        ppid = $2
        $1 = ""
        $2 = ""
        sub(/^[[:space:]]+/, "", $0)
        parent[pid] = ppid
        cmd[pid] = $0
      }
      END {
        for (pid in parent) {
          is_codex = (cmd[pid] ~ /(^|[[:space:]\/])codex([[:space:]]|$)/ || cmd[pid] ~ /@openai\/codex/ || cmd[pid] ~ /codex-[^[:space:]]*\/bin\/codex/)
          if (is_codex) {
            cur = pid
            while (cur in parent) {
              if (cur == root) {
                exit 0
              }
              cur = parent[cur]
            }
          }
        }
        exit 1
      }
    '
}

emit_rows() {
  local now s state at path label rank ago pane pane_pid session window pane_index locator
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

    printf '%s\tsession\t%s\t%s\t%s\t%5s\t%s\t%s\n' \
      "$rank" "$s" "$s" "$label" "$ago" "${path/#$HOME/~}" "$s"
  done

  case "$include_existing" in
  off | false | no | 0) return 0 ;;
  esac

  tmux list-panes -a -F '#{pane_id}	#{pane_pid}	#{session_name}	#{window_index}	#{pane_index}	#{pane_current_path}' 2>/dev/null |
    while IFS=$'\t' read -r pane pane_pid session window pane_index path; do
      case "$session" in
      "$prefix"*) continue ;;
      esac

      if pane_has_codex "$pane_pid"; then
        locator="${session}:${window}.${pane_index}"
        printf '2\tpane\t%s\t%s\t%s\t%5s\t%s\t%s\n' \
          "$pane" "$pane" $'\033[36mPANE\033[0m' '-' "${path/#$HOME/~}" "$locator"
      fi
    done
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
kill_target_quoted="$(shell_quote "$DIR/kill-target.sh")"
export FZF_DEFAULT_OPTS=''
sel=$(printf '%s\n' "$rows" | sort -t$'\t' -k1,1n -k6,6n | fzf --ansi --delimiter='\t' --with-nth=5,6,7,8 \
  --reverse --cycle --header='Codex sessions - enter: jump - ctrl-x: kill' \
  --preview='tmux capture-pane -ept {4}' --preview-window='right,62%,wrap' \
  --bind="ctrl-x:execute-silent($kill_target_quoted {2} {3})+reload($self_quoted --list)")

[ -z "$sel" ] && exit 0
kind="$(printf '%s' "$sel" | cut -f2)"
target="$(printf '%s' "$sel" | cut -f3)"

parent="$(tmux show-options -gqv @codex_parent 2>/dev/null || true)"

case "$kind" in
session)
  # Move the underlying parent client to the session's origin window, then
  # resume the session in this popup over it. Falls back to the current window.
  origin="$(tmux show-options -qv -t "$target" @codex_origin 2>/dev/null || true)"
  [ -n "$origin" ] && [ -n "$parent" ] &&
    tmux switch-client -c "$parent" -t "$origin" 2>/dev/null

  tmux attach-session -t "$target"
  ;;
pane)
  pane_session="$(tmux display-message -p -t "$target" '#{session_name}' 2>/dev/null || true)"
  pane_window="$(tmux display-message -p -t "$target" '#{window_id}' 2>/dev/null || true)"
  [ -n "$pane_window" ] && tmux select-window -t "$pane_window" 2>/dev/null
  tmux select-pane -t "$target" 2>/dev/null
  if [ -n "$parent" ] && [ -n "$pane_session" ]; then
    tmux switch-client -c "$parent" -t "$pane_session" 2>/dev/null
  fi
  ;;
esac
