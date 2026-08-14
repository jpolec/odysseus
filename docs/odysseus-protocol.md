# Odysseus Protocol and Local API

Odysseus keeps the durable model deliberately small: a current JSON snapshot
per run and an append-only NDJSON event journal. The HTTP API exposes the same
records, while SSE transports new events without inventing a second schema.

## Run States

| State | Meaning |
| --- | --- |
| `queued` | Persisted and eligible for a scheduler slot |
| `starting` | Claimed by a scheduler process |
| `running` | Implementation agent is active |
| `checking` | Project checks are running |
| `reviewing` | Read-only agent review is running |
| `review` | Waiting for a human decision |
| `failed` | Agent, check retry budget, or workflow failed |
| `cancelling` | Cancellation was requested |
| `cancelled` | Child process stopped and the run is terminal |
| `accepted` | Human accepted the review result |
| `publishing` | Branch is being committed and pushed |
| `pr_created` | Draft pull request was created |
| `session` | Adopted interactive tmux session; not scheduler-eligible |

A server restart recovers orphaned active states to `queued`. It does not erase
their existing event history or worktree.

## Event Envelope

```json
{
  "v": 1,
  "seq": 8,
  "ts": "2026-08-14T12:00:00Z",
  "run_id": "20260814-120000-example-a1b2",
  "type": "agent.output",
  "source": "codex",
  "data": {
    "stream": "stdout",
    "text": "Implemented the change.",
    "vendor_type": "item.completed"
  }
}
```

- `v` is the protocol version.
- `seq` increases monotonically within one run.
- `source` identifies `odysseus`, `git`, `check`, `user`, or the agent lane.
- `data` is event-specific and must remain a JSON object.
- Vendor-specific event names may be retained as `data.vendor_type`; consumers
  should branch on the normalized top-level `type`.

Current event types:

```text
run.queued              run.started             run.status
run.cancel_requested    run.cancelled           run.failed
run.review_ready        run.accepted
worktree.creating       worktree.ready          worktree.dirty_base
step.started            step.completed          step.failed
agent.output            agent.message           agent.reasoning
agent.session           agent.tool.started      agent.tool.completed
agent.usage             agent.cost              agent.completed
check.output            check.completed         workflow.retry
review.sent_back        review.accepted
pr.creating             pr.created              pr.failed
system.recovered
session.adopted         session.resumed         session.takeover_ready
inbox.created           inbox.promoted
```

## HTTP API

The default origin is `http://127.0.0.1:8741`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/bootstrap` | UI metadata and the per-process mutation token |
| `GET` | `/api/health` | Scheduler health, active count, and queued count |
| `GET` | `/api/runs` | All current run snapshots, newest first |
| `POST` | `/api/runs` | Create a queued run |
| `GET` | `/api/runs/:id` | One run snapshot |
| `GET` | `/api/runs/:id/events?after=N` | Replay normalized events |
| `GET` | `/api/runs/:id/stream?after=N` | Continue with Server-Sent Events |
| `GET` | `/api/runs/:id/diff` | Unified patch, stat, and untracked file list |
| `POST` | `/api/runs/:id/cancel` | Request cancellation |
| `POST` | `/api/runs/:id/accept` | Accept at the human review gate |
| `POST` | `/api/runs/:id/send-back` | Requeue with `{ "feedback": "..." }` |
| `POST` | `/api/runs/:id/resume` | Continue the saved implementation thread with `{ "prompt": "..." }` |
| `POST` | `/api/runs/:id/takeover` | Create/return a managed interactive tmux continuation |
| `POST` | `/api/runs/:id/draft-pr` | Commit, push, and create a draft PR |
| `GET` | `/api/projects` | Registered projects and Git/GitHub metadata |
| `POST` | `/api/projects` | Register or refresh a project |
| `DELETE` | `/api/projects/:id` | Remove a registry entry (does not delete files) |
| `GET` | `/api/tmux/sessions` | Auto-discovered live tmux sessions |
| `POST` | `/api/tmux/sessions/:name/adopt` | Create durable history for an interactive session |
| `GET` | `/api/inbox` | Cross-project follow-ups |
| `POST` | `/api/inbox` | Capture a follow-up |
| `POST` | `/api/inbox/:id/resolve` | Resolve a follow-up |
| `POST` | `/api/inbox/:id/promote` | Turn a follow-up into a queued run |
| `GET` | `/api/github/issues?project_id=:id` | Open GitHub issues through authenticated `gh` |
| `POST` | `/api/github/import` | Turn the supplied issue into a queued run |

Every `POST` requires the token from `/api/bootstrap` in the
`X-Odysseus-Token` header. The default server also rejects non-loopback Host and
Origin headers.

Example create request:

```json
{
  "title": "Add health endpoint",
  "task": "Add a health endpoint and tests.",
  "project_path": "/absolute/path/to/repository",
  "lane": "codex",
  "review_lane": "claude",
  "workflow": "agent-check-review",
  "checks": ["python3 -m unittest"],
  "max_retries": 2,
  "base_ref": "main"
}
```

SSE messages use `event: odysseus`, set the event `id` to the run-local
sequence number, and put the complete event envelope in `data`. Browsers can
reconnect with `Last-Event-ID` or an explicit `after` query.

## Review and Git Semantics

- A task branch starts at the recorded `base_sha`, not at uncommitted source
  checkout changes.
- Diff output compares the complete worktree, index, and task-branch commits to
  `base_sha`; readable untracked files are included.
- Accept is a durable decision only. It does not merge or remove the worktree.
- Resume/send back preserves the branch/worktree and uses the recorded Codex or
  Claude implementation session id for the new cycle.
- Draft PR runs `git add -A`, creates a commit when needed, pushes the task
  branch, and invokes `gh pr create --draft`.
