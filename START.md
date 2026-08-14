# Start Odysseus in ten minutes

This walkthrough starts the web control plane, tries a no-token demo, runs one
isolated task or Epic DAG, and connects the tmux controls. Nothing is installed
globally.

## 1. Clone and verify

```sh
git clone https://github.com/jpolec/odysseus.git
cd odysseus
bin/odysseus doctor
```

Python 3.10+ and Git are required. Install and authenticate at least one agent
CLI (`codex` or `claude`). Install tmux and fzf for terminal session management,
and authenticate `gh` for GitHub issue intake or draft pull requests.

`doctor` prints the resolved path for every optional tool and the state
directory that Odysseus will use.

## 2. Start the control plane

```sh
bin/odysseus serve --open
```

If the browser does not open, visit <http://127.0.0.1:8741/>. Keep this process
running: it serves the UI and runs the persistent scheduler. State is stored in
`~/.odysseus` unless `ODYSSEUS_HOME` or `--state-dir` overrides it.

The landing page is **Needs You**. An empty page means no agent currently needs
an operator decision; it is not a list of every running terminal.

## 3. Optional: tour the populated UI without agents

In another terminal:

```sh
scripts/demo.py --serve
```

Open <http://127.0.0.1:8742/>. The disposable state contains a passkey Epic,
parallel task roots, a blocked integration task, a structured agent question,
a review gate, composed artifacts, merge risk, failed GitHub CI, token/tool
metrics, search, and explainable evaluation. Stop with
`Ctrl-C`; your normal `~/.odysseus` state is untouched.

## 4. Queue the first task

In the web UI:

1. Select **New task**.
2. Choose a registered project or enter its absolute path.
3. Choose `codex` or `claude`.
4. Optionally add one trusted check command per line.
5. Select **Start agent task**.

The large text box is the only creative input. Write the desired result as you
would to an engineer, including constraints and what “done” means. Repository,
agent, and checks tell Odysseus where and how to run that request; retries,
priority, and budgets stay under **Advanced**.

The equivalent CLI command is:

```sh
bin/odysseus run \
  --project /absolute/path/to/your/repository \
  --lane codex \
  --priority 70 \
  --stall-timeout 300 \
  --max-tokens 80000 \
  --check "python3 -m unittest discover -s tests -v" \
  --check "git diff --check" \
  "Add a health endpoint and cover it with tests"
```

Odysseus creates an `odysseus/<run-id>` branch and isolated Git worktree, runs
the implementation agent, executes the checks, asks a read-only agent for
review, evaluates the independent signals, and stops at the human decision
gate unless an explicit project policy permits auto-accept eligibility.

## 5. Or plan a larger requirement

Select **Epics** -> **Plan multi-task work**, or run:

```sh
bin/odysseus plan \
  --project /absolute/path/to/your/repository \
  --planner-lane claude \
  --lane codex \
  --review-lane claude \
  --check "python3 -m unittest discover -s tests -v" \
  "Implement passkey authentication end to end"
```

The Planner is read-only. Inspect its proposed graph, then approve it in the UI
or with `bin/odysseus approve-epic EPIC_ID`. Only dependency-ready roots are
queued. When a root is accepted, 0.4 commits a local artifact. A downstream
task merges every predecessor artifact into its own branch before its agent
starts; failed merges stop there and appear in **Needs You**.

## 6. Make the human decision

Open the task and inspect **Activity**, **Diff**, **Integration**, **Checks**,
**Review**, **Evaluation**, and **CI**. Or stay in **Needs You**, where agent
questions, permission requests, failures, broken dependencies, and review gates
are collected.
Then choose one action:

- **Accept** records approval and creates a local artifact commit. It does not
  push, merge into your source branch, or delete anything.
- **Resume agent** sends feedback into the saved implementation thread and the
  same worktree.
- **Continue in terminal** resumes that exact thread interactively and copies
  the safe tmux command. Paste the command into a terminal to enter the agent;
  the browser never injects keystrokes into tmux.
- **Draft PR** commits and pushes the task branch, then asks `gh` to create a
  draft pull request.

CLI equivalents:

```sh
bin/odysseus resume RUN_ID "Fix the failing edge case"
bin/odysseus resume RUN_ID --strategy switch --lane claude "Try a second lane"
bin/odysseus takeover RUN_ID
bin/odysseus accept RUN_ID
bin/odysseus draft-pr RUN_ID
bin/odysseus attention
bin/odysseus answer ATTENTION_ID "Choose option A"
bin/odysseus ci RUN_ID
bin/odysseus stats
```

## 7. Add the tmux controls

With TPM, add this before `run '~/.tmux/plugins/tpm/tpm'`:

```tmux
set -g @plugin 'jpolec/odysseus'
```

Reload tmux, press `prefix` + `I`, then use:

- `prefix` + `y` to launch or reattach an agent for the current directory.
- `prefix` + `u` to browse every managed session.
- `prefix` + `O` to start or open the web UI.

The web **Sessions** view discovers managed sessions and existing Codex/Claude
panes automatically; you do not press anything to import them. Select **Track
in Odysseus** only when you want a durable entry under Tasks. Tracking leaves
the original pane untouched and cannot recreate tokens, tools, checks, or diffs
that Odysseus did not observe. **Copy tmux command** copies the exact command to
open that pane in your terminal.

## 8. Confirm resume, terminal handoff, and tracking

The important distinction is:

- **Resume agent** continues the saved thread autonomously.
- **Continue in terminal** continues the saved thread interactively and copies
  the tmux command you paste into your terminal.
- **Track in Odysseus** adds a durable shortcut for a session that started in
  tmux; the CLI command keeps its compatibility name `adopt`.

List the resulting state from any terminal:

```sh
bin/odysseus runs
bin/odysseus sessions
bin/odysseus events RUN_ID
```

Terminal handoff is not a new agent or a copy of its files: Odysseus starts or
returns a managed tmux session in the existing task worktree and resumes the
recorded agent session id.

## 9. Continue from here

- [Complete usage guide](docs/USAGE.md): projects, inbox, GitHub, custom lanes,
  state, backups, VPS installation, and troubleshooting.
- [Use cases](USE_CASES.md): concrete operator workflows.
- [Security](SECURITY.md): local trust model and protected remote access.
- [Roadmap](ROADMAP.md): what is shipped and what is planned.
- [Version](VERSION.md): current capability matrix and upgrade notes.
