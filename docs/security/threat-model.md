# Odysseus threat model

This document defines Odysseus trust boundaries for operators, implementers,
reviewers, and future architecture work. It is intentionally conservative:
planned controls are not current guarantees.

## Security objectives

- Keep the operator in control of when untrusted repository commands, external
  callbacks, credentials, and delivery actions can affect local state.
- Preserve trustworthy evidence about tasks, checks, reviews, artifacts, and
  decisions without treating model output as fact.
- Limit filesystem, credential, and network exposure for agent work, especially
  when the repository is untrusted.
- Make degraded isolation visible instead of presenting best-effort controls as
  a complete sandbox.

## Trust boundaries

| Boundary | Trust level | Current guarantee | Required controls |
| --- | --- | --- | --- |
| Human operator | Trusted decision maker | The operator approves plans, untrusted repository command gates, reviews, delivery, and remote exposure. Odysseus cannot prove the human understood every risk. | Show exact commands, environment, source, evidence, and consequences before approval; keep approvals durable and auditable. |
| Host kernel, OS, Docker engine, selected base image | Trusted computing base | Odysseus relies on the host kernel, filesystem permissions, Docker engine, and selected image. It does not implement or verify kernel isolation. | Report Docker as containment, not a formally verified sandbox; document image and engine trust; fail closed when requested isolation cannot be prepared. |
| Repository content | Untrusted unless reviewed | README, AGENTS files, `.odysseus.json`, build files, hooks, tests, dependencies, devcontainers, and scripts may be attacker-controlled. Host mode runs repository commands with the server user's permissions. | Use isolated worktrees for code changes; require Docker for `--untrusted-project`; pause before repository-supplied setup, checks, evaluators, or environment run; ignore repository-provided credential allowlists. |
| Agent output | Untrusted | Agent messages, diffs, tool summaries, and review claims are recorded as evidence, not authority. Acceptance requires human or configured policy gates. | Verify with checks, independent review, explicit acceptance, and artifact diff inspection; never treat a model assertion as proof that a command ran or a vulnerability is fixed. |
| Skills | Partially trusted | Bundled Skills are reviewed prompt guidance. Project-local Skills are repository content and may be prompt-injection material. Skills do not grant permissions by themselves. | Keep Skills text visible in context receipts; route and select Skills explicitly; require trust review before portable or shared Skills are enabled; do not let Skills expand filesystem, network, credential, or delivery permissions. |
| External MCP tools and plugins | Untrusted external capability | External MCP is not a current built-in Odysseus execution boundary. A future MCP server can return hostile text, request actions, or expose side effects. | Treat MCP responses as untrusted input; require explicit tool permission, scoped credentials, network policy, output redaction, and evidence labels that identify the external source. |
| CI output | Untrusted evidence | CI is currently polled through authenticated `gh`; log text and statuses can be misleading, truncated, stale, or produced by compromised workflow code. Odysseus does not auto-merge. | Re-fetch authoritative status; bind evidence to commit SHA and run identity; redact logs; require retry budgets and review gates; distinguish CI pass/fail from proof of correctness. |
| Webhook payloads and callbacks | Untrusted input | GitHub CI integration is polling-based today; general webhook receivers are planned, not implemented. Notification webhooks are outbound destinations. | For future inbound webhooks, verify signatures, timestamps, replay windows, event ids, repository identity, and commit SHA; fetch authoritative state before acting; reject forged callbacks and duplicate deliveries. |
| Runtime profile | Mixed | `host` gives process access as the server user. `docker` narrows mounts, environment, network, CPU, and memory per command. `devcontainer` is repository-defined and only suitable for reviewed repositories. | Make the selected profile explicit; reject host/devcontainer for untrusted projects; keep Docker mounts scoped; make review containers read-only; expose degraded isolation. |
| Credentials | Highly trusted secret material | API keys are not saved in browser state. Task `allow_env` stores names, not values, and copies values at runtime. Common credential-shaped telemetry is redacted before persistence. There is no Secret Broker. | Default-deny credential inheritance; require operator-named allowlists; never persist secret values; redact prompts, commands, logs, evidence, notifications, and UI streams before storage; add a future broker only with auditable scoped leases. |
| Browser and HTTP API | Operator-facing local control plane | The server binds to loopback by default, validates loopback Host and Origin, sends no CORS permission, and requires a per-process same-origin token on mutations. Remote bind requires explicit insecure override or authentication setup. | Keep mutation tokens, origin checks, and no ambient CORS; require TLS plus auth for remote access; avoid leaking secrets into rendered pages or local storage; preserve API failure semantics without exposing internal secrets. |
| Durable storage | Trusted local record with untrusted contents | State is JSON plus append-only NDJSON under the service user's state root. It stores prompts, events, logs, evidence, and artifact metadata. Current artifact storage is local Git/state, not CAS. | Protect the state root with owner-only permissions; record source labels and digests; redact before persistence; verify state structure; treat stored text as untrusted when rehydrated into prompts, UI, or exports. |

## Threats and mitigations

### Prompt injection in repository instructions

Untrusted `README`, `AGENTS`, issue text, ADRs, Skills, test failures, and CI
logs can instruct an agent to ignore the operator, reveal secrets, forge
evidence, or expand scope.

Mitigations:

- Context receipts label source kind, path, digest, selection reason, and
  captured content so injected instructions remain attributable.
