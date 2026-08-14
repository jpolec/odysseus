#!/usr/bin/env bash
# Shared helpers for Odysseus tmux integration.

HELPERS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# get_tmux_option <option-name> <default>
# Echoes the global tmux option value, or the default when unset/empty.
get_tmux_option() {
  local value
  value="$(tmux show-option -gqv "$1" 2>/dev/null)"
  if [ -n "$value" ]; then
    printf '%s' "$value"
  else
    printf '%s' "$2"
  fi
}

# session_hash <string>
# Short, stable, portable 8-char hash for deriving a session name from a path.
session_hash() {
  local out
  if command -v md5sum >/dev/null 2>&1; then
    out="$(printf '%s\n' "$1" | md5sum)"
  elif command -v md5 >/dev/null 2>&1; then
    out="$(printf '%s\n' "$1" | md5 -q)"
  else
    out="$(printf '%s\n' "$1" | shasum)"
  fi
  printf '%s' "${out%% *}" | cut -c1-8
}

# shell_quote <string>
# Single-quote a value for use inside a tmux shell-command string.
shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# ai_default_lane
# Backend/runner used when no lane is explicitly requested.
ai_default_lane() {
  get_tmux_option @ai_session_default_lane 'codex'
}

# ai_configured_lanes
ai_configured_lanes() {
  get_tmux_option @ai_session_lanes ''
}

# ai_lane_is_configured <lane>
# Empty @ai_session_lanes means any lane name is accepted.
ai_lane_is_configured() {
  local wanted="$1" lane lanes
  lanes="$(ai_configured_lanes)"
  [ -z "$lanes" ] && return 0

  for lane in $lanes; do
    [ "$lane" = "$wanted" ] && return 0
  done
  return 1
}

# ai_lane_command <lane>
# Command used to start a lane. The old @codex_command option remains the
# compatibility source for the codex lane when the new lane option is unset.
ai_lane_command() {
  local lane="$1" value
  value="$(get_tmux_option "@ai_session_lane_${lane}_command" '')"
  if [ -n "$value" ]; then
    printf '%s' "$value"
    return 0
  fi

  if [ "$lane" = 'codex' ]; then
    get_tmux_option @codex_command 'codex'
  else
    printf '%s' "$lane"
  fi
}

# ai_lane_env <lane>
# Optional shell-style environment prefix for a lane. Values are intentionally
# kept out of receipts because they can contain secrets.
ai_lane_env() {
  get_tmux_option "@ai_session_lane_${1}_env" ''
}

# ai_receipts_dir
ai_receipts_dir() {
  get_tmux_option @ai_session_receipts_dir "$HOME/.tmux-ai-sessions/receipts"
}

# ai_session_name <project-path> <lane>
# Codex keeps the historical codex-<hash> name. Other lanes get a compact
# lane-qualified name so one project can have separate runner sessions.
ai_session_name() {
  local path="$1" lane="$2" prefix
  if [ "$lane" = 'codex' ]; then
    prefix="$(get_tmux_option @codex_session_prefix 'codex-')"
    printf '%s%s' "$prefix" "$(session_hash "$path")"
    return 0
  fi

  prefix="$(get_tmux_option @ai_session_prefix 'ai-')"
  printf '%s%s-%s' "$prefix" "$lane" "$(session_hash "$path")"
}

# ai_is_managed_session <tmux-session-name>
ai_is_managed_session() {
  local session="$1" managed prefix
  managed="$(tmux show-options -qv -t "$session" @ai_session_managed 2>/dev/null || true)"
  [ "$managed" = '1' ] && return 0

  # Legacy sessions created before the generic agent metadata existed.
  prefix="$(get_tmux_option @codex_session_prefix 'codex-')"
  case "$session" in
  "$prefix"*) return 0 ;;
  esac

  return 1
}

# ai_session_lane <tmux-session-name>
ai_session_lane() {
  local session="$1" lane prefix
  lane="$(tmux show-options -qv -t "$session" @ai_session_lane 2>/dev/null || true)"
  if [ -n "$lane" ]; then
    printf '%s' "$lane"
    return 0
  fi

  prefix="$(get_tmux_option @codex_session_prefix 'codex-')"
  case "$session" in
  "$prefix"*) printf '%s' 'codex' ;;
  *) printf '%s' "$(ai_default_lane)" ;;
  esac
}

# ai_receipt_status <state>
ai_receipt_status() {
  case "$1" in
  working) printf '%s' 'WORK' ;;
  waiting) printf '%s' 'WAIT' ;;
  idle) printf '%s' 'IDLE' ;;
  dead) printf '%s' 'DEAD' ;;
  *) printf '%s' 'UNKNOWN' ;;
  esac
}

# ai_detect_status <session-or-pane> <lane> <explicit-state> <metadata-state>
# Codex keeps the hook/JSONL behavior. Other lanes stay conservative: if the
# pane process exists, the status is unknown rather than guessed as working.
ai_detect_status() {
  local target="$1" lane="$2" explicit="${3:-}" metadata="${4:-}" pane_pid

  case "$explicit" in
  working | waiting | idle | dead)
    printf '%s' "$explicit"
    return 0
    ;;
  esac

  if [ "$lane" = 'codex' ]; then
    case "$metadata" in
    working | waiting | idle | dead)
      printf '%s' "$metadata"
      return 0
      ;;
    esac
  fi

  pane_pid="$(tmux display-message -p -t "$target" '#{pane_pid}' 2>/dev/null || true)"
  if [ -n "$pane_pid" ] && ps -p "$pane_pid" >/dev/null 2>&1; then
    printf '%s' 'unknown'
  else
    printf '%s' 'idle'
  fi
}

# ai_write_receipt <args...>
ai_write_receipt() {
  command -v python3 >/dev/null 2>&1 || return 0
  [ -f "$HELPERS_DIR/receipt.py" ] || return 0
  python3 "$HELPERS_DIR/receipt.py" "$@"
}
