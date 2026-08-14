# Using Odysseus

This is the operator guide for local, tmux, multi-project, and remote use.

## Mental model

Odysseus manages two connected kinds of work:

1. **Autonomous tasks** start in the web UI or CLI. They receive an isolated Git
   worktree, run through implementation/check/review, and wait for a human.
2. **Interactive sessions** start in tmux. They are discovered automatically
   and remain ordinary terminal sessions until you explicitly adopt them.

An autonomous task can become interactive through **Take over in tmux**. An
interactive session can gain durable Odysseus history through **Adopt**. Neither
transition discards the existing agent thread.

## Installation

### Run from a checkout

```sh
git clone https://github.com/jpolec/odysseus.git
cd odysseus
bin/odysseus doctor
bin/odysseus serve --open
```

There is no Python package installation step. `bin/odysseus` resolves the
checkout and imports the local package directly.

### Install the tmux plugin with TPM

Add this before the TPM initialization line in `~/.tmux.conf`:

```tmux
set -g @plugin 'jpolec/odysseus'
```

Reload tmux configuration and press `prefix` + `I`. TPM clones the repository
under `~/.tmux/plugins/odysseus`.

Optional configuration, placed before the plugin declaration:

```tmux
set -g @odysseus_web_key 'O'
set -g @odysseus_web_port '8741'
set -g @odysseus_web_session 'odysseus-web'
set -g @ai_session_default_lane 'codex'
set -g @ai_session_lanes 'codex claude'
```

## Start and stop the web control plane

Foreground, with logs visible:

```sh
bin/odysseus serve
```

Open <http://127.0.0.1:8741/>. Stop with `Ctrl-C`.

Inside tmux, `prefix` + `O` starts the server in a detached `odysseus-web`
session if needed and opens the browser. Inspect that server with:

```sh
tmux attach-session -t odysseus-web
```

The health endpoint is useful for scripts:

```sh
curl -fsS http://127.0.0.1:8741/api/health
```

## Run an autonomous task

### From the web UI

1. Open **Tasks** and select **New task**.
2. Choose a project or enter an absolute repository path.
3. Choose the implementation lane and optional check commands.
4. Queue the task and watch the **Activity** stream.
5. Inspect **Diff**, **Checks**, and **Review** before deciding what happens next.

### From the CLI

```sh
bin/odysseus run \
  --project /srv/repos/api \
  --title "Add request tracing" \
  --lane codex \
  --review-lane claude \
  --base main \
  --max-retries 2 \
  --check "python3 -m unittest discover -s tests -v" \
  --check "git diff --check" \
  "Add request tracing, documentation, and tests"
```

The `--check` option is repeatable. Use `-` as the task to read a long prompt
from standard input:

```sh
bin/odysseus run --project "$PWD" --lane codex - < task.md
```

The scheduler runs while `odysseus serve` is active. Change its global parallel
limit with:

```sh
bin/odysseus config --max-parallel 3
```

## Understand task state

| State | Operator meaning |
| --- | --- |
| `queued` | Waiting for a scheduler slot. |
| `running` | The implementation agent is active. |
| `checking` | Trusted project checks are executing. |
| `reviewing` | The read-only review pass is active. |
| `review` | Waiting for Accept, Resume, Takeover, or Draft PR. |
| `failed` | Inspect the last error and event history; resume is still available. |
| `accepted` | Approval was recorded; no merge or cleanup was performed. |
| `pr_created` | A draft pull request was created. |
| `session` | A durable record for an adopted interactive tmux session. |

Every task stores a current JSON snapshot plus an append-only NDJSON journal.
The web UI replays the journal, then follows new records through Server-Sent
Events.

## Review, resume, and take over

### Resume autonomously

From the review or failed state:

```sh
bin/odysseus resume RUN_ID "Address the review findings and rerun every check"
```

Odysseus reuses the implementation agent's saved session id, original worktree,
and branch. It does not start an unrelated conversation.

### Take over interactively

```sh
bin/odysseus takeover RUN_ID
```

The command prints a `tmux attach-session` command and creates the managed
session only once. The same session appears in `prefix` + `u` and the web
**Sessions** view.

### Accept or publish

```sh
bin/odysseus accept RUN_ID
bin/odysseus draft-pr RUN_ID
```

Accept records the decision only. Draft PR stages the complete task worktree,
creates a commit when required, pushes the task branch, and invokes
`gh pr create --draft`.

## Use existing tmux sessions

### Launch from the current pane

Press `prefix` + `y`. Odysseus identifies the current repository, uses the
default lane, and launches or reattaches its managed session.

### Find all sessions

Press `prefix` + `u`, or run:

```sh
bin/odysseus sessions
```

The picker combines managed sessions with existing panes whose foreground
process is recognized as Codex or Claude. Use Enter to jump to a session.

### Make an interactive session durable

Open **Sessions** in the web UI and select **Adopt**, or run:

```sh
bin/odysseus adopt TMUX_SESSION
```

Adoption creates a durable run/event record. It does not restart the agent,
move the pane, or inject keystrokes.

## Work across projects

Projects register automatically from tasks and discovered sessions. Register
or refresh a project manually when you want it available before the first task:

```sh
bin/odysseus projects \
  --add /srv/repos/api \
  --name "Public API" \
  --tag backend \
  --tag production
```

