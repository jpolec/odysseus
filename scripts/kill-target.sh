#!/usr/bin/env bash
# Kill only sessions managed by this plugin. Existing Codex panes are listed for
# navigation, but ctrl-x should not destroy a user's normal tmux pane.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

kind="${1:-}"
target="${2:-}"

case "$kind" in
session)
  if [ -n "$target" ] && ai_is_managed_session "$target"; then
    ai_write_receipt update-status \
      --receipts-dir "$(ai_receipts_dir)" \
      --tmux-session "$target" \
      --status DEAD >/dev/null 2>&1 || true
    tmux kill-session -t "$target" 2>/dev/null
  else
    tmux display-message 'tmux-codex-session-manager: not killing unmanaged session'
  fi
  ;;
pane)
  tmux display-message 'tmux-codex-session-manager: not killing existing Codex pane'
  ;;
esac
