# Odysseus

![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Python: 3.x stdlib](https://img.shields.io/badge/python-3.x%20stdlib-3776AB)
![tmux: 3.2+](https://img.shields.io/badge/tmux-3.2%2B-1f6feb)
![GitHub Repo stars](https://img.shields.io/github/stars/jpolec/tmux-codex-session-manager?style=social)

**A local control plane for coding agents: isolated worktrees, a persistent
queue, reproducible checks, and a human review gate.**

Odysseus adds a thin web interface and a durable orchestration layer to the
existing tmux-native agent session manager. Codex and Claude remain ordinary
local CLIs. Git remains the source of truth. The UI is an operational view over
small JSON and NDJSON files, not a second project-management system.

The codebase is branded **Odysseus**. The repository URL remains
`jpolec/tmux-codex-session-manager` for now so existing TPM installations do not
break. A later GitHub rename can use `odysseus-agent-control-plane`; it is not
required to use the new runtime.

## What Odysseus Implements

1. **One worktree per task.** Every queued run starts from a recorded Git commit
   on its own `odysseus/<run-id>` branch.
2. **A persistent queue with bounded concurrency.** Run state survives process
   restarts under `~/.odysseus`; `max_parallel` defaults to `2`.
3. **One event protocol for Codex and Claude.** Vendor streams are normalized
   into versioned events such as `agent.output`, `check.completed`, and
   `run.review_ready`.
4. **Append-only NDJSON history.** Every run has a readable event journal that
   can be replayed, tailed, or processed with `jq`.
5. **A review gate.** The web detail view shows the full diff, check results,
   reviewer output, and actions to **Accept**, **Send back**, or create a
   **Draft PR**.
6. **A bounded `agent -> check -> review` workflow.** Failed checks return to the
   implementation agent with captured output, up to the configured retry limit.
   Review runs in a read-only agent mode.
7. **A thin Tasks UI with live detail over SSE.** The server and UI use only the
   Python standard library and browser-native JavaScript. There is no Node build,
   database, Redis, or container requirement.

The original tmux popup launcher and global session picker are still available
and backward compatible.

## Quick Start

Requirements:

- macOS or Linux
- Python 3.10 or newer
- Git
- [Codex CLI](https://developers.openai.com/codex/cli) and/or Claude Code
- `gh` authenticated with GitHub only when using **Draft PR**
- tmux and fzf only for the legacy tmux controls

From a checkout:

```sh
bin/odysseus doctor
bin/odysseus serve --open
```

Without `--open`, visit <http://127.0.0.1:8741/>.

In the web UI:

1. Select **New task**.
2. Enter an absolute path to a Git repository and the task prompt.
3. Choose `codex` or `claude` and optionally add one check command per line.
4. Follow the live event stream.
5. At the review gate, inspect the diff, checks, and reviewer output, then choose
   **Accept**, **Send back**, or **Draft PR**.

Accepting a run records the decision; it does not merge or delete anything.
Sending it back reuses the same worktree and includes the feedback in the next
bounded workflow cycle. Draft PR stages and commits the worktree, pushes its
branch, and runs `gh pr create --draft`.

## CLI Usage

Keep `odysseus serve` running so the persistent scheduler can claim queued work.
The same tasks can be created and inspected from another terminal:

```sh
bin/odysseus run \
  --project /absolute/path/to/repository \
  --lane codex \
  --check "python3 -m unittest discover -s tests" \
  --check "git diff --check" \
  "Add the requested feature and cover it with tests"
```

Useful commands:

```sh
bin/odysseus runs
bin/odysseus show RUN_ID
bin/odysseus events RUN_ID
bin/odysseus cancel RUN_ID
bin/odysseus accept RUN_ID
bin/odysseus send-back RUN_ID "Fix the race reported in review"
bin/odysseus draft-pr RUN_ID
bin/odysseus config --max-parallel 3
```

Use `-` to read a task or review feedback from standard input:

```sh
printf '%s\n' "Investigate and fix the flaky queue test" | bin/odysseus run --project "$PWD" -
```

## Project Configuration

Checks can be provided per task or committed in a repository-level
`.odysseus.json`:

```json
{
  "checks": [
    "python3 -m unittest discover -s tests -v",
    "git diff --check"
  ]
}
```

CLI or web task checks take precedence over `.odysseus.json`. Commands are
trusted project configuration and run through `/bin/sh -lc` inside the task
worktree.

Global configuration lives at `~/.odysseus/config.json`:

```json
{
  "max_parallel": 2,
  "default_lane": "codex",
  "default_workflow": "agent-check-review",
  "max_retries": 2,
  "lanes": {
    "local-reviewer": {
      "command": ["my-agent", "--cwd", "{worktree}", "--prompt", "{prompt}"]
    }
  }
}
```

Custom commands are argv arrays or shell-style strings. `{worktree}` and
`{prompt}` placeholders are replaced directly; commands are not passed through
a shell. Environment variables remain the right place for credentials and are
not copied into run records.

## Runtime Model

```text
queued task
    |
    v
isolated worktree + odysseus/<run-id> branch
    |
    v
implementation agent ----< failed check, retry <= limit
    |                                      |
    v                                      |
project checks ----------------------------+
    |
    v
read-only agent review
    |
    v
human gate: Accept | Send back | Draft PR
```

Codex runs as `codex exec --json` with a workspace-write sandbox for
implementation and a read-only sandbox for review. Claude runs non-interactively
with `stream-json`, using `acceptEdits` for implementation and `plan` for review.
Both streams become the same Odysseus event types.

If the source checkout is dirty, Odysseus records a `worktree.dirty_base` event
and creates the task from committed `HEAD`. It never silently copies uncommitted
source changes into a new worktree.

## Durable State and Event Protocol

By default, state is kept here:

```text
~/.odysseus/
├── config.json
├── runs/<run-id>.json
├── events/<run-id>.ndjson
└── worktrees/<repository>-<sha>/<run-id>/
```

Override the root with `ODYSSEUS_HOME` or `--state-dir`.

Every NDJSON line has the same envelope:

```json
{
  "v": 1,
  "seq": 14,
  "ts": "2026-08-14T12:00:00Z",
  "run_id": "20260814-120000-add-health-check-a1b2",
  "type": "check.completed",
  "source": "check",
  "data": {"command": "python3 -m unittest", "returncode": 0}
}
```

`seq` is monotonic within a run. The web UI replays existing events and then
continues over Server-Sent Events, so a refresh does not lose history. See
[docs/odysseus-protocol.md](docs/odysseus-protocol.md) for the event and HTTP API
reference.

## Local Web Security

The server binds to `127.0.0.1` by default. It validates loopback Host and Origin
headers and requires a per-process token on every mutating API request. The
browser obtains that token through a same-origin bootstrap request. No CORS
headers are enabled.

`--allow-remote` intentionally removes the loopback checks. Put an authenticated
reverse proxy in front of Odysseus before exposing it to another machine.

## tmux Controls

The repository started as `tmux-codex-session-manager`, and those controls remain:

| Key | Action |
| --- | --- |
| `prefix` + `y` | Launch or reattach the current project's default interactive agent lane |
| `prefix` + `u` | Open the global tmux agent-session picker |
| `prefix` + `O` | Start Odysseus in a detached tmux session and open the local web UI |

Install with TPM:

```tmux
set -g @plugin 'jpolec/tmux-codex-session-manager'
```

Then press `prefix` + `I`. Optional settings must appear before the plugin line:

```tmux
set -g @odysseus_web_key 'O'
set -g @odysseus_web_port '8741'
set -g @ai_session_default_lane 'codex'
set -g @ai_session_lanes 'codex claude'
```

The tmux picker shows managed interactive sessions and discovered Codex panes,
including status, lane, project path, recent title, and live `capture-pane`
output. Existing Codex hook support and receipts under
`~/.tmux-ai-sessions/receipts` are unchanged; they are separate from durable
Odysseus task runs.

Install or refresh the optional Codex TUI hooks:

```sh
~/.tmux/plugins/tmux-codex-session-manager/scripts/install-hooks.sh
```

## Development

The runtime has no third-party Python or JavaScript dependencies.

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q odysseus
node --check web/app.js
git diff --check
```

The test suite covers durable run/event storage, isolated Git worktrees and
diffs, bounded workflow retries, the review gate, and token-protected HTTP
creation.

## License

MIT. The original tmux session manager was adapted from
[craftzdog/tmux-claude-session-manager](https://github.com/craftzdog/tmux-claude-session-manager),
also MIT licensed.
