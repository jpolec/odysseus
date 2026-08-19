# Outcome-driven control plane: gap analysis and implementation DAG

The canonical multi-release execution plan now lives in
[`architecture/MASTER_PLAN.md`](architecture/MASTER_PLAN.md). This document
retains the original post-0.8 repository gap analysis and reuse decisions.

This document records the repository inspection behind the post-0.8 roadmap.
It is intentionally reuse-first: existing run snapshots, append-only event
journals, Epics, worktrees, Scheduler, Evaluation Engine, CI watcher, Skills,
resource lifecycle, HTTP API, and CLI remain the foundation.

## Gap analysis

| Capability | Current implementation | Reuse? | Gap | Required change | Priority |
| --- | --- | --- | --- | --- | --- |
| Task lifecycle | Explicit run states, transitions, stage, durable snapshot and NDJSON journal | Yes | `completed`, `verified`, `accepted`, `integrated`, and `delivered` are not one normalized outcome state machine | Add an outcome projection without replacing run history | P1 |
| Plan | Epic with acyclic task DAG, dependencies, approval and materialization | Yes | No first-class Milestone or validation checkpoint | Version the Epic plan schema with milestones and typed nodes | P0 |
| Planner | Read-only Codex/Claude Planner with structured plan marker | Yes | Cannot ask a structured requirement question before proposal | Add planner attention/question state and resume | P0 |
| Roles | Planner, implementer, reviewer; separate review lane | Yes | No explicit Orchestrator or Validator role/profile | Add role profiles and typed execution ownership | P0 |
| Scheduling | Slot-bounded, dependency-aware Scheduler with retries and priority | Yes | No Plan pause, critical path, milestone scheduling, or scoped repair insertion | Generalize scheduler around typed Plan nodes | P0 |
| Worktrees | Isolated Git worktree per run, artifact composition and clean-source protection | Yes | Milestone validation needs read-only access to exact composed artifacts | Create validation runs against immutable milestone heads | P0 |
| Verification | Deterministic checks, independent review, weighted evaluators and policy | Yes | Evidence is task-scoped; workers can reach review without milestone validation | Add milestone validation profiles and evidence bundles | P0 |
| Repair | Same-thread resume, check retry, CI repair, integration-conflict task | Yes | Failure often retries a whole run rather than creating a narrow graph node | Insert repair node linked to failed validation evidence | P0 |
| Mission Control | Repository status, task DAG/Gantt, task decision surface | Yes | No Plan-level critical path, worker allocation, pause/re-plan, estimate/actual | Add one Plan execution page backed by API projections | P0 |
| Budgets | Per-run token, tool, cost, stall and timeout limits | Yes | No aggregate Plan limits or remaining estimate | Add Plan budget and atomic reservation/accounting | P1 |
| Usage/cost | Normalized token/tool events, provider-reported cost, outcome economics | Yes | Billing mode and phase attribution are incomplete | Add normalized billing and phase records; preserve Unknown | P1 |
| Outcome ledger | Run snapshot, strict journal, production proof, economics receipt | Yes | No stable denormalized OutcomeRecord for learning/export | Add versioned derived ledger with source receipt hashes | P1 |
| Failure taxonomy | Detailed error strings and stage-specific events | Partial | Failure attribution is heuristic and not provider/model-safe | Emit normalized FailureEvent at the source and migrate projection | P1 |
| Skills | Bundled/project-local snapshots, policy, receipts, history-based routing | Yes | Procedures cannot require structured evidence/verification/failure handling | Version Skill metadata and compile requirements into Plan nodes | P1 |
| Routing | 0.8.1 outcome router, evidence/sample floor, Auto apply/fallback, backtest, export and drift | Yes | Lane-level, limited objectives and no policy profiles/calibration | Add RoutingDecision v2 after the ledger is trustworthy | P2 |
| Evidence score | Evaluation engine emits a heuristic score; UI labels it N/100 | Partial | Internal legacy field remains `confidence`; no calibrated delivery probability exists | Add calibration datasets/curves before exposing probability | P2 |
| Policies | Evaluation, environment trust, runtime boundary, credential allowlist | Partial | No explicit autonomy levels or inheritance/provenance | Add monotonic global → repository → Plan/task policy resolution | P3 |
| API/CLI | Tasks, Plans, approval, status, evidence, delivery, proof and JSON output | Yes | Milestone/validation/Plan controls are absent | Extend existing commands and routes; do not add another engine | P3 |
| Resource lifecycle | Inventory, leases, retention and explicit reclaim | Yes | Pending validation/repair reasons need first-class preservation | Add Plan/outcome-aware keep reasons and tests | P0/P1 |
| Frontend | Plain HTML/CSS/browser JS with lazy task evidence | Yes | Plan execution is not yet a decision-first Mission Control | Extend the existing workbench; no new frontend runtime | P0 |
| Persistence | Versioned JSON snapshots and append-only NDJSON; no database | Yes | New entities need stable schemas and migration | Add directories/projections only where an Epic/run cannot represent the concept | All |

## Entity decision

- **Plan** remains an Epic; its schema is extended.
- **PlanNode** generalizes existing task entries with `kind=worker|validation|repair|delivery`.
- **Milestone** is added inside the Plan snapshot because it owns criteria and
  node membership, not an independent scheduler.
- **AgentRun** remains a run.
- **ValidationRun** is a run with `role=validator`, immutable target artifact,
  and no worker authority.
- **OutcomeRecord**, **RoutingDecision**, and **FailureEvent** are versioned
  projections/records bound to source snapshot and journal receipts.
- **SkillVersion** is the existing immutable skill snapshot plus procedure
  metadata; no separate package manager is introduced.

## Implementation DAG

```text
0.8 stable baseline and release proof
  |
  +--> A. Plan schema v4: milestones + typed nodes + migrations
  |      |
  |      +--> B. Role profiles: orchestrator / worker / validator / reviewer
  |      |      |
  |      |      +--> C. Milestone validation + scoped repair nodes
  |      |               |
  |      |               +--> D. Plan pause / resume / re-plan / critical path
  |      |                        |
  |      |                        +--> E. Mission Control Plan execution view
  |      |
  |      +--> F. Pre-execution estimates + Plan budgets
  |
  +--> G. OutcomeRecord v1 + billing mode + phase cost
  |      |
  |      +--> H. Source-emitted failure taxonomy + recovery attribution
  |      +--> I. Measurable Skill procedures and performance
  |      +--> J. Portfolio breakdowns and sample confidence
  |              |
  |              +--> K. RoutingDecision v2 + Reliable/Balanced/Fast/Economical
  |                      +--> L. calibration diagnostics
  |
  +--> M. Autonomy policy inheritance
  +--> N. Plan/validation CLI and API
  +--> O. outcome-aware resource preservation

C + E + F + G + H + O
  |
  +--> P. end-to-end passkey acceptance scenario
          +--> Q. release proof, migration/upgrade proof, docs and screenshots
```

## Release sequence

The original product-slice numbering in this gap analysis was superseded when
the durability program became the release-critical path. The authoritative
sequence is maintained in
[`architecture/MASTER_PLAN.md`](architecture/MASTER_PLAN.md) and
[`../ROADMAP.md`](../ROADMAP.md): v0.9.0 shipped the durable event kernel,
v0.9.1 ships the idempotent Command API, and v0.9.2 is Worker Leases with
fencing. The capability DAG above remains useful, but it does not assign
release numbers.

Every release must remain independently useful, migrate old state, preserve
existing Tasks and Plans, include deterministic tests, and pass
`scripts/release-proof.sh`. No later release may redefine accepted work as
delivered or unknown cost as zero.
