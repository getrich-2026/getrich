-- 001_ohlcv_bars.sql
--
-- Minute and daily OHLCV bars for live signal production and ad-hoc
-- analytics. Read by ``apps/strategy/live_data_provider.py::LiveDataProvider
-- .load_latest_bars()`` (default ``table_name="md_bars_1m"``).
--
-- Schema (per CLAUDE.md §2 "ClickHouse" + §3.1 "时区对齐"):
--   - Engine: MergeTree series (no UPDATE / DELETE in hot path).
--   - PARTITION BY: monthly (``toYYYYMM(dt)``) — keeps partition count
--     manageable for 5-year retention; matches the typical query
--     pattern ("last N months for symbol X").
--   - ORDER BY: ``(symbol, dt)`` — primary key covers the live-signal
--     read pattern (latest N bars per symbol). Putting ``symbol``
--     first lets the index prune to a single ticker on a hot lookup.
--   - TTL: ``dt + INTERVAL 5 YEAR`` — 5 years of minute bars is
--     ~2.6M rows per symbol per year; 5y is enough for any
--     reasonable backtest, and ClickHouse's TTL automatically
--     drops expired parts.
--   - Time column: ``DateTime64(3, 'Asia/Shanghai')`` — millisecond
--     precision in the platform's primary timezone. Night-session
--     bars (e.g. 21:00 → 02:30 next day) stay correctly aligned
--     because we never use ``Date`` (which would flip a 23:30 bar
--     to the next day in UTC).
--   - Float64 for OHLCV: minute bars are tiny (~10M rows / year
--     / 1000 symbols) and ``Decimal`` would dominate disk + I/O.
--     Backtest-level PnL still uses ``decimal.Decimal`` per
--     CLAUDE.md §3.2 — the OHLCV table is a *display* layer.
--
-- We declare two tables (1m and 1d). The 1d table is built from
-- the 1m table by a materialised-view-style ETL (not yet wired;
-- rows are inserted directly for now). Other frequencies
-- (5m/15m/30m/60m) follow the same template if/when a P10-Phase-4
-- round needs them.

CREATE TABLE IF NOT EXISTS md_bars_1m
(
    dt      DateTime64(3, 'Asia/Shanghai'),
    symbol  String,
    open    Float64,
    high    Float64,
    low     Float64,
    close   Float64,
    volume  Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
TTL dt + INTERVAL 5 YEAR
SETTINGS index_granularity = 8192
COMMENT 'Minute OHLCV bars per symbol (default read table for live signal production). MergeTree, 5y TTL, monthly partitions. (P0.4)';

CREATE TABLE IF NOT EXISTS md_bars_1d
(
    dt      DateTime64(3, 'Asia/Shanghai'),
    symbol  String,
    open    Float64,
    high    Float64,
    low     Float64,
    close   Float64,
    volume  Float64
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
TTL dt + INTERVAL 10 YEAR
SETTINGS index_granularity = 8192
COMMENT 'Daily OHLCV bars per symbol. MergeTree, 10y TTL, monthly partitions. (P0.4)';

