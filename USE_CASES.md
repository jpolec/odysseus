# Odysseus use cases

## Parallel feature work

Queue independent changes in one or several repositories. Each task gets its own
branch and worktree, while the global scheduler prevents too many local agents
from running at once. Review the diff and checks before creating a draft PR.

## Keep an existing tmux habit

Launch Codex or Claude with `prefix` + `y`, jump between sessions with
`prefix` + `u`, and use the web page as a read-only overview. Sessions appear
automatically. Adopt only the sessions that deserve durable task history.

## Switch from automation to a human terminal

Let an autonomous task do the initial implementation and checks. If the work
needs interactive judgment, choose **Take over in tmux**. Odysseus resumes the
same Codex or Claude thread rather than starting with an empty context.

## Review and return work without losing context

At the human gate, provide concrete feedback through **Resume agent**. The
existing implementation session, branch, worktree, check history, and event log
remain connected to the same task.

## Operate several repositories

Use **All projects** for a portfolio view or filter the task rail to one project.
Project registration discovers the Git branch and GitHub remote. The GitHub
view can turn an open issue into a queued task.

## Capture discovered work without scope creep

Agents can write `.odysseus-followups.json`; operators can add notes in the web
Inbox. Follow-ups stay separate from the current diff and can later be promoted
to full tasks in the correct project.

## Audit an agent run

Read the JSON run record and append-only NDJSON journal to see session ids,
messages, tool starts/results, token usage, checks, retries, review, and human
decisions. The UI replays the journal and continues live through SSE.

## Run a private remote control plane

Install Odysseus on a VPS as a loopback-only systemd service and reach it
through an SSH tunnel. If browser access through a hostname is necessary, use
the installer option that adds nginx Basic auth and Let's Encrypt TLS.
