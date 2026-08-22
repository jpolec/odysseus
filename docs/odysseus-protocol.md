# Odysseus Protocol and Local API

Odysseus keeps the durable model deliberately small: a canonical hash-chained
stream per run, a replaceable JSON projection, a compact operator activity
journal, and durable command receipts. The HTTP API exposes these records,
while SSE transports new activity without inventing a second UI schema.

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
evaluation.started      evaluation.completed    evaluation.inconclusive    evaluation.failed
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
| `GET/POST` | `/api/config` | Read or update allowlisted queue, lane, budget, CI, and assistant-model settings; secrets are not accepted |
| `GET` | `/api/health` | Scheduler health plus active, queued, blocked, and attention counts |
| `GET` | `/api/runs?project_id=&status=` | Current run snapshots with optional exact filters |
| `POST` | `/api/runs` | Create a queued run |
| `GET` | `/api/runs/:id` | One run snapshot plus `_canonical_stream_version` for optimistic writes |
| `GET` | `/api/runs/:id/events?after=N` | Replay normalized events |
| `GET` | `/api/runs/:id/stream?after=N` | Continue with Server-Sent Events |
| `GET` | `/api/runs/:id/diff` | Unified patch, stat, and untracked file list |
| `POST` | `/api/runs/:id/cancel` | Request cancellation |
| `POST` | `/api/runs/:id/accept` | Accept and create a durable local artifact commit |
| `POST` | `/api/runs/:id/apply` | Merge an accepted artifact into its expected source branch; tracked edits and conflicts fail closed |
| `GET` | `/api/runs/:id/integration-candidates` | Deterministically list eligible accepted artifacts for this repository and base branch |
| `POST` | `/api/runs/:id/integration` | Record a disposition for every current candidate and queue an integration run from `integrate_now` artifacts |
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
| `GET` | `/api/projects/:id/overview` | README/instruction/ADR/stack/commit/activity Project Overview |
| `GET` | `/api/projects/:id/planning-sources` | Bounded classified repository documents with previews, hashes, and implementation state |
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
| `GET` | `/api/epics/:id` | Epic snapshot, frozen source sections, source impact, PlanVersion, and materialized runs |
| `POST` | `/api/epics/plan` | Run a read-only Planner; accepts ADR `source_paths`, `repository_source_paths`, bounded uploaded `source_documents`, authoritative `github_sources`, public `url_sources`, and explicit `force_source_paths` |
| `POST` | `/api/epics/:id/plan` | Validate an edited task contract and save a new immutable draft PlanVersion |
| `POST` | `/api/epics/:id/refresh-sources` | Explicitly freeze current local source bytes before a new PlanVersion is reviewed |
| `POST` | `/api/epics/:id/approve` | Validate and materialize a proposed task DAG |
| `GET` | `/api/commands?limit=N` | List recent durable command receipts |
| `GET` | `/api/commands/:id` | Inspect one command envelope, outcome, and redaction receipts |
| `GET` | `/api/github/issues?project_id=:id` | Open GitHub issues through authenticated `gh` |
| `GET` | `/api/github/pulls?project_id=:id` | Open GitHub pull requests through authenticated `gh` |
| `POST` | `/api/planning-sources/preview-url` | Validate and preview a public HTTPS text source; private/local redirects and likely secrets fail closed |
| `POST` | `/api/github/import` | Turn the supplied issue into a queued run |

Every `POST` and `DELETE` requires the token from `/api/bootstrap` in the
`X-Odysseus-Token` header. Mutations accept `Idempotency-Key`,
`X-Odysseus-Actor`, and `X-Odysseus-Expected-Version` headers. The default
server also rejects non-loopback Host and Origin headers.

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

## Command envelope and idempotency

Every mutating HTTP request and supported mutating CLI command first persists a
versioned envelope conceptually equivalent to:

```json
{
  "format": "odysseus-command-envelope-v1",
  "schema_version": 1,
  "command_id": "8d563b93-2f47-4b5a-a36d-67c98effc643",
  "command_type": "http.post:/api/runs/example/accept",
  "idempotency_key": "review-example-accept-v1",
  "target_stream": "run:example",
  "expected_version": 42,
  "actor": {"type": "user", "id": "web-operator"},
  "policy_context": {},
  "payload": {},
  "causation_id": "",
  "requested_at": "2026-08-19T12:00:00Z"
}
```

