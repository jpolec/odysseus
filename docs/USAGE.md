# Using Odysseus

This is the operator guide for local, tmux, multi-project, and remote use.

## Mental model

Odysseus manages two connected kinds of work:

1. **Autonomous tasks** start in the web UI or CLI. They receive an isolated Git
   worktree, run through implementation/check/review, and wait for a human or
   enter the bounded PR/CI repair loop.
2. **Interactive sessions** start in tmux. They are discovered automatically
   and remain ordinary terminal sessions until you explicitly track them.
3. **Plans** start as a requirement. A read-only Planner proposes a task DAG;
   the graph is inert until an operator approves it.

An autonomous task can become interactive through **Continue in terminal**. An
interactive session can gain durable Odysseus history through **Track in
Odysseus**. Neither transition discards the existing agent thread. The CLI
retains the compatibility commands `takeover` and `adopt`.

## Installation

### Install one command

Run once without a persistent install:

```sh
uvx --from git+https://github.com/jpolec/odysseus odysseus start --open
```

Or let pipx own the persistent Python package:

```sh
pipx install git+https://github.com/jpolec/odysseus
odysseus doctor
```

The versioned shell installer is stable-by-default:

```sh
curl -fsSL https://raw.githubusercontent.com/jpolec/odysseus/main/install.sh | bash
odysseus doctor
odysseus start --open
```

The installer resolves the latest stable GitHub release, keeps side-by-side
versions under `${XDG_DATA_HOME:-$HOME/.local/share}/odysseus/managed`, links
`odysseus` under `${ODYSSEUS_BIN_DIR:-$HOME/.local/bin}`, refuses to replace an
unrelated command, and runs the readiness check. Review
[`install.sh`](../install.sh) before piping it when required by local policy.

```sh
odysseus version
odysseus update --check
odysseus update
odysseus rollback
```

Update backs up mutable state and validates a copy before atomically moving the
`current` link. It preserves `worktrees/` and `runtime/`. `--edge` explicitly
selects `main`; the default never does. Update never performs a schema
downgrade. A rollback that crosses schemas requires the matching checksummed
backup through `rollback --restore-state`. Maintenance refuses a live server or
agent worker. Audit storage at any time with `odysseus state verify`. For pipx
use `pipx upgrade odysseus-agents`; uvx
owns and refreshes its own tool environment.

### Install from a checkout

```sh
git clone https://github.com/jpolec/odysseus.git
cd odysseus
./install.sh
odysseus start --open
```

There is no Python package installation step for this path. A checkout install links the
repository's `bin/odysseus` command, which imports the local package directly.
Use `bin/odysseus` without installing when developing Odysseus itself.

### Install the tmux plugin with TPM

Add this before the TPM initialization line in `~/.tmux.conf`:

```tmux
set -g @plugin 'jpolec/odysseus'
```

Reload tmux configuration and press `prefix` + `I`. TPM clones the repository
under `~/.tmux/plugins/odysseus`.

Optional configuration, placed before the plugin declaration:

```tmux
set -g @odysseus_web_key 'O'
set -g @odysseus_web_port '8741'
set -g @odysseus_web_session 'odysseus-web'
set -g @ai_session_default_lane 'codex'
set -g @ai_session_lanes 'codex claude'
```

## Start and stop the web control plane

Foreground, with logs visible:

```sh
odysseus start
```

Open <http://127.0.0.1:8741/>. Stop with `Ctrl-C`.

If that same Odysseus state is already running, another `start --open` opens it
without creating a second scheduler. If another service owns the port, the CLI
automatically tries consecutive ports and opens the
first working address without a traceback.

Inside tmux, `prefix` + `O` starts the server in a detached `odysseus-web`
session if needed and opens the browser. Inspect that server with:

```sh
tmux attach-session -t odysseus-web
```

The health endpoint is useful for scripts:

```sh
curl -fsS http://127.0.0.1:8741/api/health
```

### Disposable product tour

```sh
odysseus demo
```

Open <http://127.0.0.1:8742/>. This uses a new temporary state directory and no
agent API calls. It is also the reproducible source state for UI screenshots.
The seeded run includes composed artifacts, file overlap, a failed GitHub check,
and engineering outcome metrics.

Generate repeatable 1440×1000 web screenshots with local Chrome/Chromium:

