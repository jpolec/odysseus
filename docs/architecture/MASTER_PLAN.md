# Odysseus control-plane master plan

Status: canonical product plan from 0.8.x through the first complete,
outcome-driven software delivery control plane.

## Product thesis

Odysseus does not primarily manage agents. It manages the truth of a software
change: intent, contract, plan, execution, evidence, decisions, publication,
integration, deployment, observation, and the final outcome.

The replaceable worker may be Codex, Claude, another provider, or a local
model. Odysseus owns the durable delivery protocol around that worker.

```text
INTENT -> CONTRACT -> PLAN -> ROUTE -> EXECUTE -> VALIDATE -> DECIDE
       -> INTEGRATE -> DEPLOY -> OBSERVE -> OUTCOME -> LEARN
                                                    \-> ROUTE / PLAN / SKILLS
```

Every arrow must eventually have explicit state, evidence, policy, and a
receipt.

## Target system invariants

The first implementation milestone must publish these as individually
identified, test-linked invariants in `docs/architecture/invariants.md`.

1. I01 Journal is canonical.
2. I02 A snapshot is a deterministic projection of the journal.
3. I03 Every command is idempotent.
4. I04 Every external side effect has durable intent before execution.
5. I05 Every external side effect is reconcilable.
6. I06 At most one valid worker lease exists for a node.
7. I07 An old worker cannot commit a result to canonical state after lease takeover.
8. I08 Accepted is not Published.
9. I09 Published is not Integrated.
10. I10 Integrated is not Deployed.
11. I11 Deployed is not Healthy.
12. I12 A validator validates an immutable artifact SHA.
13. I13 A validator cannot mutate the candidate it validates.
14. I14 A router recommendation is not a routing decision.
15. I15 Missing evidence is not successful evidence.
16. I16 A missing metric is not zero.
17. I17 A child policy can restrict but never widen a parent policy.
18. I18 Every final outcome has lineage to a requirement and artifact.
19. I19 Every autonomous decision is explainable from stored evidence.
20. I20 State can be reconstructed after arbitrary process death.
21. I21 Artifact bytes always match their immutable content hash.
22. I22 Approval applies to exactly one artifact, evidence, and contract tuple.
23. I23 Secrets never cross the durable persistence boundary unredacted.
24. I24 Historical domain-event bytes are never rewritten during schema evolution.
25. I25 Duplicate inbound or outbound messages cannot cause duplicate logical effects.

After I21–I25 are incorporated, the core architecture is frozen. New work must
strengthen implementation, proof, operations, and dogfooding rather than add
more control-plane concepts without a demonstrated gap.

## Canonical object graph

```text
ChangeProposal
  -> ChangeContractVersion
  -> PlanVersion
       +-> RouteReceipt
       -> PlanNode
            -> Run
                 +-> ContextReceipt
                 +-> SkillReceipt
                 +-> PolicyDecision
                 +-> ActionRecord
            -> ArtifactSet
            -> MilestoneCandidate
            -> ValidationRun
            -> EvidenceBundle
            -> ReviewDecision
            -> Publication
            -> Integration
            -> Deployment
            -> ObservationWindow
            -> OutcomeRecord
```

Existing runs, Epics, worktrees, events, skills, checks, review, CI, resource
lifecycle, and delivery receipts are reused. New entities are introduced only
when an existing object cannot express the invariant without ambiguity.

## Architectural direction

### Durable kernel

The command path becomes:

```text
Command
  -> validate policy and expected stream version
  -> produce domain events
  -> append and fsync canonical event journal
  -> update deterministic projections/checkpoint
  -> enqueue durable side-effect intent in the outbox
```

An event envelope carries `event_id`, `stream_id`, continuous
`stream_version`, `event_type`, `command_id`, `idempotency_key`, correlation
and causation IDs, actor, timestamp, schema version, payload, previous event
hash, and event hash.

The command layer initially covers CreateChange, ApprovePlan, ClaimNode,
CompleteRun, RequestValidation, AcceptArtifact, RequestPublication,
RequestIntegration, RecordDeployment, RecordObservation, and FinalizeOutcome.
Each command has a stable ID, idempotency key, expected version, actor, policy
context, and payload.

`odysseus replay CHANGE_ID`, `replay --until-event`, and
`rebuild-projections` reconstruct read models from the journal. `verify-state`
checks stream continuity, event IDs and versions, hash chains, projection
sequence/hash, transitions, leases, outbox entries, artifact references, and
missing evidence. Repair may rebuild projections but never silently rewrite
the canonical journal.

