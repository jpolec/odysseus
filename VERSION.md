# Odysseus version and capabilities

## Current version

**0.6.3 — 2026-08-15**

Version 0.6 adds an explicit runtime boundary without making the simple local
path harder. Host mode remains the compatibility default; Docker and reviewed
devcontainers are opt-in task profiles.

## What is available in 0.6.3

### 0.6.3 Observed Production Proof

- Run snapshot schema 9 adds a provenance envelope: evidence class, origin,
  Odysseus version, release label, and observation time. New web, CLI, Planner,
  GitHub, and Inbox tasks are observed; tmux imports are classified separately.
- `odysseus proof` counts only terminal attempts whose complete journal proves
  ordered start, agent activity, and outcome events. Early failures remain in
  the denominator. Accepted changes and draft PRs additionally require final
  verifier success followed by artifact creation and the outcome event.
  Queued/active records and status-only edits cannot inflate the sample.
- Accepted artifacts and opened draft PRs are separate. Missing cost remains
  unobserved with a coverage ratio; CI recovery must end green and crash
  recovery must show later progress to a terminal outcome.
- Explicit user decisions and Needs You response latency replace inferred human
  time. Automatic attention resolution never counts as an intervention.
- Every included run receives a privacy-reduced receipt over its private source
  evidence and complete, untruncated journal. The aggregate SHA-256 also binds
  evidence policy, classifications, threshold, sufficiency, and metrics.
- Demo, test, imported tmux, and legacy unclassified runs never contribute to
  production numbers. The default 20-run threshold is visible and optionally
  enforceable with `--require-sufficient`.
- Legacy Epic schema 1 plans materialize as unclassified instead of silently
  turning into observed production evidence. `.odysseus.json` makes the repository directly runnable through its own
  workflow. `scripts/dogfood.sh` starts it, queues work on itself, reports
  observed status, and writes JSON/Markdown release receipts.

### 0.6.2 Stable Install Lifecycle

- The remote shell installer resolves the latest non-draft, non-prerelease
  GitHub release tag. `main` is available only through explicit `--edge`;
  `--version` and `--ref` pin an exact target.
- Managed releases live side by side. `current` and `previous` symlinks are
  switched atomically, so an update never rewrites the running checkout.
- Every activation, including a first managed install over existing state,
  takes a file-locked backup of mutable JSON/NDJSON while leaving worktrees and
  runtime in place. SHA-256 metadata binds the archive to its state directory.
- Restore extracts and strictly verifies JSON, NDJSON, record identities, and
  supported schemas in staging before a transaction replaces live records.
  Corrupt or interrupted restores leave the current state and release active.
- `odysseus version`, `update --check`, `update`, and `rollback` expose the
  lifecycle. A downgrade across run-schema versions requires the explicit
  `rollback --restore-state` recovery path.
- Ownership-checked lifecycle and state-maintenance locks prevent concurrent
  installers and new servers. Update/rollback refuse a live server or worker.
  `odysseus state verify` provides a strict, non-destructive storage audit.
- The release proof performs a real 0.6.1 -> 0.6.2 update, downgrade refusal,
  corrupt-backup refusal, verified restore, command-link preflight, and first
  managed install over existing state.
- Repeating `odysseus start` opens the already running instance when possible;
  an unrelated port owner produces a short remediation message, never a
  traceback or a half-started background scheduler.
- pipx and uvx remain owned by their package managers; the CLI explains the
  correct upgrade command rather than stealing their command link.

### 0.6.1 Release Integrity and Standard Packaging

- `pyproject.toml` ships the zero-runtime-dependency `odysseus` console entry
  point as the `odysseus-agents` distribution, including the web UI, demo,
  tmux helper, and generic Skills. A clean wheel is exercised through `uvx`.
- PR CI remains a fast Python 3.10/3.13 matrix. Actions are pinned to immutable
  commits. Pushes to `main` run the full proof; tag commits must belong to main,
  and the read-only proof/build job must pass before a separate minimal
  write-permission job can publish checksum-bearing source/wheel artifacts.