```sh
scripts/capture-web-screenshots.sh
```

Generate the fast hero film and four focused product walkthroughs with local
Chrome/Chromium, Node.js, and ffmpeg:

```sh
scripts/capture-web-video-suite.sh
```

The recorder starts a disposable no-token demo, verifies the expected content
for every scene, captures the real browser surface, and writes the films and
posters under `docs/demo/`. Run `scripts/capture-web-demo.sh` alone for the
full 90-second source tour. Set `ODYSSEUS_WORKFLOW_FPS` to trade smoothness for
capture time; the published workflow films use 3 fps because these decision
surfaces are intentionally mostly static.

## Dogfood and measure a release

This repository ships a reviewed `.odysseus.json` check contract and a wrapper
for running Odysseus on itself:

```sh
scripts/dogfood.sh run "Finished outcome for the next change"
scripts/dogfood.sh status
scripts/dogfood.sh proof
```

The last command writes a public aggregate Markdown file and a locally ignored
JSON receipt. For another project, use the underlying command directly:

```sh
odysseus --state-dir ~/.odysseus proof --release 0.9.2
odysseus --state-dir ~/.odysseus proof --release 0.9.2 --json --output proof.json
```

Classification as `observed` is necessary but not sufficient. A counted outcome
must be terminal and its complete journal must show ordered start, agent
activity, and outcome events. Early failures count; delivery claims additionally
require final verifier success followed by artifact creation. Missing costs
remain unobserved; draft PRs are not accepted changes; explicit operator actions
are distinct from Needs You response latency. A proof below 20 eligible outcomes is marked
insufficient; add `--require-sufficient` when publication should fail closed.

## CI and release gates

Repository branch protection for `main` should require `Fast CI / unit`,
`Fast CI / compatibility (3.10)`, `Security / security`, `Installer Smoke /
installer-smoke`, and `Main Proof / release-proof`. Keep required reviews and
conversation resolution enabled, block force-pushes, and avoid administrator
bypass outside a recorded incident.

Tag releases are built by `Release Proof / release-proof` and published only by
the separate `Release Proof / publish-release` job. The tag name must match the
runtime/package version and the tagged commit must already be in `main`.
Published release assets include the source archive, wheel, `SHA256SUMS`,
`SBOM.spdx.json`, and `PROVENANCE.json`.

## Run an autonomous task

### From the web UI

The workbench keeps the same three numbered circles visible for every repository:

1. **Choose a repository.** This is one local Git checkout. Add its folder
   on first use, accept the one-click current-repository suggestion, or select
   an existing repository in the Explorer. The Git remote supplies its default
   name; the local checkout folder is shown separately.
2. **Describe a change.** Write one finished outcome and choose **Start task**.
   **Agent: Auto — recommended** uses eligible repository outcomes and falls
   back transparently when history is sparse. Skills, checks, budgets, and
   review policy are applied automatically. Use **Advanced execution settings**
   only when this task needs overrides.
   The submitted text clears immediately while **Starting** is visible. Choose
   **Start & add another** to return to a blank composer after each queued task.
3. **Review.** Watch the Summary and respond only when **Needs You**
   appears. Inspect Changes, Activity, and Evidence before the final decision.

In the default Auto mode, Odysseus previews the generic Skills it will attach
after you type the task. Open Advanced only to choose Skills manually or attach
none. Evidence -> Context later shows the exact frozen sources and reasons.

### From the CLI

```sh
bin/odysseus run \
  --project /srv/repos/api \
  --title "Add request tracing" \
  --lane codex \
  --review-lane claude \
  --base main \
  --priority 70 \
  --max-retries 2 \
  --stall-timeout 300 \
  --max-tokens 80000 \
  --max-tool-calls 120 \
  --max-cost 8 \
  --check "python3 -m unittest discover -s tests -v" \
  --check "git diff --check" \
  "Add request tracing, documentation, and tests"
```

The `--check` option is repeatable. Use `-` as the task to read a long prompt
from standard input:

```sh
bin/odysseus run --project "$PWD" --lane codex - < task.md
```

## Choose an execution environment

Every task has one explicit execution profile:

