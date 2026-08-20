# Odysseus roadmap

The architecture and release DAG from 0.8.x through the outcome-driven control
plane is maintained in
[`docs/architecture/MASTER_PLAN.md`](docs/architecture/MASTER_PLAN.md).

Odysseus is moving from a session manager to an engineering control plane. The
organizing metric is **Human Attention per Successful Change**: more accepted,
verified software with fewer minutes spent supervising routine agent work.

Versions describe independently useful product increments, not promised dates.
Detailed shipped history lives in [CHANGELOG.md](CHANGELOG.md), while the
current capability and compatibility contract lives in [VERSION.md](VERSION.md).
This document is for what we are building next. The repository-inspected
implementation DAG lives in
[Outcome-driven control plane](docs/OUTCOME_CONTROL_PLANE_PLAN.md).

## Version sequence

Each independently useful capability ships as its own version and must pass the
complete release gate before the next capability begins.

| Version | Capability | Status |
| --- | --- | --- |
| `0.8.2` | Correctness, public trust, branch audit, and RouteObservation | Shipped |
| `0.9.0` | Event-sourced kernel and deterministic replay | Shipped |
| `0.9.1` | Idempotent Command API | Shipped |
| `0.9.2` | Worker Leases and fencing | Shipped |
| `0.9.3` | Durable Outbox, Action Ledger, and reconciliation | Next |
| `0.10.0` | Complete OutcomeRecord and observation semantics | Planned |
| `0.10.1` | Full routing and Skill receipts | Planned |
| `0.11.0` | Versioned ChangeContract and typed Plans | Planned |
| `0.11.1` | Content-addressed ArtifactStore | Planned |
| `0.11.2` | Immutable milestone validation and scoped repair | Planned |
| `0.12.0` | Capability and policy engine | Planned |
| `0.13.0` | Flight Recorder | Planned |
| `0.13.1` | Native semantic Context Engine | Planned |
| `0.14.0` | Learned outcome routing | Planned |
| `0.15.0` | Governed ecosystem, MCP, and remote workers | Planned |

## Now

Durable effects for v0.9.3:

- Persist external-effect intent before Git apply/merge/push, GitHub PR
  creation, notification delivery, or another provider mutation.
- Record `prepared`, `executing`, `effect_observed`, `committed`, `failed`, and
  `unknown` ActionRecord states with stable idempotency keys.
- Reconcile an unknown result against Git/GitHub before retrying so a process
  crash cannot create a duplicate logical effect.
- Add explicit compensation outcomes for effects that can be reversed, while
  keeping irreversible effects visible and human-gated.

Change Proposal intake and operational hardening after the durable-effects gate:

- Extend the shipped Project Decisions catalog into one **New change** intake
  for ADR/PRD files, GitHub Issues, existing PRs, and pasted requirements.
- Show the proposed Epic/DAG, scope, risk, estimated economics, and source
  receipts before approval; keep proposal -> tasks -> artifacts -> PR -> outcome
  as one searchable history.

- Long-lived per-task preview processes with explicit start, health, stop, and
  cleanup controls instead of relying on one disposable command lifetime.
- Broader branch, artifact, and preview-process retention policies that build
  on the current worktree/runtime inventory and explicit reclaim command.
- Verified backup, import, restore, and crash tests across approval, artifact,
  container, and delivery transitions.
- Stronger container controls: Podman support, disk/PID limits, outbound host
  allowlists, signed or allowlisted images, and an inspectable command policy.
- Ephemeral PostgreSQL, Redis, queue, and service sidecars with snapshot/seed
  policies and unique namespaces for parallel tasks.
- GitHub webhooks, review-comment classification, and explicit auto-merge
  policies for narrowly trusted changes.
- Semantic code/dependency graph overlap prediction and a cross-PR merge queue
  with ordered rebase, rerun, and rollback.

## Next

Evidence-based agent routing and context:

- High-value tournament mode where several agents or prompts attempt one
  ambiguous task and an independent judge selects a candidate.
- Per-repository benchmarks for success rate, completion time, correction rate,
  CI failures, cost, tokens, and human interventions by task class and lane.
- A router that chooses an agent from empirical project history, expected
  quality, latency, and cost while keeping every automatic choice explainable.
- Semantic project context for architecture, code maps, schemas, API
  contracts, recent changes, and known issues, retrieved as a cited subset.
- Deferred tool loading and large-result offloading so agents receive only the
  tool schemas and output fragments relevant to the current task, with every
  retrieval recorded in the Context Receipt.
- Analytics for cost per accepted task or merged PR, retry rate, human minutes,
  and **Human Attention per Successful Change**.
- NDJSON export to CSV/Parquet and budget alerts.

## Later

Workflow, organization, and operational guarantees:

- Organization -> workspace -> repository -> epic -> task -> attempt hierarchy.
- Shared organization Skills, task templates, and declarative workflows.
- Path, diff, and risk policy engine for required checks, security review,
  human review, and narrowly scoped auto-merge.
- Odysseus MCP server to queue work, read status, answer attention items, and
  query results from another agent session.
- Linear, Jira, Sentry, and richer GitHub ingestion.
- Remote authenticated workers with heartbeats and crash recovery.
- Mobile review, push notifications, and secure phone access over an
  authenticated private-network listener.
- Notification actions that answer or defer a structured question without
  opening the full cockpit, while refusing ambiguous terminal keystrokes.
- Portable generic Skills import/export with explicit trust review before
  enabling Skills or shell checks sourced from another repository.
- Versioned provider, MCP, Skill, and sandbox catalogs with authenticated MCP
  connections, scoped OAuth, and explicit operator approval before a newly
  connected capability becomes available to an agent.
- Stable event and HTTP API compatibility window.
- Tested forward migrations, backup/restore, installer upgrade, and rollback.
- Strong remote identity, session expiry, operator audit log, and signed run
  receipts.
- A repository Activity view projected from canonical events, Command Receipts,
  attention decisions, delivery receipts, and Git history, grouped into a
  readable causal timeline with actor/agent/task filters and expandable raw
  evidence. It must not become a second source of truth.
- Distributed scheduling across workstation, build server, GPU host, and cloud
  workers without weakening credential or network policy.
- End-to-end documentation for workstation, shared host, and secured VPS.

## Exploring

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
without touching the repository. Odysseus could then say "switching the review
lane would likely have saved one intervention, but auto-merge would have
violated the migration policy" before a team changes production autonomy.

This is the potential data moat: not tmux, worktrees, or a dashboard, but a
project-specific history connecting agent choices to verified engineering
outcomes and actual human attention.

## Product principles

1. Terminal and tmux remain first-class; Odysseus is not another IDE.
2. Git and inspectable local files remain the source of truth.
3. Planner, Implementer, Reviewer, and deterministic Verifier are separate
   roles to reduce correlated failure.
4. No task is complete because an agent says "done"; evidence and policy decide.
5. Resume, takeover, approval, publishing, and permission changes are explicit
   and auditable.
6. Features are prioritized by operator outcomes, not checkbox parity.
