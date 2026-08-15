# Start Odysseus in five minutes

This walkthrough installs one command, starts the local control plane, and runs
one isolated task. Advanced planning and tmux controls remain optional.

## 1. Install and verify

```sh
curl -fsSL https://raw.githubusercontent.com/jpolec/odysseus/main/install.sh | bash
odysseus doctor
```

Python 3.10+ and Git are required. Install and authenticate at least one agent
CLI (`codex` or `claude`). Install tmux and fzf for terminal session management,
and authenticate `gh` for GitHub issue intake or draft pull requests.

`doctor` prints a short readiness report. Add `--json` for scripts. To avoid a
piped installer, clone the repository and run `./install.sh`; the installer
links the checkout command and does not copy or move your repositories.

## 2. Start the control plane

```sh
odysseus start --open
```

If the browser does not open, visit <http://127.0.0.1:8741/>. Keep this process
running: it serves the UI and runs the persistent scheduler. State is stored in
`~/.odysseus` unless `ODYSSEUS_HOME` or `--state-dir` overrides it.

On a fresh state, the landing page shows three readiness checks and one
repository-path field. Add a Git repository; registration reads metadata but
does not modify the checkout. The project page then shows one large task field.

## 3. Optional: tour the populated UI without agents

In another terminal:

```sh
odysseus demo
```

Open <http://127.0.0.1:8742/>. The disposable state contains a passkey plan,
parallel task roots, a blocked integration task, a structured agent question,
a review gate, composed artifacts, merge risk, failed GitHub CI, token/tool
metrics, Project Memory, skill routing, a Context Receipt, search, and
explainable evaluation. Stop with
`Ctrl-C`; your normal `~/.odysseus` state is untouched.

## 4. Queue the first task

In the web UI:

1. Select the project in the Explorer.
2. Describe one finished outcome in **What should change?**
3. Select **Start task**.

The large text box is the only required input. Write the desired result as you
would to an engineer, including constraints and what “done” means. The selected
project supplies the repository, default agent, and automatically relevant
generic Skills. Select **Agent, checks & limits…** only when defaults are not
enough; it opens the full task form without losing the text you entered.

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

Select a project and then **Plan feature**, or run:

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

Open the task and start with **Summary**. Use **Changes**, **Activity**, and
**Evidence** only when you need their diff, integration, exact Context Receipt,
checks, review, evaluation, or CI detail. Or stay in **Needs You**, where agent
questions, permission requests, failures, broken dependencies, and review gates
are collected.
Then choose one action:

- **Approve** records approval and creates a local artifact commit. It does not
  push, merge into your source branch, or delete anything.
- **Give feedback** sends guidance into the saved implementation thread and the
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

The web **Agent terminals** view discovers managed sessions and existing Codex/Claude
panes automatically; you do not press anything to import them. Select **Track
in Odysseus** only when you want a durable entry under Tasks. Tracking leaves
the original pane untouched and cannot recreate tokens, tools, checks, or diffs
that Odysseus did not observe. **Copy tmux command** copies the exact command to
open that pane in your terminal.

## 8. Confirm resume, terminal handoff, and tracking

The important distinction is:

- **Give feedback** continues the saved thread autonomously.
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
