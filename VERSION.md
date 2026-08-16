# Odysseus version and capabilities

## Unreleased

- Nothing yet.

## Current version

**0.7.0 — 2026-08-16**

Version 0.7.0 adds auditable Project Decisions: repository ADR discovery,
multi-select planning, durable source snapshots, and decision-level execution
and economics history.

## What is available in 0.7.0

### 0.7.0 Project Decisions

- `_ADR/` is the recommended project decision catalog. Odysseus also discovers
  common `ADR/` and `docs/adr/` layouts without modifying the repository.
- Repository Overview separates the ADR's recorded status from implementation
  state and shows completed/active/unplanned counts, linked tasks, observed
  tokens, and provider-reported cost. Missing cost remains Unknown.
- Select one or more decisions and choose **Plan selected** to create one
  read-only Planner proposal. Nothing runs until the operator approves its DAG.
- Each selected document is frozen into the Epic with path, content, status,
  byte count, and SHA-256 digest. Materialized tasks receive the same snapshot
  in their Context Receipt.
- Traversal, unsupported folders, oversized selections, and more than twenty
  source documents are rejected before the Planner runs.
- The web UI now uses shorter decision labels: **1 Choose repository -> 2 New
  task -> 3 Review**, **Ask integration agent**, and one visible primary action
  on review and delivery states.

## Earlier 0.6 releases

### 0.6.12 Credential Boundary

- Host-mode agent, setup, check, review, and evaluator commands no longer
  inherit the complete Odysseus server environment.
- Runtime credentials are passed only when their variable names are explicitly
  present in task `allow_env`; repository-supplied `allow_env` remains ignored.
- Docker credential passthrough still uses name-only `--env NAME`, but the
  Docker client process itself is launched with the same scoped environment.
- Context Assistant keys such as `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` stay
  server-only unless an operator deliberately allowlists them for a task.
- `scripts/release-proof.sh` now exercises the 0.6.12 release-candidate path
  end to end: packaging/install, managed upgrade and rollback, demo boot, HTTP
  and real-browser smoke tests, credential isolation, selective artifact
  integration, conflict recovery, resource inventory/reclaim safety, lifecycle
  leases, screenshot routes, production-proof classification, and remote-access
  authentication guardrails.
- The package proof keeps `uv build` as the canonical path but can prove the
  zero-dependency wheel offline when PyPI is unavailable, then installs that
  wheel through `uvx` and verifies the shipped CLI, web assets, and Skills.
- `odysseus resources --json` remains the non-destructive resource inventory
  dry-run. Reclamation still requires the explicit `--reclaim` flag and keeps
  failed worktrees available for recovery.

### 0.6.11 Composed Operator Polish

- An explicit null task title falls back to the first request line in storage,
  IDs, and browser notifications.
- Agent terminals initially show the selected repository, or all saved
  repositories when none is selected. The complete machine-wide view remains
  one deliberate scope change away.
- The top bar includes a persistent light/dark theme switch and a packaged
  Odysseus icon. Light remains the default, including the navigation surfaces.
- The release commit retains all three accepted artifacts as Git parents, so
  their provenance and delivery status are both truthful.

### 0.6.10 Exact On-Demand Tabs

- Direct links and cross-section clicks activate the requested inner tab before
  any heavy panel renderer runs.
- Opening Integration does not issue a Diff request; opening each Evidence tab
  renders only that selected evidence surface.

### 0.6.9 Responsive Task Inspection

- Repository and task navigation use compact run summaries instead of polling
  full snapshots containing checks, context, review logs, and CI output.
- Opening a task fetches only its summary data. Changes, Activity, and each
  Evidence tab load on demand, with bounded browser rendering for large text
  and event histories.
- Task selection is generation-guarded, so late responses and SSE streams from
  a previously selected task cannot overwrite the current view.
- Live SSE starts at the stored event tail instead of replaying the complete
  journal before Activity is opened.
- Apply conflicts now offer **Ask integration agent**, prefilled with a safe
  integration instruction, alongside draft PR and repository status options.

### 0.6.8 Task Intake and Settings

- **Start task** and **Start & add another** clear the submitted request at
  once, disable duplicate submission, show an explicit Starting state, restore
  the draft on failure, and either open the live run or focus a fresh composer.
- Queue capacity is literal: `queued` is displayed as **Waiting to start**.
  The slot count, queued task action, and repository composer all link to one
  Settings surface.
- Settings controls parallel agents, default implementation/planner/reviewer
  lanes, retries, budgets, and CI repair limits without editing JSON.
- Context Assistant settings show which local CLI and direct API providers are
  configured. Direct OpenAI and Anthropic model names may be saved; API keys
  remain server-environment secrets and are never persisted in Odysseus or the
  browser.
- Local Apply acknowledges artifacts already merged into the source branch,
  allows harmless untracked files, preserves untracked collisions, and names
  tracked paths that must be committed or stashed.
