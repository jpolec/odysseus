# Odysseus version and current capabilities

This document describes what the current Odysseus release can do, the state
and protocol versions it reads, its security boundaries, and supported upgrade
paths.

- [GitHub Releases](https://github.com/jpolec/odysseus/releases) are the
  official stable distribution records.
- [CHANGELOG.md](CHANGELOG.md) is the chronological history of changes.
- [ROADMAP.md](ROADMAP.md) describes planned work.

## Current stable release

**0.9.2 — 2026-08-20**

[Odysseus 0.9.2](https://github.com/jpolec/odysseus/releases/tag/v0.9.2)
is the latest stable release. Its tag binds the exact source revision and its
release proof covers the complete automated suite, install and upgrade,
packaged `uvx` boot, real-browser smoke, HTTP health, recovery, credentials,
state verification, supply-chain assets, and remote-access guardrails.

`main` may contain later unreleased hardening and documentation. Installers use
the latest stable release unless the operator explicitly selects `--edge`, a
version, or an exact ref.

## Product contract

Odysseus is a free, local-first delivery system for coding agents:

```text
outcome
  → Plan or Task
  → isolated execution
  → checks and independent review
  → operator decision
  → immutable accepted artifact
  → explicit integration or pull request
  → measured delivery outcome
```

The source checkout remains untouched until an explicit delivery action.
Completed, accepted, integrated, and delivered are separate states.

## Current capabilities

### Intake and planning

- Create one task from the web UI, CLI, or HTTP API using a natural-language
  finished outcome.
- Create a read-only Planner proposal and approval-gated acyclic task DAG with
  dependencies, role separation, parallelism, and independent review nodes.
- Discover and plan from `_ADR/` and conventional ADR directories while
  binding source content, status, size, path, and SHA-256 to the Epic.
- Import an authenticated GitHub Issue as redacted, deduplicated evidence and
  propose a Plan without silently beginning implementation.
- Queue several tasks from one composer and schedule them by priority and the
  configured parallel-agent limit.

### Agent execution

- Run Codex CLI, Claude Code, or a configured custom lane as replaceable
  workers; configure separate planner and reviewer lanes.
- Give every autonomous task its own Git branch and worktree.
- Discover existing tmux sessions without registering or changing their
  repositories; track a terminal deliberately and hand work back to tmux when
  needed.
- Execute on the host, in Docker, or through a reviewed devcontainer profile.
- Apply time, stall, token, tool-call, retry, and reported-cost budgets when
  the selected provider emits the required telemetry.
- Retry by resuming the saved thread, switching lanes on the same branch, or
  starting a clean-context attempt without discarding existing work.

### Context, Skills, and repository knowledge

- Build a repository Overview from its README, agent instructions, stack
  markers, recent Git commits, private project brief, and Odysseus activity.
- Maintain operator-approved Repository Memory with task and folder triggers;
  repeated guidance becomes a suggestion, never automatic trusted memory.
- Use bundled or project-local generic Skills with Auto, Required, Disabled,
  or explicit manual selection.
- Freeze the exact brief, README, instructions, ADR sources, Memory, and Skill
  content given to each run in a hashed `context-receipt-v1` record.
- Explain why every context source and Skill was selected and preserve its
  path, byte count, digest, and immutable snapshot under Evidence.

### Evidence and review

- Normalize agent messages, reasoning summaries, tool calls/results, tokens,
  cached tokens, provider-reported cost, checks, questions, and decisions into
  durable JSON snapshots and append-only NDJSON events.
- Run repository checks and a separate evaluator/reviewer lane. A worker cannot
  turn its own completion statement into independent validation.
- Present an explicitly heuristic Evidence score rather than an uncalibrated
  probability of delivery.
- Distinguish passed, failed, and inconclusive evaluation; inconclusive
  evidence becomes an operator review item instead of a false failure.
- Support opt-in implementation variants and a Pareto decision surface while
  preserving unknown objectives as unknown rather than favorable zeroes.

### Attention and recovery

- Group questions, permissions, failures, review gates, dependency blocks, and
  CI findings in one Needs You queue, with task count separate from open event
  count.
- Answer structured agent questions and permission requests from the web UI.
- Resume the exact saved agent thread, branch, worktree, and execution profile
  with operator feedback.
- Ask a local Codex or Claude Context Assistant for suggested feedback using
  explicitly selected, redacted evidence, then insert, submit, copy, or queue
  its answer.
- Preserve stopped and failed work for inspection and recovery rather than
  deleting it automatically.

### Artifacts, CI, and delivery

- Accept a reviewed worktree as an immutable local Git artifact without
  touching the source checkout.
- Compose accepted predecessor artifacts into downstream DAG work in dependency
  order and surface file-overlap merge risk and real Git conflicts.
- Apply an accepted artifact only when the source checkout, branch, base
  history, and collision checks are safe; abort a conflicting merge cleanly.
- Open a draft pull request and poll GitHub checks. Failed CI evidence can
  resume the original thread, commit a bounded repair, push it, and wait for
  the next result.
- Normalize pull-request review comments into operator attention with
  send-to-agent, terminal, ignore, and resolve paths.
- Record integration and delivery receipts separately from acceptance,
  including method, target, before/after SHAs, time, and failures.

### Routing, economics, and proof

- Default New Task to Agent: Auto, applying an eligible repository-local
  outcome recommendation or explaining a sparse-sample fallback.
- Store shadow recommendations, evidence, counterfactuals, selection source,
  and backtests without presenting small samples as reliable statistics.
- Persist `odysseus-route-observation-v1` for every task, including the actual
  worker/model/Skills, selection source and propensity, versioned router
  metadata, timing, observed usage/cost, and result.
- Show an Engineering Portfolio with started and delivered work, autonomous
  and first-pass rates, corrective intervention, delivery time, observed cost
  coverage, worker effectiveness with sample size, failures, and blockers.
- Keep missing cost unknown; never silently convert absent provider telemetry
  into zero.
- Provide local search, outcome statistics, evidence export, production proof,
  and privacy-reduced proof receipts over complete eligible journals.

### Durable state and replay

- Append every run-state transition to a canonical, fsynced EventEnvelope v2
  stream before updating its replaceable JSON projection.
- Bind contiguous stream versions into a SHA-256 hash chain and verify event,
  projection, and checkpoint hashes without mutating the evidence.
- Reconstruct a current or historical run with `odysseus replay`, and rebuild
  missing or stale projections with `odysseus rebuild-projections`.
- Recover an operator activity event and run projection after a process dies
  between the canonical append and the compatibility-journal/snapshot writes.
- Read historical envelope schemas through immutable upcasters rather than
  rewriting canonical bytes during an upgrade.
- Report canonical replay throughput in state verification and projection
  rebuild receipts instead of hiding the cost of recovery.

### Idempotent commands and concurrency

- Route mutating web and supported CLI requests through one durable
  `odysseus-command-envelope-v1` Command Bus before their handlers run.
- Bind every command to a UUID, idempotency key, actor label, redacted payload,
  redacted policy context, target stream, and optional expected stream version.
- Return the exact stored result for an exact duplicate without executing its
  handler again; reject reuse of the same key for different input.
- Reject stale run mutations with an explicit concurrency conflict before the
  canonical stream or projection changes.
- Preserve an interrupted command as `unknown` rather than guessing that it
  failed or automatically repeating a possibly completed effect.
- Inspect receipts through `odysseus command [COMMAND_ID]` or
  `GET /api/commands/:id`; `odysseus state verify` includes command records.

### Worker Leases and crash fencing

- Give each claimed run a durable `odysseus-worker-lease-v1` identity,
  heartbeat TTL, scheduler worker identity, and monotonically increasing
  fencing epoch.
- Require the current lease token for worker-originated state mutations and
  activity, so an expired or replaced worker cannot commit late output into
  canonical Odysseus state or release its successor's lease.
- Recover dead or expired owners continuously: active work is safely re-queued,
  an interrupted cancellation is finalized instead of restarted, and terminal
  review state is preserved.
- Reconstruct stale checkpoints after a process dies between canonical stream
  fsync and projection writes.
- Exercise real crash windows in subprocesses with deterministic failpoints
  after claim, heartbeat, cancellation, recovery, canonical fsync, and artifact
  snapshot boundaries.

### Installation and operation

- Run with Python 3.10+ and no Python runtime dependencies or database.
- Start from `uvx`, install through `pipx`, use the reviewed shell installer,
  or run directly from a checkout.
- Use `doctor`, the token-free disposable demo, exact-version update checks,
  atomic update/rollback, locked state backup/restore, and strict state
  verification.
- Bind the web server to loopback by default. Explicit remote binding requires
  authentication; secure private-network access can be placed behind SSH,
  Tailscale, or a TLS reverse proxy.
- Send redacted attention notifications through webhook, Slack-compatible
  webhook, or ntfy without persisting destination secrets in the delivery
  journal.

## State semantics

| State | Meaning |
| --- | --- |
| Completed | The worker process finished its attempt. |
| Verified | Required deterministic and/or independent evidence passed. |
| Accepted | Odysseus preserved the reviewed result as an exact Git artifact. |
| Published | An artifact branch or draft pull request was pushed. |
| Integrated | The artifact was applied or merged into the target branch. |
| Delivered | The configured delivery boundary was observed and recorded. |

No later state is inferred merely because an earlier state is present.

## Compatibility markers

| Surface | Current marker |
| --- | --- |
| Application version | `0.9.2` |
| Run snapshot schema | `15` |
| Epic snapshot schema | `3` |
| Canonical state event envelope | `2` |
| Operator activity event envelope | `1` |
| Command envelope | `1` |
| Worker lease | `odysseus-worker-lease-v1` |
| Context receipt | `context-receipt-v1` |
| State export | `odysseus-state-v1` |
| Python | `3.10+` |
| tmux | `3.2+` recommended |
| Built-in lanes | Codex CLI, Claude Code |

The local HTTP API is documented but does not yet have a stable compatibility
window. Consumers should check application, snapshot, event, command, and
export markers.

## Security boundaries

- Repository content, project-local Skills, agent output, tool output, CI
  output, and inbound issue/review content are untrusted inputs.
- Secret-looking values are redacted before durable snapshots, NDJSON events,
  evidence, notifications, and the browser stream.
- Host worktrees isolate Git changes, not process authority. Host commands run
  with the permissions of the Odysseus server user.
- Docker adds scoped mounts, isolated task Git, read-only reviewer mounts,
  dropped capabilities, `no-new-privileges`, network mode, and CPU/RAM limits;
  the Docker engine and chosen image remain trusted infrastructure.
- Credentials are name-allowlisted and resolved at execution time. Values are
  not stored in run snapshots, Context Receipts, events, or the browser.
- `--untrusted-project` requires an operator-controlled Docker boundary and an
  explicit gate before repository-supplied commands execute.

See [SECURITY.md](SECURITY.md) and
[docs/security/threat-model.md](docs/security/threat-model.md) for the complete
model.

## Known boundaries

- Merge prediction is currently file-surface analysis plus authoritative Git
  merge behavior; native semantic code-graph blast radius and conflict
  prediction are not yet shipped.
- GitHub CI uses authenticated polling rather than an inbound webhook, and
  Odysseus does not auto-merge pull requests.
- Cost and hard usage budgets depend on telemetry emitted by the provider.
- Docker execution is command-scoped. Long-lived previews, ephemeral database
  and queue sidecars, disk/PID quotas, signed-image policy, and host-level
  egress allowlists remain planned work.
- The stdlib HTTP service is a single-operator local/private control plane, not
  a multi-tenant application server.
- Worker fencing protects canonical Odysseus state; it does not revoke
  arbitrary host filesystem access or reconcile Git/GitHub effects that may
  already have occurred. Docker provides containment, while durable external
  intent and reconciliation are planned for v0.9.3.
- Remote distributed workers, organization RBAC, and learned autonomous
  routing are not part of 0.9.2.
- Repository knowledge is explicit and provenance-bound; a native semantic
  context graph is planned but not included in this release.

## Install and upgrade

Run the stable release without a persistent install:

```sh
uvx --from git+https://github.com/jpolec/odysseus odysseus start --open
```

For the managed shell installation:

```sh
odysseus version
odysseus update --check
odysseus update
odysseus rollback
odysseus state verify
```

Stop the server and active workers before install, update, rollback, or state
maintenance. Managed updates validate a copy of state and take a locked backup
before atomically switching releases. Rollback across an incompatible state
schema requires the explicit verified restore path.

Package-manager installations remain owned by that manager:

```sh
pipx upgrade odysseus-agents
# uvx resolves the selected source/version for each invocation
```

Existing branches, worktrees, tmux sessions, project registrations, accepted
artifacts, and append-only event journals are preserved across supported
upgrades. Older snapshots are projected forward when opened; newer unsupported
schemas are rejected rather than guessed.

## Verification

Use the complete local release gate before tagging a new stable version:

```sh
scripts/release-proof.sh
```

See [PROOF.md](PROOF.md) for CI/release requirements and
[PRODUCTION_PROOF.md](PRODUCTION_PROOF.md) for observed-run evidence policy.