| Profile | Use it for | Boundary |
| --- | --- | --- |
| `host` | Existing local setup and fastest compatibility | Git worktree only; commands retain the server user's host access. |
| `docker` | Isolation, untrusted repositories, reproducible dependencies | Disposable command containers with only the task worktree, an isolated Git directory, and a per-run home mounted. |
| `devcontainer` | Repositories that already own a reviewed devcontainer | Runs `devcontainer up` and then `devcontainer exec`; the repository configuration defines its security boundary. |

Docker is the only profile accepted by `--untrusted-project`. Odysseus does not
mount the source repository's `.git`, home directory, SSH directory, or Docker
socket. It creates isolated Git metadata for the task, drops Linux capabilities,
sets `no-new-privileges`, makes the container root filesystem read-only, and
makes the worktree and Git metadata read-only during the reviewer phase.

The image must contain `/bin/sh`, Git, the selected agent CLI, and project
tooling. Odysseus does not silently build or pull an image. A complete example:

```sh
bin/odysseus run \
  --project /srv/repos/api \
  --environment docker \
  --image ghcr.io/example/codex-node:2026-08 \
  --network bridge \
  --cpus 2 \
  --memory 4g \
  --env NODE_ENV=test \
  --allow-env OPENAI_API_KEY \
  --allow-env GH_TOKEN \
  --port APP_PORT=3000 \
  --setup "npm ci" \
  "Fix the request race and add an integration test"
```

`--env NAME=VALUE` is for non-secret values and is stored in task state.
Credential-shaped names are rejected there. `--allow-env NAME` stores only the
name and asks Docker to copy the current host value at process start; values do
not enter JSON snapshots, NDJSON events, or the generated private env file.
Each `--port NAME=CONTAINER_PORT` gets a free loopback host port. The task's
Summary shows the mapping and preview link. CPU and memory limits apply to each
disposable command container. Setup commands should be idempotent and write
dependencies to the worktree or per-run home, because the container root is
discarded after each command.

A reviewed project default belongs in `.odysseus.json`:

```json
{
  "environment": {
    "profile": "docker",
    "image": "ghcr.io/example/codex-node:2026-08",
    "network": "bridge",
    "env": {"NODE_ENV": "test"},
    "ports": {"APP_PORT": 3000},
    "cpus": 2,
    "memory": "4g",
    "setup": ["npm ci"]
  },
  "checks": ["npm test"]
}
```

A repository may not grant itself host credential variables: project
`allow_env` entries are ignored. Operator task options override the project
profile. With `--untrusted-project`, Odysseus displays the resolved image,
network, setup, checks, and evaluators in **Needs You** and executes none of
them until **Approve once** is selected. Rejecting the gate cancels the task.

Use the repository devcontainer only after reviewing it:

```sh
bin/odysseus run --project /srv/repos/api --environment devcontainer \
  "Update the API and run its contract tests"
```

The devcontainer CLI must be installed and `.devcontainer/devcontainer.json`
or `.devcontainer.json` must exist. Credentials for this profile must be
configured by the reviewed devcontainer itself; `--allow-env` is rejected.

The scheduler runs while `odysseus serve` is active. Change its global parallel
limit with:

```sh
bin/odysseus config --max-parallel 3
```

## Plan and approve a task DAG

From **Plans** in the web UI, enter a requirement and project; advanced agent
and verification choices are optional. **Create draft** runs only the read-only
Planner and produces an editable task template. Plan Studio opens immediately
so you can revise the tasks, prompts, dependencies, evidence, and execution
profiles. No implementation agent starts at this boundary. The equivalent CLI
flow is:

After choosing the repository, either select a source or add your own
instructions. A complete ADR, specification, or GitHub Issue can stand on its
own; **Additional instructions** is optional in that case. Open **Add source
material** for an ADR, specification, incident, finding, milestone, or another
supporting document. The GitHub tab lists open Issues
and pull requests through the authenticated `gh` CLI. You can also drag/drop an ADR, PRD, specification,
finding, or incident note, choose its type independently, inspect its preview,
or add a public HTTPS text document. The composer shows every selected source
before submission. Odysseus freezes those exact bytes into the proposed
PlanVersion; the original repository and uploaded files remain untouched.

Likely secrets, duplicate document content, private/local URLs, and unsupported
remote content fail closed. A source whose linked Plan is completed is marked
**Implemented** and cannot be selected again unless you choose **Force again**.
That override is stored in the source snapshot; it never edits the ADR file.