- Exact-commit installer tests work from branches, tags, and detached CI
  checkouts instead of assuming a branch name.
- The release proof includes packaged and checkout HTTP boot, health,
  bootstrap-version, asset, Skill, and clean-shutdown checks.
- HTTP request threads and SSE streams have explicit, independently visible
  concurrency limits. Slow sockets time out and live streams exit when the
  server stops. The stdlib server remains intentionally single-operator rather
  than a multi-tenant application tier.
- README positioning now leads with the product's verifiable properties: no
  runtime dependencies, no database, append-only NDJSON, and a terminal-first
  workflow.

### 0.6.0 Explicit Execution Environments

- Every run stores and displays a resolved `host`, `docker`, or `devcontainer`
  execution plan. The web form keeps it under Advanced; the CLI exposes the
  complete profile without changing the one-command first run.
- Agent, setup, check, evaluator, and review commands all use the same resolved
  profile. Host mode is explicitly labeled as not isolated.
- Docker commands use a read-only root filesystem, dropped capabilities,
  `no-new-privileges`, explicit network mode, CPU/RAM limits, an automatic
  loopback port map, and only three scoped mounts: task worktree, per-run home,
  and isolated task Git metadata.
- The Docker container can use normal Git inspection without seeing or changing
  the source repository's `.git`. Reviewer mounts are read-only.
- Non-secret environment values may be stored in the task plan. Credentials use
  name-only allowlisting; values are resolved from the server environment at
  runtime and never enter run snapshots, events, or the private env file.
- A reviewed repository can supply environment defaults and idempotent setup in
  `.odysseus.json`; operator task options override them, and repository
  `allow_env` entries are ignored.
- `--untrusted-project` requires Docker. When the repository supplies an
  environment, setup, check, or evaluator, Odysseus stops before the agent and
  presents the exact configuration as a structured **Needs You** permission
  request with approve/reject.
- `doctor` and `/api/bootstrap` report Docker and devcontainer availability.
  Summary shows isolation, image, network, resources, ports, credentials names,
  status, and preview URL without revealing secret values.
- The automated suite includes command-policy, secret-persistence, port/env,
  untrusted-gate, schema migration, CLI/API, and scheduler coverage. An opt-in
  real Docker test proves isolated Git, writes, environment injection, and
  read-only review against `node:20-bookworm`.

### 0.5.4 Product Proof and Simpler First Run

- `install.sh` supports a reviewed checkout install and a one-command GitHub
  install, creates only an `odysseus` command link, refuses to overwrite an
  unrelated file, and finishes with a local readiness check.
- `odysseus start` is the plain-language entry point for the scheduler and web
  UI. `odysseus demo` opens a disposable populated tour without agent tokens.
- `doctor` now defaults to a readable required/optional dependency report and
  retains stable machine output through `doctor --json`.
- A clean state opens with repository registration and real capability status.
  A selected project opens with one inline outcome field; default routing,
  Skills, worktree isolation, checks, and review are applied automatically.
- Advanced task settings remain one click away and preserve the draft. Project
  Skills, Memory, Git history, and the audit timeline are grouped under one
  progressive-disclosure section instead of dominating routine work.
- The deterministic demo and nine-view screenshot capture path remain tied to
  shipped fresh/demo server state rather than UI mockups.

### 0.5.3 Project Memory and Explainable Skill Routing

- Project Memory stores repository-specific guidance separately from generic
  engineering Skills. Each item has task triggers, optional folder signals,
  source, enable/disable state, and operator-owned content.
- Matching memory is frozen into the same per-run Context Receipt as README,
  instructions, brief, and Skills. `knowledge.selected` records why it matched.
- Repeated review guidance, check failures, and CI failure summaries may appear
  as suggestions. They remain disabled until an operator reviews and saves
  them; Odysseus never silently trains on its own output.
