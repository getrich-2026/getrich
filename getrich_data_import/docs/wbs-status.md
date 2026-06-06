# WBS Status

This project is a new implementation aligned with the design document. It is not based on the old `data_import` or `import_data` projects.

## Implemented

| Task | Status | Notes |
|---|---|---|
| T1.1 | Partial | Independent uv project, package layout, CLI, tests. Root-level CI/pre-commit not added. |
| T1.2 | Partial | Layered TOML/env config implemented with stdlib. `pydantic-settings` can be added if strict design conformance is required. |
| T2.1 | Done | `00_extensions.sql` creates TimescaleDB extension and schemas. |
| T2.2 | Done | `10_meta.sql` creates instruments, symbol_map, trading_calendar, future_contracts, option_contracts. |
| T2.3 | Done | `20_market.sql` creates index/stock/ETF/future/option daily and minute fact tables with raw source fields. |
| T2.4 | Partial | Compression policies are attempted for all 1m market tables, and 1m-to-1d helper materialized views aggregate by `trading_day`. Automatic refresh jobs are not implemented. |
| T2.5 | Done | `40_realtime.sql` creates short-retention tick buffer. |
| T2.6 | Done | `50_ops.sql` creates users, api_keys, etl_job_run, data_quality_check. |
| T2.7 | Partial | `migrate-schema` tracks DDL files in `ops.schema_migrations` with checksums. Rollback is not implemented. |
| T3.1 | Partial | HistoryDataSource protocol and provider registry exist. RealtimeDataSource is not implemented yet. |
| T3.3 | Partial | Insight historical metadata and kline adapter added as optional provider, with runtime path, env-file credential loading, and login. Realtime callback/Redis path is not implemented yet. |
| T3.4 | Partial | SymbolMapService supports resolving source symbols to instrument metadata through `meta.symbol_map`. Missing-code alerting is not wired yet. |
| T3.5 | Partial | TradingCalendarService supports open-day checks, previous/next trading day, and configurable night-session assignment; minute-bar import uses it to assign `trading_day`. |
| T4.1 | Partial | Imports generic instruments from Yinhe hist_code parquet. Contract extension details depend on upstream fields. |
| T4.2 | Partial | Imports trading calendars from Yinhe calendar parquet. P1 found only SH calendar rows loaded while instruments include SH and SZ, so SZ minute-bar trading-day assignment still needs an exchange mapping or calendar coverage fix. |
| T5.1 | Partial | `extract` request/plan layer structures import-bars asset/freq/date/symbol/mode and source kwargs. Source-level checkpoint persistence is not implemented. |
| T5.2 | Partial | Normalizes bar fields and attaches `instrument_id`; full unit/adjustment policy still needs source-specific detail. |
| T5.3 | Partial | OHLC/non-negative/adj_factor and configurable price-jump checks implemented; missing-bar and expected-minute checks still pending. |
| T5.4 | Partial | PostgreSQL temp-table upsert with `ON CONFLICT DO UPDATE`. P1 small samples pass, but full stock 1d import hit PostgreSQL `out of shared memory` because many temp tables were created inside one large transaction. |

## Database Initialization

Local `getrich` PostgreSQL/TimescaleDB was cleaned, rebuilt, and verified through `migrate-schema` and `verify-schema` on 2026-06-05.

- PostgreSQL server version: 16.14
- TimescaleDB version: 2.27.2
- TimescaleDB license: apache
- Schema migrations applied: `00_extensions.sql`, `10_meta.sql`, `20_market.sql`, `30_compress_ca.sql`, `40_realtime.sql`, `50_ops.sql`.
- `verify-schema` passed with no missing tables, hypertables, or migrations.
- Compression and retention policy DDL degrade gracefully under Apache license; 1m-to-1d helper materialized views use explicit `trading_day` grouping instead of Timescale continuous aggregates.

## P1 Local Data Verification

Local source directory: `/home/quant/data`.

- `scan` found one calendar file, 578 index instruments, 5244 stock instruments, 1548 ETF instruments, 126179 daily kline files, and 5195+ minute kline files. Future and option instruments were not available and were skipped.
- `load-metadata` completed with 23394 rows written.
- 1d sample imports passed:
  - stock: 397 rows, 100 instruments, 2026-06-01 to 2026-06-04.
  - ETF: 200 rows, 50 instruments, 2026-06-01 to 2026-06-04.
  - index: 200 rows, 50 instruments, 2026-06-01 to 2026-06-04.
- 1m sample import passed for SH stock only: 720 rows, 3 instruments, 2026-06-04.
- Sample checks passed for duplicate keys and core OHLCV nulls.
- Parquet exports were written and read back from `/tmp/getrich_p1_*`.
- Verification commands passed: `.venv/bin/ruff check src tests` and `.venv/bin/pytest tests -q` with 73 tests.

## Not Yet Implemented

RQData direct adapter, scheduler, realtime Redis stream, API/SDK, missing-bar checks, full contract-detail import, and production deployment are not implemented in this first cut.
