-- 002_factors_long.sql
--
-- Long-format factor values for live signal production. Read by
-- ``apps/strategy/live_data_provider.py::LiveDataProvider.load_latest_factors()``
-- (default ``table_name="factors_long"``).
--
-- Long format (one row per (dt, symbol, factor)) rather than wide
-- (one column per factor) — factor names are strategy-defined and
-- change frequently as new factors are added. A wide schema would
-- require a migration every time a strategy registers a new factor;
-- the long format lets ``set_ctx_factors()`` group by factor name
-- in Polars / pandas.
--
-- Schema (per CLAUDE.md §2 "ClickHouse" + §3.1 "时区对齐"):
--   - Engine: MergeTree (factor values are append-only).
--   - PARTITION BY: monthly (``toYYYYMM(dt)``).
--   - ORDER BY: ``(factor, symbol, dt)`` — primary key covers the
--     read pattern ("latest N values for factor F across symbols"),
--     which is the inverse of bars (latest N per symbol). Putting
--     ``factor`` first lets the index prune to a small set of
--     ticker scans per factor, which is the dominant cost when
--     a strategy uses 10+ factors.
--   - TTL: ``dt + INTERVAL 5 YEAR`` — same as minute bars; factor
--     data is denser (more symbols per factor) so 5y covers the
--     same backtest window.
--   - Time column: ``DateTime64(3, 'Asia/Shanghai')`` — same
--     rationale as the bars table.
--   - Float64 for ``value``: factor values are normalised z-scores
--     / ranks; precision is not load-bearing.

CREATE TABLE IF NOT EXISTS factors_long
(
    dt      DateTime64(3, 'Asia/Shanghai'),
    symbol  String,
    factor  String,
    value   Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(dt)
ORDER BY (factor, symbol, dt)
TTL dt + INTERVAL 5 YEAR
SETTINGS index_granularity = 8192
COMMENT 'Long-format factor values (one row per dt/symbol/factor). MergeTree, 5y TTL, monthly partitions. Read by live signal producer. (P0.4)';
