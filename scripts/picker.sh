#!/usr/bin/env bash
# Interactive picker for running agent sessions.
#
#   picker.sh           fzf picker; on enter, switches the parent client to the
#                       chosen session's origin window and resumes it in popup.
#   picker.sh --list    print the rows only (used by fzf's ctrl-x reload).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

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

metadata_for_path() {
  local path="$1" lane="$2"
  if [ "$lane" != 'codex' ]; then
    printf '\t-\t-\t-\t\n'
    return 0
  fi
  "$DIR/session-meta.py" --path "$path" 2>/dev/null || printf '\t-\t-\t-\t\n'
}

state_label_rank() {
  case "$1" in
  waiting) printf '0\t\033[33mWAIT\033[0m' ;;
  idle) printf '1\t\033[32mIDLE\033[0m' ;;
  working) printf '3\t\033[31mWORK\033[0m' ;;
  dead) printf '4\t\033[90mDEAD\033[0m' ;;
  *) printf '2\t\033[90m????\033[0m' ;;
  esac
}

age_from_epoch() {
  local at="$1" now="$2"
  if [[ "$at" =~ ^[0-9]+$ ]]; then
    printf '%sm' "$(((now - at) / 60))"
  else
    printf '%s' '-'
  fi
}

emit_rows() {
  local now s state at path label rank ago pane pane_pid session window pane_index locator
  local meta meta_state meta_age meta_ctx meta_title meta_file display_path source
  local label_rank lane
  now="$(date +%s)"
  tmux list-sessions -F '#{session_name}' 2>/dev/null | while IFS= read -r s; do
    ai_is_managed_session "$s" || continue

    lane="$(ai_session_lane "$s")"
    state="$(tmux show-options -qv -t "$s" @ai_session_state 2>/dev/null || true)"
    [ -n "$state" ] || state="$(tmux show-options -qv -t "$s" @codex_state 2>/dev/null || true)"
    at="$(tmux show-options -qv -t "$s" @ai_session_state_at 2>/dev/null || true)"
    [ -n "$at" ] || at="$(tmux show-options -qv -t "$s" @codex_state_at 2>/dev/null || true)"
    path="$(tmux show-options -qv -t "$s" @ai_session_project_path 2>/dev/null || true)"
    [ -n "$path" ] || path="$(tmux display-message -p -t "$s" '#{pane_current_path}' 2>/dev/null || true)"
    meta="$(metadata_for_path "$path" "$lane")"
    IFS=$'\t' read -r meta_state meta_age meta_ctx meta_title meta_file <<<"$meta"
    state="$(ai_detect_status "$s" "$lane" "$state" "$meta_state")"

    label_rank="$(state_label_rank "$state")"
    IFS=$'\t' read -r rank label <<<"$label_rank"

    ago="$(age_from_epoch "$at" "$now")"
    [ "$ago" = '-' ] && ago="${meta_age:--}"
    meta_ctx="${meta_ctx:--}"
    meta_title="${meta_title:--}"
    display_path="${path/#$HOME/~}"
    [ -n "$display_path" ] || display_path='-'
    source=$'\033[35mMGR\033[0m'

    printf '%s\tsession\t%s\t%s\t%s\t%-7s\t%s\t%5s\t%4s\t%s\t%s\t%s\n' \
      "$rank" "$s" "$s" "$label" "$lane" "$source" "$ago" "$meta_ctx" "$display_path" "$meta_title" "$s"
  done

  case "$include_existing" in
  off | false | no | 0) return 0 ;;
  esac

  tmux list-panes -a -F '#{pane_id}	#{pane_pid}	#{session_name}	#{window_index}	#{pane_index}	#{pane_current_path}' 2>/dev/null |
    while IFS=$'\t' read -r pane pane_pid session window pane_index path; do
      ai_is_managed_session "$session" && continue

      if pane_has_codex "$pane_pid"; then
        lane='codex'
        state="$(tmux show-options -pqv -t "$pane" @ai_session_state 2>/dev/null || true)"
        [ -n "$state" ] || state="$(tmux show-options -pqv -t "$pane" @codex_state 2>/dev/null || true)"
        at="$(tmux show-options -pqv -t "$pane" @ai_session_state_at 2>/dev/null || true)"
        [ -n "$at" ] || at="$(tmux show-options -pqv -t "$pane" @codex_state_at 2>/dev/null || true)"
        meta="$(metadata_for_path "$path" "$lane")"
        IFS=$'\t' read -r meta_state meta_age meta_ctx meta_title meta_file <<<"$meta"
        state="$(ai_detect_status "$pane" "$lane" "$state" "$meta_state")"
        label_rank="$(state_label_rank "$state")"
        IFS=$'\t' read -r rank label <<<"$label_rank"
        ago="$(age_from_epoch "$at" "$now")"
        [ "$ago" = '-' ] && ago="${meta_age:--}"
        meta_ctx="${meta_ctx:--}"
        meta_title="${meta_title:--}"
        display_path="${path/#$HOME/~}"
        [ -n "$display_path" ] || display_path='-'
        locator="${session}:${window}.${pane_index}"
        source=$'\033[36mPANE\033[0m'
        printf '%s\tpane\t%s\t%s\t%s\t%-7s\t%s\t%5s\t%4s\t%s\t%s\t%s\n' \
          "$rank" "$pane" "$pane" "$label" "$lane" "$source" "$ago" "$meta_ctx" "$display_path" "$meta_title" "$locator"
      fi
    done
}

[ "${1:-}" = '--list' ] && {
  emit_rows
  exit 0
}

if ! command -v fzf >/dev/null 2>&1; then
  tmux display-message "odysseus: fzf is required for the picker"
  exit 0
fi

rows="$(emit_rows)"
if [ -z "$rows" ]; then
  tmux display-message 'odysseus: no agent sessions'
  exit 0
fi

self="${BASH_SOURCE[0]}"
self_quoted="$(shell_quote "$self")"
kill_target_quoted="$(shell_quote "$DIR/kill-target.sh")"
export FZF_DEFAULT_OPTS=''
sel=$(printf '%s\n' "$rows" | sort -t$'\t' -k1,1n -k10,10 -k12,12 | fzf --ansi --delimiter='\t' --with-nth=5,6,7,8,9,10,11,12 \
  --reverse --cycle --header='Agent sessions - enter: jump - ctrl-x: kill managed - columns: state lane kind age ctx path title target' \
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
