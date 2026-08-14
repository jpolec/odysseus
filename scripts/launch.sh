#!/usr/bin/env bash
# Launch (or re-attach to) an agent session for a directory, shown in a popup.
#
# Legacy args remain supported:
#   launch.sh <dir> [origin-window-id]
#
# Flag form:
#   launch.sh [launch] [--lane codex] [--role general] [--prompt-file file] [dir]
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

usage() {
  cat <<EOF
Usage:
  $0 [launch] [--lane LANE] [--role ROLE] [--prompt-file FILE] [--dry-run] [--] [DIR] [ORIGIN_WINDOW_ID]

Examples:
  $0 --lane codex
  $0 --lane claude --role docs
  $0 launch --lane codex --role security --prompt-file .agents/security-review.md
EOF
}

show_message() {
  local message="$1"
  if ! tmux display-message "$message" 2>/dev/null; then
    printf '%s\n' "$message" >&2
  fi
}

lane=''
role='general'
prompt_file=''
dry_run=0
args=()

[ "${1:-}" = 'launch' ] && shift

while [ "$#" -gt 0 ]; do
  case "$1" in
  --lane)
    if [ -z "${2:-}" ]; then
      usage >&2
      exit 2
    fi
    lane="$2"
    shift 2
    ;;
  --lane=*)
    lane="${1#--lane=}"
    shift
    ;;
  --role)
    if [ -z "${2:-}" ]; then
      usage >&2
      exit 2
    fi
    role="$2"
    shift 2
    ;;
  --role=*)
    role="${1#--role=}"
    shift
    ;;
  --prompt-file)
    if [ -z "${2:-}" ]; then
      usage >&2
      exit 2
    fi
    prompt_file="$2"
    shift 2
    ;;
  --prompt-file=*)
    prompt_file="${1#--prompt-file=}"
    shift
    ;;
  --dry-run)
    dry_run=1
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  --)
    shift
    while [ "$#" -gt 0 ]; do
      args+=("$1")
      shift
    done
    ;;
  -*)
    printf 'odysseus: unknown launch option: %s\n' "$1" >&2
    usage >&2
    exit 2
    ;;
  *)
    args+=("$1")
    shift
    ;;
  esac
done

path="${args[0]:-$PWD}"
window="${args[1]:-}"
lane="${lane:-$(ai_default_lane)}"

case "$lane" in
'' | *[!A-Za-z0-9_.-]*)
  show_message "odysseus: invalid lane: ${lane:-<empty>}"
  exit 0
  ;;
esac

case "$role" in
'' | *[!A-Za-z0-9_.-]*)
  show_message "odysseus: invalid role: ${role:-<empty>}"
  exit 0
  ;;
esac

if ! ai_lane_is_configured "$lane"; then
  show_message "odysseus: lane is not in @ai_session_lanes: $lane"
  exit 0
fi

cmd="$(ai_lane_command "$lane")"
env_spec="$(ai_lane_env "$lane")"
w="$(get_tmux_option @codex_popup_width '90%')"
h="$(get_tmux_option @codex_popup_height '90%')"

if [ ! -d "$path" ]; then
  show_message "odysseus: directory not found: $path"
  exit 0
fi

path="$(cd "$path" && pwd -P)" || exit 0
session="$(ai_session_name "$path" "$lane")"

prompt_file_path=''
if [ -n "$prompt_file" ]; then
  case "$prompt_file" in
  /*) prompt_file_path="$prompt_file" ;;
  *) prompt_file_path="$path/$prompt_file" ;;
  esac

  if [ ! -f "$prompt_file_path" ]; then
    show_message "odysseus: prompt file not found: $prompt_file"
    exit 0
  fi
  prompt_file_path="$(cd "$(dirname "$prompt_file_path")" && pwd -P)/$(basename "$prompt_file_path")"
fi

if [ "$dry_run" = 1 ]; then
  printf 'path=%s\n' "$path"
  printf 'lane=%s\n' "$lane"
  printf 'role=%s\n' "$role"
  printf 'session=%s\n' "$session"
  printf 'command=%s\n' "$cmd"
  printf 'env_configured=%s\n' "$([ -n "$env_spec" ] && printf yes || printf no)"
  printf 'prompt_file=%s\n' "$prompt_file"
  printf 'prompt_file_path=%s\n' "$prompt_file_path"
  exit 0
fi

current_session="$(tmux display-message -p '#S' 2>/dev/null || true)"
if [ -n "$current_session" ] && ai_is_managed_session "$current_session"; then
  tmux display-message 'Agent popup already open'
  exit 0
fi

if ! tmux has-session -t "$session" 2>/dev/null; then
  launch_cmd="$cmd"
  [ -n "$env_spec" ] && launch_cmd="$env_spec $cmd"
  if ! tmux new-session -d -s "$session" -c "$path" "$launch_cmd"; then
    show_message "odysseus: failed to create session: $session"
    exit 1
  fi

  initial_state='unknown'
  if [ "$lane" = 'codex' ]; then
    initial_state='idle'
    tmux set-option -t "$session" @codex_state idle >/dev/null
    tmux set-option -t "$session" @codex_state_at "$(date +%s)" >/dev/null
  fi
  tmux set-option -t "$session" @ai_session_state "$initial_state" >/dev/null
  tmux set-option -t "$session" @ai_session_state_at "$(date +%s)" >/dev/null
else
  initial_state="$(tmux show-options -qv -t "$session" @ai_session_state 2>/dev/null || true)"
  [ -n "$initial_state" ] || initial_state="$(tmux show-options -qv -t "$session" @codex_state 2>/dev/null || true)"
  [ -n "$initial_state" ] || initial_state='unknown'
fi

tmux set-option -t "$session" @ai_session_managed 1 >/dev/null
tmux set-option -t "$session" @ai_session_lane "$lane" >/dev/null
tmux set-option -t "$session" @ai_session_role "$role" >/dev/null
tmux set-option -t "$session" @ai_session_project_path "$path" >/dev/null
tmux set-option -t "$session" @ai_session_command "$cmd" >/dev/null
tmux set-option -t "$session" @ai_session_prompt_file "$prompt_file" >/dev/null
tmux set-option -t "$session" @ai_session_prompt_file_path "$prompt_file_path" >/dev/null

receipt_path="$(
  ai_write_receipt write \
    --receipts-dir "$(ai_receipts_dir)" \
    --session-id "$session" \
    --tmux-session "$session" \
    --project-path "$path" \
    --lane "$lane" \
    --role "$role" \
    --command "$cmd" \
    --prompt-file "$prompt_file" \
    --prompt-file-path "$prompt_file_path" \
    --status "$(ai_receipt_status "$initial_state")" 2>/dev/null || true
)"
[ -n "$receipt_path" ] && tmux set-option -t "$session" @ai_session_receipt "$receipt_path" >/dev/null

# Record which window launched it, so the picker can jump back here later.
[ -n "$window" ] && tmux set-option -t "$session" @codex_origin "$window" >/dev/null

if [ -n "$prompt_file" ]; then
  tmux display-message 'Prompt file recorded in metadata; automatic TUI injection is not enabled yet'
fi

tmux display-popup -w "$w" -h "$h" -E "tmux attach-session -t $(shell_quote "$session")"
