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
7. I07 An old worker cannot commit after lease takeover.
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

### Vendor-neutral agent execution

AgentAdapter exposes capabilities, start, resume, interrupt, cancel, health,
usage, events, checkpoint, and permission requests. A provider manifest states
support for resume, structured events, usage, tool interception, worktrees,
containers, and checkpoints. Provider-specific branching stays inside
adapters/integrations rather than scheduler policy.

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
5. Pass exact-commit installer, upgrade/rollback, demo, HTTP, browser, package,
   security, state verification, and release proof; publish docs/screenshots.

Dependencies: 3 -> 4; 1, 2, and 4 -> 5.

### 0.9.0 — durable kernel

1. EventEnvelope v2 and append/fsync EventLog.
2. CommandEnvelope, expected_version, idempotency, and concurrency conflicts.
3. Deterministic projections/checkpoints and migrations from existing runs.
4. Replay, replay-until-event, rebuild-projections, and verify-state v2.
5. Journal hash chain and corruption/tamper tests.

### 0.9.1 — runtime correctness

1. WorkerLease, epoch, heartbeat TTL, and fencing.
2. Stale-worker and duplicate-claim concurrency tests.
3. Failpoint framework and crash matrix.
4. Recovery proof across journal, projection, artifact, and worker windows.

### 0.9.2 — durable effects

1. Outbox and ActionRecord including UNKNOWN.
2. Git apply/merge/push integration through the action ledger.
3. GitHub PR reconciler and duplicate-effect tests.
4. Webhook/notification reconciler.

### 0.10.0 — outcome model

1. Orthogonal status projection with backward-compatible run states.
2. Immutable OutcomeRecord and lineage receipts.
3. Publication/integration/deployment receipts.
4. ObservationWindow, HealthSignal, revert/rollback tracking.
5. Outcome portfolio and healthy-change economics.

### 0.10.1 — routing instrumentation

1. TaskFeatures and RouteCandidate.
2. RouteReceipt and eventual OutcomeRecord link.
3. RoutingAdvisor, RoutingPolicyEngine, ExecutionResolver boundaries.
4. Transparent shadow/recommend mode and coverage/drift gates.
5. SkillReceipt and non-causal effectiveness reporting.

### 0.11.0 — contract and typed plan

1. ChangeProposal intake shared by human, issue, incident, ADR, and API.
2. ChangeContractVersion with amendment approval.
3. Immutable PlanVersion and typed PlanNode.
4. Plan budgets, reservations, admission control, and typed RetryPolicy.
5. Plan-level Mission Control and controls.

### 0.11.1 — immutable validation

1. ArtifactSet and MilestoneCandidate.
2. Read-only ValidationRun against exact SHA and contract version.
3. Structured Finding and EvidenceBundle.
4. Scoped RepairNode and affected-validation rerun.
5. End-to-end contract/plan/validation/delivery proof.

### 0.12.0 — governance

1. Capability model and monotonic Policy Engine.
2. PolicyReceipt and approval gates.
3. Secret Broker interface and scoped credential leases.
4. Runtime/ResourceLease policies.
5. One Command API shared by CLI, UI, REST, and later MCP.

### 0.13.0 — flight recorder

1. Correlation/causation coverage.
2. Full causal timeline and Replay UI.
3. CounterfactualExperiment.
4. Read-model and OpenTelemetry exports.

### 0.14.0 — learned routing

1. Healthy-outcome-labelled dataset.
2. Hierarchical statistical model and calibrated uncertainty.
3. Utility profiles and guarded Auto.
4. Drift, risk, and exploration policy.
5. Matched Skill contribution analysis.

### 0.15.0 — ecosystem

1. Agent Adapter Protocol and capability manifests.
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