### Runtime correctness

PID ownership is replaced by a WorkerLease with lease ID, worker ID, epoch,
acquired/expiry/heartbeat timestamps, and claim stream version. Every worker
mutation carries lease ID and fencing epoch; stale epochs are rejected.

Fault injection covers journal writes/fsync, projection writes, external
effects, artifact writes, merge, push, and process death. Recovery must retain
a valid journal, rebuild equivalent projections, execute each logical side
effect no more than once, and reject zombie workers.

### Durable effects and reconciliation

Git push, PR creation, merge, deployment, webhook delivery, ticket mutation,
and other external writes first create a durable outbox intent. ActionRecord
tracks prepared, executing, effect_observed, committed, failed, and unknown.
Unknown is not retried blindly: a reconciler queries the external system and
records the observed receipt.

Inbound webhooks use a verified WebhookEnvelope containing provider delivery
ID, signature result, receipt time, payload hash, and the single processed
event/command ID. Deduplication is enforced at the command boundary, so N
deliveries cause one logical transition. Outbound messages use the same
idempotent outbox/action-ledger guarantees.

### Artifact integrity and SHA-bound human decisions

ArtifactStore is content-addressed and immutable. A worktree or temporary path
is never the long-term source of artifact truth. A stored object is addressed
by hash and contains a manifest, complete diff/source payload where applicable,
metadata, and provenance.

```text
sha256:ab7...
  +-- manifest.json
  +-- diff.patch
  +-- source.tar.zst
  +-- metadata.json
  +-- provenance.json
```

Artifact records bind artifact ID/type, content and manifest hashes, creating
run, source HEAD, parent artifact, execution-environment hash, size, and
timestamp. Every read verifies bytes against the content hash. ArtifactSet and
MilestoneCandidate reference ArtifactStore objects rather than mutable paths.

A ReviewDecision binds exactly one `artifact_sha`, `evidence_bundle_hash`,
`contract_version`, and `plan_version`, together with actor and decision time.
Changing any member makes the approval stale and requires a new decision.
Repair can never inherit approval for the pre-repair candidate.

### Cancellation and compensation

Cancellation is a durable workflow, not process termination. It distinguishes
stopping future execution from compensating committed effects:

```text
CancelRequested -> CancelAccepted -> CancellationInProgress
                -> Cancelled | CancellationFailed

CommittedAction -> CompensationRequested -> Compensating
                -> Compensated | CompensationFailed
```

CompensationPolicy is action-specific and records whether compensation is
possible, automatic, or approval-gated. PR closure, deployment rollback,
credential revocation, resource cleanup, and preservation of evidence/artifacts
are explicit decisions. Irreversible effects remain recorded rather than being
described as undone.

### Durable sensitive-data boundary

RedactionEngine runs before every persistent or browser-stream boundary for
context, agent/tool events, commands, logs, evidence, and artifact metadata.
RedactionReceipt records ruleset version, redacted fields/classes, and detection
source without recording the secret. Secret-shaped values, `.env` contents,
credentials in tracebacks, and sensitive customer data must not enter journal,
projection, EvidenceBundle, export, notification, or UI events unredacted.

`docs/security/threat-model.md` defines trust boundaries. The human and kernel
are trusted; repository content, agent output, CI output, webhook payloads, and
external MCP are untrusted. Skills are reviewed but only partially trusted.
The model explicitly covers prompt injection in AGENTS/README, malicious build
and test scripts, dependency hooks, filesystem/credential access, data
exfiltration, forged callbacks, and poisoned evidence.

### Event evolution and lifecycle

Canonical historical event bytes are immutable across upgrades. A versioned
upcaster chain translates old envelopes into the current domain representation
at read/projection time. Migrations may add new projections/checkpoints but do
not rewrite old journal records.

RetentionPolicy, reachability-based GarbageCollector, and OrphanScanner manage
worktrees, CAS artifacts, containers/images, logs, validation outputs,
screenshots, variants, counterfactuals, projections, and journals. Objects
reachable from an OutcomeRecord, active plan, pending review/repair, retention
hold, or referenced EvidenceBundle cannot be deleted. Lifecycle states are
hot, warm, archived, and deletable; age alone is insufficient.

### Outcome semantics

One generic success flag is replaced by orthogonal axes:

- Execution: queued, running, blocked, completed, failed, cancelled.
- Evidence: missing, collecting, passed, failed, inconclusive.
- Review: pending, accepted, changes_requested, rejected.
- Publication: local_only, branch_pushed, pr_opened, pr_closed.
- Integration: not_integrated, applied, merged, conflict, reverted.
- Deployment: not_deployed, deploying, deployed, failed, rolled_back.
- Observed outcome: unknown, observation_pending, healthy, regressed,
  incident, reverted, superseded.

OutcomeRecord is immutable/versioned and binds the proposal, contract, plan,
selected route, artifact SHAs, evidence bundle, review, publication,
integration, deployment, observation, rollback/revert, compute usage, human
attention, and final outcome.

Post-merge ObservationWindow consumes typed HealthSignals from CI, tests,
deployment, Sentry/metrics, or a human. Reverts and regressions become negative
router labels. Accepted or PR-opened is never used as the terminal learning
label when healthy outcome evidence exists.

### Executable change contract and typed plan

ChangeProposal records human/issue/incident/ADR/API intent. An approved
ChangeContractVersion freezes objective, required behavior, invariants,
forbidden regressions, path scope, compatibility, performance, security,
migration, rollback, required evidence, and observation policy. Workers may
request an amendment but cannot edit an approved contract.

PlanVersion is immutable after approval and records supersession, reason, and
approver. Typed PlanNodes are worker, validator, repair, human_gate, delivery,
deployment, or observation nodes. They declare requirements, products,
artifact target, acceptance criteria, runtime, capabilities, policy, budgets,
retry policy, timeout, and failure strategy.

A MilestoneCandidate represents a concrete immutable artifact set and contract
version that can be independently validated. ValidationRun receives an
artifact SHA and contract version through a read-only environment. A validator
never repairs. Structured Findings create narrowly scoped RepairNodes, and the
repaired artifact receives a new ValidationRun.

EvidenceBundle binds tests, static/security/performance/API/migration evidence,
screenshots, logs, validation runs, completeness, coverage, and a bundle hash.
The invariant is always `validated_sha == accepted_sha`.

### Pareto judge correctness

Every objective uses a typed metric with nullable value, observed flag, source,
and optional uncertainty. Unknown cost is never zero and cannot dominate an
observed cost. Comparisons with missing required evidence are explicitly
incomparable.

Hard constraints are evaluated before ranking: required tests, security
findings, maximum cost, allowed paths, and minimum evidence coverage. A
constraint-violating candidate cannot win. Objectives include evidence,
quality, maintainability, cost, latency, human attention, regression risk,
blast radius, and change size. The data shape admits mean/lower/upper bounds
without pretending the first implementation is Bayesian.

### Policy and credentials

Agents receive capabilities rather than ambient terminal authority:
`fs.read`, `fs.write`, `shell.exec`, `network.egress`, `git.commit`, `git.push`,
`github.pr.create`, `github.pr.merge`, `secret.use`, `deploy.execute`, and
`database.migrate`.

Policy inheritance is monotonic across system, organization, repository,
change, plan, node, and attempt. Each decision writes a PolicyReceipt with
action, actor, policy version, context hash, allowed/denied/approval-required
result, and reason.

A future Secret Broker issues short-lived, action-scoped credentials instead
of placing global provider/cloud tokens in a worker environment. Sidecars such
as databases, browsers, Redis, and mock services receive ResourceLeases with
namespace, credentials reference, expiry, and teardown state.

Capability policy is enforced by a concrete RuntimeProfile: rootless user,
read-only root filesystem, no-new-privileges, dropped Linux capabilities,
seccomp, PID/CPU/RAM/disk/wall-clock quotas, egress deny-by-default with DNS and
host allowlists, digest-pinned container images, and optional signature policy.
The profile receipt binds image digest, filesystem/resource/network policy,
and empty-by-default secret set. A declared capability without runtime
enforcement is reported as degraded isolation, not as a security guarantee.

ExecutionEnvironmentReceipt records OS, architecture, container digest,
runtime and tool versions, dependency-lock hash, environment-policy hash, and
network-policy hash. Artifact SHA plus environment receipt makes execution and
validation materially reproducible.

### Human attention and evaluator calibration

AttentionReceipt records actor, change, activity class, source (UI/CLI/API),
active interval, and active seconds for review, question answering, plan edit,
manual fix, override, and approval. Browser-open time and Needs You queue age
are never counted as active attention. UI interaction windows use inactivity
cutoffs and explicit activation/submission boundaries.

