#!/usr/bin/env bash
# Odysseus tmux integration
#
# List, monitor status, and jump across managed AI agent sessions from a
# single popup. Codex remains the default lane and compatibility path. tpm runs
# this file as an executable on tmux startup; it reads user options and installs
# the key bindings.

CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/helpers.sh
. "$CURRENT_DIR/scripts/helpers.sh"

launch_key="$(get_tmux_option @codex_launch_key 'y')"
list_key="$(get_tmux_option @codex_list_key 'u')"
web_key="$(get_tmux_option @odysseus_web_key 'O')"

# Launch (or re-attach to) the default-lane session for the current pane's
# directory.
# #{pane_current_path} / #{window_id} are expanded by run-shell before the args
# reach the script.
tmux bind-key "$launch_key" \
  run-shell "$CURRENT_DIR/scripts/launch.sh '#{pane_current_path}' '#{window_id}'"

# Open the session picker. When pressed from inside a session popup, list.sh
# closes that popup first so the picker opens full-size on the outer client.
tmux bind-key "$list_key" \
  run-shell "$CURRENT_DIR/scripts/list.sh '#{client_name}'"

# Start the durable scheduler and open the local Odysseus web control plane.
tmux bind-key "$web_key" \
  run-shell "$CURRENT_DIR/scripts/web.sh"
