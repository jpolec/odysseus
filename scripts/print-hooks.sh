#!/usr/bin/env bash
# Print a Codex hooks.json snippet with commands pointing at this checkout.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=helpers.sh
. "$DIR/helpers.sh"

json_escape() {
  awk 'BEGIN { ORS="" } { gsub(/\\/,"\\\\"); gsub(/"/,"\\\""); print }' <<EOF
$1
EOF
}

state_cmd() {
  printf '%s %s' "$(shell_quote "$DIR/state.sh")" "$1"
}

cmd_idle="$(json_escape "$(state_cmd idle)")"
cmd_working="$(json_escape "$(state_cmd working)")"
cmd_waiting="$(json_escape "$(state_cmd waiting)")"

cat <<EOF
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume",
        "hooks": [
          {
            "type": "command",
            "command": "$cmd_idle",
            "statusMessage": "Marking Codex session idle"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$cmd_working",
            "statusMessage": "Marking Codex session working"
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$cmd_waiting",
            "statusMessage": "Marking Codex session waiting"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$cmd_working",
            "statusMessage": "Marking Codex session working"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "$cmd_idle",
            "statusMessage": "Marking Codex session idle"
          }
        ]
      }
    ]
  }
}
EOF