When the source is incomplete, use **Additional instructions** for the missing
outcome or constraints. Without a source, this field is required. For a
stricter contract, expand **Add success criteria** and separate Must work, Must
not break, and Proof required.

The source browser keeps the list on the left and a readable document preview
on the right. Selecting **Read** no longer expands a small preview below the
list item.

Open **Edit draft** to return to Plan Studio. The frozen requirement is on
the left and its task contracts are on the right. Select a task to highlight
the clauses that justify it; select a clause to link or unlink it. You can edit
the finished outcome, agent instruction, dependencies, acceptance criteria,
required evidence, full Execution Profile, and low/medium/high-confidence
cost/time range. Filter task contracts to one ADR/source and sort them by Plan,
source, or dependency order. **Save draft** creates a new immutable version.
You can add and remove draft tasks before saving.
Only **Approve & start** binds the exact source and PlanVersion and creates
implementation runs. The Plans page and repository sidebar can also group or
filter history by ADR, GitHub, specification, incident/security, other source,
or one exact source path.

```sh
bin/odysseus plan \
  --project /srv/repos/api \
  --planner-lane claude \
  --lane codex \
  --review-lane claude \
  --check "python3 -m unittest" \
  "Add passkey registration and login"

bin/odysseus epics EPIC_ID
bin/odysseus approve-epic EPIC_ID
```

The Planner runs with the built-in lane's read-only mode and must finish with a
single `ODYSSEUS_PLAN:` JSON object. Approval validates the complete graph and
materializes its tasks. A task is ready only when all predecessor runs are
`accepted` or `pr_created`. Cycles and unknown keys fail before any task is
created.

Accepting a predecessor creates a local artifact commit. Before a downstream
task starts, Odysseus merges all predecessor artifact SHAs into that task's
isolated branch in dependency order. It records the complete file surface and
cross-task overlap. A real Git conflict is aborted in the downstream worktree
and becomes a high-priority operator item; the source checkout is untouched.

## Understand task state

| State | Operator meaning |
| --- | --- |
| `queued` | **Waiting to start** because every configured agent slot is busy. Open Settings or click the slot count to change capacity. |
| `blocked` | Waiting for DAG dependencies or a failed predecessor decision. |
| `running` | The implementation agent is active. |
| `checking` | Trusted project checks are executing. |
| `reviewing` | The read-only review pass is active. |
| `review` | The agent finished; use the 1 Review, 2 Test, 3 Deliver checklist. Nothing is applied yet. |
| `attention` | The agent yielded a question, permission request, or decision. |
| `failed` | Inspect the last error and event history; resume is still available. |
| `accepted` | Approval and a local artifact commit were recorded; delivery is separately not applied, applied, failed, or represented by a PR. |
| `pr_created` | A draft pull request exists and GitHub checks are being observed. |
| `session` | A durable record for an adopted interactive tmux session. |

Every task stores a current JSON snapshot plus an append-only NDJSON journal.
The web UI replays the journal, then follows new records through Server-Sent
Events.

## Work from Needs You

### Recover a failed task in the browser

When a task is in `failed` or `attention`, its Summary puts a recovery card
immediately below the status explanation:

1. Enter a concrete correction in **Resume this task with feedback**.
2. Choose **Resume with feedback**.
3. Odysseus reuses the same branch, worktree, and saved agent thread, then runs
   checks and review again.

The Summary **Context assistant** is optional. Choose **Codex CLI** or
**Claude Code CLI** to use the authentication already configured for that local
command; no API key is needed. The side panel keeps the full conversation and
context controls. Select exactly which task context may be attached. Diff/code
remains off until explicitly enabled. You can then **Insert answer**, **Submit
answer**, **Copy answer**, or **Queue as new task**. Conversation history is
local to the browser and messages derived from a context scope are omitted from
later requests when that scope is disabled.

When a task reaches `review`, Summary instead shows a deliberate three-step
checklist: review the complete diff, open a preview when the run provides one
or inspect checks and review evidence, then choose delivery. **Request changes
instead** returns feedback to the same agent thread without presenting a
successful review as a recovery failure.