EvaluatorCalibration tracks false-accept/false-reject rate, judge disagreement,
and evidence-score-to-healthy-outcome calibration. Periodic blind human samples
hide agent/model/cost identity from quality judges; cost and latency enter only
the subsequent Pareto decision. Evidence score remains heuristic until enough
outcomes support calibration.

### Vendor-neutral agent execution

AgentAdapter exposes capabilities, start, resume, interrupt, cancel, health,
usage, events, checkpoint, and permission requests. A provider manifest states
support for resume, structured events, usage, tool interception, worktrees,
containers, and checkpoints. Provider-specific branching stays inside
adapters/integrations rather than scheduler policy.

A minimal adapter boundary (`start`, `interrupt`, `cancel`, `health`, `usage`,
and `events`) is introduced by 0.12 at the latest, before leases, policy,
routing, and telemetry accumulate more provider conditionals. Full checkpoint,
remote-worker, gateway, and ecosystem capabilities remain a later extension.

### Routing and learning

Routing is separated into:

- RoutingAdvisor: what route is expected to work best?
- RoutingPolicyEngine: may that recommendation be applied?
- ExecutionResolver: how is the selected route launched?

A RouteCandidate includes agent, model, skills, validator, runtime profile,
context strategy, and budget profile. TaskFeatures include repository,
language, class, complexity, expected diff/scope, subsystem, dependency graph,
test coverage, risk, production criticality, and historical failure.

Every decision writes a RouteReceipt containing feature hash, candidates,
recommendation and uncertainty, actual selection, selection source, mode,
reason, and eventual outcome link. Telemetry covers tokens/cache, cost,
latency, tools, retries, interventions, validation/repairs, integration,
deployment, health, and revert.

Minimal RouteObservation is recorded from 0.8.2 onward, before routing is
trusted to decide. It captures task class, selected agent/model/skills,
selection source, start/end, tokens, cost observability, and result. This early
history later upcasts into RouteReceipt rather than being discarded.

RouteReceipt additionally records `selection_propensity`, `advisor_version`,
`policy_version`, `model_version`, `feature_schema_version`, and
`utility_profile_version`. Deterministic selection has propensity 1.0; any
future controlled exploration logs the probability with which the chosen route
was assigned. These fields make off-policy evaluation and causal analysis
possible without pretending historical human choices were randomized.

Router v1 remains transparent heuristics and repository aggregates. Statistical
v2 comes only after trustworthy OutcomeRecords and should use a modest
hierarchical model with partial pooling and intervals, not a neural network.
Profiles FAST, CHEAP, BALANCED, RELIABLE, and MIN_ATTENTION vary one utility
function. Guarded Auto additionally requires sample size, recency, outcome and
cost coverage, no drift, and acceptable risk. Exploration is limited to
low-risk work.

Skills write versioned SkillReceipts with selection source, injected context
hash, task features, and outcome. Early analysis controls for repository, task
class, and difficulty; raw selected-skill success percentages are not causal
claims.

### Flight recorder, projections, and observability

Correlation and causation IDs produce a complete change timeline across
requirement, contract, plan, route, context, skills, policy, agent/tools,
artifacts, validation, human interaction, delivery, deployment, observation,
and outcome. Mission Control Replay exposes inputs, policy, context, evidence,
and artifacts at each event. Counterfactual replay creates a separate
experiment and never mutates history.

Read models include change_summary, mission_control, needs_attention,
cost_summary, router_training, outcome_history, agent_performance, and
skill_performance. SQLite may later index projections but never replaces the
canonical local event journal. OpenTelemetry export is optional telemetry, not
system truth.

Backend modules converge toward domain, application, persistence,
orchestration, policies, routing, validation, integrations, projections, and
API. The domain layer has no filesystem, git, network, tmux, or Docker IO.
Frontend modularization keeps browser-native JavaScript and zero runtime
dependencies while splitting API, state, pages, components, events, and router.

ControlPlaneSLO makes operational correctness measurable: command append p95,
projection lag p95, startup/recovery ceiling, replay throughput floor, Mission
Control query p95, memory footprint, and journal growth. Initial releases may
publish measured baselines rather than hard promises, but regression gates use
the same versioned measurement protocol.

## Verification strategy

