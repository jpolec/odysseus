# 03 — Task delivery workflow

Built across **Odysseus v0.2.0–v0.8.1**.

## The problem

Starting a coding agent is easy. Knowing which repository it changed, keeping
the source checkout safe, verifying the result, deciding what to preserve, and
delivering the exact reviewed bytes is the actual workflow.

## The guarantee

One Odysseus task owns one durable run, branch, isolated Git worktree, agent
thread, evidence history, and delivery state.

```text
requested outcome
    ↓
isolated branch + worktree
    ↓
implementation agent
    ↓
checks + independent review
    ↓
operator decision
    ↓
accepted artifact → integration or draft PR
```

The source checkout is not modified while the agent works. `Ready for review`,
`Accepted`, `Integrated`, and `Delivered` are separate states.

## Use it

From the web UI, choose **New task**, select a repository, describe the finished
outcome, and leave **Agent: Auto** unless you have a reason to override it.

From a checkout:

```sh
odysseus run \
  --project /absolute/path/to/repository \
  --check "python3 -m unittest" \
  "Implement the change and cover it with tests"
```

The task page leads with the next decision. Detailed changes, activity, tool
calls, checks, context, and provenance remain available below it.

## Evidence to inspect

- **Summary** — lifecycle, decision, usage, environment, and delivery state.
- **Changes** — the complete candidate diff and touched files.
- **Activity** — agent messages, tool calls, usage, failures, and recovery.
- **Evidence** — checks, independent evaluation, CI, and context receipts.

## Failure behavior

- Failed work keeps its branch and worktree.
- Feedback resumes the saved agent thread instead of silently starting over.
- Retry, token, tool-call, stall, and cost limits stop the workflow in a clear
  recoverable state.
- A blocked local integration does not invalidate or delete an accepted
  artifact.

## Current boundary

A task is one focused engineering outcome. Use a [Plan](04-plans-and-task-dags.md)
when the outcome requires multiple dependent or parallel tasks. Acceptance is
an approval of the artifact; it is not proof that the change has been deployed
or is healthy in production.

