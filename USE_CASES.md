# Odysseus use cases

Each story names the earliest version that supports it and gives observable
success criteria. Planned stories are clearly marked; they are not claims about
the current release.

## Run several independent changes — 0.2

An operator queues bug fixes across two repositories. Each receives its own
branch and worktree; the global scheduler starts only as many agents as the
machine can support. A failed check in one run does not contaminate another.

Success means each diff is isolated, task history survives a server restart,
and a draft PR contains only its task's changes.

## Keep the existing tmux habit — 0.2

A developer launches Codex or Claude with `prefix` + `y`, switches with
`prefix` + `u`, and occasionally uses the web page for overview. Existing panes
appear automatically. **Adopt** adds durable history without restarting the
agent or injecting keystrokes.

Success means terminal interaction remains normal, non-adopted panes remain
ephemeral, and adopted work is visible beside autonomous tasks.

## Switch one autonomous task to a human terminal — 0.2

An agent has useful context and a working diff, but the next step needs human
judgment. **Take over in tmux** opens the saved Codex or Claude thread in the
same worktree. It does not create a replacement task or a blank chat.

Success means the exact session id, branch, files, and event history survive the
transition. **Resume agent** is the autonomous equivalent: it sends guidance to
that same thread without opening a terminal.

## Turn a requirement into an approved work graph — 0.3

The operator submits “Implement passkey authentication.” A read-only Planner
inspects the repository and proposes investigation, backend, frontend,
integration, tests, and security-review tasks with dependencies. The operator
edits their intent if needed and explicitly approves before any task runs.

Success means:

- planner activity never edits the repository;
- cycles or unknown dependencies are rejected before materialization;
- independent roots become ready together;
- downstream tasks remain blocked until every predecessor is accepted or has a
  draft PR; and
- non-parallelizable integration work waits for active siblings.

Version 0.3 orders execution but does not yet compose predecessor diffs into an
integration branch; that artifact merge layer is planned for 0.4.

## Answer an agent without entering tmux — 0.3

An agent discovers that the database permits `NULL` email and asks which
migration behavior is intended. **Needs You** displays the question with
structured choices. The operator answers in the web UI or runs:

```sh
bin/odysseus attention
bin/odysseus answer ATTENTION_ID "Retain NULL for legacy accounts"
```

Success means the run pauses before checks, the question and answer are in the
append-only journal, duplicate requests do not flood the queue, and the same
agent session resumes with the answer.

## Review only exceptions across many projects — 0.3

Instead of watching thirty agent terminals, an operator opens **Needs You**.
It contains only questions, permission requests, failures, broken dependencies,
evaluation failures, and review-ready changes, sorted by priority.

Success means an empty queue really means no current human decision is needed;
opening an item links to the relevant project, epic, task, evidence, and action.

## Use independent evidence, not “agent said done” — 0.3

The implementation lane passes unit tests. A different lane reviews the diff,
while deterministic evaluators run static analysis or a project-specific
command. Odysseus combines the signals into an explainable confidence record.

For a research or quant repository, `.odysseus.json` can make a numerical
regression gate a first-class evaluator:

```json
{
  "checks": ["python3 -m unittest"],
  "evaluators": [
    {
      "id": "backtest-regression",
      "kind": "behavioral",
      "command": "./verify-backtest.sh --max-regression-bps 5",
      "weight": 0.4
    }
  ],
  "policy": {
    "min_confidence": 0.92,
    "require_human_review": true,
    "required_evaluators": ["backtest-regression"]
  }
}
```

Success means the UI shows every component, weight, verdict, missing required
evaluator, threshold, and final policy decision. Failing evidence cannot be
hidden by a confident reviewer narrative.

## Dogfood Odysseus on Odysseus — 0.3

The project queues its own documentation or implementation task. The task runs
in a separate worktree and its event stream reveals real product failures such
as an unsupported model, a denied tool permission, a redacted metric, or a
provider rate limit. The operator can preserve the worktree, fix the control
plane, and resume the same session.

Success means the orchestration failure is a durable, actionable attention
item rather than lost terminal output. `scripts/demo.py --serve` supplies a safe
seeded tour when real model usage is undesirable.

## Close the pull-request feedback loop — planned 0.4

A draft PR turns red in GitHub Actions. Odysseus captures the relevant log,
resumes the same implementation thread, reruns the local gate, pushes a fix,
and watches the next CI attempt within a bounded retry budget. Review comments
follow the same classify/fix/reject/ask-human loop.

Success means the task reaches green or creates one precise attention item; it
never retries forever or silently ignores a requested change.

## Integrate parallel task artifacts safely — planned 0.4

Two accepted task branches both touch `UserService`. Before integration,
Odysseus reports predicted file and semantic overlap, builds an integration
branch in dependency order, and reruns the combined checks.

Success means “both tasks pass alone but fail together” becomes a visible merge
risk with an auditable recommended sequence.

## Isolate runtime state as well as files — planned 0.5

Several agents need PostgreSQL and a web port. Each lane gets a disposable
container, unique ports, scoped environment, ephemeral database, resource
limits, and explicit network policy. No agent can read another repository,
production cloud credentials, or `~/.ssh`.

Success means parallel runs cannot collide on services and untrusted project
configuration cannot execute shell checks without explicit approval.

## Learn which agent works on this repository — planned 0.6

After enough accepted tasks, the operator compares lanes by task class: success
rate, median time, review corrections, CI failures, cost, tokens, and human
interventions. The router recommends a lane and explains the project-specific
evidence behind the choice.

Success means routing optimizes verified outcomes and human attention, not a
generic benchmark or model popularity.

## Queue work from another agent — planned 0.7

An interactive agent finds a bug in a shared library and calls the Odysseus MCP
server to create a task in that project. It can read status later, while the
new work still passes through isolation, checks, evaluation, and policy.

Success means provenance links the originating session to the resulting task
without granting that session hidden merge or production credentials.

## Answer routine questions from approved precedent — exploring 0.8

Attention Autopilot sees a question that matches a prior human-approved
decision and an applicable policy. It proposes the answer with citations and
confidence. Low-risk routine cases may continue under an explicit policy;
novel, conflicting, or sensitive cases remain in **Needs You**.

Success means human attention per successful change declines while permission
scope, decision provenance, and the ability to override remain fully visible.
