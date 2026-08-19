# 09 — CI, integration, and delivery

Built across **Odysseus v0.4.0–v0.6.12**.

## The problem

A reviewed patch still has to reach a real repository safely. The source branch
may have changed, CI may fail, or two correct isolated artifacts may conflict
when composed.

## The guarantee

Acceptance, local integration, branch publication, draft PR creation, CI
observation, and delivery are explicit transitions with separate receipts.
Odysseus checks source preconditions and aborts conflicts without leaving a
half-merged checkout.

```text
accepted artifact
   ├─ integrate into expected local branch
   └─ push task branch → draft PR → CI observe/repair
```

The CI repair loop captures failing GitHub Actions evidence and resumes the
same saved agent thread under bounded attempts.

## Use it

At the delivery gate:

- **Integrate into repository** applies the reviewed artifact to the expected
  local branch after safety checks.
- **Create draft PR** commits the task worktree, pushes its branch, and opens a
  draft pull request without changing the source checkout.
- **Resolve integration** or **Ask agent to resolve** handles a recorded merge
  conflict without claiming delivery.

Configure GitHub and CI behavior in Settings and authenticate the local `gh`
CLI for repository operations.

## Evidence to inspect

- Artifact commit and expected target SHA.
- Source cleanliness and changed-path collision checks.
- Delivery/integration receipt and final target commit.
- Draft PR URL, branch, GitHub CI state, and captured repair history.
- Merge-risk findings and dependency artifact provenance.

## Failure behavior

- Dirty tracked source changes or path collisions block integration.
- A Git merge conflict is aborted and recorded; the checkout is not left in a
  merge state.
- Failed CI returns to the same task thread within the configured budget.
- Unknown or unobserved CI stays distinct from green CI.

## Current boundary

Odysseus does not currently claim exactly-once external effects, automatic
merge, deployment, or post-deployment health. Durable Outbox/Action Ledger,
provider reconciliation, deployment receipts, and Observation Windows are
planned after the durable kernel work.

