# Odysseus version and capabilities

## Current version

**0.4.1 — 2026-08-14**

Version 0.4 makes DAG edges carry code, not only scheduling state. Accepted
tasks become durable local artifacts; downstream branches compose those
artifacts before implementation; draft pull requests enter a bounded GitHub CI
repair loop. The operator sees merge risk, CI, liveness, budgets, and outcomes
in the same attention-first control plane.

## What is available in 0.4.1

### 0.4.1 operator clarity patch

- The task form starts with the natural-language outcome; repository and agent
  are explicit, while retries, priority, and budgets stay under Advanced.
- Registered repositories are selected automatically. The absolute-path field
  appears only when **Other repository path** is chosen.
- Epic planning now explains requirement -> proposal -> approval -> execution
  in the dialog and states twice that the button does not start implementation.
- Existing tmux panes are grouped by tmux session and use real window/pane
  labels instead of duplicating the latest Codex prompt for every pane sharing
  a directory.
- **Track in Odysseus** replaces the ambiguous Adopt label. A tracked terminal
  gets a deliberately reduced detail view and never displays invented zeros,
  diff, CI, confidence, or agent-session telemetry.
- Terminal handoff actions say whether they copy a tmux command, Inbox explains
  when work starts, and empty navigation counters no longer look like status
  lights.

### Artifact DAG and merge intelligence

- **Accept** snapshots the complete task worktree as a local Git commit and
  records its SHA plus changed-file surface.
- A downstream run merges every accepted predecessor artifact, in dependency
  order, into its own isolated worktree before its agent starts.
- Cross-task file overlap is classified as low, medium, or high merge risk.
- A failed merge is aborted in the downstream worktree and becomes one
  structured, high-priority `Needs You` item with conflicted files.
- Integration sources, merge head, overlap analysis, and artifact events remain
  auditable in JSON/NDJSON and the web UI.

### Closed pull-request feedback loop

- A background watcher polls GitHub checks for Odysseus draft pull requests.
- Failed-check summaries and best-effort failed logs resume the original
  implementation thread in its existing branch/worktree.
- A locally verified repair is committed and pushed to the same PR branch; the
  watcher observes the next attempt until green or the retry budget is spent.
- New PR review comments become structured attention items with send-to-agent,
  tmux takeover, and resolve paths.
- Manual `odysseus ci [RUN_ID]` polling is available for immediate feedback.

### Operator economics and reliability

- Per-task and default time, stall, token, tool-call, and reported-cost budgets.
- Process heartbeat, current stage, last activity, timeout, and stall events.
- Priority-aware scheduling from 0 to 100.
- Retry strategies: resume the saved thread, switch lanes on the same branch,
  or start a clean-context attempt without discarding work.
- Generic webhook, Slack, and ntfy delivery for attention-worthy events, with
  a local delivery journal that never stores destination URLs.
- Local search across runs, events, Epics, projects, attention, and Inbox.
- `stats` for verified outcomes, observed tokens/cost, interventions, CI loops,
  and merge risk; `export` produces one inspectable JSON evidence bundle.

### Web console and demo

- Six-stage Isolate/Compose/Agent/Verify/Review/CI progress strip.
- Artifact and Integration inspector with source SHAs and overlap surfaces.
- GitHub CI inspector with individual checks, failed logs, and repair attempts.
- Insights view for outcome metrics and local full-text search.
- Task forms expose priority and hard budgets; Resume exposes all three retry
  strategies.
- The no-token demo includes a DAG, human question, composed artifacts, merge
  risk, failed CI, search results, and engineering economics.

### Retained 0.3 and 0.2 capabilities

- Read-only Planner, approval-gated Epic DAGs, cycle validation, dependency
  gates, fan-out/fan-in, role separation, and independent evaluation.
- Central Needs You queue, structured agent questions, web answers, exact-thread
  resume, and explicit tmux takeover.
- Persistent bounded queue, one branch/worktree per task, checks and retries,
  multi-project registry, follow-up Inbox, GitHub intake, and draft PRs.
- Normalized telemetry for messages, reasoning, tools, tokens/cache, cost,
  checks, evaluation, and decisions.

## Compatibility markers

| Surface | Current marker |
| --- | --- |
| Application version | `0.4.1` |
| Run snapshot schema | `4` |
| Epic snapshot schema | `1` |
| Event envelope version | `1` |
| Export format | `odysseus-state-v1` |
| Python | `3.10+` |
| tmux | `3.2+` recommended |
| Built-in lanes | Codex CLI, Claude Code |

The local HTTP API is documented but not yet stable. Consumers should check
the application, run-schema, event-envelope, and export-format markers.

## Known 0.4 boundaries

- Merge prediction is exact at the file surface and authoritative at the real
  Git merge. Semantic code-graph conflict prediction and a cross-PR merge queue
  remain future work.
- CI integration polls through authenticated GitHub CLI. It is not yet a
  webhook receiver, and Odysseus never auto-merges the pull request.
- Review comments are normalized and can be sent back to the agent; there is no
  learned comment classifier.
- Token/tool/cost limits depend on telemetry emitted before process
  termination. Providers that omit a metric cannot be limited by that metric.
- Worktrees isolate repository files, not ports, databases, environment files,
  credentials, CPU, RAM, or network access. Runtime isolation is next.
- Search is local substring search, not semantic retrieval or project memory.

## Upgrade from 0.3

Stop the running server and back up the complete state directory, then:

```sh
git pull --ff-only
bin/odysseus doctor
python3 -m unittest discover -s tests -v
bin/odysseus serve
```

Opening the state store adds schema-4 defaults to older run snapshots. Event
journals remain append-only and are not rewritten. Existing branches,
worktrees, tmux sessions, project registrations, and 0.3 Epics are preserved.
An old accepted run without an artifact SHA remains visible; resume/review and
accept it once under 0.4 before using it as a new downstream dependency.

## Version history

### 0.4.1 — operator clarity

Removed misleading inferred tmux metadata, grouped discovered panes, added a
purpose-built tracked-terminal view, simplified task/Epic input, and documented
exactly which actions start work or only copy a terminal command.

### 0.4.0 — artifacts reach green

Added durable accepted artifacts, isolated DAG composition, merge-risk and
conflict handling, bounded GitHub CI repair, PR feedback intake, notifications,
liveness/budgets, retry strategies, priority scheduling, search/stats/export,
and the Integration/CI/Insights web surfaces.

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
