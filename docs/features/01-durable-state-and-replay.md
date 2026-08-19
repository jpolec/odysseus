# 01 — Durable state and deterministic replay

Shipped in **Odysseus v0.9.0**.

## The problem

An agent run can last minutes or hours. A server process can die between
recording an event and updating the file shown by the UI. If the current JSON
file is the only truth, the operator cannot know whether the task state is
complete, stale, or partly written.

## The guarantee

For every run, Odysseus appends and fsyncs a canonical EventEnvelope v2 before
replacing the JSON projection. Canonical events have continuous stream
versions and a SHA-256 hash chain. The JSON run file and checkpoint are caches:
both can be deleted and rebuilt from the stream.

```text
state-changing operation
        ↓
append + fsync canonical event
        ↓
write compact activity event when applicable
        ↓
replace JSON projection + checkpoint
```

If the process stops after canonical fsync, reopening writable state replays
the stream, restores the projection, and reconciles a missing operator activity
event. Historical event bytes are never rewritten; readers upcast old schemas
in memory.

## Use it

Inspect current reconstructed state:

```sh
odysseus replay RUN_ID
```

Inspect the state after one historical stream version:

```sh
odysseus replay RUN_ID --until-event 42
```

Verify without writing:

```sh
odysseus rebuild-projections --dry-run
odysseus state verify --json
```

Rebuild replaceable run projections after stopping the server and workers:

```sh
odysseus rebuild-projections
```

## Evidence to inspect

Under the selected state directory:

```text
streams/RUN_ID.ndjson       canonical state transitions
runs/RUN_ID.json            replaceable current projection
events/RUN_ID.ndjson         compact operator/UI activity
checkpoints/runs/RUN_ID.json replaceable append checkpoint
```

`state verify` checks stream continuity, event and projection hashes,
checkpoint agreement, projection equality, supported schemas, and measured
replay throughput. It reports corruption instead of skipping invalid records.

## Failure behavior

- A missing or stale projection is rebuilt from a valid stream.
- A deleted middle event, broken hash, duplicate version, or unsupported future
  schema fails verification.
- Projection repair never edits the canonical stream.
- Read-only proof and replay do not create state directories or migrate
  evidence.

## Current boundary

v0.9.0 makes run state replayable. It does not by itself make external GitHub,
Git, webhook, or deployment effects exactly once. Durable commands, worker
fencing, and outbox reconciliation are separate releases because those
guarantees require different evidence.

See [the protocol reference](../odysseus-protocol.md) for exact envelope fields
and [the invariant registry](../architecture/invariants.md) for test-linked
claims.
