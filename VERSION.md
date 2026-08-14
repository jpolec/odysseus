# Odysseus version and capabilities

## Current version

**0.2.0 — 2026-08-14**

The runtime version is defined in `odysseus/__init__.py`. Version 0.2 turns the
tmux session manager into a local control plane while preserving the terminal
workflow.

## What is available in 0.2.0

### Web control plane

- Light, responsive interface for Tasks, Sessions, Inbox, Projects, and GitHub.
- Live connection status and Server-Sent Event activity.
- Task diff, check output, review summary, workflow state, and operator actions.
- Repository link in the top bar next to the live indicator.
- Mutation protection with a per-process same-origin token.

### Autonomous execution

- Durable queue and configurable global parallelism.
- Isolated Git worktree plus `odysseus/<run-id>` branch for every task.
- `agent -> checks -> read-only review -> human decision` workflow.
- Bounded retries, restart recovery, cancellation, and persisted errors.
- Separate Accept, Resume, Takeover, and Draft PR actions.

### Agents and telemetry

- Built-in Codex and Claude lanes plus configurable custom lanes.
- Saved implementation session ids and exact-thread continuation.
- Normalized agent messages, reasoning summaries, tool starts/results, and raw
  output fallbacks.
- Input, cached-input, output, and reasoning-token totals; tool-call counts; and
  agent-reported cost where available.
- Credential-shaped field and common token-pattern redaction before persistence.

### tmux

- `prefix` + `y` launches or reattaches an agent for the current repository.
- `prefix` + `u` opens the global session picker.
- `prefix` + `O` starts or opens the web control plane.
- Automatic discovery of managed sessions and existing Codex/Claude panes.
- Explicit adoption into durable history.
- Interactive takeover that resumes an autonomous task's saved agent thread.

### Multi-project work

- Project registry with paths, tags, branch metadata, and recognized GitHub
  remotes.
- Cross-project task filtering.
- Inbox for operator notes and agent-discovered follow-ups.
- Promotion of follow-ups into autonomous tasks.
- GitHub issue intake and draft pull-request creation through `gh`.

### Deployment and operations

- Loopback-only server by default with Host and Origin validation.
- Direct remote binding requires HTTP Basic credentials unless an explicit
  unsafe override is supplied.
- VPS installer for systemd with SSH-tunnel access as the default.
- Optional nginx Basic auth and Let's Encrypt TLS for a public hostname.
- Inspectable JSON snapshots and append-only NDJSON history under one state
  directory.

### Documentation and verification

- Quick start, complete usage guide, use cases, security guide, roadmap, and
  protocol/API reference.
- Unit coverage for events, runners, scheduler, server, store, tmux discovery,
  and worktrees.
- Python compilation, JavaScript syntax, shell syntax, and whitespace checks.

## Compatibility markers

| Surface | Current marker |
| --- | --- |
| Application version | `0.2.0` |
| Run snapshot schema | `2` |
| Event envelope version | `1` |
| Python | `3.10+` |
| tmux | `3.2+` recommended |
| Built-in lanes | Codex CLI, Claude Code |

The local HTTP API is documented but not yet declared stable. Automation should
check the application, run-schema, and event-envelope versions before depending
on undocumented fields.

## Upgrade from an earlier checkout

From the cloned repository:

```sh
git pull --ff-only
bin/odysseus doctor
python3 -m unittest discover -s tests -v
```

Restart a foreground `bin/odysseus serve` process after pulling. If the tmux web
shortcut owns the server, attach to `odysseus-web`, stop the old process with
`Ctrl-C`, detach, and press `prefix` + `O` again.

TPM installations can update with `prefix` + `U`, then reload tmux
configuration. Existing task snapshots and event journals remain in
`~/.odysseus`.

Before any future schema-changing upgrade, stop the server and back up the
complete state directory. Versioned automatic migrations are tracked in
[ROADMAP.md](ROADMAP.md) for the 1.0 line.

## Version history

### 0.2.0 — control plane

Added the web UI, persistent autonomous workflow, exact-thread resume and tmux
takeover, normalized telemetry, multi-project registry, Inbox, GitHub intake,
and protected VPS operation.

### 0.1.x — tmux session manager

Established managed agent sessions, the repository-aware launcher, global fzf
picker, session metadata, and optional Codex status hooks.
