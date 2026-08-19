# Odysseus feature guides

These short guides explain one shipped capability at a time. They are for an
operator who wants to understand the guarantee, use it, inspect its evidence,
and know where it stops. Planned capabilities stay in the
[roadmap](../../ROADMAP.md) until code and focused tests exist.

| Guide | Shipped | What it answers |
| --- | --- | --- |
| [01 — Durable state and replay](01-durable-state-and-replay.md) | v0.9.0 | Can a run be reconstructed and audited after a crash? |
| [02 — Idempotent Command API](02-idempotent-command-api.md) | v0.9.1 | Can a UI, CLI, or HTTP retry mutate state twice? |

For the complete workflow, start with [START.md](../../START.md) and then use
the [usage guide](../USAGE.md). The exact wire and persistence formats live in
the [protocol reference](../odysseus-protocol.md).