- `project-skill-router-v1` ranks eligible Skills from task signals, required or
  disabled project policy, and sufficiently observed project outcome and human
  intervention history. New Task previews what Auto will attach and why.
- CLI tasks support `--skill-mode auto|manual|none` and repeatable `--skill` for
  explicit manual selection.

### 0.5.2 Context Receipts

- Every autonomous run freezes the exact project brief, README, repository
  instructions, and selected skill snapshots attached at queue time.
- `context-receipt-v1` records the task digest, source paths, source kinds,
  selection reasons, byte sizes, individual digests, and one complete bundle
  digest. A later repository edit cannot silently change the recorded context.
- The Evidence -> Context inspector reveals both provenance and snapshot
  content; `context.receipt.created` preserves creation in append-only NDJSON.
- Per-project skill history reports observed runs, accepted outcomes, average
  tokens/cost, and human interventions. Sparse history stays explicitly
  unknown instead of presenting a misleading success percentage.

### 0.5.1 Generic Project Skills

- A bundled catalog covers security, databases, tests, API contracts, frontend
  accessibility, dependencies, performance, incidents, and documentation.
- Project-local skills can live in `.agents/skills`, `.github/skills`, or
  `.claude/skills`; they apply only to that repository and override a bundled
  skill with the same name.
- Project Overview previews every skill and controls its Auto, Required, or
  Disabled policy. New Task keeps automatic selection as the default and puts
  manual selection behind Advanced.
- Selection reason, source, relative path, and SHA-256 digest are stored on the
  run. The scheduler loads the immutable skill snapshot and records
  `skill.selected` and `skill.loaded` events.

### 0.5.0 Project Knowledge

- Project Overview reads an existing repository README without modifying it,
  detects common agent-instruction files and stack markers, and shows recent
  Git commits beside Odysseus work.
- A private Project Brief and operator notes live in Odysseus state, so teams
  can add onboarding context without creating or rewriting repository files.
- Significant events from every task are projected into one project timeline
  that answers what changed, how it progressed, and where to inspect evidence.
- Every displayed repository source includes its relative path and content
  digest, laying the provenance foundation for later context receipts.

### 0.4.3 project-first workbench

- A single visible hierarchy—workspace, project, task—replaces the flat row of
  product features. The Explorer owns project selection and reveals recent
  tasks inside the selected repository.
- The default All work surface summarizes projects, active tasks, operator
  decisions, and completed outcomes; a project surface summarizes that
  repository's tasks, decisions, and discovered terminal count.
- A compact Activity Bar holds global exception, terminal, Inbox, search, and
  GitHub entry points without competing with the selected project.
- New task requires only the outcome and project. Agent, checks, retries,
  priority, and budgets are hidden under one customization disclosure.
- Task detail opens on Summary and offers three deeper surfaces: Changes,
  Activity, and Evidence. Run ids, branches, worktrees, dependencies, cache,
  and tool telemetry remain available under Technical details.
- The visual system follows a quiet workbench vocabulary: Segoe typography,
  compact toolbars, tree navigation, restrained surfaces, blue focus states,
  and mobile bottom navigation.

### 0.4.2 visual hierarchy patch

- A refined light visual system with clearer navigation, spacing, depth,
  typography, active states, and responsive behavior.
- Every autonomous task explains its current step, what Odysseus is doing, and
  whether the operator needs to act; technical metadata is collapsed by
  default.
- Agent terminals show a four-signal summary, default to the current attached
  tmux sessions, group panes by session, and distinguish Codex and Claude
  visually without inventing telemetry.
- Needs You has a real all-clear state with direct paths to start a task, plan
  multi-task work, or inspect terminals.
- Screenshot URLs can select a task inspector tab or open a form dialog. The
  deterministic capture script now produces six correctly named browser views
  instead of labeling the default Diff view as Integration/CI.

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
| Application version | `0.6.3` |
| Run snapshot schema | `9` |
| Epic snapshot schema | `1` |
| Event envelope version | `1` |
| Export format | `odysseus-state-v1` |
| Python | `3.10+` |
| tmux | `3.2+` recommended |
| Built-in lanes | Codex CLI, Claude Code |

