# Production proofs

This directory accepts release receipts generated from real, explicitly
observed Odysseus runs:

```sh
scripts/dogfood.sh proof
```

Do not commit seeded demo numbers as production evidence. `odysseus proof`
excludes demo, test, imported tmux, and legacy unclassified runs by design. A
receipt says when its eligible sample is below the default 20-run publication
threshold. A counted attempt needs ordered start/agent/outcome evidence; a
delivery claim also needs final verifier success and an artifact. An observed
label alone is insufficient. JSON uses opaque per-run IDs and is ignored
by Git by default; Markdown is the safe public summary.