Payload, policy context, results, and errors cross the redaction boundary
before the receipt is written. The receipt state is one of:

| State | Meaning |
| --- | --- |
| `executing` | Durable intent exists and the recorded owner may still be running. |
| `completed` | The handler finished and its exact redacted result is durable. |
| `failed` | The request was rejected or the handler failed; the failure is durable. |
| `unknown` | The recorded process ended before committing an outcome; Odysseus will not guess or repeat it. |

An exact duplicate—same actor, idempotency key, command type, target, expected
version, policy context, and payload—returns the stored result. Reusing a key
for different request material returns a conflict. For a run-targeting command,
the expected version is checked atomically at the first canonical append; a
stale write cannot replace a newer projection.

HTTP responses include `X-Odysseus-Command-Id`,
`X-Odysseus-Command-State`, and `X-Odysseus-Idempotent-Replay`. The browser
client supplies a fresh key for each new mutation; callers implementing network
retries must reuse their original key.

The CLI options are global and therefore precede the subcommand:

```sh
odysseus --idempotency-key accept-run-42 \
  --expected-version 42 \
  --actor operator@example.com \
  accept RUN_ID

odysseus command
odysseus command COMMAND_ID
```

Command idempotency protects the local mutation handler. It does not yet claim
exactly-once behavior for every GitHub, Git, notification, or deployment side
effect; durable outbox reconciliation owns that boundary in v0.9.3.

## Worker lease and fencing record (v0.9.2)

The scheduler's claim operation atomically embeds one
`odysseus-worker-lease-v1` record in the run projection before a worker thread
starts. Its durable identity contains:

```json
{
  "format": "odysseus-worker-lease-v1",
  "lease_id": "d60545cd-770b-426e-bb4d-1fb7ab56ac4f",
  "run_id": "example-run",
  "worker_id": "scheduler:host:1234:instance-uuid",
  "worker_host": "host",
  "worker_pid": 1234,
  "epoch": 2,
  "stream_version_at_claim": 17,
  "acquired_at": "2026-08-19T20:00:00Z",
  "heartbeat_at": "2026-08-19T20:00:15Z",
  "expires_at": "2026-08-19T20:01:15Z",
  "ttl_seconds": 60,
  "active": true
}
```

Every scheduler-worker state mutation and activity append carries an in-process
token containing the run ID, lease ID, worker ID, and fencing epoch. The Store
checks that tuple and renews the heartbeat under the same cross-process lock as
the mutation. An expired lease can be recovered and replaced with epoch `N+1`;
the old worker then fails closed on its next write and cannot clear the new
lease during late cleanup.

The scheduler scans lease health continuously. When a heartbeat expires it
signals the old worker, preserves its active slot until that thread stops, and
only then permits the queued run to be claimed with epoch `N+1`. A crash after
the task reached review, failure, or another non-active state releases only the
stale lease; the completed state is not reverted.

Cancellation intent is stored in the same canonical append as the
`run.cancel_requested` event. If the owning process dies before it can stop,
recovery finalizes `cancelled` instead of re-queueing work the operator asked
to stop. Scheduler shutdown without an operator cancellation remains a
recoverable re-queue.

Release tests activate exact, otherwise inert failpoints through
`ODYSSEUS_FAILPOINT` and terminate a subprocess immediately after canonical
fsync, claim persistence, heartbeat persistence, cancellation intent, recovery
projection, or Git artifact snapshot. These variables are a test interface,
not a runtime recovery control or a substitute for process supervision.

Control-plane actions such as an operator cancellation do not impersonate a
worker token. Fencing protects acceptance of worker results into Odysseus
state; host-mode process isolation and prevention of arbitrary filesystem
writes remain separate runtime-security concerns.

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
  `pr_created`; the UI calls this explicit action **Integrate into repository**.
  The stable `/apply` API action records the target branch and before/after SHAs.