- Every invariant has at least one automated test and a stable test reference.
- Property-based state-machine tests generate create/approve/claim/heartbeat/
  pause/resume/cancel/complete/validate/repair/accept/publish/merge/crash/recover.
- Concurrency tests cover duplicate claims, lease takeover and stale return,
  duplicate idempotency keys/webhooks/integration requests, and heartbeat races.
- Mutation testing targets transitions, Pareto dominance, policy, fencing, and
  outcome classification.
- Fault injection uses real process death at every durable-write/effect window.
- Benchmarks compare Codex and Claude standalone versus with Odysseus across
  bugfix, feature, refactor, migration, test repair, and architectural change.

Every BenchmarkSuite is versioned and binds task IDs, repository commit,
contract versions, execution-environment digest, provider/model versions, and
scoring version. Longitudinal results are compared only when those inputs are
compatible; a model/task/scoring change cannot masquerade as product progress.

North-star reporting is healthy changes per active human minute, accompanied
by compute, first-pass healthy rate, regressions, reverts, recovery, and median
human minutes per healthy change. Queue residence time is not active human
attention; UI focus/review/answer/override intervals are measured separately.

## Release DAG

### 0.8.2 — correctness and public trust

1. Publish invariants with a machine-readable registry and invariant-to-test
   coverage check.
2. Repair CI/release consistency: fast CI, Main Proof, Security, Installer
   Smoke, Release Proof, version consistency, pinned Actions, SHA256, SBOM,
   provenance, and documented branch-protection requirements.
3. Replace Pareto scalar assumptions with nullable observed metrics.
4. Add Pareto hard constraints, missing-evidence incomparability, uncertainty
   shape, and property tests.
5. Publish the explicit threat model and enforce/test redaction before every
   existing durable event, log, notification, export, and UI-stream boundary.
6. Persist minimal RouteObservation with selection source/propensity and
   versioned advisor/policy/model/feature metadata; it observes but does not
   expand autonomous routing authority.
7. Pass exact-commit installer, upgrade/rollback, demo, HTTP, browser, package,
   security, state verification, and release proof; publish docs/screenshots.

Dependencies: 3 -> 4; 1, 2, 4, 5, and 6 -> 7.

### 0.9.0 — durable kernel

Status: shipped in `v0.9.0`.

1. EventEnvelope v2 and append/fsync EventLog.
2. Deterministic projections/checkpoints and migrations from existing runs.
3. Replay, replay-until-event, rebuild-projections, and verify-state v2.
4. Journal hash chain and corruption/tamper tests.
5. Immutable historical event upcasters and schema-evolution proof.
6. Baseline append/projection/replay/recovery/query SLO measurements.

### 0.9.1 — idempotent Command API

Status: shipped in `v0.9.1`.

1. CommandEnvelope, command IDs, idempotency keys, actor, and policy context.
2. Expected stream version and explicit concurrency conflicts.
3. One Command Bus shared by CLI, UI, and HTTP mutations.
4. Durable command result lookup and duplicate-submission proof.
5. Command property tests across valid and invalid lifecycle transitions.

### 0.9.2 — runtime correctness

Status: shipped in `v0.9.2`. WorkerLease identity, TTL, fencing, atomic claim,
stale-worker rejection, cancellation-aware recovery, deterministic failpoints,
and the process-death crash matrix are release-gated.

1. WorkerLease, epoch, heartbeat TTL, and fencing.
2. Stale-worker and duplicate-claim concurrency tests.
3. Failpoint framework and crash matrix.
4. Recovery proof across journal, projection, artifact, and worker windows.
5. Durable cancellation state and fencing-aware worker stop semantics.

### 0.9.3 — durable effects

1. Outbox and ActionRecord including UNKNOWN.
2. Git apply/merge/push integration through the action ledger.
3. GitHub PR reconciler and duplicate-effect tests.
4. Signed/deduplicated WebhookEnvelope and notification reconciler.
5. CompensationPolicy and explicit compensated/failed/irreversible outcomes.

### 0.10.0 — outcome model

1. Orthogonal status projection with backward-compatible run states.
2. Immutable OutcomeRecord and lineage receipts.
3. Publication/integration/deployment receipts.
4. ObservationWindow, HealthSignal, revert/rollback tracking.
5. AttentionReceipt and active-human-time economics.
6. Reachability retention, Artifact/Evidence lifecycle, GC, and orphan scan.
7. Outcome portfolio and healthy-change economics.

