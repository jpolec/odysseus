# Security

The detailed threat model is maintained in
[docs/security/threat-model.md](docs/security/threat-model.md). This page is
the operational summary for the current release.

## Local default

Odysseus binds to `127.0.0.1`, validates loopback Host and Origin headers, sends
no CORS permission, and requires a per-process same-origin token on mutations.
The default `host` execution profile still operates with the permissions of the
user who started the server, so use it only with repositories and commands you
trust.

> **Trusted-repository boundary:** in `host` mode, `setup`, `checks`, and
> `evaluators` execute through `/bin/sh -c` in the task worktree with the
> server user's permissions. Opening an untrusted repository without
> `--untrusted-project` is remote code execution by design.

A Git worktree isolates code changes, not filesystem permissions. Host,
Docker, and devcontainer command launches receive a scoped process environment:
common non-secret shell variables such as `PATH` are preserved, per-task
non-secret environment values are added, and server credentials are passed only
when an operator explicitly names them in task `allow_env`. Context Assistant
API keys remain server-only by default. The optional Docker profile adds a
controlled runtime boundary for each command:

- only the task worktree, isolated task Git metadata, and per-run home are
  mounted; the source repository's `.git`, `~/.ssh`, other repositories, and
  Docker socket are not mounted;
- the root filesystem is read-only, Linux capabilities are dropped, and
  `no-new-privileges` is set;
- network mode, loopback port publication, CPU, and memory are explicit;
- credential values are passed only for operator-named variables and are not
  persisted in run snapshots, events, or the generated owner-only env file;
- the review phase mounts the worktree and isolated Git metadata read-only.

Docker is meaningful containment, not a claim of a formally verified sandbox.
The selected image and Docker engine remain trusted computing base; kernel or
Docker vulnerabilities, writable task files, explicitly allowed network, and
explicitly passed credentials remain in scope. `network=bridge` can reach the
network allowed by Docker. Use `network=none` when the task needs no network.

`--untrusted-project` requires the Docker profile and stops before any
repository-supplied environment, setup, check, or evaluator command. The
resolved configuration is shown in **Needs You** for one explicit approval.
Repository-provided `allow_env` is ignored. Host and devcontainer profiles are
rejected because a repository-controlled devcontainer can request host mounts
or other privileges and is therefore not an untrusted-code boundary.

The Docker image must contain the selected agent CLI and project tools. Setup
commands run in disposable containers and should persist only into the task
worktree or per-run home. Automatic service sidecars, disk quotas, image
signature policy, and stronger outbound allowlists are not yet implemented.

Common credential-shaped fields, env-file assignments, authorization headers,
private-key blocks, URL credentials, token patterns, and configured runtime
credential values are redacted by the central RedactionEngine before current
run snapshots, append-only events, agent/check telemetry, notifications,
exports, proof inputs, and browser/SSE event responses cross durable or UI
boundaries. Redaction receipts record only the ruleset version and redacted
field classes, never the material that was removed. This is defense in depth,
not a reason to put secrets in prompts or shell commands.

Accepting a task creates a local commit on its Odysseus task branch and does not
update the operator's source checkout. Downstream artifact composition runs
`git merge` only in the downstream task worktree and aborts on conflict. The
separate, confirmed **Apply to repository** action is the only normal workflow
action that updates the source checkout: it refuses tracked local edits, a
detached HEAD, wrong branch, missing artifact, or rewritten base history, and
aborts a conflicting merge. Unrelated untracked files remain untouched, while
Git refuses an untracked path that the artifact would overwrite. Draft PR and
CI-repair actions can push the task branch
through the service user's Git credentials. Odysseus does not auto-merge pull
requests.

GitHub CI and review intake invoke authenticated `gh` as the service user.
Notification destinations may embed webhook credentials. Protect
`~/.odysseus/config.json` (or the configured state root) with owner-only write
access. The notification journal stores destination names and outcomes, never
destination URLs; message bodies can still contain repository-sensitive error
text, so use private destinations.

## Remote access

Prefer a tunnel while the service remains on VPS loopback:

```sh
ssh -N -L 8741:127.0.0.1:8741 USER@VPS
```

The VPS installer uses this model by default. `--domain` adds nginx Basic auth
and obtains a TLS certificate through Certbot. Keep the VPS firewall closed for
port 8741; only nginx ports 80/443 should be public.

For phone and tablet access, prefer a private tailnet over a public hostname:

```sh
sudo scripts/install-vps.sh --service-user "$USER" --tailscale
```

This keeps Odysseus bound to `127.0.0.1` on the VPS and uses Tailscale Serve to
publish the port inside your tailnet. The phone still needs to be signed in to
the same Tailscale network. Treat every tailnet device as an operator device for
this service.

Odysseus also supports defense-in-depth HTTP Basic auth when binding directly:

```sh
umask 077
printf '%s' 'use-a-password-manager-value' > ~/.odysseus/web.password
bin/odysseus serve --host 0.0.0.0 --allow-remote \
  --auth-user odysseus --auth-password-file ~/.odysseus/web.password
```

Do this only behind TLS. A direct remote bind without a password is rejected
unless `--insecure-remote` is explicitly supplied.

## Reporting

Do not include credentials, private prompts, or repository data in a public
report. Use GitHub's private vulnerability reporting when enabled for the
repository, or contact the maintainer privately.