Use the project selector in **Tasks** to narrow the task rail. **Projects** shows
repository paths, tags, branch information, and recognized GitHub remotes.

## Capture follow-up work in the inbox

Add a note from the web **Inbox**, or from the CLI:

```sh
bin/odysseus inbox \
  --project /srv/repos/api \
  --title "Rollback coverage" \
  --add "Add an integration test for rollback after a partial migration"
```

Resolve an item without creating a task:

```sh
bin/odysseus inbox --resolve ITEM_ID
```

In the web UI, **Promote** converts an open item into a queued autonomous task.
Agents can submit follow-ups with `.odysseus-followups.json`; Odysseus imports
the file after the implementation phase and removes it before review.

## Queue GitHub issues

Authenticate GitHub CLI first:

```sh
gh auth status
```

Register a repository with a GitHub remote, open **GitHub**, choose the project,
and select **Load issues**. **Queue issue** copies the issue title/body and
source URL into a new task. Odysseus does not modify or close the source issue.

## Configure project checks

Commit `.odysseus.json` in a project to provide default checks:

```json
{
  "checks": [
    "python3 -m unittest discover -s tests -v",
    "git diff --check"
  ]
}
```

Checks passed directly with `--check` or the web form take precedence. These
commands are trusted configuration and execute through `/bin/sh -lc` inside the
isolated task worktree.

## Configure a custom lane

Edit `~/.odysseus/config.json`. A custom lane can be an argv array:

```json
{
  "max_parallel": 2,
  "default_lane": "codex",
  "max_retries": 2,
  "lanes": {
    "my-agent": ["my-agent", "--cwd", "{worktree}", "--prompt", "{prompt}"]
  }
}
```

Shell-style strings are also accepted. Prefer argv arrays because argument
boundaries are unambiguous. `{worktree}` and `{prompt}` are replaced for each
run. Built-in Codex and Claude adapters additionally normalize telemetry and
support durable resume.

## Inspect, back up, and relocate state

Default layout:

```text
~/.odysseus/
├── config.json
├── projects.json
├── inbox.json
├── runs/<run-id>.json
├── events/<run-id>.ndjson
└── worktrees/<repository>-<sha>/<run-id>/
```

Use a separate state root for testing or another operator profile:

```sh
ODYSSEUS_HOME=/srv/odysseus-state bin/odysseus serve
bin/odysseus --state-dir /srv/odysseus-state runs
```

For a consistent backup, stop the server first and copy the complete state
directory. Worktrees also remain registered in their source Git repositories;
do not move individual state files independently.

## Install on a VPS

The installer copies the current checkout into `/opt/odysseus`, creates a
systemd service, stores state in `/var/lib/odysseus`, and binds the application
to VPS loopback:

```sh
sudo scripts/install-vps.sh --service-user "$USER"
```

The service user must own the agent and GitHub CLI credentials that tasks need.
From your workstation:

```sh
ssh -N -L 8741:127.0.0.1:8741 USER@VPS
```

Then open <http://127.0.0.1:8741/> locally. Keep port 8741 closed in the VPS
firewall.

For a public hostname, install nginx, Certbot, and `htpasswd`, then run:

```sh
sudo scripts/install-vps.sh \
  --service-user odysseus \
  --domain agents.example.com \
  --web-user odysseus
```

The installer prompts for the Basic-auth password and obtains a Let's Encrypt
certificate. See [../SECURITY.md](../SECURITY.md) for the trust model.

## Troubleshooting

### A queued task never starts

- Confirm `bin/odysseus serve` is still running.
- Open `/api/health` and check the active/queued counts.
- Run `bin/odysseus doctor` and verify the selected agent CLI exists.
- Inspect `bin/odysseus events RUN_ID` and `bin/odysseus show RUN_ID`.

### A tmux session is missing

- Select **Refresh** in the Sessions view.
- Confirm the pane's foreground command is Codex or Claude.
- Run `bin/odysseus sessions --json` for the raw discovery result.
- Confirm the web server runs as the same OS user and can access the same tmux
  server.

### The web shortcut says the API is not responding

Attach to `odysseus-web` and inspect its output:

```sh
tmux attach-session -t odysseus-web
```

If another process owns the configured port, either stop it or change
`@odysseus_web_port` before the plugin declaration.

### Resume is unavailable

Resume requires a saved Codex or Claude implementation session id and a task in
review or failed state. Inspect `agent_sessions` with:

```sh
bin/odysseus show RUN_ID
```

### GitHub features fail

Run `gh auth status` as the same OS user that runs Odysseus. Confirm the project
has a recognized GitHub remote and that the task branch can be pushed.

## Command reference

```text
serve       Run the scheduler and local web UI
run         Queue an autonomous task
runs        List persisted tasks and adopted sessions
show        Print one run snapshot
events      Print one run's event journal
resume      Continue the saved implementation thread
takeover    Continue the saved thread interactively in tmux
accept      Record human approval
send-back   Return review feedback to the agent workflow
cancel      Request task cancellation
draft-pr    Commit, push, and create a draft pull request
sessions    List auto-discovered tmux sessions
adopt       Give an interactive session durable history
projects    List or register repositories
inbox       List, add, or resolve follow-ups
config      Read or change scheduler configuration
doctor      Inspect dependencies and state
```

Run `bin/odysseus COMMAND --help` for exact options.
