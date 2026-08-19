# 10 — Portfolio, outcome routing, and variants

Built across **Odysseus v0.8.0–v0.8.1**.

## The problem

Token volume and task count do not show whether coding agents deliver useful
changes. Operators need to see where delivery stops, how much evidence exists,
which workers perform well on comparable work, and when an expensive second
candidate is justified.

## The guarantee

The Engineering Portfolio reports observed delivery outcomes, first-pass
results, interventions, latency, cost coverage, worker effectiveness, failure
attribution, and blockers. Percentages show sample size, and unknown cost is
not converted to zero.

**Agent: Auto** uses transparent local outcome evidence when the sample is
sufficient and explicitly falls back to a default when it is not. The current
router is advisory/heuristic; it does not pretend to have a calibrated delivery
probability.

## Use it

- Open **Portfolio** for repository and cross-repository delivery outcomes.
- Keep **Agent: Auto** for normal work and inspect the routing reason.
- Override the agent when repository knowledge or risk justifies it.
- Use Variants only for high-value or ambiguous work:

```sh
odysseus run \
  --project /absolute/path/to/repository \
  --variants 2 \
  --variant-lane codex \
  --variant-lane claude \
  --check "python3 -m unittest" \
  "Find the least risky parser replacement"
```

Each variant receives a separate branch, worktree, prompt, evidence history,
budget share, and artifact. The Pareto judge compares only observed objectives;
missing cost does not make a candidate artificially cheap.

## Evidence to inspect

- Delivered/accepted/failed classification and provenance.
- Worker and Skill sample size, observed cost coverage, retries, and human
  intervention.
- Routing recommendation, alternatives, reason, and sparse-sample warning.
- Variant constraints, comparable/incomparable objectives, Pareto frontier,
  and each full candidate diff.

## Failure behavior

- Demo, test, imported tmux, and legacy/unclassified runs do not inflate
  production outcomes.
- Missing cost remains unknown.
- An inconclusive comparison asks the operator; it does not invent a winner.
- Selecting a variant preserves that artifact but does not auto-merge it.

## Current boundary

The current router is not yet a learned causal model and does not optimize for
observed production health. Versioned Route Receipts, task feature extraction,
calibrated uncertainty, guarded auto-routing, and skill contribution analysis
remain staged in the master plan.