The local HTTP API is documented but not yet stable. Consumers should check
the application, run-schema, event-envelope, and export-format markers.

## Known boundaries

- Merge prediction is exact at the file surface and authoritative at the real
  Git merge. Semantic code-graph conflict prediction and a cross-PR merge queue
  remain future work.
- CI integration polls through authenticated GitHub CLI. It is not yet a
  webhook receiver, and Odysseus never auto-merges the pull request.
- Review comments are normalized and can be sent back to the agent; there is no
  learned comment classifier.
- Token/tool/cost limits depend on telemetry emitted before process
  termination. Providers that omit a metric cannot be limited by that metric.
- Host worktrees still isolate only repository changes, not the process. Docker
  adds scoped files, environment, network mode, CPU, and RAM, but it is not a
  formally verified sandbox and the selected image/Docker engine remain trusted.
- Docker execution is command-scoped. Long-lived preview process lifecycle,
  ephemeral database/queue sidecars, disk/PID quotas, signed image policy, and
  outbound host allowlists remain future 0.6.x work.
- Devcontainers are repository-defined and therefore intended only for reviewed
  repositories; they are rejected by `--untrusted-project`.
- Project discovery is deterministic and read-only; semantic repository
  retrieval and autonomous knowledge extraction are not
  part of 0.5.4. History creates reviewable suggestions, not trusted memory.

## Upgrade from 0.4 or earlier

Stop the running server and back up the complete state directory, then:

```sh
git pull --ff-only
./install.sh
odysseus doctor
python3 -m unittest discover -s tests -v
odysseus start
```

Opening the state store adds schema-8 environment defaults to older run snapshots. Event
journals remain append-only and are not rewritten. Existing branches,
worktrees, tmux sessions, project registrations, and 0.3 Epics are preserved.
An old accepted run without an artifact SHA remains visible; resume/review and
accept it once under 0.4 before using it as a new downstream dependency.

## Version history

### 0.6.0 — Explicit Execution Environments

Added host/Docker/devcontainer task profiles, isolated task Git for Docker,
scoped environment and name-only credentials, automatic preview ports,
resource/network controls, read-only review mounts, and an approval gate that
prevents untrusted repository commands or agents from running prematurely.

### 0.5.4 — Product Proof and Simpler First Run

Added the source installer, plain-language start/demo/doctor commands, guided
repository onboarding, an inline quick-task composer, and progressive project
depth without removing the existing orchestration controls.

### 0.5.3 — Project Memory and Explainable Skill Routing

Added triggered/folder-scoped project memory, enable/disable and history-based
suggestions with operator approval, explainable project-history skill routing,
and automatic-selection previews in New Task.

### 0.5.2 — Context Receipts

Added immutable, hashed per-run context snapshots; an Evidence inspector for
exact provenance; and project-specific skill outcome, token, cost, and human
intervention statistics.

### 0.5.1 — Generic Project Skills

Added generic bundled and project-local skills, preview and project policy,
automatic or manual task assignment, immutable per-run skill snapshots, and
auditable selection/load events.

### 0.5.0 — Project Knowledge

Added evidence-backed Project Overview, README/instruction discovery, private
project briefs, stack markers, recent Git commits, and a cross-run project
activity timeline.

### 0.4.3 — project-first workbench

Reorganized the entire web console around workspace -> project -> task, added a
project Explorer and overview, reduced task creation to two decisions, grouped
task depth into Summary/Changes/Activity/Evidence, and introduced a compact
Fluent-inspired desktop and mobile shell.

### 0.4.2 — visual hierarchy

Refined the complete light UI, added plain-language workflow state, terminal
summaries and filtering, collapsible technical metadata, a useful all-clear
state, and deterministic deep links for real screenshot capture.

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
