---
description: optimize the code
---

Goal: Maximize execution speed and readability.
1.Identify: Locate bottlenecks (loops, Pandas overhead, unnecessary copies).
2.Action: Convert to Polars/Numpy or apply numba.jit.
3.Benchmark: Provide before/after time.perf_counter results.
4.Constraint: Zero change in numerical output.