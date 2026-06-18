# tmux-codex-session-manager

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Shell: Bash](https://img.shields.io/badge/shell-bash-4EAA25)
![Python: 3.x stdlib](https://img.shields.io/badge/python-3.x%20stdlib-3776AB)
![tmux: 3.2+](https://img.shields.io/badge/tmux-3.2%2B-1f6feb)
![TPM ready](https://img.shields.io/badge/tpm-ready-blue)
![GitHub Repo stars](https://img.shields.io/github/stars/jpolec/tmux-codex-session-manager?style=social)

A tmux popup manager for [Codex CLI](https://developers.openai.com/codex/cli).

Keep many Codex sessions running in tmux, but manage them from one popup:

- `prefix` + `y` opens the current project's Codex session in a tmux popup.
- `prefix` + `u` opens a global picker for every managed Codex session and
  every existing Codex pane it can discover.

The picker shows live preview, status, source (`MGR` or `PANE`), age, estimated
remaining context, project path, and the latest prompt/title from
`~/.codex/sessions`.

## Screenshots

![Codex session picker with status, source, context, project path, prompt title, and live preview](docs/picker.png)

The picker is the control surface: jump into a managed popup, switch to an
existing Codex pane, preview output, or kill only plugin-managed sessions.

![Codex session running inside a tmux popup over the project window](docs/popup.png)

Managed sessions are normal tmux sessions named with the configured prefix. They
survive detach, terminal restarts, SSH disconnects, and laptop sleep.

## Features

- Popup launcher for the current project (`prefix` + `y`).
- Global picker for managed Codex sessions and already-running Codex panes
  (`prefix` + `u`).
- Per-session and per-pane status: `WORK`, `WAIT`, `IDLE`, or `????`.
- Metadata from Codex JSONL session logs: last prompt/title and approximate
  remaining context.
- Live `capture-pane` preview inside the picker.
- Safe navigation to existing panes without killing the user's normal tmux
  windows.
- `ctrl-x` kill action for managed `codex-*` sessions only.
- Hook installer and uninstaller that merge into an existing Codex hooks file
  with backups.
- TPM-compatible plugin, implemented with Bash plus Python 3 standard library
  helpers.

## Requirements

- tmux >= 3.2, for `display-popup`
- [fzf](https://github.com/junegunn/fzf)
- [Codex CLI](https://developers.openai.com/codex/cli), available as `codex`
- Bash
- Python 3, standard library only
- macOS or Linux

## Install With TPM

Add this to `~/.tmux.conf` or `~/.config/tmux/tmux.conf`:

```tmux
set -g @plugin 'jpolec/tmux-codex-session-manager'
```

Then press `prefix` + `I`.

Recommended: install the Codex hooks so status and metadata update naturally:

```sh
~/.tmux/plugins/tmux-codex-session-manager/scripts/install-hooks.sh
```

Start Codex and run `/hooks` if Codex asks you to review and trust the new hook
commands.

## Manual Install

```sh
git clone https://github.com/jpolec/tmux-codex-session-manager ~/clone/path
```

Add this to your tmux config, then reload tmux:

```tmux
run-shell ~/clone/path/codex_session_manager.tmux
```

Install hooks from that checkout:

```sh
~/clone/path/scripts/install-hooks.sh
```

## Usage

| Key            | Action                                                                       |
| -------------- | ---------------------------------------------------------------------------- |
| `prefix` + `y` | Launch or re-attach the current project's managed Codex popup                |
| `prefix` + `u` | Open the global Codex picker                                                 |

Inside the picker:

| Key                 | Action                                                                          |
| ------------------- | -------------------------------------------------------------------------------- |
| `enter`             | Jump to the selected managed session or existing Codex pane                      |
| `ctrl-x`            | Kill the highlighted managed `codex-*` session                                   |
| `up` / `down`, type | fzf navigation and filtering                                                     |

Picker columns:

| Column | Meaning                                                            |
| ------ | ------------------------------------------------------------------ |
| state  | `WAIT`, `IDLE`, `WORK`, or `????`                                  |
| kind   | `MGR` for plugin-managed popup sessions, `PANE` for existing panes |
| age    | Time since the last hook event or matching Codex session event     |
| ctx    | Approximate remaining context from recent Codex token events       |
| path   | Current working directory                                          |
| title  | Latest prompt/title recovered from `~/.codex/sessions`             |
| target | tmux session name or `session:window.pane` locator                  |

## Status And Metadata

The plugin uses two sources of information.

Codex hooks update tmux options in real time:

| Codex hook          | State  | Meaning                                   |
| ------------------- | ------ | ----------------------------------------- |
| `UserPromptSubmit`  | `WORK` | Codex started a turn                      |
| `PermissionRequest` | `WAIT` | Codex is asking for approval              |
| `PostToolUse`       | `WORK` | Codex resumed work after a tool completed |
| `Stop`              | `IDLE` | The turn finished                         |
| `SessionStart`      | `IDLE` | A Codex TUI session started or resumed    |

Codex JSONL logs under `~/.codex/sessions` provide a fallback and richer picker
metadata: latest prompt/title, last activity age, inferred state, and estimated
remaining context.

Install or refresh hooks:

```sh
~/.tmux/plugins/tmux-codex-session-manager/scripts/install-hooks.sh
```

Remove only this plugin's hooks:

```sh
~/.tmux/plugins/tmux-codex-session-manager/scripts/uninstall-hooks.sh
```

Both scripts preserve unrelated Codex hooks and create timestamped backups
before changing the hooks file.

To print the raw hook snippet instead:

```sh
~/.tmux/plugins/tmux-codex-session-manager/scripts/print-hooks.sh
```

## Options

Set any of these before the plugin loads:

```tmux
set -g @codex_launch_key     'y'        # prefix key: launch/open for current dir
set -g @codex_list_key       'u'        # prefix key: open the picker
set -g @codex_command        'codex'    # command run in new sessions
set -g @codex_session_prefix 'codex-'   # tmux session name prefix
set -g @codex_popup_width    '90%'      # popup width
set -g @codex_popup_height   '90%'      # popup height
set -g @codex_include_existing_panes 'on' # show Codex already running in tmux panes
```

Example:

```tmux
set -g @codex_command 'codex --search'
```

## How It Works

The launcher creates a detached `codex-<hash-of-dir>` tmux session running
`codex`, records the origin window, and attaches to it in a popup.

The picker lists all managed sessions plus existing tmux panes that have a Codex
process below the pane PID. For each row, it reads tmux hook state and recent
Codex JSONL metadata, then opens a live `capture-pane` preview.

When you press `prefix` + `u` from inside a managed Codex popup, the plugin
detaches that popup first and opens the picker on the outer tmux client.

## Development

Useful local checks:

```sh
scripts/picker.sh --list
scripts/session-meta.py --path "$PWD"
scripts/print-hooks.sh | jq empty
```

## License

MIT. This project is adapted from
[craftzdog/tmux-claude-session-manager](https://github.com/craftzdog/tmux-claude-session-manager),
also MIT licensed.

## GitHub Signals

GitHub does not expose a public share counter for repositories. The public
signals closest to that are stars, forks, watchers, issues, and recent activity:

![GitHub Repo stars](https://img.shields.io/github/stars/jpolec/tmux-codex-session-manager?style=social)
![GitHub forks](https://img.shields.io/github/forks/jpolec/tmux-codex-session-manager?style=social)
![GitHub watchers](https://img.shields.io/github/watchers/jpolec/tmux-codex-session-manager?style=social)
![GitHub issues](https://img.shields.io/github/issues/jpolec/tmux-codex-session-manager)
![GitHub last commit](https://img.shields.io/github/last-commit/jpolec/tmux-codex-session-manager)
