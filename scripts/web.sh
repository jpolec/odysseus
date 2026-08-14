#!/usr/bin/env bash
# Start Odysseus in a detached tmux session and open its local web UI.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

port="$(get_tmux_option @odysseus_web_port '8741')"
session="$(get_tmux_option @odysseus_web_session 'odysseus-web')"
url="http://127.0.0.1:${port}/"

healthy() {
  python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1).read()' \
    "$url/api/health" >/dev/null 2>&1
}

case "$port" in
'' | *[!0-9]*)
  tmux display-message "Odysseus: invalid @odysseus_web_port: $port"
  exit 0
  ;;
esac

if ! healthy; then
  if tmux has-session -t "=$session" 2>/dev/null; then
    tmux display-message "Odysseus: tmux session '$session' exists, but its API is not responding"
    exit 1
  fi
  command="$(shell_quote "$DIR/../bin/odysseus") serve --host 127.0.0.1 --port $(shell_quote "$port")"
  if ! tmux new-session -d -s "$session" -c "$DIR/.." "$command"; then
    tmux display-message "Odysseus: could not start the web server"
    exit 1
  fi

  for _ in $(seq 1 30); do
    healthy && break
    sleep 0.1
  done
fi

if command -v open >/dev/null 2>&1; then
  open "$url"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$url" >/dev/null 2>&1 &
else
  tmux display-message "Odysseus: $url"
fi
