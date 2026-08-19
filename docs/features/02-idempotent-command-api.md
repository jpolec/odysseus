# 02 — Idempotent Command API

Shipped in **Odysseus v0.9.1**.

## The problem

A browser, CLI wrapper, CI job, or mobile connection can lose the response to a
successful request and retry it. Without a durable command identity, the same
click can create two tasks, accept twice, or repeat another mutation. A stale
screen can also overwrite a newer run state.

## The guarantee

Mutating HTTP requests and supported mutating CLI commands enter one durable
Command Bus before their handlers run. The bus stores the request identity and
redacted input, executes the handler at most once for that identity, and stores
the exact redacted result.

```text
CommandEnvelope persisted + fsynced
        ↓
optional expected stream-version check
        ↓
handler mutates canonical state
        ↓
completed / failed result persisted
```

The identity is scoped by actor plus idempotency key. The same key with exactly
the same request returns the stored result. The same key with different input
is an explicit conflict.

## HTTP use

Read the current run and retain `_canonical_stream_version`:

```sh
curl http://127.0.0.1:8741/api/runs/RUN_ID
```

Submit the mutation with a stable key and, for stale-write protection, the
version that the operator reviewed:

```sh
curl -X POST http://127.0.0.1:8741/api/runs/RUN_ID/accept \
  -H "X-Odysseus-Token: $ODYSSEUS_TOKEN" \
  -H "Idempotency-Key: accept-RUN_ID-v42" \
  -H "X-Odysseus-Expected-Version: 42" \
  -H "Content-Type: application/json" \
  -d '{}'
```

If transport fails, repeat the same request with the same key. A successful
response exposes:

```text
X-Odysseus-Command-Id
X-Odysseus-Command-State
X-Odysseus-Idempotent-Replay
```

## CLI use

Global command options appear before the subcommand:

```sh
odysseus \
  --idempotency-key accept-RUN_ID-v42 \
  --expected-version 42 \
  --actor operator@example.com \
  accept RUN_ID
```

List or inspect receipts:

```sh
odysseus command
odysseus command COMMAND_ID
```

## Receipt states

| State | Operator meaning |
| --- | --- |
| `executing` | Do not submit a new key merely because the first response is slow. |
| `completed` | The stored result is authoritative and exact duplicates replay it. |
| `failed` | The stored rejection/failure is authoritative for that key. |
| `unknown` | The owner ended before recording the result; inspect and reconcile before choosing a new key. |

The command receipt includes its envelope, request hash, timestamps, owner,
HTTP status when applicable, result/error, and redaction receipts. Canonical
run events created by the command carry its `command_id` and
`idempotency_key`.

## Failure behavior

- A stale expected version returns a conflict before the newer projection is
  changed.
- Reusing one key for different input returns a conflict.
- A duplicate of a completed or failed HTTP command returns the stored status
  and result.
- A command owned by a live process remains `executing`.
- When the recorded local process is known to have ended, the command becomes
  `unknown`; Odysseus does not automatically repeat it.
- Payloads, policy context, results, and errors are redacted before durable
  persistence.

## Current boundary

This release provides idempotent local command execution and optimistic run
concurrency. It does not claim that every external side effect is exactly once.
For example, a process can still die after GitHub creates a pull request but
before the receipt is recorded. v0.9.3 adds the durable Outbox, Action Ledger,
and provider reconciliation required for that stronger guarantee.

See [the protocol reference](../odysseus-protocol.md) for exact fields.
