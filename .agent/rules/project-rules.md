---
trigger: always_on
---

Project Context: High-Frequency Factor Research

1. Infrastructure (ClickHouse)

Engine: MergeTree family only.
Optimization: Mandatory PARTITION BY, ORDER BY, TTL, and CODEC(ZSTD(1)).

Standard Schema:
```sql
CREATE TABLE market_data (...) 
ENGINE = MergeTree() PARTITION BY toYYYYMM(dt) ORDER BY (symbol, dt) 
TTL dt + INTERVAL 5 YEAR;
```

2. Environment & Safety

Timezone: Always Asia/Shanghai (UTC+8).
Risk Control: Execution logic must include "Pre-trade Checks" (price bands, max size).

3. Current Focus (Validation & Pandas)

Validation: Use assert statements for logic verification.
Benchmarking: Provide time.perf_counter for performance-critical logic.
Pandas Best Practices:
  * Integrity: Always check df.index alignment after joins or reindexing.
  * Schema: Explicitly verify dtypes (especially datetime64[ns] and float64) for ETL tasks.
  * Safety: Avoid SettingWithCopyWarning; prefer .loc or .iloc for assignments.
  * Continuity: Check for unexpected gaps in time-series data using .diff().

4. Recommended Workflow Presets (Chat Settings)

Explain

Goal: Deep dive into logic & complexity.
1.Analyze: Input/Output types and core logic.
2.Complexity: State Time/Space complexity.
3.Quant Focus: Identify vectorization opportunities (Polars/Numpy) or hidden loops.
4.Risks: Point out NaN/Inf handling, memory bottlenecks, or Pandas index misalignment.

Fix

Goal: Resolve errors or IDE warnings with production-grade code.
1.Root Cause: One-sentence diagnosis.
2.Fix: Smallest corrective change using Strict Type Hinting.
3.Robustness: Ensure handling of edge cases (empty DFs, zero-division, SettingWithCopy).
4.Verification: Provide a minimal assert based MRE.

Optimize (Perf & Refactor)

Goal: Maximize execution speed and readability.
1.Identify: Locate bottlenecks (loops, Pandas overhead, unnecessary copies).
2.Action: Convert to Polars/Numpy or apply numba.jit.
3.Benchmark: Provide before/after time.perf_counter results.
4.Constraint: Zero change in numerical output.

Test

Goal: Ensure data integrity and factor correctness.
1.Scope: Critical paths and boundary conditions (e.g., market open/close).
2.Method: Fast, deterministic assert or pytest snippets.
3.Pandas Check: Verify index continuity and column-level null counts.
4.Data: Generate realistic dummy data (OHLCV) for testing.

Commit

Goal: Conventional commit message.
1.Summary: type(scope): description.
2.Details: 1-line rationale for key changes.