The optional **Direct API: ChatGPT** and **Direct API: Claude** choices require
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in the server environment. Settings can
save the non-secret model names and show whether each provider is ready, but
Odysseus never stores API keys in JSON or browser storage. Run-derived
context is secret-redacted before it leaves Odysseus. Local CLI helpers run in
a blank scratch workspace, not the task repository, although their host process
still has the filesystem permissions of the user running Odysseus.

**Continue in terminal** is an escape hatch for interactive debugging and full
control, not a required step. Most tasks can be queued, followed, corrected,
reviewed, and approved entirely in the web interface.

The default page is an operator queue, not an agent monitor. It contains open:

- structured questions and permission requests;
- agent, dependency, integration, CI, workflow, and evaluation failures;
- actionable pull-request review feedback;
- review-ready changes.

CLI equivalents:

```sh
bin/odysseus attention
bin/odysseus answer ATTENTION_ID "Retain NULL for legacy accounts"
```

An answer is recorded as `attention.answered` and supplied to the saved
implementation session in the same worktree. **Continue in terminal** is an option
when the decision is easier to make interactively. Resolving an item without an
answer closes the notification but does not invent agent guidance.

## Review, resume, and take over

### Resume autonomously

From the review or failed state:

```sh
bin/odysseus resume RUN_ID "Address the review findings and rerun every check"
```

Odysseus reuses the implementation agent's saved session id, original worktree,
and branch. It does not start an unrelated conversation.

Choose a different recovery strategy when repeating the same thread is not the
right answer:

```sh
# Give the existing branch/worktree to another lane with no foreign session id.
bin/odysseus resume RUN_ID --strategy switch --lane claude \
  "Review the previous attempt and repair it"

# Keep branch and files, but start with a clean agent context.
bin/odysseus resume RUN_ID --strategy clean \
  "Use the persisted failure trace and finish the task"
```

### Take over interactively

```sh
bin/odysseus takeover RUN_ID
```

The command prints a `tmux attach-session` command and creates the managed
session only once. The same session appears in `prefix` + `u` and the web
**Agent terminals** view.

### Accept, apply, or publish

```sh
bin/odysseus accept RUN_ID
bin/odysseus apply RUN_ID
bin/odysseus draft-pr RUN_ID
```

Accept records the decision and snapshots the complete worktree into a local
Git artifact. It does not push or merge the artifact. Apply is a separate,
explicit action: the source checkout must be clean, checked out on the task's
base branch, and still descend from the recorded base commit. Here “clean”
means no tracked local edits: unrelated untracked files are preserved, while
Git refuses any untracked path the artifact would overwrite. Odysseus merges
the complete artifact branch so composed DAG predecessors are not lost, and it
aborts a conflicting merge before returning an error. A blocked web action
shows the reason, a source-status command, and—when applicable—a recoverable
stash command before **Try apply again**. Draft PR pushes the task
branch and invokes `gh pr create --draft` without changing the source checkout.

## Reach green after publishing

The server watches every Odysseus draft PR through authenticated `gh`. On a
failed check it records the check set, fetches failed logs when a GitHub Actions
run id is available, and resumes the saved implementation thread. A locally
verified repair is committed and pushed to the same PR branch. The configured
attempt budget then either reaches green or creates a precise Needs You item.

Poll immediately instead of waiting for the background interval:

```sh
bin/odysseus ci RUN_ID
```

New PR review comments are deduplicated and normalized into operator decisions.
Odysseus never auto-merges the PR.

## Use existing tmux sessions

### Launch from the current pane

Press `prefix` + `y`. Odysseus identifies the current repository, uses the
default lane, and launches or reattaches its managed session.

### Find all sessions

Press `prefix` + `u`, or run:

```sh
bin/odysseus sessions
```

The picker combines managed sessions with existing panes whose foreground
process is recognized as Codex or Claude. Use Enter to jump to a session.

### Track an interactive session durably

Open **Agent terminals** in the web UI and select **Track in Odysseus**, or run:

```sh
bin/odysseus adopt TMUX_SESSION
```

Tracking creates a durable run/event record. It does not restart the agent,
move the pane, inject keystrokes, or invent telemetry from before tracking.
By default, the web view is scoped to the selected repository, or to saved
repositories when no single repository is selected. Choose **All discovered
sessions** when you want the global resume-style picker for other Codex or
Claude panes.

## Work across repositories

