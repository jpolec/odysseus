---
name: performance-review
description: Diagnose and improve latency, throughput, memory, CPU, query, and caching behavior using measurements and explicit performance budgets.
triggers: performance, latency, throughput, memory, cpu, slow, optimize, profiling, benchmark, cache, allocation, n+1
---

# Performance Review

Establish a repeatable baseline and identify the dominant resource before optimizing. Instrument the relevant path, change one bottleneck at a time, and compare equivalent workloads. Protect correctness and tail behavior, not only averages. Add a regression benchmark or budget when stable enough for CI. Report measurement conditions and avoid claims unsupported by data.
