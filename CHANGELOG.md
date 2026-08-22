# Odysseus changelog

This is the chronological, user-facing history of Odysseus, grouped by the day
changes reached `main`. Merge-only bookkeeping is omitted.

- [VERSION.md](VERSION.md) is the detailed capability, compatibility, and
  upgrade reference.
- [ROADMAP.md](ROADMAP.md) describes planned work.
- [GitHub Releases](https://github.com/jpolec/odysseus/releases) contains
  published stable release records.

Dates use repository commit dates. Exact implementation history remains in
Git; this file records observable operator and product changes.

## Unreleased

- Added a full-screen Plan Studio that turns ADRs, specifications, issues,
  incidents, findings, milestones, document sets, or direct requirements into
  versioned execution contracts before any implementation starts.
- Added bidirectional source-clause ↔ task mapping, editable task outcomes and
  prompts, acceptance criteria, required evidence, dependency-aware DAGs, and
  complete Execution Profiles spanning Auto/override routing, harness, model,
  Skills, environment, policy, and independent review.
- Added immutable PlanVersion history, source-content hashes, targeted source
  impact analysis, explicit source refresh, and honest cost/time ranges with a
  confidence label and estimation basis.
- Copied the approved task contract, source links, execution profile, estimate,
  and plan version into each materialized run; interpreted common Codex-version
  and MCP-auth failures into actionable recovery guidance while retaining raw
  evidence.
- Separated wall-clock elapsed, active compute, model tokens, cache-read
  tokens, observed billable tokens, and provider-reported cost so large cached
  histories no longer masquerade as active or billable work.
- Enlarged Activity typography and added a wide event stream below the retained
  task context. It uses the full workspace width by default, has distinct actor
  backgrounds, and offers diagonal expand/narrow controls plus Escape.
- Added honest task economics beside the prompt and inside Activity: total
  elapsed time, observed Agent/Checks/Review time, per-event relative timing,
  reported event cost where available, and total observed provider cost.
- Compacted the Decision Assistant, reduced its empty-state whitespace, and
  exposed Copy answer and Create separate task without a More disclosure.
- Balanced sidebar identity with a 23 px target mark and one-step larger
  Odysseus wordmark.
- Replaced the vague graph/Gantt link with a visible Open delivery plan action,
  plain-language Dependencies and Timeline & cost sections, per-task observed
  or explicit estimated/cap costs, and repository cost coverage.
- Expanded every primary surface—task Overview, Changes, Activity, Evidence,
  Needs You, Plans, Skills, Outcomes, terminals, repositories, GitHub issues,
  follow-ups, and Settings—to use the full workspace beside the repository
  sidebar by default.
- Reworked the web shell around four primary operator surfaces: Home, Needs
  You, Plans, and Outcomes, while keeping repositories and task history in the
  persistent sidebar.
- Added one direct Home composer that asks what the agent should change and
  starts the existing Task flow immediately with Agent Auto; repository,
  advanced overrides, and approval-gated Plans remain explicit when needed.
- Made every New task entry point return to the same composer, removed the
  intermediate Continue and Plan-first choice, and reduced the default task
  form to one primary Start task action.
- Reworded the review handoff as Approve change followed by Apply to repository,
  preserving the durable approval/application boundary without exposing
  artifact terminology in the primary flow.
- Made task pages decision-first: Follow, Decide, and Deliver change with the
  lifecycle, while workflow stages, usage, CI, and environment remain available
  in one compact execution disclosure.
- Made proposed Plan graphs visible for approval and active Plan graphs
  collapsible behind live task, dependency, attention, and acceptance counts.
- Moved the engineering portfolio to the Outcomes page so Home is no longer a
  dashboard hidden inside a task composer.
- Grouped Settings into execution, resource lifecycle, and optional assistant
  sections with progressive disclosure.
- Unified the visual system around a warm neutral canvas, black primary
  actions, cherry identity, a resizable repository sidebar, and responsive
  layouts verified in the real-browser regression suite.
- Made the sidebar the only global navigation surface, increased its type size,
  tightened vertical density, and reduced task entries to one-line rows with
  compact outcome metadata and an on-hover detail preview.
- Added screen-aware Help as a shared right column. It explains the current
  surface, its colors, and the next operator action without changing work.
- Made sidebar search focus the global field, added clear-on-Escape behavior,
  removed the redundant top-bar Live label, and added safe syntax coloring to
  task diffs and verification output.
- Restored the light-red concentric Odysseus target mark and normalized task
  status colors: green done, orange working, blue question, red needs action.
- Shifted the shell to cool neutral grays and navy text, enlarged sidebar
  identity and icons, removed the redundant Home link and repeated Odysseus
  page eyebrow, and focused Repositories on adding or choosing local folders.
- Removed redundant eyebrows from every primary page header and moved secondary
  navigation behind a bottom-anchored More disclosure while keeping Skills and
  Terminals immediately available.
- Removed the repeated Follow/Decide/Deliver badge from task headings and
  matched the contextual Help column to the sidebar surface.
- Replaced the fragmented task header with one compact repository/status/agent
  bar and added a canonical Executed → Verified → Accepted → Published →
  Integrated → Deployed → Observed → Healthy/Regressed lifecycle with the next
  action and responsible actor stated explicitly.
- Replaced precise-looking uncalibrated confidence scores with qualitative
  evidence strength, while showing hard gates, independent review, unknowns,
  CI, observed cost, and sample size separately.
- Renamed Context Assistant to Decision Assistant, made its destination and
  consequences explicit, and moved copy/queue actions behind a secondary
  disclosure.
- Added status-color filters beside Active, All, and Review; task dots are now
  flat green/orange/blue/logo-red markers without decorative halos.
- Added observed cost to every sidebar task row and hover preview, preserving
  unknown provider cost as an explicit dash rather than a misleading zero.
- Reworked Activity into a readable causal conversation that distinguishes
  operator input, agent messages and questions, tool commands/results,
  independent review, Git, failures, and system events while retaining the
  canonical event type and timestamp.
- Cleaned conversational prompts into concise display titles while retaining
  the full original task instruction as the durable body.
- Added current-folder repository registration with visible Git/path preflight,
  clearer Plan critical-path/parallelism/gate/budget signals, and token-budget
  warnings before exhaustion.
- Allowed Codex workspace-write runs to access only the linked worktree Git
  metadata directory they require, eliminating `.git/worktrees` index-lock
  failures without granting full-disk access; recovery now explains and retries
  that exact condition.
- Aligned first-pass and autonomous-delivery metrics to the delivered-task
  cohort, preserved unknown cost as unknown, and marked small Skill samples as
  low-confidence observations.

## Released history

## 2026-08-20

### [0.9.2](https://github.com/jpolec/odysseus/releases/tag/v0.9.2) — Worker Leases and fencing

- Added durable per-run WorkerLease v1 records with scheduler worker identity,
  heartbeat TTLs, and monotonically increasing fencing epochs.
- Fenced every scheduler-worker run mutation and activity append through its
  exact lease token; an expired or replaced worker can no longer overwrite a
  successor's run state, append late output, or release the successor's lease.
- Made scheduler shutdown, explicit cancellation, expired-owner takeover, and
  post-terminal lease recovery preserve the intended run state.
- Revalidated the exact lease heartbeat, epoch, cancellation intent, and run
  status under the store lock before recovery, preventing a stale scan from
  re-queueing a worker that had just renewed its lease.
- Made cancellation intent and terminal transitions canonical-event atomic;
  recovery finalizes a durable cancellation instead of silently re-queueing it.
- Ordered Variants cancellation as parent intent, child intents, then terminal
  parent state; a completed cancellation can no longer be re-queued during
  concurrent scheduler shutdown.
- Added deterministic failpoints and a real subprocess crash matrix across
  canonical fsync, claim, heartbeat, cancellation, recovery, and artifact
  snapshot windows.
- Rebuilt stale run projections and checkpoints from the canonical stream after
  a crash, and made an interrupted Git artifact snapshot safely retryable
  without creating a second commit.
- Treated HTTP clients disconnecting during request reads or response writes as
  normal transport lifecycle events instead of printing server-side tracebacks.

## 2026-08-19

### [0.9.1](https://github.com/jpolec/odysseus/releases/tag/v0.9.1) — Idempotent Command API

- Added one durable Command Bus for mutating HTTP requests and supported CLI
  control commands, with versioned envelopes, command IDs, actor labels,
  policy context, and redacted payloads/results.
- Added caller-supplied idempotency keys so an exact retry returns the original
  result without executing the mutation twice; conflicting key reuse fails
  closed.
- Added optimistic concurrency through expected canonical stream versions and
  explicit conflicts that leave the newer run projection untouched.
- Persisted completed, failed, executing, and unknown command receipts under
  local state, exposed through CLI and HTTP inspection endpoints.
- Made interrupted outcomes deliberately unknown and non-retriable with the
  same key, while distinguishing a live owner from a process that ended.
- Propagated command and idempotency provenance into canonical run events and
  included command receipts in strict state verification.
- Added focused duplicate, conflict, interruption, live-owner, redaction,
  HTTP, CLI, and state-integrity tests plus operator feature guides.

### [0.9.0](https://github.com/jpolec/odysseus/releases/tag/v0.9.0) — Durable event kernel and replay

- Made a per-run EventEnvelope v2 stream the canonical source for run state;
  run JSON is now a deterministic, replaceable projection.
- Added contiguous stream versions, SHA-256 hash chaining, projection hashes,
  checkpoints, immutable schema upcasting, and strict tamper detection.
- Added `odysseus replay RUN_ID`, historical `--until-event` replay, and
  `odysseus rebuild-projections` with dry-run and machine-readable modes.
- Extended `odysseus state verify` to validate canonical streams, projection
  equality, checkpoints, legacy state, and measured replay throughput.
- Added journal-first crash recovery that repairs a missing/stale projection
  and reconciles an operator event written only to the canonical stream before
  process death.
- Added focused deletion, corruption, crash-window, migration, historical
  replay, state verification, and bit-for-bit rebuild tests.
- Kept repository-only hidden files out of public release checksums, SBOM, and
  provenance so every listed subject is an uploaded asset.

### [0.8.2](https://github.com/jpolec/odysseus/releases/tag/v0.8.2) — Correctness and trust foundations

- Repositioned Odysseus as the free, local delivery system for coding agents:
  outcome in, independently verified artifact out.
- Reworked the README around the repository-to-delivery workflow, concise
  installation, source-checkout protection, and operator use cases.
- Added a product comparison covering local agent managers, hosted agents,
  workflow platforms, and Odysseus's evidence/delivery model.
- Added four reproducible films for task execution, Plan/DAG,
  recovery/terminal handoff, and evidence/delivery/portfolio.
- Added an inline 15-second README animation linked to the 45-second tour,
  clickable workflow posters, and reproducible video build tooling.
- Added a reproducible 90-second walkthrough recorded from the real web UI and
  disposable demo state without invoking an agent or spending model tokens.
- Added deterministic capture tooling and a poster for the complete tour.
- Added the outcome-control-plane master plan, implementation DAG, formal
  invariant registry, invariant coverage proof, and explicit threat model.
- Added release-consistency, supply-chain, installer, security, main-proof, and
  release-proof governance with pinned GitHub Actions and checksum, SBOM, and
  provenance assets.
- Corrected Pareto evaluation so missing evidence or cost remains unknown
  instead of becoming a favorable zero.
- Enforced the durable sensitive-data boundary through normalized redaction.
- Removed redundant UI controls and metrics, made Portfolio and Needs You more
  decision-first, and reduced empty interface density.
- Cached portfolio projections, scheduler snapshots, idle scans, and Plan
  refreshes to reduce unnecessary background work.
- Added a versioned `RouteObservation` that records the actual worker/model,
  Skills, selection source and propensity, router metadata versions, timing,
  observed usage/cost, and outcome without expanding routing authority.
- Audited eleven retained task branches: ten were superseded by newer `main`
  implementations; only the missing RouteObservation was integrated.

## 2026-08-17

### [0.8.1](https://github.com/jpolec/odysseus/releases/tag/v0.8.1) — Decision-first task flow

- Reduced New Task to outcome, repository, and **Agent: Auto** by default;
  runtime, Skills, verification, variants, budgets, and retries moved behind
  progressive disclosure.
- Made outcome routing explain its evidence and explicitly fall back when the
  local sample is too small; manual worker selection remains available.
- Replaced uncalibrated confidence language with **Evidence score N/100** and
  separated failed evaluation from inconclusive evidence needing review.
- Grouped Needs You events by task while reporting task and decision counts
  separately.
- Renamed the gate to **Accept artifact** and made acceptance-versus-delivery
  semantics explicit.

## 2026-08-16

### [0.8.0](https://github.com/jpolec/odysseus/releases/tag/v0.8.0) — Outcome-driven delivery

- Added the Engineering Portfolio with delivered outcomes, autonomous and
  first-pass rates, intervention, observed cost coverage, worker effectiveness
  with sample size, failure attribution, and blockers.
- Added shadow outcome routing with transparent recommendations,
  counterfactual evidence, sparse-sample safeguards, export, and backtesting.
- Added authenticated GitHub Issue intake that redacts/deduplicates evidence
  and creates an approval-gated Plan instead of silently starting work.
- Added repository delivery status, dependency graph, task timeline, generic
  Skills management, and explicit integration language.
- Introduced the calmer neutral visual system and light default theme without
  adding a remote font or frontend runtime dependency.

### [0.7.0](https://github.com/jpolec/odysseus/releases/tag/v0.7.0) — Project Decisions

- Added `_ADR/` and conventional ADR discovery, keeping decision status
  separate from implementation status.
- Added selection of decisions and a read-only Planner proposal;
  implementation remains blocked until the operator approves the DAG.
- Bound source paths, content, status, byte counts, and SHA-256 digests to the
  Epic and every materialized task Context Receipt.
- Added traversal, directory, count, and size protections for source documents.

### [0.6.12](https://github.com/jpolec/odysseus/releases/tag/v0.6.12) — Credential boundary and stabilized delivery

- Prevented host agent, setup, check, reviewer, and evaluator commands from
  inheriting the complete server environment.
- Passed credentials only through explicit task `allow_env` names and kept
  Context Assistant credentials server-only by default.
- Strengthened accepted-artifact integration, conflict recovery, resource
  lifecycle, remote-access guardrails, and release proof coverage.
- Preserved explicit inventory/reclaim behavior and recoverable failed
  worktrees instead of silently cleaning them up.

### [0.6.11](https://github.com/jpolec/odysseus/releases/tag/v0.6.11) — Composed operator polish

- Fixed null task titles, improved repository-scoped terminal discovery, and
  added a persistent theme switch with packaged icon assets.
- Composed accepted fixes while retaining Git parents and truthful provenance.

### [0.6.10](https://github.com/jpolec/odysseus/releases/tag/v0.6.10) — Exact on-demand tabs

- Made deep links activate the requested tab before expensive rendering.
- Stopped Integration from loading Diff and made Evidence fetch only the
  selected surface.

### [0.6.9](https://github.com/jpolec/odysseus/releases/tag/v0.6.9) — Responsive task inspection

- Replaced heavyweight navigation polling with compact summaries and
  lazy-loaded Changes, Activity, and Evidence.
- Added generation guards so stale requests/SSE cannot overwrite a new task.
- Added explicit **Resolve integration** recovery for merge conflicts.

### [0.6.8](https://github.com/jpolec/odysseus/releases/tag/v0.6.8) — Task intake and Settings

- Made Start Task and Start & add another clear drafts, prevent duplicates,
  show starting state, and recover the draft on failure.
- Added one Settings surface for parallel slots, lanes, retries, budgets, CI
  repair, assistant providers, and safe API-key status.
- Improved blocked Apply diagnostics and allowed harmless untracked files while
  preserving collision safety.

### [0.6.7](https://github.com/jpolec/odysseus/releases/tag/v0.6.7) — Review and delivery clarity

- Added the Review → Test → Deliver checklist and made it explicit that agent
  completion does not modify the source checkout.
- Split artifact acceptance from local integration and draft-PR creation.
- Added guarded merge preconditions, conflict abort, delivery receipts, and an
  accessible Odysseus confirmation dialog.

### [0.6.6](https://github.com/jpolec/odysseus/releases/tag/v0.6.6) — Guided recovery and Context Assistant

- Put Resume with feedback below failures and decisions; terminal continuation
  became a secondary escape hatch.
- Added a persistent local Codex/Claude context assistant with explicit context
  chips, redaction, answer insertion/submission/copy, and new-task flow.
- Preserved the same thread, branch, worktree, sandbox, and toolchain PATH.

## 2026-08-15

### [0.6.5](https://github.com/jpolec/odysseus/releases/tag/v0.6.5) — Repository clarity

- Defined the nouns literally: Odysseus is the application, a repository is one
  Git checkout, and a task is one requested agent change.
- Derived identity from Git remotes while preserving checkout folder/path and
  suggested the current unregistered repository without writing.
- Made tmux discovery read-only and hid internal worktrees from repositories.
- Added safe Remove/Forget and multi-task submission from one composer.

### [0.6.4](https://github.com/jpolec/odysseus/releases/tag/v0.6.4) — Explicit three-step workflow

- Added **1 Choose repository → 2 New task → 3 Review** on desktop and mobile.
- Reduced default input to one outcome while keeping advanced controls under
  More options.

### [0.6.3](https://github.com/jpolec/odysseus/releases/tag/v0.6.3) — Observed production proof

- Added provenance classification, strict ordered-event eligibility, privacy-
  reduced run receipts, aggregate hashes, honest cost coverage, and thresholds.
- Excluded demos, tests, tmux imports, status-only edits, and legacy records
  from production metrics.
- Added dogfooding commands and public Markdown proof receipts.

### [0.6.2](https://github.com/jpolec/odysseus/releases/tag/v0.6.2) — Stable install lifecycle

- Made the installer resolve stable releases by default while requiring an
  explicit edge/ref/version choice for non-stable code.
- Added atomic activation, locked backups, verified restore, update checks,
  update, rollback, and strict state verification.
- Added live-server protection, ownership checks, port handling, and
  package-manager-aware pipx/uvx guidance.

### [0.6.1](https://github.com/jpolec/odysseus/releases/tag/v0.6.1) — Release integrity and packaging

- Added the zero-dependency Python package, console entry point, wheel, uvx
  verification, packaged web/demo/tmux/Skills assets, and exact-ref install.
- Added fast CI, full proof, tag ancestry checks, pinned Actions, release
  artifacts, and packaged HTTP smoke tests.
- Added bounded stdlib HTTP/SSE concurrency and shutdown behavior.

### [0.6.0](https://github.com/jpolec/odysseus/releases/tag/v0.6.0) — Explicit execution environments

- Added host, Docker, and devcontainer profiles shared by all execution stages.
- Added Docker filesystem, Git, environment, network, credential, CPU/RAM,
  port, and read-only reviewer boundaries.
- Added an untrusted-project permission gate and environment/security tests.

### [0.5.4](https://github.com/jpolec/odysseus/releases/tag/v0.5.4) — Simpler first run

- Added checkout/remote install, `odysseus start`, token-free demo, readable
  doctor, guided repository registration, and an inline outcome field.
- Kept advanced controls and knowledge behind progressive disclosure and tied
  screenshots to real disposable state.

## 2026-08-14

### [0.5.3](https://github.com/jpolec/odysseus/releases/tag/v0.5.3) — Project Memory and explainable Skill routing

- Added triggered/folder-scoped memory, reviewable suggestions, and immutable
  selection in Context Receipts.
- Added explainable Skill ranking from task signals, project policy, and
  sufficiently observed repository outcomes.

### [0.5.2](https://github.com/jpolec/odysseus/releases/tag/v0.5.2) — Context Receipts

- Added immutable snapshots/digests for the brief, README, instructions, and
  selected Skills sent to each run.
- Added provenance inspection and Skill outcome/token/cost/intervention stats
  without misleading sparse-sample percentages.

### [0.5.1](https://github.com/jpolec/odysseus/releases/tag/v0.5.1) — Generic Project Skills

- Added bundled security, database, testing, API, accessibility, dependency,
  performance, incident, and documentation procedures.
- Added project-local Skills, Auto/Required/Disabled policy, manual selection,
  immutable snapshots, and selection/load events.

### [0.5.0](https://github.com/jpolec/odysseus/releases/tag/v0.5.0) — Project Knowledge

- Added repository Overview with README/instruction/stack discovery, private
  project briefs, Git history, and cross-run timeline.
- Added paths and content digests as provenance for Context Receipts.

### [0.4.3](https://github.com/jpolec/odysseus/releases/tag/v0.4.3) — Project-first workbench

- Reorganized the UI around workspace → repository → task, with Explorer,
  overview, compact activity bar, and Summary/Changes/Activity/Evidence depth.
- Reduced routine task creation while retaining technical details and a
  responsive workbench shell.

### [0.4.2](https://github.com/jpolec/odysseus/releases/tag/v0.4.2) — Visual hierarchy

- Refined navigation, spacing, typography, active states, responsive behavior,
  workflow explanations, terminal summaries, all-clear states, and screenshot
  deep links.

### [0.4.1](https://github.com/jpolec/odysseus/releases/tag/v0.4.1) — Operator clarity

- Simplified task/Epic input, grouped real tmux panes, removed invented
  telemetry, renamed Track in Odysseus, and clarified start/copy/plan actions.

### [0.4.0](https://github.com/jpolec/odysseus/releases/tag/v0.4.0) — Artifacts reach green

- Added accepted Git artifacts, DAG composition, merge-risk/conflicts, GitHub
  CI repair, review feedback, notifications, liveness/budgets, retries,
  priority, search/stats/export, and Integration/CI/Insights surfaces.

### [0.3.0](https://github.com/jpolec/odysseus/releases/tag/v0.3.0) — Engineering orchestration core

- Added read-only Planner proposals, approval-gated DAGs, dependency
  scheduling, fan-out/fan-in, Needs You, structured questions, exact-thread
  resume, independent evaluation, and deterministic demo state.

### [0.2.0](https://github.com/jpolec/odysseus/releases/tag/v0.2.0) — Local control plane

- Added the web UI, isolated branch/worktree workflow, bounded queue,
  checks/retries, normalized telemetry, multi-project registry, Inbox, GitHub
  intake, draft PRs, exact-thread resume, tmux takeover, and remote operation.

### [0.1.0](https://github.com/jpolec/odysseus/releases/tag/v0.1.0) — Odysseus foundation

- Turned the tmux manager into the first Odysseus application with persisted
  repository/session concepts and a path toward the local control plane.

## Odysseus origins

Odysseus began as a terminal-first session manager and grew into the delivery
system documented above. These are the first public steps of the same project.

### 2026-06-23

- Expanded Odysseus's terminal foundation with Codex and Claude lanes,
  per-pane/session receipts, configurable defaults, and clearer lane state.

### 2026-06-19

- Replaced conceptual README art with real Odysseus terminal captures and
  clarified its terminal-first value proposition.

### 2026-06-18

- Created the first Odysseus terminal experience: a tmux-native Codex session
  manager with a global repository-aware picker, existing-pane discovery,
  pane metadata, Codex status hooks, and robust host-client selection.