Repositories register from managed tasks or explicit operator action. Passive
tmux discovery is read-only and never changes the repository list. Add or
refresh a repository before its first task with:

```sh
bin/odysseus projects \
  --add /srv/repos/api \
  --name "Public API" \
  --tag backend \
  --tag production
```

Use the repository selector in **Tasks** to narrow the task rail. **Manage
repositories** shows paths, tags, branch information, and recognized GitHub remotes.

### Use Repository Overview, Skills, and Memory

Select a repository in the Explorer:

- **Repository overview** uses the README by default. **Edit overview** stores
  an optional private summary and notes in Odysseus; it never rewrites README.
- **Repository context** lists detected agent instructions and stack markers.
  Recent commits and Task History explain what happened across runs.
- **Project Decisions** discovers versioned ADRs in `_ADR/` and conventional
  ADR folders. Select one or more and choose **Plan selected**. The Planner
  proposes a DAG for approval and freezes the exact documents into the Epic
  and every task Context Receipt. The catalog then reports what is unplanned,
  proposed, active, blocked, or completed, including task counts, observed
  tokens, and provider-reported cost. See
  [Project decisions and ADRs](PROJECT_DECISIONS.md).
- **Skills** are generic engineering playbooks. Expand one to inspect
  it, then choose Auto, Required, or Disabled for this repository. Bundled
  skills cover common security, database, API, test, accessibility,
  dependency, performance, incident, and documentation work.
- **Repository Memory** is only for facts unique to this codebase. Add a title,
  exact guidance, task triggers, and optional folder signals. An item with no
  triggers or folders is always attached; use that sparingly. Toggle an item
  off without deleting its history.

Repository-local skills can be added at `.agents/skills/NAME/SKILL.md`,
`.github/skills/NAME/SKILL.md`, or `.claude/skills/NAME/SKILL.md`. A local skill
overrides a bundled skill with the same `name` for that repository only. Minimal
format:

```markdown
---
name: release-check
description: Verify this repository's release compatibility contract.
triggers: release, version, changelog
---

# Release check

Run the compatibility suite and verify upgrade notes before declaring done.
```

The New Task default is automatic selection. From the CLI:

```sh
# Explainable automatic selection from task signals, policy, and observed history.
bin/odysseus run --project /srv/repos/api --skill-mode auto \
  "Review authentication security"

# Explicit selection, repeat --skill as needed.
bin/odysseus run --project /srv/repos/api --skill-mode manual \
  --skill security-review --skill test-strategy \
  "Review authentication security"

# Attach no generic Skills. Matching Project Memory still applies.
bin/odysseus run --project /srv/repos/api --skill-mode none \
  "Perform a clean-context investigation"
```

Repeated review guidance or failing checks may appear under **Suggested from
history**. A suggestion is not active context: inspect and save it before use.
Odysseus does not silently convert model output into trusted project memory.

For every autonomous task, **Evidence -> Context** displays
`context-receipt-v1`: task and bundle digests, source path/type, selection
reason, byte count, and the immutable snapshot. The run JSON and append-only
NDJSON retain the same provenance even if README, Memory, or Skills change
later.

## Capture follow-up work in the inbox

Add a note from the web **Inbox**, or from the CLI:

```sh
bin/odysseus inbox \
  --project /srv/repos/api \
  --title "Rollback coverage" \
  --add "Add an integration test for rollback after a partial migration"
```

Resolve an item without creating a task:

```sh
bin/odysseus inbox --resolve ITEM_ID
```

In the web UI, **Queue as agent task** converts an open item into a queued autonomous task.
Agents can submit follow-ups with `.odysseus-followups.json`; Odysseus imports
the file after the implementation phase and removes it before review.

## Queue GitHub issues

Authenticate GitHub CLI first:

```sh
gh auth status
```

Register a repository with a GitHub remote, open **GitHub**, choose the project,
and select **Load issues**. **Queue issue** copies the issue title/body and
source URL into a new task. Odysseus does not modify or close the source issue.

## Configure project checks

Commit `.odysseus.json` in a project to provide default checks:

```json
{
  "checks": [
    "python3 -m unittest discover -s tests -v",
    "git diff --check"
  ]
}
```

Checks passed directly with `--check` or the web form take precedence. These
commands are trusted configuration and execute through `/bin/sh -c` inside the
isolated task worktree. Host checks inherit the Odysseus server's `PATH`; they
do not load login-shell files that could silently select a different Python,
Node, or other toolchain.

