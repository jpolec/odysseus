# Odysseus roadmap

Odysseus is moving from a session manager to an engineering control plane. The
organizing metric is **Human Attention per Successful Change**: more accepted,
verified software with fewer minutes spent supervising routine agent work.

Versions describe independently useful product increments, not promised dates.

## Shipped — 0.6.11: composed operator polish

- Task titles and notifications fall back to the request text when an API
  client explicitly sends a null title; operators no longer see `null` notices.
- Agent terminals default to the selected or saved repositories, with the
  complete machine-wide session list available as an explicit wider scope.
- A light-by-default theme gains a compact dark-mode switch and a packaged
  Odysseus icon while the navigation surfaces remain visually stable.
- Three independently accepted task artifacts are composed into one release,
  so their delivery history remains traceable without replaying conflicting
  patches against a newer frontend.

## Shipped — 0.6.10: exact on-demand tabs

- Cross-section and deep-link navigation activates the requested inner tab
  before rendering, so Integration never preloads Diff.

## Shipped — 0.6.9: responsive task inspection

- Task lists poll compact summaries; full run evidence is fetched only for the
  selected task.
- Changes, Activity, and Evidence render on demand with bounded text and event
  windows, while the complete auditable records remain on disk.
- Selection generations and run-bound SSE streams prevent stale responses from
  making a newly selected task appear frozen or incorrect.
- Conflicting accepted artifacts have a direct **Ask agent to resolve** path.

## Shipped — 0.6.8: task intake and operator settings

- Starting work clears the submitted prompt, shows an explicit progress state,
  prevents duplicate clicks, and makes **Start & add another** a true blank
  next-task loop.
- Queue capacity and defaults have one Settings surface for parallel slots,
  agents, retries, budgets, and CI repair behavior.
- Context Assistant settings expose provider readiness and configurable direct
  API models while keeping API keys out of browser and state storage.
- Local delivery allows unrelated untracked files, explains tracked-file and
  merge-conflict gates, and recognizes artifacts already present in `main`.

## Shipped — 0.6.7: review and delivery clarity

- Review now says explicitly that the agent is finished while nothing has been
  applied, then presents one numbered **Review -> Test -> Deliver** checklist.
- Accepting and delivering are separate states. The UI distinguishes a durable
  artifact, a locally applied change, and a draft pull request.
- Explicit local Apply refuses dirty or detached checkouts, the wrong branch,
  unavailable artifacts, and incompatible base history; conflicting merges are
  aborted and routed to Needs You.
- Review feedback is named **Request changes** rather than Recovery. Failed and
  attention states retain focused recovery in the same thread and worktree.
- Browser confirmations use one Odysseus dialog with X and Escape behavior;
  empty or null notices receive readable fallback text.

## Shipped — 0.6.6: guided browser recovery

- Failed and attention states place same-thread feedback directly beside the
  status, with tmux retained as an optional expert handoff.
- A context-controlled Codex/Claude assistant drafts, inserts, submits, copies,
  or queues the next instruction without requiring another local CLI API key.

## Shipped — 0.6.5: repository clarity

- The visible product model now has three explicit nouns: Odysseus is the
  application, a repository is one local Git checkout, and a task is one agent
  change. “Project” remains an internal API name only.
- Repository remotes provide the default display identity; local checkout
  folders and paths remain separately visible, including multiple checkouts of
  the same repository.
- A repository used to launch Odysseus can be added with one click. The primary
  Explorer shows repositories first and only reveals tasks after selection;
  secondary tools stay under **More**.
- Passive tmux discovery no longer mutates the repository list or leaks managed
  worktrees into it. Explicit tracking remains available.
- Stale registry entries can be forgotten without deleting or modifying local
  repository files.

## Shipped — 0.6.4: one visible path

- A persistent, clickable **1 Choose a project -> 2 Describe a change ->
  3 Follow & review** path anchors first use, normal project work, and mobile.
- Readiness checks become quiet diagnostics rather than a second numbered
  process. The task composer requires only a Codex-style natural-language
  outcome.
- Advanced routing, checks, Skills, limits, and environments remain available
  under **More options…**, preserving depth without front-loading complexity.
