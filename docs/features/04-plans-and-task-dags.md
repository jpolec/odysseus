# 04 — Plans and task DAGs

Built across **Odysseus v0.3.0 and v0.7.0**.

## The problem

A large requirement should not become one enormous prompt. It needs explicit
dependencies, safe parallelism, integration points, and an operator-approved
interpretation before agents start changing code.

## The guarantee

The Planner is read-only. It proposes an acyclic task graph with intended
outcomes, acceptance criteria, dependencies, lanes, Skills, and checks. The
proposal creates no implementation runs until the operator approves it.

```text
requirement → Planner → proposed DAG → operator approval
                                      ↓
                          ready nodes run in parallel
                                      ↓
                         dependent nodes compose artifacts
```

A node becomes runnable only when its required predecessors have produced the
accepted artifacts it depends on. Fan-in happens in an isolated worktree.

## Use it

From the repository page, choose **Plan feature**, describe the finished
outcome, inspect the proposed graph, and approve it only when the breakdown is
correct.

```sh
odysseus plan \
  --project /absolute/path/to/repository \
  --planner-lane claude \
  --lane codex \
  --review-lane claude \
  "Implement passkey authentication end to end"

odysseus approve-epic EPIC_ID
```

Project ADRs can also be selected and sent to the Planner. Their exact source
content and digests are bound to the resulting Plan and task context.

## Evidence to inspect

- Proposed nodes and dependency edges before approval.
- Plan history and its immutable source snapshot.
- Task graph and timeline on the repository page.
- Each materialized task's branch, worktree, context receipt, and artifact.
- Integration checks for composed dependent work.

## Failure behavior

- A cyclic or invalid graph is rejected.
- A failed or blocked dependency prevents downstream execution.
- Completed sibling work remains preserved when another node fails.
- Integration conflicts become explicit operator work; they do not leave the
  source checkout half-merged.

## Current boundary

The shipped Plan is an approval-gated task DAG, not yet the future typed Plan
with immutable milestones, validation checkpoints, repair nodes, aggregate
budgets, and critical-path re-planning. Those additions remain in the roadmap.