### Add independent evaluators and policy

```json
{
  "checks": ["python3 -m unittest"],
  "evaluators": [
    {
      "id": "security",
      "kind": "static",
      "command": "semgrep --config auto",
      "weight": 0.3
    }
  ],
  "policy": {
    "min_confidence": 0.9,
    "require_human_review": true,
    "required_evaluators": ["security"]
  }
}
```

Evaluators are trusted shell commands executed after the normal checks. The
evaluation view combines them with check outcomes, the structured independent
review, and lane independence. Keep `require_human_review` true until the
project's gates are mature. Setting it false can mark an eligible run accepted,
but never merges or publishes code.

## Configure a custom lane

Edit `~/.odysseus/config.json`. A custom lane can be an argv array:

```json
{
  "max_parallel": 2,
  "default_lane": "codex",
  "max_retries": 2,
  "lanes": {
    "my-agent": ["my-agent", "--cwd", "{worktree}", "--prompt", "{prompt}"]
  }
}
```

Shell-style strings are also accepted. Prefer argv arrays because argument
boundaries are unambiguous. `{worktree}` and `{prompt}` are replaced for each
run. Built-in Codex and Claude adapters additionally normalize telemetry and
support durable resume.

### Configure budgets, CI, and notifications

The same config file accepts global defaults:

```json
{
  "budgets": {
    "timeout_seconds": 1800,
    "stall_seconds": 300,
    "max_tokens": 80000,
    "max_tool_calls": 120,
    "max_cost_usd": 8.0
  },
  "ci": {
    "watch": true,
    "auto_resume": true,
    "max_attempts": 2,
    "poll_seconds": 30
  },
  "notifications": [
    {"type": "webhook", "name": "automation", "url": "https://example.test/hook"},
    {"type": "ntfy", "name": "phone", "url": "https://ntfy.sh/private-topic"},
    {"type": "slack", "name": "team", "url": "https://hooks.slack.com/services/..."}
  ]
}
```

Zero disables a budget. Token, tool, and cost enforcement can observe only
metrics emitted by the selected agent. Destination URLs are operator secrets;
Odysseus records destination names and delivery outcomes, not their URLs.

## Search and engineering outcomes

Use **Insights** in the web UI, or:

```sh
bin/odysseus search "privilege escalation"
bin/odysseus stats
bin/odysseus resources --json
bin/odysseus export --output odysseus-evidence.json
```

Search covers local run snapshots, recent run events, Epics, projects,
attention, and Inbox records. `stats` reports successful changes, observed
tokens/tool calls/cost, interventions, CI repair loops, and high merge-risk
tasks. `resources --json` is a non-destructive inventory of retained worktrees
and runtime directories; deletion requires an explicit `resources --reclaim`.
Export is a portable evidence bundle; 0.4 does not import it back.

## Inspect, back up, and relocate state

Default layout:

```text
~/.odysseus/
├── config.json
├── projects.json
├── inbox.json
├── attention.json
├── notifications.ndjson
├── epics/<epic-id>.json
├── runs/<run-id>.json
├── events/<run-id>.ndjson
└── worktrees/<repository>-<sha>/<run-id>/
```

Use a separate state root for testing or another operator profile:

```sh
ODYSSEUS_HOME=/srv/odysseus-state bin/odysseus serve
bin/odysseus --state-dir /srv/odysseus-state runs
```

For a consistent backup, stop the server first and copy the complete state
directory. Worktrees also remain registered in their source Git repositories;
do not move individual state files independently.

## Install on a VPS

The installer copies the current checkout into `/opt/odysseus`, creates a
systemd service, stores state in `/var/lib/odysseus`, and binds the application
to VPS loopback:

```sh
sudo scripts/install-vps.sh --service-user "$USER"
```

The service user must own the agent and GitHub CLI credentials that tasks need.
From your workstation:

```sh
ssh -N -L 8741:127.0.0.1:8741 USER@VPS
```

Then open <http://127.0.0.1:8741/> locally. Keep port 8741 closed in the VPS
firewall.

### Private mobile access with Tailscale

Use this path when you want to operate Odysseus from a phone or tablet without
opening the service to the public internet. Odysseus still binds to
`127.0.0.1` on the VPS; Tailscale Serve publishes that local port only inside
your tailnet.

