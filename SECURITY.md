# Security

## Local default

Odysseus binds to `127.0.0.1`, validates loopback Host and Origin headers, sends
no CORS permission, and requires a per-process same-origin token on mutations.
Agent commands still operate with the permissions of the user who started the
server, so only register repositories and check commands you trust.

> **Trusted-repository boundary:** `checks` and `evaluators` from a project's
> `.odysseus.json` execute through `/bin/sh -lc` in the task worktree with the
> server user's permissions. Opening an untrusted repository and running its
> configuration is remote code execution by design. Review that file first.

A Git worktree isolates code changes, not the process environment. Agents may
still reach the user's readable files, credentials, local databases, ports, and
network according to the underlying Codex/Claude mode and operating system.
Per-task container, credential, resource, and network isolation is planned for
0.5; it is not a property of 0.4.

Common credential-shaped fields and token patterns are redacted from normalized
vendor telemetry before it is persisted. This is defense in depth, not a reason
to put secrets in prompts or shell commands.

Accepting a task creates a local commit on its Odysseus task branch. Downstream
artifact composition runs `git merge` only in the downstream task worktree and
aborts on conflict; it does not update the operator's source checkout. Draft PR
and CI-repair actions can push the task branch through the service user's Git
credentials. Odysseus does not auto-merge pull requests.

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