- Task detail explains the operator's role and sends step 3 to the current run
  or **Needs You** item. Imported tmux sessions remain clearly distinct from
  Odysseus-managed tasks.

## Shipped — 0.6.3: observed dogfooding proof

- Versioned run provenance separates observed autonomous work from demos,
  tests, imported tmux sessions, and legacy unclassified history.
- `proof` emits privacy-reduced, content-addressed JSON receipts and a public
  Markdown summary with release filtering and an honest sample threshold.
- Only terminal attempts with ordered start, agent activity, and outcome events
  count; early failures remain in the denominator. Delivery claims additionally
  require final verifier success before artifact creation and outcome. Draft PRs
  remain distinct from accepted artifacts.
- Missing cost stays unobserved with an explicit coverage ratio. Operator
  actions and Needs You response latency are measured separately; repaired CI
  must finish green and recovered work must progress to completion.
- Repository-owned checks and `scripts/dogfood.sh` let Odysseus develop and
  measure Odysseus without publishing seeded numbers as production outcomes.

## Shipped — 0.6.2: stable lifecycle

- Latest-stable-by-default remote installation; `--edge`, `--version`, and
  exact-ref modes are explicit.
- Side-by-side releases, atomic current/previous switches, checksummed state
  backups, staging verification, transactional restore, schema-aware rollback,
  and ownership-checked install/state/server leases.
- `version`, `update --check`, `update`, `rollback`, and `state verify` commands
  plus an N-1 -> N -> N-1 proof with fault and live-process cases.

## Shipped — 0.6.1: release integrity

- Standard Python source/wheel packaging with a zero-runtime-dependency
  `odysseus` entry point and bundled UI, demo, helpers, and generic Skills.
- Fast PR CI, full main proof, proof-gated tag releases, release artifacts, and
  SHA-256 checksums.
- Exact-commit and packaged install tests plus HTTP boot and shutdown smoke
  tests.
- Bounded HTTP and SSE concurrency for the documented single-operator
  workstation/private-VPS scope.

## Shipped — 0.2: local agent control plane

- Persistent multi-agent queue with bounded global concurrency.
- One Git branch and worktree per autonomous run.
- Implementation, deterministic checks, read-only review, and a human gate.
- Codex and Claude lanes with saved-thread resume and tmux takeover.
- Automatic tmux discovery plus explicit durable tracking.
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

## Shipped — 0.5: project intelligence and context provenance

- Project Overview grounded in an existing README, repository instruction
  files, stack markers, recent commits, private operator brief, and one
  cross-run activity timeline.
- Generic bundled and repository-local Markdown Skills with preview and
  project-level Auto, Required, or Disabled policy.
- Automatic or explicit per-task skill selection with immutable skill content
  snapshots and normalized selection/load events.
- Context Receipts that prove the exact project brief, README, instructions,
  Project Memory, and Skills sent to each run, including reasons and digests.
- Project-specific Skill outcomes: observed success, tokens, reported cost, and
  human interventions. Unknown history remains unknown.
- Triggered and folder-scoped Project Memory with enable/disable, explicit
  operator ownership, and history-derived suggestions that require approval.
- Explainable skill routing from task signals, policy, and sufficiently
  observed outcomes on the current repository.
- A first-run path built around one repository and one outcome: guided local
  readiness, inline project registration, a quick task composer, and advanced
  controls disclosed only when requested.
- One-command source installation, a stable `odysseus start` entry point,
  readable/JSON diagnostics, and `odysseus demo` for a no-token product tour.
- A reproducible release-proof gate covering syntax, both installer paths, the
  complete test suite, and Odysseus-on-Odysseus demo/CLI state without claiming
  seeded outcomes as real model work.

Current boundary: the router chooses context Skills, not the agent model.
Project Memory is deterministic and operator-approved; semantic code retrieval,
autonomous fact extraction, shared organizational memory, and vector search are
not claimed.

## Shipped — 0.6: explicit execution environments

- A task chooses `host`, `docker`, or `devcontainer`; the resolved environment
  and honest isolation description are visible in Summary and NDJSON events.
