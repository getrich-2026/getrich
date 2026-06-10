# Database Schema Audit & Optimization Report (v2)

- **Date**: 2026-06-04
- **Status**: DONE — only findings A and E were adopted and implemented. All other findings (B/C/D/F) were evaluated and intentionally not implemented (see decision note below).
- **Audited Paths**: `/home/quant/project/getrich-database/getrich_data_import/sql/init/backend/`
  - [00_extensions.sql](file:///home/quant/project/getrich-database/getrich_data_import/sql/init/backend/00_extensions.sql)
  - [10_meta.sql](file:///home/quant/project/getrich-database/getrich_data_import/sql/init/backend/10_meta.sql)
  - [20_market.sql](file:///home/quant/project/getrich-database/getrich_data_import/sql/init/backend/20_market.sql)
  - [30_compress_ca.sql](file:///home/quant/project/getrich-database/getrich_data_import/sql/init/backend/30_compress_ca.sql)
  - [40_realtime.sql](file:///home/quant/project/getrich-database/getrich_data_import/sql/init/backend/40_realtime.sql)
  - [50_ops.sql](file:///home/quant/project/getrich-database/getrich_data_import/sql/init/backend/50_ops.sql)

---

## Executive Summary

The database initialization schema files were audited. Of the optimization opportunities identified, only two were adopted — both have a real benefit, near-zero cost, and no semantic risk:

- **A**: replace `array_agg(... ORDER BY ...)[1]` with TimescaleDB `first()`/`last()` in the daily rollup materialized views.
- **E**: add a BRIN index on `trading_day` to `market.option_greeks_1d`, matching the other daily fact tables.

The remaining findings (continuous aggregates, auto-update triggers, calendar self-FKs, identity columns) were evaluated and deliberately **not** implemented to avoid over-engineering — see the decision note at the end.

---

## Adopted Findings

### A. Replace `array_agg` with `first()`/`last()` in `30_compress_ca.sql`
> [!WARNING]
> The daily rollup views used `(array_agg(open ORDER BY dt))[1]` and `(array_agg(close ORDER BY dt DESC))[1]` to determine the day's opening and closing prices.
>
> PostgreSQL's `array_agg` allocates memory to build an array of all values in a group, sorts them, and retrieves a single element. With 240 bars per day across ~5,000 stocks, this creates substantial CPU and memory overhead during refreshes.
>
> **Resolution**: TimescaleDB's `first(value, time)` and `last(value, time)` aggregates were used instead. They operate in O(1) memory and are significantly faster. `first`/`last` are plain aggregate functions and do **not** require the source to be a hypertable nor a continuous aggregate, so the views remain regular materialized views.

### E. Missing `trading_day` Index on Option Greeks
> [!TIP]
> The table `market.option_greeks_1d` has `PRIMARY KEY (instrument_id, trading_day)`. Queries filtering only by `trading_day` (e.g. cross-sectional options greeks analysis) would result in sequential scans.
>
> **Resolution**: Added a BRIN index on `trading_day` to match the index design of the other daily fact tables:
> ```sql
> CREATE INDEX IF NOT EXISTS idx_option_greeks_1d_trading_day ON market.option_greeks_1d USING brin (trading_day);
> ```

---

## Implemented Code Diffs

### `20_market.sql` (Option Greeks Index)
```diff
--- /home/quant/project/getrich-database/getrich_data_import/sql/init/backend/20_market.sql
+++ /home/quant/project/getrich-database/getrich_data_import/sql/init/backend/20_market.sql
@@ -282,4 +282,5 @@
     updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
     PRIMARY KEY (instrument_id, trading_day)
 );
+CREATE INDEX IF NOT EXISTS idx_option_greeks_1d_trading_day ON market.option_greeks_1d USING brin (trading_day);
```

### `30_compress_ca.sql` (First/Last Aggregates)
The 5 daily rollup materialized views (index/stock/etf/future/option `*_bar_1d_ca`) replace the
`array_agg` pattern with `first()`/`last()`, while remaining regular materialized views
(no continuous aggregate, no `time_bucket`):

```diff
-       (array_agg(open ORDER BY dt))[1] AS open,
+       first(open, dt) AS open,
        max(high) AS high,
        min(low) AS low,
-       (array_agg(close ORDER BY dt DESC))[1] AS close,
+       last(close, dt) AS close,
```

For `future_bar_1d_ca` and `option_bar_1d_ca`, the open interest column is also converted:

```diff
-       (array_agg(open_interest ORDER BY dt DESC))[1] AS open_interest
+       last(open_interest, dt) AS open_interest
```

Direction check: `first(x, dt)` takes the value at the minimum `dt` (the open), and
`last(x, dt)` takes the value at the maximum `dt` (the close / latest open interest).

---

## Decision Note — Findings Not Implemented

The following findings from the original audit were evaluated and intentionally **not** implemented:

- **B — Continuous aggregates for stock/etf/index**: deferred. The proposed `GROUP BY time_bucket('1 day', dt), trading_day` carries a UTC-vs-`Asia/Shanghai` date-offset risk, and switching to continuous aggregates requires reworking the ETL refresh path (`call refresh_continuous_aggregate` instead of `REFRESH MATERIALIZED VIEW`). With A applied, the full-refresh performance pressure is largely relieved, so B is not urgent. The schema deliberately keeps regular materialized views grouped by `trading_day` (guarded by `test_compress_ca_groups_day_rollups_by_trading_day`).
- **C — Auto-update `updated_at` triggers**: not implemented. The application layer (`load/postgres.py`, `pipeline.py`) already maintains `updated_at` on upsert; triggers would be a defensive duplicate, not a bug fix.
- **D — `trading_calendar` self-referencing FKs**: rejected. Mutually-referencing `prev_trading_day`/`next_trading_day` FKs create an unsolvable insert-order deadlock for batch ETL, requiring `DEFERRABLE` constraints and a single-transaction calendar load. The existing `CHECK` constraints already guard the common date-ordering errors.
- **F — `BIGSERIAL` → `GENERATED BY DEFAULT AS IDENTITY`**: not implemented. Pure spec-compliance change with no behavior/performance benefit; can be folded into a future schema reset.
