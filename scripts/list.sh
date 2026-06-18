#!/usr/bin/env bash
# Open the Codex session picker in a popup.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

client="${1:-}"
prefix="$(get_tmux_option @codex_session_prefix 'codex-')"
w="$(get_tmux_option @codex_popup_width '90%')"
h="$(get_tmux_option @codex_popup_height '90%')"

# The session of a client attached to a prefixed session, i.e. the popup we are
# inside, if any. Empty when invoked from a normal non-popup pane.
nested_session() {
  tmux list-clients -F '#{client_name} #{session_name}' 2>/dev/null |
    awk -v p="$prefix" 'index($2, p) == 1 { print $2; exit }'
}

# A client NOT attached to a prefixed session, preferring the invoking client.
host_client() {
  local found
  if [ -n "$client" ]; then
    found="$(
      tmux list-clients -F '#{client_name} #{session_name}' 2>/dev/null |
        awk -v c="$client" -v p="$prefix" '$1 == c && index($2, p) != 1 { print $1; exit }'
    )"
    if [ -n "$found" ]; then
      printf '%s\n' "$found"
      return 0
    fi
  fi
  tmux list-clients -F '#{client_name} #{session_name}' 2>/dev/null |
    awk -v p="$prefix" 'index($2, p) != 1 { print $1; exit }'
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