- Integration delivery requires an explicit disposition for every current
  candidate: `integrate_now`, `keep_for_later`, or `supersede`. Stale,
  incompatible-base, already-delivered, and superseded artifacts are excluded
  from the candidate set. Superseded artifacts remain accepted and inspectable
  with `integration_disposition.superseded_by` or an operator reason when given.
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
`budget_status`, `stage`, `stage_started_at`, and `last_heartbeat`.
Schema 11 adds `integration_disposition` for selected, deferred, and
superseded accepted artifacts. Store open migrates old snapshots by adding
defaults; it never rewrites event journals.

Schema 12 adds `outcome_routing`, an immutable recommendation captured when a
task is queued. It records the operator default, recommendation, applied lane,
features, minimum sample policy, candidate evidence, counterfactual, drift,
and governance note. Requests without `auto_route=true` remain shadow-only.
With explicit Auto, eligible evidence may set the run lane; sparse or disabled
routing records `automatic_fallback` and retains the configured default.

Schema 13 adds `route_observation`, a minimal versioned envelope derived from
the applied run and existing `outcome_routing` record. It captures task class,
selected agent/model/skills, selection source, deterministic selection
propensity, advisor/policy/model/feature/utility metadata versions, start/end
timing, token counters, cost observability, result, and an upcast pointer for
future RouteReceipt conversion. It observes current routing behavior only; it
does not create new autonomous routing authority.

Schema 14 makes the JSON run record a compatibility projection of a canonical
per-run stream under `streams/RUN_ID.ndjson`. Every state transition appends
and fsyncs an `odysseus-event-envelope-v2` record before the projection is
replaced. The envelope carries a contiguous `stream_version`, unique event and
command IDs, correlation/causation fields, actor, immutable projection patch,
projection hash, previous-event hash, and event hash. Checkpoints under
`checkpoints/runs/` accelerate appends but are disposable and verified against
the stream tail and materialized projection.

The canonical stream is distinct from the compact operator activity journal
under `events/`: the former reconstructs state, while the latter is the
normalized UI/proof activity feed. When a process dies after canonical fsync
but before the activity feed or projection write, opening the writable store
replays the stream, rebuilds the projection, and reconciles the missing
activity record. Historical schemas are upcast at read time; existing
canonical bytes are never rewritten.

Operators can inspect or recover state with:

```sh
odysseus replay RUN_ID
odysseus replay RUN_ID --until-event 42
odysseus rebuild-projections --dry-run
odysseus rebuild-projections
odysseus state verify --json
```

`rebuild-projections` refuses a live server-owned state directory. Rebuild and
verification receipts expose processed event counts, elapsed time, and replay
throughput so recovery cost remains observable.

Schema 15 adds `worker_lease`, including its stable record format, unique
identity, scheduler owner, fencing epoch, claim stream version, heartbeat TTL,
and release receipt. Older projections gain an inactive default lease during
migration; canonical historical event bytes are not rewritten.

Command schema 1 stores `odysseus-command-receipt-v1` records under
`commands/`. Command state is independent of run snapshot schema 15. Command
receipts introduced in v0.9.1 and Worker Leases introduced in v0.9.2 do not
rewrite existing canonical run streams.

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

## Outcome and intake APIs

- `GET /api/portfolio?days=7` returns windowed engineering delivery metrics,
  per-agent sample sizes, failure attribution, and current blockers. Unknown
  cost and unconfigured engineer-time baselines remain `null`.
- `POST /api/projects/:id/router/recommend` returns a read-only recommendation;
  `GET|POST .../router/backtest` evaluates only evidence that predates each
  decision; `GET /api/router/export` exports normalized records.
- `POST /api/projects/:id/router/delete` excludes that repository from future
  router recommendation/export. Raw run deletion remains a separate lifecycle
  decision.
- `GET /api/github/issues` lists authenticated `gh` results. A subsequent
  `POST /api/github/import` accepts the project and issue number, re-fetches the
  issue server-side, redacts its evidence, and proposes an Epic. It never trusts
  browser-supplied title/body as audit evidence and never starts tasks before
  Plan approval.
- Repeated issue intake refreshes the same Epic's latest evidence and appends a
  bounded observation receipt instead of creating a duplicate Plan.