- Agent prompts must rank operator and Odysseus control instructions above
  repository text.
- Repository instructions never grant shell, credential, network, delivery, or
  approval permissions.
- Human review and independent checks are required for risky changes unless a
  mature explicit policy says otherwise.

### Malicious build, test, dependency, and repository hooks

Repository setup commands, checks, evaluators, package install hooks, Git hooks,
devcontainer hooks, and generated test scripts can run arbitrary code.

Mitigations:

- Host mode is documented as trusted-repository execution with the server
  user's permissions.
- `--untrusted-project` requires Docker and pauses before repository-supplied
  setup, check, evaluator, or environment configuration runs.
- Docker runs with scoped mounts, isolated task Git metadata, per-run home,
  dropped capabilities, `no-new-privileges`, read-only root filesystem, and
  explicit network, CPU, and memory settings.
- The review phase mounts the worktree and isolated Git metadata read-only.
- Repository-defined devcontainers are rejected for untrusted projects.

### Filesystem and credential access

An agent or repository command can try to read other repositories, SSH keys,
state files, shell history, cloud credentials, or API keys.

Mitigations:

- Prefer Docker for unknown repositories; it does not mount the source
  repository `.git`, `~/.ssh`, other repositories, home directory, or Docker
  socket.
- Pass credentials only by explicit operator `allow_env` names; do not accept
  repository-provided credential allowlists.
- Store `allow_env` names rather than values and keep generated env files
  private to the owner.
- Protect the Odysseus state root and config with owner-only filesystem
  permissions.

### Data exfiltration

Untrusted commands or tools can send prompts, repository data, logs, tokens, or
state to remote services over network, Git, package manager, browser, MCP, or
webhook channels.

Mitigations:

- Make Docker network mode explicit and use `network=none` when network is not
  required.
- Keep credential inheritance default-deny.
- Redact credential-shaped telemetry before persistence and before displaying
  or forwarding evidence.
- Treat outbound notification destinations as sensitive; store destination
  names and outcomes, not destination URLs.
- Future external MCP and webhook features require scoped credentials, source
  labels, redaction, and explicit operator permission.

### Forged callbacks and command responses

Webhook payloads, browser/API calls, notification actions, CI callbacks, and
tool responses can be spoofed, replayed, stale, or attributed to the wrong
repository or commit.

Mitigations:

- Current CI repair uses authenticated `gh` polling and re-fetches authoritative
  issue data for GitHub intake instead of trusting browser-submitted fields.
- The browser API validates Host and Origin on loopback and requires a
  same-origin mutation token.
- Future inbound webhooks must verify signatures, timestamps, event ids, replay
  windows, repository identity, and commit SHA before creating tasks or changing
  state.
- Any callback-derived decision must be recorded with source, time, subject,
  and fetched authoritative evidence.

### Poisoned evidence and forged success

An agent, test, CI job, or reviewer can claim success without executing the
right checks, can hide failures in logs, or can generate tests that only prove
its own interpretation.

Mitigations:

- Evidence is labeled by source and remains distinct from approval.
- Checks and evaluators record return code and output; independent review is a
  separate signal.
- Acceptance creates a local artifact but does not merge into the source
  checkout or auto-merge a pull request.
- Delivery actions check clean checkout, expected branch, base history, and
  conflicts before applying artifacts.
- Planned immutable CAS, signed receipts, stronger invariant registries, and
  calibrated outcome records are not current guarantees.

## Current guarantees versus planned controls

| Area | Current status | Planned or required before claiming stronger security |
| --- | --- | --- |
| Host execution | Trusted-repository only; commands run as the service user. | Policy engine that can require containerization by path, diff, and task class. |
| Docker isolation | Implemented as command-scoped containment with scoped mounts and environment. | Podman support, disk and PID limits, outbound allowlists, signed or allowlisted images, sidecar lifecycle, and clearer degradation reporting. |
| Devcontainer | Implemented for reviewed repositories; rejected for `--untrusted-project`. | No stronger claim unless repository-controlled privileges are constrained by an external policy. |
| Credential handling | `allow_env` names only; no browser API-key storage; common telemetry redaction. | Secret Broker with scoped leases, complete redaction receipts before every durable and browser-stream boundary, and revocation workflows. |
| Durable evidence | JSON and append-only NDJSON with source labels in several records. | Immutable content-addressed storage, signed receipts, invariant-to-test registry, and stricter evidence provenance. |
| Webhooks | General inbound webhook receiver is not implemented. | Signature verification, replay protection, authoritative re-fetch, source binding, and policy-gated side effects. |
| External MCP | Not a current Odysseus security boundary. | Tool registry, per-tool permissions, scoped credentials, output labels, redaction, and deny-by-default network policy. |
| CI | Authenticated `gh` polling; no auto-merge. | Commit-bound evidence bundles, poisoned-log defenses, and explicit auto-merge policies for narrowly trusted changes. |
| Kernel and container escape | Relies on host kernel, Docker engine, and selected image. | Odysseus should continue to describe this as TCB, not as implemented kernel security. |

## Documentation and test registry

This threat model is required documentation for the master-plan security
boundary. Tests should verify that it remains linked from `SECURITY.md`, names
the required trust boundaries and threat classes, and preserves the
implemented-versus-planned distinction for Secret Broker, CAS, webhooks,
external MCP, and kernel/container guarantees.
