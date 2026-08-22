# Versioned source-to-plan contracts

Available on `main` after **Odysseus v0.9.2**.

Plan Studio turns a requirement source into a reviewable execution contract:

```text
source requirement
  → linked task contract
  → execution profile
  → required evidence
  → immutable approved PlanVersion
  → execution receipt and outcome
```

It is not a model picker. A task binds the intended finished outcome and its
source clauses to an execution profile containing the harness, optional model,
Skills, environment, policy, independent-review policy, routing reason, and an
honest estimate range.

## Supported sources

The composer accepts a user request, ADR, PRD/specification, GitHub issue,
security finding, incident, milestone, or document set. Odysseus freezes the
exact source bytes, content hash, and paragraph-level references such as `S1`
and `S2`. Remote intake remains a redacted snapshot; local documents can be
compared with their current bytes.

In **Plans → New plan**, first choose a repository. The composer then lists
ADRs discovered in `_ADR/` and the other supported ADR directories. Select one
or more there, or choose **Upload documents** to attach Markdown, text, JSON,
or YAML from outside the repository. Uploaded text is read locally by the web
client and sent only to the local Odysseus server; files are limited to 80 KB
each and all selected sources to 320 KB. The selected-source summary shows
exactly what will be frozen before the Planner runs.

The finished-outcome field remains required. A document says where the
requirements came from; the outcome tells the Planner what this Plan is meant
to deliver. Do not attach secrets because source contracts are durable audit
records.

## Plan Studio

Open a proposed Plan and choose **Review plan contract**. The full-screen
studio keeps the frozen source on the left and task contracts on the right.

- Selecting a task highlights the source clauses that justify it.
- Selecting a source clause links or unlinks it from the active task.
- Each task has an editable outcome, agent instruction, dependencies,
  acceptance criteria, required evidence, execution profile, and cost/time
  range.
- The DAG remains visible below the editor.
- **Save draft** creates a new immutable `PlanVersion`; it never edits the
  preceding version in place.
- **Approve & start** binds approval to the exact plan and source hashes, then
  materializes the existing dependency-aware runs.

No implementation starts before approval. Approval still does not grant push,
pull-request, integration, or deployment authority; those existing delivery
gates remain separate.

## Source changes and impact

A local source is checked against the frozen `SourceVersion`. When it changes,
the studio reports `SOURCE_CHANGED` and identifies only task contracts linked
to changed clauses. Unrelated source edits do not automatically invalidate the
whole graph.

The operator can explicitly freeze the current source and save a new plan
version. An approved Plan is immutable; a later source or implementation
change requires another version instead of silently changing what was
approved.

## Honest estimates

Estimates are ranges with `low`, `medium`, `high`, or `unknown` confidence and
a visible basis. Missing history remains unknown; it is never converted into a
precise dollar value or zero cost. Actual run time, model tokens, cache-read
tokens, billable tokens, and provider-reported cost remain separate from the
pre-run estimate.

## Stored contract

The durable Plan stores four conceptual records without introducing a second
orchestration engine:

- `SourceVersion`: content, sections, digest, and frozen timestamp context.
- `PlanVersion`: numbered immutable DAG, source hashes, status, and history.
- `TaskContract`: outcome, source links, criteria, evidence, instruction, and
  dependencies.
- `ExecutionProfile`: Auto/override decision, harness, model, Skills,
  environment, policy, reviewer, reason, and estimate.

Materialized runs copy these fields into their own durable snapshot so later
plan edits cannot change the instruction or evidence contract of an active
worker.

## Current boundary

The current router can preserve an Auto recommendation or an operator
override, but it does not claim calibrated cost or delivery probabilities.
Full learned routing, content-addressed artifacts, and automatic post-deploy
outcome learning remain roadmap work. Plan Studio establishes the versioned
lineage those systems will consume.
