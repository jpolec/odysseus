# Start Odysseus

This guide takes you from a checkout to one autonomous task and one interactive
tmux session.

## 1. Verify the machine

```sh
bin/odysseus doctor
```

Python and Git are required. Install at least one agent CLI (`codex` or
`claude`). Install tmux and fzf if you want the terminal session manager, and
authenticate `gh` if you want GitHub issue intake or draft pull requests.

## 2. Start the control plane

```sh
bin/odysseus serve --open
```

The default address is <http://127.0.0.1:8741/> and state is stored under
`~/.odysseus`.

## 3. Queue an autonomous task

In the web UI, select **New task**, choose or enter a Git repository, choose the
agent lane, and add optional checks. Or use the CLI:

```sh
bin/odysseus run --project "$PWD" --lane codex \
  --check "python3 -m unittest discover -s tests -v" \
  "Add a health endpoint and tests"
```

Odysseus creates a worktree, runs the agent, executes checks with bounded
retries, asks a read-only agent for review, and waits for your decision.

## 4. Review, resume, or take over

- **Accept** records approval without merging or deleting anything.
- **Resume agent** returns feedback to the saved implementation thread and the
  same worktree.
- **Take over in tmux** resumes that thread in an interactive managed session.
- **Draft PR** commits the task worktree, pushes the branch, and calls
  `gh pr create --draft`.

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

Reload tmux and press `prefix` + `I`. Then:

- `prefix` + `y` launches or reattaches an agent for the current directory.
- `prefix` + `u` lists every managed session.
- `prefix` + `O` starts or opens the web UI.

The web **Sessions** view polls tmux automatically. **Adopt** is optional; use it
when you want that interactive session represented in durable Odysseus history.

## 6. Use more than one project

Projects are registered automatically when a task is queued or a tmux session
is discovered. The **Projects** page and task rail can filter across all of
them. You can also register one explicitly:

```sh
bin/odysseus projects --add /srv/repos/api --tag backend --tag production
```

## 7. Run on a VPS

SSH-only access is the recommended default:

```sh
sudo scripts/install-vps.sh --service-user "$USER"
ssh -N -L 8741:127.0.0.1:8741 "$USER"@YOUR_VPS
```

Open <http://127.0.0.1:8741/> locally. For a hostname with TLS and Basic auth,
see [SECURITY.md](SECURITY.md).
