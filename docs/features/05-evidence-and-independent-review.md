# 05 — Evidence and independent review

Built across **Odysseus v0.3.0–v0.8.1**.

## The problem

An agent saying “done” is not independent evidence. It can misunderstand the
requirement, write tests around its own mistake, or produce a plausible diff
that fails in integration.

## The guarantee

Odysseus keeps implementation, deterministic checks, independent evaluation,
CI observation, and the human delivery decision as distinct evidence sources.
A worker cannot turn its own completion message into independent validation.

```text
candidate artifact
   ├─ configured checks
   ├─ diff and merge-risk analysis
   ├─ independent reviewer/evaluators
   ├─ optional GitHub CI
   └─ operator acceptance
```

The UI reports qualitative **Evidence strength**, not a calibrated delivery
probability or a precise-looking heuristic percentage. Hard gates, soft
evidence, and unknowns remain separate, and missing or inconclusive evidence is
not relabeled as success.

## Use it

Configure repository checks in `.odysseus.json`, in Settings, or per task. Use
a different review lane when independent model review matters:

```sh
odysseus run \
  --project /absolute/path/to/repository \
  --lane codex \
  --review-lane claude \
  --check "python3 -m unittest discover -s tests" \
  --check "git diff --check" \
  "Fix the regression without changing the public API"
```

At **Ready for review**, inspect Changes and Evidence before selecting
**Accept artifact** or requesting changes.

## Evidence to inspect

- Exact commands, exit codes, output summaries, and timestamps.
- Reviewer findings and evaluator verdicts by source.
- Files changed, additions/deletions, and merge risk.
- CI state bound to the candidate branch/commit when available.
- Context Receipt showing which instructions and Skills informed the run.

## Failure behavior

- A failed check returns the same agent thread to a bounded repair loop.
- Inconclusive evaluation asks for a decision; it is not called failed.
- CI failure can resume the same thread with captured logs.
- Acceptance preserves a Git artifact but does not silently integrate it.

## Current boundary

Evidence is currently task-scoped. Immutable milestone candidates,
content-addressed artifact storage, structured Evidence Bundles, evaluator
calibration, and production health observation are planned capabilities, not
claims of the current release.
