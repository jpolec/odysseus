# Odysseus Protocol and Local API

Odysseus keeps the durable model deliberately small: a current JSON snapshot
per run and an append-only NDJSON event journal. The HTTP API exposes the same
records, while SSE transports new events without inventing a second schema.

## Run States

| State | Meaning |
| --- | --- |
| `queued` | Persisted and eligible for a scheduler slot |
| `blocked` | A DAG predecessor is incomplete, failed, cancelled, or missing |
| `starting` | Claimed by a scheduler process |
| `running` | Implementation agent is active |
| `checking` | Project checks are running |
| `reviewing` | Read-only agent review is running |
| `review` | Waiting for a human decision |
| `attention` | Agent yielded a question, permission request, or decision |
| `failed` | Agent, check retry budget, or workflow failed |
| `cancelling` | Cancellation was requested |
| `cancelled` | Child process stopped and the run is terminal |
| `accepted` | Human accepted the review result |
| `publishing` | Branch is being committed and pushed |
| `pr_created` | Draft pull request was created |
| `session` | Durably tracked interactive tmux session; not scheduler-eligible |

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
run.attention           run.review_ready        run.accepted
run.heartbeat           run.stalled             run.budget_exceeded
worktree.creating       worktree.ready          worktree.dirty_base
artifact.created
integration.started     integration.artifact_applied
integration.completed   integration.conflict
step.started            step.completed          step.failed
agent.output            agent.message           agent.reasoning
agent.session           agent.tool.started      agent.tool.completed
agent.usage             agent.cost              agent.completed
agent.question          agent.permission_request
agent.blocked           agent.decision_required
check.output            check.completed         workflow.retry
review.sent_back        review.accepted         review.comment
pr.creating             pr.created              pr.failed
ci.started              ci.passed               ci.failed
ci.poll_failed          ci.retry_queued         ci.retry_pushed
ci.retry_exhausted
system.recovered
session.adopted         session.resumed         session.takeover_ready
inbox.created           inbox.promoted
attention.answered      attention.resolved
evaluation.started      evaluation.completed    evaluation.failed
epic.created            epic.proposed           epic.activated
epic.task_created       epic.completed          epic.failed
dag.dependency_met      dag.blocked              dag.unblocked
planner.started         planner.completed        planner.failed
skill.selected          skill.loaded
context.receipt.created knowledge.selected
environment.prepared    environment.starting    environment.started
environment.setup_started environment.setup_completed
environment.approved    environment.rejected
```

## HTTP API

The default origin is `http://127.0.0.1:8741`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/bootstrap` | UI metadata and the per-process mutation token |
| `GET` | `/api/health` | Scheduler health plus active, queued, blocked, and attention counts |
| `GET` | `/api/runs?project_id=&status=` | Current run snapshots with optional exact filters |
| `POST` | `/api/runs` | Create a queued run |
| `GET` | `/api/runs/:id` | One run snapshot |
| `GET` | `/api/runs/:id/events?after=N` | Replay normalized events |
| `GET` | `/api/runs/:id/stream?after=N` | Continue with Server-Sent Events |
| `GET` | `/api/runs/:id/diff` | Unified patch, stat, and untracked file list |
| `POST` | `/api/runs/:id/cancel` | Request cancellation |
| `POST` | `/api/runs/:id/accept` | Accept and create a durable local artifact commit |
| `POST` | `/api/runs/:id/apply` | Merge an accepted artifact into its clean expected source branch |
| `POST` | `/api/runs/:id/send-back` | Requeue with `{ "feedback": "..." }` |
| `POST` | `/api/runs/:id/resume` | Continue with `{ "prompt": "...", "strategy": "resume|switch|clean", "lane": "..." }` |
| `POST` | `/api/runs/:id/takeover` | Create/return a managed interactive tmux continuation |
| `POST` | `/api/runs/:id/draft-pr` | Commit, push, and create a draft PR |
| `POST` | `/api/runs/:id/ci-poll` | Poll GitHub checks for this published run now |
| `GET` | `/api/search?q=...` | Search runs, recent events, Epics, projects, attention, and Inbox |
| `GET` | `/api/stats` | Aggregate outcomes, observed economics, interventions, CI, and merge risk |
| `GET` | `/api/projects` | Registered projects and Git/GitHub metadata |
| `POST` | `/api/projects` | Register or refresh a project |
| `DELETE` | `/api/projects/:id` | Remove a registry entry (does not delete files) |
| `GET` | `/api/projects/:id/overview` | README/instruction/stack/commit/activity Project Overview |
| `GET/POST` | `/api/projects/:id/profile` | Read or update the private Project Brief |
| `GET/POST` | `/api/projects/:id/skills` | Inspect catalog/effectiveness or update skill policies |
| `POST` | `/api/projects/:id/skills/recommend` | Explain automatic skill ranking for `{ "task": "..." }` |
| `GET/POST` | `/api/projects/:id/knowledge` | Inspect Memory/suggestions or create/update an item |
| `GET` | `/api/tmux/sessions` | Auto-discovered live tmux sessions |
| `POST` | `/api/tmux/sessions/:name/adopt` | Create durable history for an interactive session |
| `GET` | `/api/inbox` | Cross-project follow-ups |
| `POST` | `/api/inbox` | Capture a follow-up |
| `POST` | `/api/inbox/:id/resolve` | Resolve a follow-up |
| `POST` | `/api/inbox/:id/promote` | Turn a follow-up into a queued run |
| `GET` | `/api/attention?status=open` | Cross-project operator attention queue |
| `GET` | `/api/attention/:id` | One attention item |
| `POST` | `/api/attention/:id/respond` | Answer with `{ "response": "..." }` and resume the linked session |
| `POST` | `/api/attention/:id/resolve` | Close a notification without inventing an answer |
| `GET` | `/api/epics` | List Epic proposals and active graphs |
| `GET` | `/api/epics/:id` | Epic snapshot plus materialized runs |
| `POST` | `/api/epics/plan` | Run a read-only Planner and create a proposal |
| `POST` | `/api/epics/:id/approve` | Validate and materialize a proposed task DAG |
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
  "base_ref": "main",
  "priority": 70,
  "skill_mode": "auto",
  "skills": [],
  "environment": {
    "profile": "docker",
    "image": "ghcr.io/example/coding-agent:2026-08",
    "network": "none",
    "env": {"APP_MODE": "test"},
    "allow_env": ["OPENAI_API_KEY"],
    "ports": {},
    "cpus": 2,
    "memory": "4g",
    "setup": []
  },
  "untrusted_project": true,
  "budgets": {
    "timeout_seconds": 1800,
    "stall_seconds": 300,
    "max_tokens": 80000,
    "max_tool_calls": 120,
    "max_cost_usd": 8.0
  }
}
```

SSE messages use `event: odysseus`, set the event `id` to the run-local
sequence number, and put the complete event envelope in `data`. Browsers can
reconnect with `Last-Event-ID` or an explicit `after` query.

## Planner and evaluation markers

The read-only Planner's final output contains one line:

```text
ODYSSEUS_PLAN: {"summary":"...","tasks":[{"task_key":"api","title":"API","task":"...","role":"implementer","depends_on":[]}]}
```

The independent Reviewer's final output contains one line:

```text
ODYSSEUS_EVALUATION: {"score":0.94,"verdict":"pass","findings":[]}
```

An implementation agent that cannot safely continue may yield:

```text
ODYSSEUS_ATTENTION: {"type":"question","title":"Migration policy","message":"Retain NULL?","options":["retain","not-null"],"priority":"medium"}
```

Built-in Codex and Claude normalizers also translate native question and denied
permission events. Marker parsing is a compatibility path for headless/custom
lanes; unknown or malformed markers never become implicit approval.

## DAG semantics

- `depends_on` contains run ids; `dependency_keys` retains stable Epic keys.
- A dependency is met only at `accepted` or `pr_created`.
- Failed, cancelled, or missing dependencies keep downstream work blocked and
  emit an attention item.
- The scheduler validates readiness again while claiming, closing the race
  between graph refresh and worker start.
- `parallelizable: false` excludes overlap with active siblings in the Epic.
- `accepted` records an `artifact_sha` and `artifact_files` surface.
- `delivery.status` distinguishes `not_applied`, `applied`, `failed`, and
  `pr_created`; Apply records the target branch and before/after commit SHAs.
- Before a downstream agent starts, artifacts are merged in `depends_on` order
  into that run's worktree. Applied sources and resulting head are recorded.
- Pairwise file overlap produces `merge_analysis`; a real Git conflict emits
  `integration.conflict`, aborts the merge, and fails the downstream run.

## Review and Git Semantics

- A task branch starts at the recorded `base_sha`, not at uncommitted source
  checkout changes.
- Diff output compares the complete worktree, index, and task-branch commits to
  `base_sha`; readable untracked files are included.
- Accept stages the complete task worktree and creates a local artifact commit.
  It does not push, merge to the source branch, or remove the worktree.
- Resume/send back preserves the branch/worktree. `resume` reuses the recorded
  implementation session; `switch` clears it and changes lane; `clean` clears
  it without changing lane.
- Draft PR runs `git add -A`, creates a commit when needed, pushes the task
  branch, and invokes `gh pr create --draft`.
- Published runs carry normalized `ci.status`, check records, failed logs, and
  attempt count. Eligible automatic repairs push to the same PR branch; retry
  exhaustion creates attention and never auto-merges.

## Run snapshot schema additions

Schema 4 adds `priority`, `artifact_sha`, `artifact_files`,
`artifact_created_at`, `integration_sources`, `integration_head`,
`merge_analysis`, `ci`, `ci_retry_active`, `github_feedback_seen`, `budgets`,
`budget_status`, `stage`, `stage_started_at`, and `last_heartbeat`. Store open
migrates old snapshots by adding defaults; it never rewrites event journals.

Schema 5 adds `skill_mode`, `skills_requested`, `skills_selected`, and immutable
`skill_context`. Schema 6 adds `context_bundle` and `context_receipt`. Schema 7
adds `knowledge_selected` and the explainable `skill_routing` record. Context
and skill payloads are queue-time snapshots; consumers must not replace their
digests with the current contents of a repository file.

Schema 8 adds `environment_request`, the resolved `environment` plan,
`untrusted_project`, and `project_commands_approved`. Credential values named
by `allow_env` are deliberately absent from snapshots and event data. An
untrusted run may enter `attention` with `environment.trust_status=pending`
before any agent or repository command; answering its permission request with
`approve` queues the same run once with `project_commands_approved=true`.