- Docker wraps agent, setup, check, evaluator, and review commands in disposable
  containers with a read-only root filesystem, dropped capabilities,
  `no-new-privileges`, explicit network mode, and CPU/RAM limits.
- Only the task worktree, per-run home, and isolated Git metadata are mounted.
  The main repository `.git`, other repositories, host home, SSH material, and
  Docker socket are not exposed by Odysseus.
- Review commands receive read-only task and Git mounts. Docker tasks can still
  use normal Git inspection without sharing the source repository's metadata.
- Non-secret environment values, automatic loopback preview ports, and
  operator-named credential passthrough are supported. Credential values never
  enter snapshots, events, or the private generated env file.
- Project setup commands run inside the selected profile and persist artifacts
  only through the worktree or per-run home.
- `--untrusted-project` accepts only operator-controlled Docker, ignores
  repository credential requests, and sends repository environment/setup/check/
  evaluator configuration to a one-time **Needs You** gate before execution.
- The release proof includes unit-level command inspection, a scheduler test
  proving zero agent/check calls before approval, and an opt-in real Docker test
  for isolated Git, environment injection, writes, and read-only review.

The default remains `host` for a simple first run. It is deliberately labeled
as compatible but not sandboxed.

## Next — 0.6.x: environment lifecycle and operational hardening

- Long-lived per-task preview processes with explicit start, health, stop, and
  cleanup controls instead of relying on one disposable command lifetime.
- Ephemeral PostgreSQL/Redis/queue sidecars, snapshot/seed policies, and unique
  service namespaces for parallel tasks.
- Podman support, disk/PID limits, outbound host allowlists, signed/allowlisted
  images, and an inspectable command policy.
- Safe runtime/worktree/branch retention and cleanup, verified backup/import,
  and crash tests across approval and container transitions.
- Semantic code/dependency graph overlap prediction and a cross-PR merge queue
  with ordered rebase, rerun, and rollback.
- GitHub webhooks, review-comment classification, and explicit auto-merge
  policies for narrowly trusted changes.

## Planned — 0.7: evidence-based agent routing

- High-value tournament mode: several agents or prompts attempt one ambiguous
  task and an independent judge selects a candidate.
- Per-repository benchmarks: success rate, completion time, correction rate,
  CI failures, cost, tokens, and human interventions by task class and lane.
- Router that chooses an agent from empirical project history, expected
  quality, latency, and cost; every automatic choice remains explainable.
- Semantic project context for architecture, code maps, ADRs, schemas, API
  contracts, recent changes, and known issues, retrieved as a cited subset.
- Analytics for cost per accepted task/merged PR, retry rate, human minutes,
  and **Human Attention per Successful Change**.
- NDJSON export to CSV/Parquet and budget alerts.

## Planned — 0.8: workflow and organization plane

- Organization -> workspace -> project -> epic -> task -> attempt hierarchy.
- Shared organization Skills, task templates, and declarative workflows.
- Path/diff/risk policy engine for required checks, security review, human
  review, and narrowly scoped auto-merge.
- Odysseus MCP server: queue work, read status, answer attention items, and
  query results from another agent session.
- Linear, Jira, Sentry, and richer GitHub ingestion.
- Remote authenticated workers with heartbeats and crash recovery.
- Mobile review and push notifications.

## Cross-cutting adoption track

- Extend the shipped source installer with a Homebrew tap, signed versioned
  artifacts, and an explicit upgrade/rollback path.
- Keep the shipped five-minute first-run flow continuously tested against a
  clean state before asking the operator to configure advanced policy.
- Reproducible dogfooding state and real browser screenshots for every major
  release; examples must be generated from the shipped server, never mockups.
- Secure phone access over an authenticated private-network listener, with
  responsive Needs You, structured answers, diff/review, and terminal handoff.
- Notification actions that answer or defer a structured question without
  opening the full cockpit, while refusing ambiguous terminal keystrokes.
- Import/export for portable generic Skills and an explicit trust review before
  enabling Skills or shell checks sourced from another repository.

## Exploring — 0.9: Attention Autopilot and Flight Recorder

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
