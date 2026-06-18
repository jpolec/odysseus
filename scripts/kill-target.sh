#!/usr/bin/env bash
# Kill only sessions managed by this plugin. Existing Codex panes are listed for
# navigation, but ctrl-x should not destroy a user's normal tmux pane.
set -uo pipefail

kind="${1:-}"
target="${2:-}"

case "$kind" in
session)
  [ -n "$target" ] && tmux kill-session -t "$target" 2>/dev/null
  ;;
pane)
  tmux display-message 'tmux-codex-session-manager: not killing existing Codex pane'
  ;;
esac
