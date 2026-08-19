# Odysseus and tmux

tmux is optional. The normal Odysseus workflow runs from the web workbench; use
tmux when you want to watch an existing Codex or Claude pane, open the saved
agent thread interactively, or keep the web server in a detached session.

## Install with TPM

Add this before `run '~/.tmux/plugins/tpm/tpm'` in `~/.tmux.conf`:

```tmux
set -g @plugin 'jpolec/odysseus'
```

Reload tmux, press `prefix` + `I`, then use:

| Key | Action |
| --- | --- |
| `prefix` + `y` | Launch or reattach the current repository's interactive agent. |
| `prefix` + `u` | Open the global agent-session picker. |
| `prefix` + `O` | Start or open the local Odysseus web workbench. |

## Optional configuration

Place settings before the plugin declaration:

```tmux
set -g @odysseus_web_key 'O'
set -g @odysseus_web_port '8741'
set -g @odysseus_web_session 'odysseus-web'
set -g @ai_session_default_lane 'codex'
set -g @ai_session_lanes 'codex claude'
```

| Session picker | Managed agent session |
| --- | --- |
| ![Odysseus tmux session picker](picker.png) | ![Odysseus managed agent session](popup.png) |

## Optional Codex TUI status hooks

```sh
~/.tmux/plugins/odysseus/scripts/install-hooks.sh
```

The web UI never injects keystrokes into an arbitrary pane. Passive discovery
is read-only. Tracking, resume, and terminal handoff are explicit transitions.
**Copy tmux command** copies a safe command for you to paste into your own
terminal; **Continue in terminal** opens the preserved task worktree and saved
agent thread without restarting the task.

For repository setup, remote access, lifecycle details, and troubleshooting,
continue with the [complete usage guide](USAGE.md).
