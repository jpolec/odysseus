# 11 — Worker Leases and fencing

Shipped in **Odysseus v0.9.2**.

## The problem

A task may outlive a scheduler process. After a heartbeat expires, another
worker can resume it, but the old process may wake up late and try to submit
output, change the run state, or clear the new owner's claim. A PID alone is
not a durable ownership identity and can be reused after a restart.

## The guarantee

Every claimed run receives one durable WorkerLease containing a unique lease
ID, scheduler worker identity, heartbeat TTL, and monotonically increasing
fencing epoch. Every worker-originated state mutation and activity append must
present the exact current token.

```text
worker A claims epoch 1
       ↓ heartbeat expires
recovery preserves/re-queues state
       ↓
worker B claims epoch 2
       ↓
late worker A write → rejected as stale
```

The old worker cannot overwrite canonical run state, append late output, or
release worker B's lease. Within one scheduler, the expired owner is signalled
and retains its active slot until its thread stops, so the successor is not
started concurrently in the same run worktree.

## Use it

Worker Leases are automatic. Start Odysseus normally:

```sh
odysseus start --open
```

Inspect the selected task's technical details or its run snapshot under the
state directory. `odysseus state verify --json` validates lease identity,
epoch, TTL, timestamps, active/released state, and its canonical projection.

## Evidence to inspect

- `worker_lease.lease_id` and `worker_lease.worker_id`.
- `epoch`, which increases after every recovered claim.
- `heartbeat_at`, `expires_at`, and `ttl_seconds`.
- `released_at` and `release_reason` for a completed/recovered owner.
- `system.recovered` activity with the previous lease ID, epoch, and outcome.
- The ordered `run.cancel_requested` and `run.cancelled` events after an
  interrupted cancellation.

## Failure behavior

- Concurrent claim attempts produce exactly one owner.
- A worker that loses its lease fails closed on its next state write.
- Recovery rechecks the exact heartbeat, expiry, epoch, status, and cancellation
  intent under the store lock; a stale health scan cannot revoke a renewed
  worker.
- A crash after claim or heartbeat re-queues the preserved run for a higher
  epoch.
- A crash after durable cancellation finalizes cancellation rather than
  silently restarting the task.
- A crash after Review or another non-active state releases only the stale
  lease and preserves that state.
- A crash after canonical stream fsync rebuilds stale JSON and checkpoint
  projections on startup.
- An interrupted Git artifact snapshot can be accepted again without creating
  a second commit.

## Proof

The test suite contains a deterministic failpoint framework. Subprocess tests
terminate without cleanup immediately after canonical fsync, claim, heartbeat,
cancellation, recovery, and artifact snapshot boundaries, then open the same
state and assert recovery, fencing, and journal integrity.

## Current boundary

Fencing protects acceptance of worker results into Odysseus canonical state.
It does not revoke arbitrary host filesystem writes already available to an
agent process. Use Docker for containment. Durable intent and reconciliation
for Git/GitHub and other external side effects belong to the v0.9.3 Outbox and
Action Ledger.
