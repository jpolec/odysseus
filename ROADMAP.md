# Odysseus roadmap

The roadmap describes intended direction, not a promise of dates. Work is
ordered by operator value, recoverability, and the ability to keep tmux and Git
as first-class interfaces.

Status: **shipped**, **next**, **planned**, or **exploring**.

## Shipped — 0.2

- [x] Persistent multi-agent queue with a global concurrency limit.
- [x] One Git worktree and task branch per autonomous run.
- [x] Bounded implementation, checks, read-only review, and human decision gate.
- [x] Codex and Claude lanes with exact saved-thread resume.
- [x] Interactive takeover of an autonomous task through tmux.
- [x] Automatic discovery of managed and existing Codex/Claude tmux panes.
- [x] Explicit adoption of interactive sessions into durable history.
- [x] Light web control plane with tasks, sessions, projects, inbox, and GitHub
  issue intake.
- [x] Normalized messages, reasoning, tool calls/results, token/cache usage, and
  reported cost.
- [x] Append-only event journal, live SSE updates, diff, checks, and review.
- [x] Draft pull-request publishing through authenticated GitHub CLI.
- [x] Loopback-safe defaults, SSH-first VPS installer, and optional nginx Basic
  auth with TLS.

## Next — 0.3 operator workflows

- [ ] Saved task templates for recurring implementation, audit, and maintenance
  jobs.
- [ ] Declarative workflows with named steps, per-step lane selection, retries,
  and explicit human approval gates.
- [ ] Task dependencies and a small DAG view for blocked/ready work.
- [ ] Search and filters across task titles, event history, projects, tags, and
  inbox items.
- [ ] Per-task timeouts plus configurable token, tool-call, and cost budgets.
- [ ] Richer approval requests and operator replies in the Inbox.
- [ ] State export/import and documented backup/restore verification.

## Planned — 0.4 collaborative execution

- [ ] Run several implementation variants against the same base revision.
- [ ] Compare variants by diff, checks, review findings, tokens, latency, and
  operator-selected criteria.
- [ ] Promote one variant while preserving the others as an audit trail.
- [ ] Reviewer policies such as required checks, independent lane review, and
  configurable acceptance gates.
- [ ] Runner capability discovery and a visible model/lane catalog.
- [ ] Project roles and per-project execution policy.

## Planned — 0.5 GitHub operations

- [ ] Background issue synchronization and durable source linkage.
- [ ] Pull-request status, check runs, review comments, and requested changes in
  the task detail view.
- [ ] Promote review comments into Resume feedback or Inbox follow-ups.
- [ ] Optional webhook receiver for installations that already expose a secured
  HTTPS endpoint.
- [ ] Release and changelog workflow for Odysseus itself.

## Toward 1.0

Odysseus reaches 1.0 when these operational guarantees are in place:

- [ ] Versioned, tested state migrations with forward-only upgrade guidance.
- [ ] Stable event protocol and documented API compatibility window.
- [ ] Crash and restart integration tests across every active workflow state.
- [ ] Installer upgrade/rollback path and automated service health verification.
- [ ] Backup, restore, retention, and worktree cleanup commands.
- [ ] Strong remote identity, session expiry, and an operator audit log.
- [ ] End-to-end documentation for local workstation, shared host, and VPS use.

## Exploring

- Remote worker nodes that keep the control plane small and move execution near
  the repository.
- Read-only mobile views and notification delivery for human decision gates.
- A plugin interface for issue trackers, CI providers, and agent runtimes.
- Signed run receipts for teams that need portable provenance.

## Product principles

1. Local-first state must remain understandable without a proprietary service.
2. Git branches and worktrees are the source of truth for code changes.
3. tmux is a first-class operating surface, not a compatibility afterthought.
4. Resume, adoption, takeover, approval, and publishing must be explicit.
5. Agent telemetry must be useful without persisting obvious credentials.
6. Safe defaults come before remote convenience.

## Contributing to the roadmap

Open a GitHub issue with the operator problem, an example workflow, and the
failure mode the proposal should prevent. Small, independently testable slices
are preferred over broad rewrites.
