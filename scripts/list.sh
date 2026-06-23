#!/usr/bin/env bash
# Open the agent session picker in a popup.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

client="${1:-}"
w="$(get_tmux_option @codex_popup_width '90%')"
h="$(get_tmux_option @codex_popup_height '90%')"

# The session of a client attached to a managed session, i.e. the popup we are
# inside, if any. Empty when invoked from a normal non-popup pane.
nested_session() {
  local _client session
  tmux list-clients -F '#{client_name} #{session_name}' 2>/dev/null |
    while IFS=' ' read -r _client session; do
      if ai_is_managed_session "$session"; then
        printf '%s\n' "$session"
        return 0
      fi
    done
}

# A client NOT attached to a managed session, preferring the invoking client.
host_client() {
  local found candidate candidate_session
  if [ -n "$client" ]; then
    found=''
    while IFS=' ' read -r candidate candidate_session; do
      if [ "$candidate" = "$client" ] && ! ai_is_managed_session "$candidate_session"; then
        found="$candidate"
        break
      fi
    done <<EOF
$(tmux list-clients -F '#{client_name} #{session_name}' 2>/dev/null)
EOF
    if [ -n "$found" ]; then
      printf '%s\n' "$found"
      return 0
    fi
  fi

  while IFS=' ' read -r candidate candidate_session; do
    if ! ai_is_managed_session "$candidate_session"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done <<EOF
$(tmux list-clients -F '#{client_name} #{session_name}' 2>/dev/null)
EOF
}

# If we are inside a session popup, close it by detaching its client.
sess="$(nested_session)"
if [ -n "$sess" ]; then
  tmux detach-client -s "$sess"
  for _ in $(seq 1 100); do
    [ -z "$(nested_session)" ] && break
    sleep 0.05
  done
fi

host="$(host_client)"
tmux set-option -g @codex_parent "$host" >/dev/null

# Host the picker on the outer client. -c is honored because that client has no
# popup open now; fall back to the default client if none was found.
if [ -n "$host" ]; then
  tmux display-popup -c "$host" -w "$w" -h "$h" -E "$(shell_quote "$DIR/picker.sh")"
else
  tmux display-popup -w "$w" -h "$h" -E "$(shell_quote "$DIR/picker.sh")"
fi
