# Odysseus roadmap

Odysseus is moving from a session manager to an engineering control plane. The
organizing metric is **Human Attention per Successful Change**: more accepted,
verified software with fewer minutes spent supervising routine agent work.

Versions describe independently useful product increments, not promised dates.

## Shipped — 0.2: local agent control plane

- Persistent multi-agent queue with bounded global concurrency.
- One Git branch and worktree per autonomous run.
- Implementation, deterministic checks, read-only review, and a human gate.
- Codex and Claude lanes with saved-thread resume and tmux takeover.
- Automatic tmux discovery plus explicit adoption.
- Multi-project web UI, Inbox, GitHub issue intake, and draft PR creation.
- Normalized NDJSON events for messages, reasoning, tool calls, tokens, cache,
  reported cost, checks, review, and operator decisions.
- Loopback-safe server defaults and an SSH-first VPS installer.

## Shipped — 0.3: engineering orchestration core

- Epic records and a planner role that inspects but does not implement.
- `requirement -> proposed DAG -> explicit approval -> execution` workflow.
- Validated task DAGs with cycle detection, dependency gates, fan-out/fan-in,
  blocked/ready transitions, and non-parallelizable tasks.
- Clear Planner, Implementer, and Reviewer role metadata.
- A central **Needs You** queue for questions, permission requests, failures,
  dependency blocks, evaluation failures, and review gates.
- Structured answers from web or CLI; the same agent session and worktree are
  resumed with the operator response.
- Independent evaluation that combines checks, reviewer verdict, lane
  independence, and optional deterministic evaluators into explainable
  confidence and a policy decision.
- Configurable evaluation thresholds, required evaluators, and an explicit
  opt-in policy path for auto-accept eligibility.
- Run snapshot schema 3 with automatic forward migration from existing state.
- Attention-first white web UI with Epic DAG cards and evaluation details.
- A disposable seeded demo environment for product tours and screenshots.

## Shipped — 0.4: artifacts reach green

- Accept creates a durable local Git artifact without pushing or merging to the
  source branch.
- Downstream DAG tasks compose predecessor artifacts in their own worktree
  before the agent starts.
- File-surface merge-risk analysis plus authoritative real-merge conflict
  detection; conflicts are aborted and routed to Needs You.
- GitHub check watcher that captures failing logs, resumes the original thread,
  verifies locally, pushes the repair, and obeys an automatic retry budget.
- Pull-request review comments normalized into fix/takeover/resolve decisions.
- Webhook, Slack, and ntfy delivery for exceptional events.
- Heartbeats, stage/last-activity tracking, stall detection, and time, token,
  tool-call, and reported-cost budgets.
- Explicit retry choice: saved thread, switched lane, or clean context on the
  existing branch.
- Priority-aware scheduling, cross-record local search, outcome/cost totals,
  and a portable JSON evidence export.
- Web Integration, CI, and Insights surfaces plus a deterministic 0.4 demo.

Current boundary: merge-risk prediction understands the exact file surface and
Git's real conflict result, but not semantic code graphs. GitHub integration is
polling-based and never auto-merges. State export is shipped; verified import,
retention, and cleanup remain below.

## Planned — 0.5: isolated execution environments

- Optional disposable Docker/Podman/devcontainer environment per task lane.
- Automatic port allocation and environment variables per worktree.
- Project setup/teardown hooks for dependencies, configuration, and dev-server
  lifecycle, plus an optional per-lane browser preview URL.
- Generated or copied `.env` profiles with explicit secret scope.
- Ephemeral service dependencies such as PostgreSQL snapshots and test queues.
- Filesystem sandbox, outbound network policy, credential scope, command
  policy, and CPU/RAM/disk limits.
- `--untrusted-project` mode that requires explicit approval of repository
  supplied shell checks before their first execution.
- Semantic code/dependency graph overlap prediction and a cross-PR merge queue
  with ordered rebase, rerun, and rollback.
