# Odysseus feature guides

These short guides explain one shipped capability at a time. They are for an
operator who wants to understand the guarantee, use it, inspect its evidence,
and know where it stops. Planned capabilities stay in the
[roadmap](../../ROADMAP.md) until code and focused tests exist.

| Guide | Shipped | What it answers |
| --- | --- | --- |
| [01 — Durable state and replay](01-durable-state-and-replay.md) | v0.9.0 | Can a run be reconstructed and audited after a crash? |
| [02 — Idempotent Command API](02-idempotent-command-api.md) | v0.9.1 | Can a UI, CLI, or HTTP retry mutate state twice? |
| [03 — Task delivery workflow](03-task-delivery-workflow.md) | v0.2.0–v0.8.1 | How does one request become a reviewed, deliverable Git artifact? |
| [04 — Plans and task DAGs](04-plans-and-task-dags.md) | v0.3.0, v0.7.0 | How does a large outcome become approved parallel work? |
| [05 — Evidence and independent review](05-evidence-and-independent-review.md) | v0.3.0–v0.8.1 | What was actually proved before an artifact is accepted? |
| [06 — Repository knowledge, ADRs, and Skills](06-knowledge-adrs-and-skills.md) | v0.5.0–v0.7.0 | What context and engineering procedure did the agent receive? |
| [07 — Recovery, saved threads, and tmux](07-recovery-and-tmux.md) | v0.2.0–v0.6.6 | How can work continue without losing the branch or agent thread? |
| [08 — Execution environments and credential boundaries](08-execution-environments.md) | v0.6.0, v0.6.12 | What can a task access on host, Docker, or devcontainer? |
| [09 — CI, integration, and delivery](09-ci-integration-and-delivery.md) | v0.4.0–v0.6.12 | How does accepted work reach a checkout or draft PR safely? |
| [10 — Portfolio, routing, and variants](10-portfolio-routing-and-variants.md) | v0.8.0–v0.8.1 | Which outcomes, costs, workers, and alternatives are performing? |
| [11 — Worker Leases and fencing](11-worker-leases-and-fencing.md) | v0.9.2 | Can an expired worker overwrite its successor after a crash or takeover? |

For the complete workflow, start with [START.md](../../START.md) and then use
the [usage guide](../USAGE.md). The exact wire and persistence formats live in
the [protocol reference](../odysseus-protocol.md).
