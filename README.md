# Odysseus

![Version: 0.2.0](https://img.shields.io/badge/version-0.2.0-171a16)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python: stdlib](https://img.shields.io/badge/python-stdlib-3776AB)
![tmux: 3.2+](https://img.shields.io/badge/tmux-3.2%2B-1f6feb)
![GitHub Repo stars](https://img.shields.io/github/stars/jpolec/odysseus?style=social)

**A local-first control plane for coding agents and the tmux sessions you
already use.**

Odysseus runs isolated agent tasks, preserves their event history, shows tool
calls and token usage, and keeps a human gate before publishing. Its light web
UI is also a live window into existing tmux sessions: discovery is automatic,
while adoption and takeover stay explicit.

[Quick start](START.md) · [Complete usage guide](docs/USAGE.md) ·
[Use cases](USE_CASES.md) · [Roadmap](ROADMAP.md) ·
[Version and capabilities](VERSION.md) · [Security](SECURITY.md) ·
[Protocol and API](docs/odysseus-protocol.md)

## Why Odysseus

- **Keep tmux.** Existing Codex and Claude panes appear automatically and stay
  usable from the terminal.
- **Run safely in parallel.** Every autonomous task receives its own branch and
  Git worktree; a persistent scheduler enforces the global concurrency limit.
- **Continue, do not restart.** Resume sends feedback to the saved agent thread
  and the same worktree. Takeover opens that thread interactively in tmux.
- **See the work.** The UI exposes normalized messages, reasoning summaries,
  tool calls/results, token and cache usage, checks, review, and live activity.
- **Keep control.** Accept only records approval. Creating a draft pull request
  is a separate, explicit action.
- **Operate more than one repository.** Projects, tasks, tmux sessions, GitHub
  issues, and follow-ups share one local control plane.
- **Stay inspectable.** State is JSON plus append-only NDJSON. The runtime uses
  Python's standard library and browser-native JavaScript—no database, Redis,
  Node build, or mandatory container.

## Quick start

Requirements: Python 3.10+, Git, and Codex CLI and/or Claude Code. tmux and fzf
are needed for terminal controls; authenticated `gh` is needed for GitHub issue
intake and draft pull requests.

```sh
git clone https://github.com/jpolec/odysseus.git
cd odysseus
bin/odysseus doctor
bin/odysseus serve --open
```

Without `--open`, visit <http://127.0.0.1:8741/>. Keep this process running: it
serves the UI and claims queued tasks. The fastest end-to-end walkthrough is in
[START.md](START.md).

## Where tasks come from

| Source | What happens |
| --- | --- |
| **New task** in the web UI | A branch and worktree are created, then the bounded agent/check/review workflow runs. |
| `bin/odysseus run ...` | The same workflow is queued from a terminal or script. |
| Existing Codex/Claude tmux pane | It appears in **Sessions** automatically; no import button is required. |
| **Adopt** on a tmux session | A durable Odysseus record is created without interrupting the pane. |
| Inbox **Promote** | A human or agent follow-up becomes a queued task in its project. |
| GitHub **Queue issue** | An open issue becomes a queued task through authenticated `gh`. |

Automatic discovery does not silently turn arbitrary panes into autonomous
jobs. Use **Adopt** only when an interactive session should have durable
Odysseus history.

## The autonomous workflow

```text
queue -> isolated worktree -> implementation agent -> project checks
      -> read-only review -> human decision -> accept / resume / takeover / draft PR
```

Queue a task from the CLI:

```sh
bin/odysseus run \
  --project /absolute/path/to/repository \
  --lane codex \
  --review-lane claude \
  --check "python3 -m unittest discover -s tests -v" \
  --check "git diff --check" \
  "Implement the feature and cover it with tests"
```

At the review gate:

| Action | Result |
| --- | --- |
| **Accept** | Records human approval; it does not merge or delete the worktree. |
| **Resume agent** | Sends feedback to the saved implementation thread in the same worktree. |
| **Take over in tmux** | Resumes the exact implementation thread in a managed interactive session. |
| **Draft PR** | Commits the task worktree, pushes its branch, and opens a draft pull request. |

## tmux controls

Install with TPM by adding this before `run '~/.tmux/plugins/tpm/tpm'`:

```tmux
set -g @plugin 'jpolec/odysseus'
```

Reload tmux, press `prefix` + `I`, then use:

| Key | Action |
| --- | --- |
| `prefix` + `y` | Launch or reattach the current project's interactive agent. |
| `prefix` + `u` | Open the global agent-session picker. |
| `prefix` + `O` | Start or open the local Odysseus web control plane. |

Optional settings must precede the plugin line:

```tmux
set -g @odysseus_web_key 'O'
set -g @odysseus_web_port '8741'
set -g @ai_session_default_lane 'codex'
set -g @ai_session_lanes 'codex claude'
```

| Session picker | Managed agent session |
| --- | --- |
| ![Odysseus tmux session picker](docs/picker.png) | ![Odysseus managed agent session](docs/popup.png) |

Optional Codex TUI status hooks:

```sh
~/.tmux/plugins/odysseus/scripts/install-hooks.sh
```

The web UI never injects keystrokes into an arbitrary pane. Adoption, resume,
and takeover are explicit, auditable transitions.

## Projects, inbox, and GitHub

Projects register automatically when a task is queued or a tmux session is
discovered. You can also register one directly:

```sh
bin/odysseus projects --add /srv/repos/api --tag backend --tag production
```

The cross-project **Inbox** holds work that should not expand the current task.
Add an operator note in the UI or CLI:

```sh
bin/odysseus inbox \
  --project /srv/repos/api \
  --title "Migration follow-up" \
  --add "Add a rollback integration test"
```

An implementation agent can create `.odysseus-followups.json` in its worktree:

```json
[
  {
    "title": "Harden the migration rollback",
    "task": "Add a rollback integration test for the newly discovered edge case.",
    "priority": "high"
  }
]
```

Odysseus imports at most 50 entries and removes the handoff file before the
diff/review stage, so discovered work does not pollute the current patch.

## Configuration and state

Checks can be supplied per task or committed as `.odysseus.json`:

```json
{
  "checks": [
    "python3 -m unittest discover -s tests -v",
    "git diff --check"
  ]
}
```

Task checks take precedence. Check commands are trusted project configuration
and run through `/bin/sh -lc` inside the task worktree.

State is stored under `~/.odysseus` by default:

```text
~/.odysseus/
├── config.json
├── projects.json
├── inbox.json
├── runs/<run-id>.json
├── events/<run-id>.ndjson
└── worktrees/<repository>-<sha>/<run-id>/
```

Override it with `ODYSSEUS_HOME` or `--state-dir`. Custom lanes can be added to
`config.json` as an argv array or shell-style command using `{worktree}` and
`{prompt}` placeholders. See [docs/USAGE.md](docs/USAGE.md) for examples and an
operator command reference.

## Remote and VPS

The server binds to loopback by default. For a private VPS installation:

```sh
sudo scripts/install-vps.sh --service-user "$USER"
ssh -N -L 8741:127.0.0.1:8741 USER@VPS
```

Open <http://127.0.0.1:8741/> on your workstation. The service stays private on
the VPS. To expose a hostname with nginx Basic auth and Let's Encrypt TLS:

```sh
sudo scripts/install-vps.sh \
  --service-user odysseus \
  --domain agents.example.com
```

A direct remote bind without a password is refused unless the explicitly
unsafe override is supplied. Read [SECURITY.md](SECURITY.md) before exposing the
service.

## CLI operator commands

```sh
bin/odysseus runs
bin/odysseus show RUN_ID
bin/odysseus events RUN_ID
bin/odysseus resume RUN_ID "Address the review findings"
bin/odysseus takeover RUN_ID
bin/odysseus sessions
bin/odysseus adopt TMUX_SESSION
bin/odysseus inbox
bin/odysseus projects
bin/odysseus accept RUN_ID
bin/odysseus draft-pr RUN_ID
bin/odysseus config --max-parallel 3
```

Use `bin/odysseus COMMAND --help` for command-specific arguments.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q odysseus
node --check web/app.js
bash -n scripts/*.sh codex_session_manager.tmux
git diff --check
```

See [ROADMAP.md](ROADMAP.md) for planned work and [VERSION.md](VERSION.md) for
the shipped capability matrix and upgrade notes.

## License

MIT. The original tmux manager was adapted from
[craftzdog/tmux-claude-session-manager](https://github.com/craftzdog/tmux-claude-session-manager),
also MIT licensed.
