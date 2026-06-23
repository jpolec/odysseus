# tmux-codex-session-manager

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Shell: Bash](https://img.shields.io/badge/shell-bash-4EAA25)
![Python: 3.x stdlib](https://img.shields.io/badge/python-3.x%20stdlib-3776AB)
![tmux: 3.2+](https://img.shields.io/badge/tmux-3.2%2B-1f6feb)
![TPM ready](https://img.shields.io/badge/tpm-ready-blue)
![GitHub Repo stars](https://img.shields.io/github/stars/jpolec/tmux-codex-session-manager?style=social)

A tmux-native session manager for AI agent CLIs. It started as a
[Codex CLI](https://developers.openai.com/codex/cli) popup manager, and Codex
remains the default lane and compatibility path.

If you launch Codex per directory, or keep several Codex panes open while
working across projects, you quickly end up with a stack of sessions and no
single place to see which one is working, waiting, or finished. This plugin gives
you one tmux-native control surface for them.

What you get:

- Central switcher (`prefix` + `u`) listing managed agent popups and existing
  Codex panes.
- Live status per session or pane: `WORK`, `WAIT`, `IDLE`, or `????`.
- Live preview of the selected agent screen inside the switcher.
- Smart jump: selecting a managed session resumes it in a popup; selecting an
  existing pane switches tmux directly to it.
- Per-directory launcher (`prefix` + `y`) that opens or attaches a managed
  default-lane session for the current project.
- Quick kill (`ctrl-x`) for plugin-managed sessions only.
- Codex metadata in the picker: latest prompt/title and approximate remaining
  context from `~/.codex/sessions`.

Status is optional. Without hooks, the switcher still lists, previews, jumps,
and kills managed sessions; rows just fall back to `????` or metadata-inferred
state where available.

## Current Status

This project is in an incremental transition from a Codex-only tmux popup
manager to a minimal tmux-native AI agent session manager.

Implemented now:

- The existing Codex workflow remains the default and should behave as before.
- `prefix` + `y` still opens the current project's Codex/default-lane popup.
- Managed sessions now have lane metadata, role metadata, project path, command,
  status, and optional prompt-file metadata.
- The picker shows a compact lane column.
- New lanes can be launched from the script with `--lane`.
- Receipts are written as lightweight JSON under
  `~/.tmux-ai-sessions/receipts`.
- Example read-only review prompts live under `.agents/`.

Partial in this iteration:

- Codex has real status through the existing hook and JSONL metadata flow.
- Claude, GLM, and custom lanes can be launched, but their status is generic and
  may show `????`.
- Prompt files are validated and recorded, but not injected into interactive
  TUIs.
- Roles are metadata only; they do not enforce permissions or change sandboxing.

Not implemented yet:

- Per-role permission policy.
- Reliable prompt injection per agent CLI.
- Native Claude/GLM status detection.
- Worktree-per-job, scheduled jobs, daily scans, diff/test receipts, and
  multi-lane comparison mode.

## Screenshots

![Codex switcher with status, source, context, path, title, target, and live preview](docs/picker.png)

The switcher is the control surface: jump into a managed popup, switch to an
existing Codex pane, preview output, or kill only plugin-managed sessions.

![Managed Codex session running in the tmux popup](docs/popup.png)

Managed sessions are normal tmux sessions named with the configured prefix. They
survive detach, terminal restarts, SSH disconnects, and laptop sleep.

## Features

- Central switcher for every managed Codex popup and discovered Codex pane.
- Per-directory launcher for persistent managed popup sessions.
- Per-session and per-pane status, driven by Codex hooks when installed.
- Latest prompt/title and approximate context remaining from Codex JSONL logs.
- Lane and role metadata for managed agent sessions.
- Lightweight JSON receipts under `~/.tmux-ai-sessions/receipts`.
- Live `capture-pane` preview inside the switcher.
- Safe navigation to existing Codex panes without killing normal tmux windows.
- `ctrl-x` kill action for managed `codex-*` sessions only.
- Hook installer and uninstaller that merge into existing Codex hooks with
  backups.
- TPM-compatible plugin, implemented with Bash plus Python 3 standard library
  helpers.

## Requirements

- tmux >= 3.2, for `display-popup`
- [fzf](https://github.com/junegunn/fzf)
- [Codex CLI](https://developers.openai.com/codex/cli), available as `codex`,
  for the default lane
- Other agent CLIs only if you configure lanes for them
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
| `prefix` + `y` | Launch or re-attach the current project's managed default-lane popup         |
| `prefix` + `u` | Open the global agent picker                                                 |

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
| lane   | Backend used for the managed session, such as `codex` or `claude`  |
| kind   | `MGR` for plugin-managed popup sessions, `PANE` for existing panes |
| age    | Time since the last hook event or matching Codex session event     |
| ctx    | Approximate remaining context from recent Codex token events       |
| path   | Current working directory                                          |
| title  | Latest prompt/title recovered from `~/.codex/sessions`             |
| target | tmux session name or `session:window.pane` locator                  |

## Agent Lanes

A lane is the backend used to run an AI coding session: Codex, Claude, GLM
through a proxy, or a custom command. A role is the purpose of that session.

Think of it this way:

| Concept | Answers                         | Examples                         | Affects command? |
| ------- | ------------------------------- | -------------------------------- | ---------------- |
| lane    | Which agent runner starts?      | `codex`, `claude`, `glm52`       | Yes              |
| role    | What is this session meant for? | `general`, `security`, `docs`    | No, metadata now |

For example:

```sh
scripts/launch.sh --lane codex --role security
```

This starts the Codex runner and labels the session as a security-review job.
It does not make Codex read-only by itself. To make the job read-only, use a
read-only prompt such as `.agents/security-review.md` and enforce any stronger
policy outside this plugin until role permissions are added.

The default lane is `codex`, so existing Codex behavior and key bindings
continue to work when you do not configure anything new.

Configure lanes in tmux before the plugin loads:

```tmux
set -g @ai_session_default_lane "codex"
set -g @ai_session_lanes "codex claude glm52"

set -g @ai_session_lane_codex_command "codex"
set -g @ai_session_lane_claude_command "claude"
set -g @ai_session_lane_glm52_command "claude"
set -g @ai_session_lane_glm52_env "ANTHROPIC_BASE_URL=http://localhost:4141 ANTHROPIC_AUTH_TOKEN=sk-local-only"
```

The old Codex options still work. If `@ai_session_lane_codex_command` is not set,
the Codex lane uses `@codex_command`, then falls back to `codex`.
When `@ai_session_lanes` is set, launches are limited to those lane names; when
it is unset, any lane name is accepted and its command defaults to the lane name.

Launch lanes from the plugin checkout:

```sh
scripts/launch.sh --lane codex
scripts/launch.sh --lane claude
scripts/launch.sh --lane glm52 --role tests
scripts/launch.sh launch --lane codex --role security --prompt-file .agents/security-review.md
```

Roles are metadata describing the job purpose, such as `general`, `security`,
`docs`, `tests`, `review`, or `architecture`. They are stored on the tmux session
and in the receipt, but do not enforce permissions yet.

Prompt files are validated and recorded in metadata and receipts. Automatic
prompt injection into interactive TUIs is intentionally not enabled in this
iteration because it is CLI-specific and easy to make brittle.

Every managed session writes a JSON receipt:

```text
~/.tmux-ai-sessions/receipts/<tmux-session>.json
```

Receipts include the tmux session, project path, lane, role, command, prompt
file, timestamps, status, and `managed: true`. Lane environment values are not
stored, so configured tokens are not copied into receipts.

Current limitations:

- Codex has the richest status and metadata through hooks and JSONL logs.
- Claude, GLM, and custom lanes currently use conservative generic status
  detection and may show `????`.
- Prompt files are recorded, not pasted into the TUI.
- The picker discovers existing Codex panes, not arbitrary existing agent panes.

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

For non-Codex managed lanes, status detection is intentionally small: explicit
tmux state wins, otherwise an existing pane process reports as unknown instead
of guessing that the agent is working.

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
set -g @codex_command        'codex'    # legacy Codex command option
set -g @codex_session_prefix 'codex-'   # tmux session name prefix
set -g @codex_popup_width    '90%'      # popup width
set -g @codex_popup_height   '90%'      # popup height
set -g @codex_include_existing_panes 'on' # show Codex already running in tmux panes

set -g @ai_session_default_lane 'codex'
set -g @ai_session_lanes 'codex claude glm52'
set -g @ai_session_prefix 'ai-' # non-Codex sessions become ai-<lane>-<hash>
set -g @ai_session_lane_codex_command 'codex'
set -g @ai_session_lane_claude_command 'claude'
set -g @ai_session_lane_glm52_command 'claude'
set -g @ai_session_lane_glm52_env 'ANTHROPIC_BASE_URL=http://localhost:4141 ANTHROPIC_AUTH_TOKEN=sk-local-only'
set -g @ai_session_receipts_dir '~/.tmux-ai-sessions/receipts'
```

Example:

```tmux
set -g @codex_command 'codex --search'
```

## How It Works

The launcher creates a detached tmux session for the requested lane, records the
origin window and metadata, writes a receipt, and attaches to it in a popup.
Codex keeps the historical `codex-<hash-of-dir>` name. Other lanes use
`ai-<lane>-<hash-of-dir>` by default.

The picker lists all managed sessions plus existing tmux panes that have a Codex
process below the pane PID. For each row, it reads tmux hook state and recent
Codex JSONL metadata, then opens a live `capture-pane` preview.

When you press `prefix` + `u` from inside a managed Codex popup, the plugin
detaches that popup first and opens the picker on the outer tmux client.

## Roadmap

- Worktree per job.
- Scheduled read-only jobs.
- Daily security scan lane.
- Diff and test receipts.
- Multi-lane benchmark mode.
- Claude, Codex, and GLM comparison views.

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
