#!/usr/bin/env bash
# tmux-codex-session-manager
#
# List, monitor status, and jump across nested Codex CLI sessions from a
# single popup. tpm runs this file as an executable on tmux startup; it reads
# user options and installs the key bindings.

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/helpers.sh
. "$CURRENT_DIR/scripts/helpers.sh"

launch_key="$(get_tmux_option @codex_launch_key 'y')"
list_key="$(get_tmux_option @codex_list_key 'u')"

# Launch (or re-attach to) a Codex session for the current pane's directory.
# #{pane_current_path} / #{window_id} are expanded by run-shell before the args
# reach the script.
tmux bind-key "$launch_key" \
  run-shell "$CURRENT_DIR/scripts/launch.sh '#{pane_current_path}' '#{window_id}'"

# Open the session picker. When pressed from inside a session popup, list.sh
# closes that popup first so the picker opens full-size on the outer client.
tmux bind-key "$list_key" \
  run-shell "$CURRENT_DIR/scripts/list.sh '#{client_name}'"
