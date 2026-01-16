---
description: optimize the code
---

Goal: Maximize execution speed and readability.
1. Bottleneck: Locate loops, unnecessary copies, or eager evaluation overhead.
2. Action: Convert to Polars LazyFrame or Numba.jit (if loops are unavoidable).
3. Memory: Assess peak memory usage for large factor datasets.
4. Benchmark: Compare `time.perf_counter` results (Before vs. After).