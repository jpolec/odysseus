# 08 — Execution environments and credential boundaries

Built in **Odysseus v0.6.0 and v0.6.12**.

## The problem

A Git worktree separates code changes, but it does not isolate credentials,
processes, ports, network access, databases, or the rest of the operator's
filesystem.

## The guarantee

Every task records an explicit execution environment: `host`, `docker`, or
`devcontainer`. The chosen profile is shared by implementation, checks,
reviewers, and evaluators. Environment variables are allowlisted by name; their
secret values are resolved only at execution time and are not written into run
snapshots or events.

For an untrusted project, Odysseus requires Docker and pauses before executing
repository-provided setup, checks, evaluators, or environment configuration.

## Use it

Host mode is convenient for a trusted local repository. Use Docker when the
task must not inherit the server user's normal filesystem and credentials:

```sh
odysseus run \
  --project /absolute/path/to/repository \
  --environment docker \
  --image ghcr.io/your-org/coding-agent:latest \
  --network none \
  --cpus 2 --memory 4g \
  --allow-env OPENAI_API_KEY \
  --untrusted-project \
  "Audit and fix the parser"
```

The image must contain the selected agent CLI and project toolchain.

## Evidence to inspect

- Environment kind, image, network mode, CPU/RAM, ports, and allowed variable
  names on the task.
- Permission request before untrusted repository commands.
- Runtime paths and container identity in technical details.
- The [threat model](../security/threat-model.md) for explicit trust boundaries.

## Failure behavior

- Requested Docker isolation fails closed when Docker cannot be prepared.
- Untrusted host/devcontainer execution is rejected.
- Review mounts are read-only where the runtime supports it.
- Server-only Decision Assistant keys are not inherited by task processes unless
  explicitly allowlisted.

## Current boundary

Docker is practical containment, not a formally verified sandbox. Odysseus
still trusts the host kernel, Docker engine, and selected image. Rootless
runtime enforcement, deny-by-default egress allowlists, PID/disk quotas,
short-lived secret brokerage, signed images, and service sidecars remain
planned.
