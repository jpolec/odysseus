# Odysseus production proof

Release proof answers: **can this checkout be built, installed, started,
upgraded, rolled back, and tested reproducibly?**

Production proof answers a different question: **what did coding agents really
deliver while Odysseus observed them?**

## Evidence boundary

Run schema 9 stores `odysseus-run-provenance-v1` with an evidence class, origin,
application version, release label, and observation timestamp. The production
aggregator first selects autonomous tasks classified `observed`, then counts an
attempt only when its complete journal proves `run.started -> agent activity ->
terminal outcome`. Early agent failures therefore remain in the denominator.
Accepted changes and draft PRs additionally require the last verifier to pass,
then an artifact, then the outcome event. Queued work, active work, and snapshots
whose status was edited without that trail never enter the denominator.

It excludes:

- seeded product-tour runs (`demo`);
- automated fixtures (`test`);
- tmux sessions adopted after work started (`imported`);
- history created before provenance existed (`unclassified`).

This means the first proof for a new release may honestly contain zero or only
a few runs.
The default publication threshold is 20, and the receipt states whether that
threshold was met. Odysseus does not backfill or guess old outcomes.

## Generate a receipt

```sh
odysseus proof --release 0.6.4
odysseus proof --release 0.6.4 --json --output proof.json
odysseus proof --release 0.6.4 --require-sufficient
```

For this repository:

```sh
scripts/dogfood.sh run "Implement one finished Odysseus outcome"
scripts/dogfood.sh proof
```

JSON includes a privacy-reduced, content-addressed receipt for every eligible
outcome. Public receipt IDs are opaque hashes: task titles, paths, repository
IDs, and raw run IDs are not emitted. Each receipt binds the private source
record, provenance, outcome, artifact, Context Receipt, explicit operator
events, and the complete normalized event journal including its event count and
final sequence. The aggregate digest also binds the release, evidence policy,
classification counts, publication threshold, metrics, and ordered receipts.
It is tamper-evident local evidence, not a third-party signature or a claim that
the host itself was uncompromised.

Receipt generation opens the state in shared, read-only mode: it does not make
directories, create config or lock files, or migrate legacy records.

An intervention is counted only from an explicit `source=user` decision event.
The time metric covers a **Needs You** item from creation to an explicit answer.
It is operator-response latency, not active human work time. Automatic queue
cleanup and time spent outside Odysseus are not counted or guessed.

Costs come only from recorded `agent.cost` events. Missing telemetry is
`not observed`, with a visible coverage ratio; it is never converted to zero.
Draft pull requests and accepted changes are separate outcomes. CI repair
requires a failure followed by a later pass with final state green, and crash
recovery requires post-recovery progress to a terminal outcome.

## Central metric

The organizing product metric remains **Human Attention per Successful
Change**. Today Odysseus reports its measurable proxy—Needs You response latency
per accepted change—alongside explicit operator actions, acceptance, runtime,
reported-cost coverage, CI repairs, completed crash recovery, and Context
Receipt coverage. Empty observations remain `not observed`.
