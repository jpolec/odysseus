# Odysseus release proof

Every release should be reproducible from the public checkout:

```sh
scripts/release-proof.sh
```

The gate verifies JavaScript, Python, and shell syntax; both checkout and piped
installer paths; the complete unit/integration suite; and a disposable
Odysseus-on-Odysseus state that can be queried through the real CLI. The same
state powers `odysseus demo` and the real-browser screenshot pipeline.

This is deliberately honest evidence. Seeded demo outcomes prove UI, storage,
API, routing, and inspection behavior without spending model tokens; they do
not claim that a model produced those exact changes. Real agent runs retain
their own immutable Context Receipts, event journals, checks, review, costs,
and operator decisions in the selected state directory.

For 0.5.4 the release gate is:

- 54 automated tests, including temporary HTTP servers and protected reads;
- a checkout installer smoke test and a clean clone/piped-installer smoke test;
- a live no-token demo server reporting version 0.5.4 and three projects;
- deterministic fresh-state and demo routes for nine screenshot target views.

The public release notes should never claim a screenshot or real agent outcome
that was not actually captured or observed during that release.
