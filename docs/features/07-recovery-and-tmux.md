# 07 — Recovery, saved threads, and tmux

Built across **Odysseus v0.2.0–v0.6.6**.

## The problem

When an agent stalls, asks a question, exhausts a limit, or fails a check, the
operator should not lose the useful work or have to reconstruct its context in
a fresh terminal.

## The guarantee

Odysseus preserves the task branch, isolated worktree, saved agent session ID,
events, and failure evidence. **Resume with feedback** returns to that same
thread. **Continue in terminal** opens the same worktree and session in tmux as
an explicit escape hatch.

```text
failure / decision
      ↓
Needs You
      ├─ answer or resume in the web UI
      └─ continue the exact thread in tmux
```

tmux is optional. Existing Codex and Claude panes are discovered read-only;
they are not silently converted into autonomous Odysseus tasks.

## Use it

- On a failed or decision-ready task, enter precise feedback and choose
  **Resume with feedback**.
- Use the Context Assistant to draft an answer, then insert or submit it.
- Choose **Continue in terminal** when direct interactive debugging is useful.
- Use **Agent terminals** to see existing panes; choose **Track in Odysseus**
  only when you want a durable shortcut in the task list.

Optional tmux setup and key bindings are documented in the
[tmux guide](../TMUX.md).

## Evidence to inspect

- Attempt number, saved agent session, branch, and worktree.
- The failure or permission request that caused Needs You.
- Feedback and answer events with their actor and timestamp.
- Recovery events and activity after the recovery point.

## Failure behavior

- Cancel and retry limits stop future work without deleting the worktree.
- A failed resume remains recoverable and records another attempt.
- Terminal continuation does not merge into the source checkout.
- Imported panes cannot invent historical tokens or tool events that Odysseus
  did not observe.

## Current boundary

tmux provides interactive continuity, not process isolation or distributed
worker ownership. Durable Worker Leases and fencing are being developed
separately for v0.9.2; they are not a property of tmux.

