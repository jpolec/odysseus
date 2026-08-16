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

For 0.6.8 the release gate is:

- 95 automated tests, including safe local artifact application, preservation
  of unrelated and colliding untracked files, conflict abort,
  repository identity, hidden internal worktrees,
  read-only tmux discovery,
  strict untruncated evidence journals, terminal
  outcome eligibility, privacy-reduced receipts, legacy Epic provenance,
  temporary HTTP servers, port-conflict behavior,
  bounded SSE capacity, protected reads, strict state verification, process leases,
  environment-plan validation, and a zero-execution untrusted-command gate;
- an opt-in real Docker proof showing isolated Git access, environment
  injection, writable implementation/check mounts, and read-only review mounts;
- a checkout installer smoke test and an exact-commit clone/piped-installer smoke test;
- a clean wheel tested through `uvx`, including installed web assets and nine Skills;
- a real versioned install from 0.6.1, live-process refusal, upgrade to 0.6.8,
  downgrade refusal, checksummed state backup, corrupt-restore refusal, verified
  state restore, first-install backup, command-link preflight, and atomic rollback;
- packaged and checkout HTTP servers reporting version 0.6.8;
- deterministic fresh-state and demo routes for eleven screenshot target views.
- a production-proof assertion that every seeded task is classified as demo,
  every other evidence class is empty, and observed autonomous outcomes are zero.

The public release notes should never claim a screenshot or real agent outcome
that was not actually captured or observed during that release.
