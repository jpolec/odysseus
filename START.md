# Start Odysseus in ten minutes

This walkthrough starts the web control plane, runs one isolated task, and
connects the tmux controls. Nothing is installed globally.

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

## 3. Queue the first task

In the web UI:

1. Select **New task**.
2. Choose a registered project or enter its absolute path.
3. Choose `codex` or `claude`.
4. Add one check command per line.
5. Select **Queue task**.

The equivalent CLI command is:

```sh
bin/odysseus run \
  --project /absolute/path/to/your/repository \
  --lane codex \
  --check "python3 -m unittest discover -s tests -v" \
  --check "git diff --check" \
  "Add a health endpoint and cover it with tests"
```

Odysseus creates an `odysseus/<run-id>` branch and isolated Git worktree, runs
the implementation agent, executes the checks, asks a read-only agent for
review, and stops at the human decision gate.

## 4. Make the human decision

Open the task and inspect **Activity**, **Diff**, **Checks**, and **Review**.
Then choose one action:

- **Accept** records approval without merging or deleting anything.
- **Resume agent** sends feedback into the saved implementation thread and the
  same worktree.
- **Take over in tmux** resumes that exact thread interactively and copies the
  safe attach command.
- **Draft PR** commits and pushes the task branch, then asks `gh` to create a
  draft pull request.

CLI equivalents:

```sh
bin/odysseus resume RUN_ID "Fix the failing edge case"
bin/odysseus takeover RUN_ID
bin/odysseus accept RUN_ID
bin/odysseus draft-pr RUN_ID
```

## 5. Add the tmux controls

With TPM, add this before `run '~/.tmux/plugins/tpm/tpm'`:

```tmux
set -g @plugin 'jpolec/odysseus'
```

Reload tmux, press `prefix` + `I`, then use:

- `prefix` + `y` to launch or reattach an agent for the current directory.
- `prefix` + `u` to browse every managed session.
- `prefix` + `O` to start or open the web UI.

The web **Sessions** view discovers managed sessions and existing Codex/Claude
panes automatically. Select **Adopt** only when you want a durable Odysseus
record for an interactive pane.

## 6. Confirm resume and takeover

The important distinction is:

- **Resume agent** continues the saved thread autonomously.
- **Take over in tmux** continues the saved thread interactively.
- **Adopt** attaches durable history to a session that started in tmux.

List the resulting state from any terminal:

```sh
bin/odysseus runs
bin/odysseus sessions
bin/odysseus events RUN_ID
```

## 7. Continue from here

- [Complete usage guide](docs/USAGE.md): projects, inbox, GitHub, custom lanes,
  state, backups, VPS installation, and troubleshooting.
- [Use cases](USE_CASES.md): concrete operator workflows.
- [Security](SECURITY.md): local trust model and protected remote access.
- [Roadmap](ROADMAP.md): what is shipped and what is planned.
- [Version](VERSION.md): current capability matrix and upgrade notes.