- A blocked Apply now includes a short diagnosis, a status command, an optional
  recoverable stash command, and an explicit retry action.

### 0.6.7 Review and Delivery Clarity

- Review Summary presents one numbered **Review -> Test -> Deliver** checklist
  and says explicitly that the agent is finished while nothing has been
  applied.
- **Accept result** snapshots the artifact without touching the source checkout.
  Accepted tasks then offer **Apply to repository**, **Create draft PR**, or the
  safe default of keeping the artifact only.
- Local Apply merges the complete artifact branch, including composed DAG
  predecessors. It refuses a dirty checkout, detached HEAD, wrong branch,
  missing artifact, or rewritten base history and aborts conflicts.
- Delivery state records the method, target branch, before/after SHAs, timestamp,
  and failure detail in JSON and append-only NDJSON events.
- Successful review feedback is **Request changes**, while failed and attention
  states retain the focused recovery editor.
- Native confirmations were replaced with an Odysseus dialog that supports X,
  Cancel, and Escape. Empty/null notifications now have readable fallback text.
- The Review stage visibly remains current until acceptance and becomes complete
  after acceptance instead of appearing inactive.

### 0.6.6 Guided Recovery and Context Assistant

- `Failed`, `Review`, and `Needs You` place a recovery editor and **Resume with
  feedback** directly below the status narrative. **Continue in terminal** is
  secondary and never required for the normal workflow.
- A persistent right-side conversation can use the locally authenticated Codex
  CLI or Claude Code CLI without another API key. Optional direct ChatGPT and
  Claude modes use server environment keys.
- Operators explicitly choose Task, Failure, Review, Checks, and Diff/code
  context. Diff/code is off by default; narrowing context also excludes older
  answers derived from scopes that are no longer enabled.
- Local assistant CLIs run from a disposable blank workspace. Run-derived
  strings are secret-redacted before prompt construction, including task text
  and check commands. An explicit empty context selection remains empty.
- Assistant answers can be inserted, submitted to the saved thread, copied, or
  queued as a separate task. Accepted and published runs retain follow-up flow
  without showing a failure recovery card.
- Host checks preserve the Odysseus server's `PATH` instead of starting a login
  shell that can silently fall back to an older system Python on macOS.
- Codex continuation places execution options before the `resume` subcommand,
  matching the current Codex CLI and preserving the task worktree and sandbox.

### 0.6.5 Repository Clarity

- Odysseus is always identified as the application. A project is explicitly
  one local Git repository, and a task is one natural-language change for an
  agent.
- Automatic project names come from the Git remote (`owner/repository`) instead
  of an arbitrary local folder. The checkout folder and full path stay visible
  as separate location metadata.
- Multiple checkouts of one repository share the repository identity and are
  distinguished by folder, so an old clone and a development checkout are no
  longer presented as unrelated products.
- Starting Odysseus inside an unregistered Git repository produces a one-click
  **Use this repository** suggestion. No registration write occurs until the
  operator chooses it.
- The Explorer no longer duplicates task trees inside project trees or mixes
  every repository's tasks by default. Tasks appear after choosing a project;
  infrequent Plans, Follow-ups, GitHub, Insights, and management surfaces live
  under **More**.
- Tmux discovery is read-only. Merely seeing a Codex or Claude pane can no
  longer register its directory—or an internal Odysseus worktree—as a project.
  Existing internal worktree records are hidden from the user project list;
  explicit **Track in Odysseus** still creates the durable entry.
- **Your repositories** now explains that it is the saved local list and offers
  a direct **Remove** action. Removing an entry never deletes its checkout or
  files.
- Step 2 is named **New task** everywhere. The implementation agent is visible
  in the primary composer, and **Start & add another** queues successive tasks
  for parallel execution without leaving the form.
- New registrations accept only Git repositories. Legacy plain folders are
  omitted from the web UI instead of appearing as unexplained projects.
- **Forget** removes a stale repository from Odysseus while explicitly leaving
  the repository directory and its files untouched.

### 0.6.4 Clarity

- A persistent, clickable three-step path now anchors the web workbench:
  **1 Choose repository -> 2 New task -> 3 Review**.
- The current step is visually distinct. Completed and upcoming steps remain
  visible, and each step takes the operator directly to the relevant surface.
- First-run readiness is presented as unnumbered diagnostics, so it no longer
  competes with the actual product workflow.
- The task composer speaks in Codex terms: one natural-language outcome is the
  only required input. Agent, check, Skill, budget, and environment overrides
  remain under **More options…**.
- Task details repeat step 3 and explain the operator's job: watch progress and
  act when Odysseus asks. Imported tmux sessions do not claim this managed flow.
- The same model becomes a compact vertical sequence on narrow and mobile
  screens. All orchestration, evidence, policy, and terminal capabilities from
  0.6.3 remain available through progressive disclosure.

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
| Application version | `0.7.0` |
| Run snapshot schema | `12` |
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
