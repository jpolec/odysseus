# Odysseus

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python: stdlib](https://img.shields.io/badge/python-stdlib-3776AB)
![tmux: 3.2+](https://img.shields.io/badge/tmux-3.2%2B-1f6feb)
![GitHub Repo stars](https://img.shields.io/github/stars/jpolec/odysseus?style=social)

**A local-first control plane for coding agents and the tmux sessions you
already use.**

Odysseus runs isolated agent tasks, preserves their event history, shows tool
calls and token usage, and puts a human gate before publishing. Its light web
UI is also a live window into existing tmux sessions: sessions appear
automatically, while adoption is explicit.

There is no database, Node build, Redis, or mandatory container. The runtime is
Python's standard library, browser-native JavaScript, Git worktrees, JSON, and
append-only NDJSON.

## Start here

Requirements: Python 3.10+, Git, and Codex CLI and/or Claude Code. tmux and fzf
are needed for the interactive terminal controls; `gh` is needed for GitHub
issues and draft pull requests.

```sh
git clone https://github.com/jpolec/odysseus.git
cd odysseus
bin/odysseus doctor
bin/odysseus serve --open
```

Without `--open`, visit <http://127.0.0.1:8741/>. See [START.md](START.md) for
the first task, tmux setup, remote access, and common commands.

## What is included

- One Git worktree and `odysseus/<run-id>` branch per autonomous task.
- A persistent queue with a global concurrency limit and restart recovery.
- A bounded `agent -> checks -> read-only review -> human decision` workflow.
- Codex and Claude adapters with a normalized, append-only event protocol.
- Typed agent messages, reasoning summaries, tool start/result records, token
  totals, cached tokens, tool-call counts, and Claude-reported cost.
- Real continuation of the implementation thread with Codex `exec resume` or
  Claude `--resume` when a task is retried or sent back.
- Interactive takeover of an autonomous thread in a managed tmux session.
- Automatic tmux discovery, with explicit **Adopt** for durable task history.
- Multi-project registry, filtering, tags, GitHub remote links, and GitHub issue
  intake.
- A cross-project inbox for human notes and agent-discovered follow-up work.
- Full diff, checks, review, Accept, Resume, Draft PR, and live SSE activity.
- A loopback-safe default plus an SSH-first VPS installer and optional
  TLS + Basic-auth nginx setup.

Read [USE_CASES.md](USE_CASES.md) for concrete workflows.

## Deliberate scope

Odysseus is not a line-for-line Cezar clone. Version 0.2 covers the operational
features this project needs—tmux discovery and takeover, durable resume,
telemetry, projects, inbox, GitHub issue intake, and secure remote operation.
It does not yet include Cezar's visual workflow builder, multi-variant
tournaments, model catalog, or full pull-request cockpit. Native Codex/Claude
skills continue to work inside each lane rather than being copied into a second
skill store.

## tmux: automatic discovery vs adoption

These are intentionally separate:

1. Press `prefix` + `y` to launch or reattach an interactive agent for the
   current directory.
2. Open the web UI with `prefix` + `O`.
3. The managed session—or an existing Codex/Claude pane—appears under
   **Sessions** automatically within a few seconds. You do not press an import
   button.
4. Press **Adopt** only if you want a durable Odysseus task record and history.
5. **Take over in tmux** on an autonomous task resumes its exact agent session
   in a managed tmux session. The UI copies the safe attach command; the same
   session is also available through `prefix` + `u`.

The web UI never injects keystrokes into an arbitrary pane. It exposes explicit,
auditable transitions and keeps the terminal as a first-class interface.

## CLI

Keep `odysseus serve` running so the scheduler can claim queued work:

```sh
bin/odysseus run \
  --project /absolute/path/to/repository \
  --lane codex \
  --check "python3 -m unittest discover -s tests" \
  --check "git diff --check" \
  "Implement the feature and cover it with tests"
```

Operator commands:

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

`resume` reuses the saved implementation session and worktree. `takeover`
creates (or returns) an interactive tmux session and prints its attach command.

## Project configuration

Checks can be supplied per task or committed as `.odysseus.json`:

```json
{
  "checks": [
    "python3 -m unittest discover -s tests -v",
    "git diff --check"
  ]
}
```

Task checks take precedence. These commands are trusted project configuration
and run through `/bin/sh -lc` inside the task worktree.

Global state is under `~/.odysseus` by default:

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
`{prompt}` placeholders.

## Agent follow-ups

An implementation agent may leave `.odysseus-followups.json` in its worktree:

```json
[
  {
    "title": "Harden the migration rollback",
    "task": "Add a rollback integration test for the newly discovered edge case.",
    "priority": "high"
  }
]
```

Odysseus imports at most 50 entries into the cross-project inbox and removes
the handoff file before diff/review. Follow-ups therefore do not pollute the
project patch.

## Event protocol

Every event has a version, per-run sequence, UTC timestamp, run id, type,
source, and data object. Representative v0.2 types are:

```text
agent.session
agent.message
agent.reasoning
agent.tool.started
agent.tool.completed
agent.usage
agent.cost
check.completed
run.review_ready
session.adopted
session.takeover_ready
```

Vendor tool payloads are normalized and common credential fields and token
patterns are redacted before persistence. See
[docs/odysseus-protocol.md](docs/odysseus-protocol.md).

## tmux plugin installation

With TPM:

```tmux
set -g @plugin 'jpolec/odysseus'
```

Press `prefix` + `I`, then use:

| Key | Action |
| --- | --- |
| `prefix` + `y` | Launch or reattach the current project's interactive agent |
| `prefix` + `u` | Open the global agent-session picker |
| `prefix` + `O` | Start/open the Odysseus web control plane |

Optional settings must precede the plugin line:

```tmux
set -g @odysseus_web_key 'O'
set -g @odysseus_web_port '8741'
set -g @ai_session_default_lane 'codex'
set -g @ai_session_lanes 'codex claude'
```

Optional Codex TUI status hooks:

```sh
~/.tmux/plugins/odysseus/scripts/install-hooks.sh
```

## Remote and VPS

The safe default is loopback. On a VPS, run:

```sh
sudo scripts/install-vps.sh --service-user "$USER"
```

Then create an SSH tunnel from your workstation:

```sh
ssh -N -L 8741:127.0.0.1:8741 USER@VPS
```

For a public hostname, the installer can configure nginx Basic auth and obtain
TLS with Certbot:

```sh
sudo scripts/install-vps.sh --service-user odysseus --domain agents.example.com
```

Direct remote binding is refused unless an HTTP Basic password file is supplied
(or the explicitly unsafe override is used). Details are in
[SECURITY.md](SECURITY.md).

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q odysseus
node --check web/app.js
bash -n scripts/*.sh codex_session_manager.tmux
git diff --check
```

## License

MIT. The original tmux manager was adapted from
[craftzdog/tmux-claude-session-manager](https://github.com/craftzdog/tmux-claude-session-manager),
also MIT licensed.