- GitHub webhooks, review-comment classification, and explicit auto-merge
  policies for narrowly trusted changes.
- State import, backup verification, retention policy, and safe worktree/branch
  cleanup.

The goal is isolation of both code and runtime state: worktrees alone do not
prevent two agents from fighting over the same port, database, or credentials.

## Planned — 0.6: evidence-based agent routing

- High-value tournament mode: several agents or prompts attempt one ambiguous
  task and an independent judge selects a candidate.
- Per-repository benchmarks: success rate, completion time, correction rate,
  CI failures, cost, tokens, and human interventions by task class and lane.
- Router that chooses an agent from empirical project history, expected
  quality, latency, and cost; every automatic choice remains explainable.
- Project memory for architecture, code map, ADRs, schemas, API contracts,
  recent changes, and known issues, retrieved as a task-specific subset.
- Analytics for cost per accepted task/merged PR, retry rate, human minutes,
  and **Human Attention per Successful Change**.
- NDJSON export to CSV/Parquet and budget alerts.

## Planned — 0.7: workflow and organization plane

- Organization -> workspace -> project -> epic -> task -> attempt hierarchy.
- Reusable Markdown skills, task templates, and declarative workflows.
- Path/diff/risk policy engine for required checks, security review, human
  review, and narrowly scoped auto-merge.
- Odysseus MCP server: queue work, read status, answer attention items, and
  query results from another agent session.
- Linear, Jira, Sentry, and richer GitHub ingestion.
- Remote authenticated workers with heartbeats and crash recovery.
- Mobile review and push notifications.

## Exploring — 0.8: Attention Autopilot and Flight Recorder

Every run already creates an evidence trail. The proposed Flight Recorder turns
it into a learning loop:

```text
task + context + route + tools + diff + checks + review
     + human question/answer + outcome + attention minutes
                         -> project decision memory
```

Attention Autopilot would search only prior, human-approved decisions and
explicit policy before escalating a routine question. It would show its cited
precedent and confidence, never expand its own permissions, and send novel or
risky decisions to the operator. Counterfactual replay could then estimate
whether another lane, prompt, or policy would have produced a better outcome
without silently changing production routing.

A complementary **Executable Change Contract** could compile each requirement
into explicit invariants before implementation: allowed behavioral changes,
forbidden regressions, security properties, performance envelopes, migration
and rollback conditions, and acceptable human decisions. Independent verifiers
would test the contract against every candidate and integrated artifact. Unlike
ordinary generated tests, the contract would be owned by the Epic and frozen
before implementers run, reducing the chance that an agent validates only its
own interpretation.

The most experimental extension is **shadow orchestration**: replay a completed
run's evidence through alternative routers, policies, and decomposition plans
without touching the repository. Odysseus could then say “switching the review
lane would likely have saved one intervention, but auto-merge would have
violated the migration policy” before a team changes production autonomy.

This is the potential data moat: not tmux, worktrees, or a dashboard, but a
project-specific history connecting agent choices to verified engineering
outcomes and actual human attention.

## Toward 1.0: operational guarantees

- Stable event and HTTP API compatibility window.
- Tested forward migrations, backup/restore, installer upgrade, and rollback.
- Crash/restart integration tests across every active workflow state.
- Strong remote identity, session expiry, operator audit log, and signed run
  receipts.
- Distributed scheduling across workstation, build server, GPU host, and cloud
  workers without weakening credential or network policy.
- End-to-end documentation for workstation, shared host, and secured VPS.

## Product principles

1. Terminal and tmux remain first-class; Odysseus is not another IDE.
2. Git and inspectable local files remain the source of truth.
3. Planner, Implementer, Reviewer, and deterministic Verifier are separate
   roles to reduce correlated failure.
4. No task is complete because an agent says “done”; evidence and policy decide.
5. Resume, takeover, approval, publishing, and permission changes are explicit
   and auditable.
6. Features are prioritized by operator outcomes, not checkbox parity.