Prerequisites:

- Tailscale is installed and signed in on the VPS.
- MagicDNS is enabled for the tailnet, or you know the VPS tailnet DNS name.
- The Tailscale mobile app is installed and signed in to the same tailnet.

Install Odysseus and configure the private mobile URL:

```sh
sudo scripts/install-vps.sh --service-user "$USER" --tailscale
```

If you already know the VPS tailnet name, make the final installer output
copy-pasteable:

```sh
sudo scripts/install-vps.sh \
  --service-user "$USER" \
  --tailscale-name vps-name.tailnet.ts.net
```

On the phone or tablet, connect Tailscale and open the printed
`http://vps-name.tailnet.ts.net:8741/` URL. If the installer cannot detect the
name, run this on the VPS and use the URL it prints:

```sh
tailscale serve status
```

To remove the private mobile route without stopping Odysseus:

```sh
sudo tailscale serve reset
```

Keep the VPS firewall closed for port 8741. Tailscale handles device identity
and network reachability; Odysseus is still a one-operator control plane and is
not a public multi-tenant service.

### Public hostname

For a public hostname, install nginx, Certbot, and `htpasswd`, then run:

```sh
sudo scripts/install-vps.sh \
  --service-user odysseus \
  --domain agents.example.com \
  --web-user odysseus
```

The installer prompts for the Basic-auth password and obtains a Let's Encrypt
certificate. See [../SECURITY.md](../SECURITY.md) for the trust model.

## Troubleshooting

### A queued task never starts

- Confirm `bin/odysseus serve` is still running.
- Open `/api/health` and check the active/queued counts.
- Run `bin/odysseus doctor` and verify the selected agent CLI exists.
- Inspect `bin/odysseus events RUN_ID` and `bin/odysseus show RUN_ID`.
- For tasks created from a plan, inspect `depends_on`, `blocked_reason`, and
  `bin/odysseus epics EPIC_ID`.

### A tmux session is missing

- Select **Refresh now** in the Agent terminals view.
- Confirm the pane's foreground command is Codex or Claude.
- Run `bin/odysseus sessions --json` for the raw discovery result.
- Confirm the web server runs as the same OS user and can access the same tmux
  server.

### The web shortcut says the API is not responding

Attach to `odysseus-web` and inspect its output:

```sh
tmux attach-session -t odysseus-web
```

If another process owns the configured port, either stop it or change
`@odysseus_web_port` before the plugin declaration.

### Resume is unavailable

Resume requires a saved Codex or Claude implementation session id and a task in
attention, review, failed, accepted, or `pr_created` state. A switch/clean
strategy can start without reusing that id. Inspect `agent_sessions` with:

```sh
bin/odysseus show RUN_ID
```

### GitHub features fail

Run `gh auth status` as the same OS user that runs Odysseus. Confirm the project
has a recognized GitHub remote and that the task branch can be pushed.

## Command reference

```text
serve       Run the scheduler and local web UI
run         Queue an autonomous task
runs        List persisted tasks and adopted sessions
plan        Propose an approval-gated Epic task DAG
epics       List Epics or inspect one graph
approve-epic Materialize and queue an approved graph
attention   List open operator decisions
answer      Answer and resume the linked agent session
show        Print one run snapshot
events      Print one run's event journal
resume      Resume, switch lane, or start clean on the existing branch
takeover    Continue the saved thread interactively in tmux
accept      Record approval and create a local artifact commit
send-back   Return review feedback to the agent workflow
cancel      Request task cancellation
draft-pr    Commit, push, and create a draft pull request
sessions    List auto-discovered tmux sessions
adopt       Give an interactive session durable history
projects    List or register repositories
inbox       List, add, or resolve follow-ups
config      Read or change scheduler configuration
ci          Poll GitHub checks and run the bounded repair policy
command     List or inspect durable Command API receipts
replay      Reconstruct one run from its canonical event stream
rebuild-projections Rebuild replaceable run projections from canonical streams
search      Search local runs, events, and operator records
stats       Show engineering outcomes and observed economics
export      Write an inspectable JSON evidence bundle
doctor      Inspect dependencies and state
```

Run `bin/odysseus COMMAND --help` for exact options.
