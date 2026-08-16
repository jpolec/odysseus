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

For the 0.7.0 release candidate the local gate is:

- JavaScript, Python, shell, and `git diff --check` validation from the clean
  checkout.
- A required local Chrome/Chromium browser prerequisite, followed by a real
  browser regression that exercises artifact delivery, integration surfaces,
  and sidebar recovery behavior.
- A checkout installer smoke test and an exact-commit clone/piped-installer
  smoke test.
- A real versioned install from 0.6.1, live-process refusal, upgrade to the
  current checkout version, downgrade refusal, checksummed state backup,
  corrupt-restore refusal, verified state restore, first-install backup,
  command-link preflight, and atomic rollback.
- Targeted release slices for credential isolation, selective artifact
  integration, Apply conflict abort/recovery, conflicting predecessor
  artifacts, and resource inventory/reclaim safety.
- The complete automated unit/integration suite.
- A clean wheel tested through `uvx`, including the console entry point,
  installed web assets, bundled Skills, and packaged HTTP boot. The package
  proof uses the normal isolated `uv build` path first; if build requirements
  cannot be fetched, it falls back to a repository-local stdlib builder for this
  zero-dependency package and still installs the resulting wheel through `uvx`.
- A deterministic demo state queried through the real CLI for runs, stats,
  resource inventory dry-run, and production-proof receipts. Seeded demo tasks
  must all classify as demo, every non-demo evidence class must be empty, and
  observed autonomous outcomes must be zero.
- Eleven real browser screenshots from fresh-state and demo routes: First run,
  Repositories, Repository, Attention, Review, Delivery, Integration, CI
  repair, Context Receipt, New task, and Settings.
- Checkout HTTP health/bootstrap smoke tests reporting the current application
  version, plus a remote-access guardrail proving direct remote binds require
  authentication unless explicitly marked insecure.

The public release notes should never claim a screenshot or real agent outcome
that was not actually captured or observed during that release.
