#!/usr/bin/env bash
# Record a Codex CLI session's state on its tmux session and pane, for the picker.
# Wire this into Codex hooks (see README): state.sh <working|waiting|idle>
#
# Codex hooks inherit the Codex process environment, so $TMUX_PANE is set
# whenever Codex runs inside tmux. Outside tmux this is a no-op.
set -uo pipefail

[ -z "${TMUX_PANE:-}" ] && exit 0

session="$(tmux display-message -p -t "$TMUX_PANE" '#{session_name}' 2>/dev/null)" || exit 0
[ -z "$session" ] && exit 0

case "${1:-idle}" in
working | waiting | idle) state="${1:-idle}" ;;
*) state='idle' ;;
esac

tmux set-option -t "$session" @codex_state "$state" >/dev/null
tmux set-option -t "$session" @codex_state_at "$(date +%s)" >/dev/null
tmux set-option -pt "$TMUX_PANE" @codex_state "$state" >/dev/null 2>&1 || true
tmux set-option -pt "$TMUX_PANE" @codex_state_at "$(date +%s)" >/dev/null 2>&1 || true
exit 0
