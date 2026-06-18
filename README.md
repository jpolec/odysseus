# tmux-codex-session-manager

Run many [Codex CLI](https://developers.openai.com/codex/cli) sessions across
your projects, each in its own tmux session. List them, see which sessions are
working or waiting, preview their screens, and jump back into one from a single
popup.

It is meant for the everyday workflow where you have Codex open in several
repositories at once and need one place to see what needs attention. Use
`prefix` + `y` to open the current project's Codex session, and `prefix` + `u`
to pick from all running Codex sessions with status, preview, jump, and kill
actions.

## Screenshots

![Codex session picker showing status, age, project path, and live preview](docs/picker.png)

The picker shows every managed Codex session, sorted so sessions waiting for you
rise to the top.

![Codex session running inside a tmux popup over the project window](docs/popup.png)

Launching a project opens Codex in a large popup, while keeping the underlying
tmux window in place.

## Features

- Central picker (`prefix` + `u`) listing every running Codex session.
- Launcher (`prefix` + `y`) that opens or re-attaches a Codex session for the
  current directory.
- Live preview of each session's screen in the picker.
- Existing Codex panes are discovered too, so `prefix` + `u` can jump to Codex
  sessions you started outside the launcher.
- Status per session: `WORK`, `WAIT`, `IDLE`, or `????`.
- Smart jump: selecting a session switches your outer tmux client to the window
  where it was launched, then resumes the Codex popup over it.
- Quick kill (`ctrl-x`) from the picker.

Status is optional. Without Codex hooks, the picker still lists, previews, jumps,
and kills sessions; status may show `????` or the launch-time `IDLE`.

## Prerequisites

- tmux >= 3.2, for `display-popup`
- [fzf](https://github.com/junegunn/fzf)
- [Codex CLI](https://developers.openai.com/codex/cli), available as `codex`
- bash; macOS or Linux

## Install with tpm

Add this to `~/.tmux.conf` or `~/.config/tmux/tmux.conf`:

```tmux
set -g @plugin 'jpolec/tmux-codex-session-manager'
```

Then press `prefix` + `I` to install.

## Manual install

```sh
git clone https://github.com/jpolec/tmux-codex-session-manager ~/clone/path
```

Add this to your tmux config, then reload tmux:

```tmux
run-shell ~/clone/path/codex_session_manager.tmux
```

## Usage

| Key            | Action                                                                         |
| -------------- | ------------------------------------------------------------------------------ |
| `prefix` + `y` | Launch or re-attach to a Codex session for the current directory, in a popup   |
| `prefix` + `u` | Open the session picker                                                        |

Inside the picker:

| Key                       | Action                                                                    |
| ------------------------- | ------------------------------------------------------------------------- |
| `enter`                   | Jump to the session and resume it in the popup                            |
| `ctrl-x`                  | Kill the highlighted managed `codex-*` session                            |
| `up` / `down`, type       | fzf navigation and filtering                                              |

Sessions needing attention (`WAIT`, then `IDLE`) sort to the top.
Existing Codex panes show as `PANE`; `ctrl-x` intentionally does not kill them.

## Status setup

Codex hooks are enabled by default in current Codex CLI releases. This plugin can
use them to stamp the active tmux session with state:

| Codex hook         | State     | Meaning                                      |
| ------------------ | --------- | -------------------------------------------- |
| `UserPromptSubmit` | `WORK`    | Codex started a turn                         |
| `PermissionRequest`| `WAIT`    | Codex is asking for an approval              |
| `PostToolUse`      | `WORK`    | Codex resumed work after a tool completed    |
| `Stop`             | `IDLE`    | The turn finished                            |
| `SessionStart`     | `IDLE`    | A Codex TUI session started or resumed       |

Generate a ready-to-use `hooks.json` snippet from the installed plugin path:

```sh
~/.tmux/plugins/tmux-codex-session-manager/scripts/print-hooks.sh
```

Put the generated JSON in one of the locations Codex reads, for example:

- `~/.codex/hooks.json` for all projects
- `<repo>/.codex/hooks.json` for a trusted project

Then start Codex and use `/hooks` to review and trust the new hook commands if
Codex asks for that. Existing sessions begin reporting status on the next
matching hook event.

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

For example, to launch Codex with web search enabled:

```tmux
set -g @codex_command 'codex --search'
```

## How it works

- The launcher creates a detached `codex-<hash-of-dir>` tmux session running
  `codex`, records the origin window in `@codex_origin`, and attaches to it in a
  popup.
- Codex hooks call `scripts/state.sh`, which sets `@codex_state` and
  `@codex_state_at` on the tmux session that is running Codex.
- The picker lists sessions matching `@codex_session_prefix`, reads state, shows
  a live `capture-pane` preview, and attaches to the selected session.
- Pressing `prefix` + `u` from inside a Codex popup detaches that popup first,
  then opens the picker on the outer tmux client.

## License

MIT. This project is adapted from
[craftzdog/tmux-claude-session-manager](https://github.com/craftzdog/tmux-claude-session-manager),
also MIT licensed.