### 0.10.1 — routing instrumentation

1. TaskFeatures and RouteCandidate.
2. RouteReceipt and eventual OutcomeRecord link.
3. RoutingAdvisor, RoutingPolicyEngine, ExecutionResolver boundaries.
4. Transparent shadow/recommend mode and coverage/drift gates.
5. Propensity/version provenance migration from RouteObservation.
6. SkillReceipt and non-causal effectiveness reporting.

### 0.11.0 — contract and typed plan

1. ChangeProposal intake shared by human, issue, incident, ADR, and API.
2. ChangeContractVersion with amendment approval.
3. Immutable PlanVersion and typed PlanNode.
4. ReviewDecision bound to artifact/evidence/contract/plan tuple with automatic
   stale-approval invalidation.
5. Plan budgets, reservations, admission control, and typed RetryPolicy.
6. Plan-level Mission Control and controls.

### 0.11.1 — content-addressed artifacts

1. Content-addressed ArtifactStore and verified immutable artifact bytes.
2. ArtifactSet manifests, lineage, source head, and execution-environment hash.
3. ExecutionEnvironmentReceipt with runtimes, dependencies, tools, and policy.
4. Reachability-aware retention and integrity verification.

### 0.11.2 — immutable milestone validation

1. MilestoneCandidate bound to ArtifactSet and ChangeContract versions.
2. Read-only ValidationRun against one exact candidate SHA.
3. Structured Finding and EvidenceBundle.
4. Scoped RepairNode and affected-validation rerun.
5. Evaluator calibration and blind quality samples.
6. End-to-end contract/plan/validation/delivery proof.

### 0.12.0 — governance

1. Capability model and monotonic Policy Engine.
2. PolicyReceipt and approval gates.
3. Secret Broker interface and scoped credential leases.
4. Runtime/ResourceLease policies.
5. Minimal AgentAdapter boundary for start/interrupt/cancel/health/usage/events.
6. One Command API shared by CLI, UI, REST, and later MCP.

### 0.13.0 — flight recorder

1. Correlation/causation coverage.
2. Full causal timeline and Replay UI.
3. CounterfactualExperiment.
4. Read-model and OpenTelemetry exports.

### 0.13.1 — native semantic context engine

1. Versioned code, dependency, API, schema, ownership, and test graphs.
2. Task-scoped retrieval with cited source nodes and bounded token budgets.
3. Context relevance/evidence receipts and stale-graph detection.
4. Semantic overlap and blast-radius signals for planning and scheduling.
5. Retrieval quality benchmarks without granting repository content authority.

### 0.14.0 — learned routing

1. Healthy-outcome-labelled dataset.
2. Hierarchical statistical model and calibrated uncertainty.
3. Utility profiles and guarded Auto.
4. Drift, risk, and exploration policy.
5. Matched Skill contribution analysis.

### 0.15.0 — ecosystem

1. Full Agent Adapter ecosystem, capability manifests, checkpoints, and gateways.
2. Read-only MCP, then governed writes through the same Command API.
3. Remote workers only after leases/fencing/reconciliation are proven locally.
4. External observability and selected GitHub/Jira/Linear/Sentry integrations.

## Explicit non-goals until the kernel is proven

- More providers merely for feature count.
- Distributed workers or a Kubernetes scheduler.
- A Skills marketplace before contribution can be measured.
- Broad autonomous merge/deploy.
- A multi-tenant SaaS control plane or enterprise RBAC hierarchy.
- A React rewrite or another IDE.
- Twenty shallow integrations before Git, GitHub, and CI are reconciled.

## Per-step dogfooding protocol

Each release task follows the same path:

1. Create a small Odysseus Plan node with explicit finished outcome,
   constraints, acceptance criteria, checks, dependencies, and likely files.
2. Execute in an isolated worktree. Parallelize only disjoint semantic
   surfaces.
3. Require deterministic tests and independent review evidence.
4. Inspect the artifact and accept it without changing source.
5. Integrate exactly one reviewed artifact or one deliberately composed set.
6. Run the relevant tests, then the release proof at a release boundary.
7. Commit and push the integrated product increment.
8. Install the exact commit locally, restart the web service, verify health and
   version, and record the result in Version/roadmap documentation.
9. Start dependent nodes only after the updated product is live.

This protocol is itself a product test: Odysseus must be able to develop
Odysseus while preserving the source checkout and the audit trail.
