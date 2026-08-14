# Odysseus version and capabilities

## Current version

**0.3.0 — 2026-08-14**

Version 0.3 adds the first engineering-orchestration layer: requirements can be
planned into approval-gated task DAGs, exceptional work is normalized into one
attention queue, and independent evidence produces an explainable policy
decision.

## What is available in 0.3.0

### Epics, Planner, and task DAGs

- Durable Epic records and a read-only Planner lane.
- Structured `ODYSSEUS_PLAN:` proposal protocol.
- Explicit approval before task materialization.
- Cycle and unknown-dependency validation.
- Dependency-aware blocked/ready transitions and scheduler claims.
- Fan-out/fan-in and non-parallelizable task semantics.
- Planner, Implementer, and Reviewer role metadata.
- Epic/DAG views and CLI/API controls.

### Human Attention

- Central **Needs You** view across projects.
- Normalized questions, permission requests, broken dependencies, failures,
  evaluation failures, and review gates.
- Structured option buttons plus free-form answers.
- Answering resumes the same implementation session and worktree.
- Explicit tmux takeover remains available when terminal judgment is useful.

### Evaluation and policy

- Structured `ODYSSEUS_EVALUATION:` reviewer verdicts.
- Weighted checks, independent review, lane independence, and optional
  project-specific deterministic evaluators.
- Confidence, missing/failing evaluators, eligibility, and human-review policy
  persisted on each run.
- Human review is the default; policy auto-accept eligibility is explicit and
  does not merge or publish code.

### Reliability found through dogfooding

- Redacted or vendor-specific token counters no longer crash event aggregation.
- Permission denials are normalized into operator attention instead of being
  buried in raw output.
- Old run snapshots migrate forward to schema 3 when the store opens.
- A seeded `scripts/demo.py` environment exercises Needs You, Epics, DAG states,
  telemetry, and evaluation without consuming model tokens.

### Retained 0.2 capabilities

- Persistent bounded queue, isolated worktrees, checks, retries, review, and
  restart recovery.
- Codex/Claude telemetry and saved-thread resume.
- tmux discovery, adoption, picker, and takeover.
- Multi-project registry, follow-up Inbox, GitHub issue intake, and draft PR.
- Local JSON/NDJSON state, SSE, loopback-safe web server, and VPS installer.

## Compatibility markers

| Surface | Current marker |
| --- | --- |
| Application version | `0.3.0` |
| Run snapshot schema | `3` |
| Epic snapshot schema | `1` |
| Event envelope version | `1` |
| Python | `3.10+` |
| tmux | `3.2+` recommended |
| Built-in lanes | Codex CLI, Claude Code |

The local HTTP API is documented but not yet stable. Consumers should check
the application, run-schema, and event-envelope versions.

## Known 0.3 boundaries

- DAG dependencies control readiness; accepted predecessor diffs are not yet
  automatically composed into a downstream integration branch.
- Questions are delivered when the current CLI process yields. A runner that
  waits forever for an interactive permission prompt still needs a timeout or
  tmux takeover; process timeouts are planned for 0.4.
- Worktrees isolate repository files, not ports, databases, environment files,
  credentials, CPU, RAM, or network access. Container isolation is planned for
  0.5.
- There is no CI check-run watcher, merge queue, tournament, learned router,
  project memory, or distributed worker yet.

## Upgrade from 0.2

Stop the running server and back up the complete state directory, then:

```sh
git pull --ff-only
bin/odysseus doctor
python3 -m unittest discover -s tests -v
bin/odysseus serve
```

Opening the state store adds schema-3 defaults to older run snapshots. Event
journals remain append-only and are not rewritten. Existing branches,
worktrees, tmux sessions, and project registrations are preserved.

## Version history

### 0.3.0 — engineering orchestration core

Added Epics, a separated Planner, task DAG scheduling, Needs You, structured
operator interaction, independent evaluation/policy, schema migration, and a
reproducible demo.

### 0.2.0 — local control plane

Added the web UI, persistent autonomous workflow, exact-thread resume and tmux
takeover, normalized telemetry, multi-project registry, Inbox, GitHub intake,
and protected VPS operation.

### 0.1.x — tmux session manager

Established managed agent sessions, the repository-aware launcher, global fzf
picker, session metadata, and optional Codex status hooks.
