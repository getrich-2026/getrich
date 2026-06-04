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
| T4.2 | Done | Imports trading calendars from Yinhe calendar parquet. |
| T5.1 | Partial | `extract` request/plan layer structures import-bars asset/freq/date/symbol/mode and source kwargs. Source-level checkpoint persistence is not implemented. |
| T5.2 | Partial | Normalizes bar fields and attaches `instrument_id`; full unit/adjustment policy still needs source-specific detail. |
| T5.3 | Partial | OHLC/non-negative/adj_factor and configurable price-jump checks implemented; missing-bar and expected-minute checks still pending. |
| T5.4 | Done | PostgreSQL temp-table upsert with `ON CONFLICT DO UPDATE`. |

## Database Initialization

Local `getrich` PostgreSQL/TimescaleDB was previously initialized through `migrate-schema`.

- PostgreSQL server version: 16.14
- TimescaleDB version: 2.27.2
- TimescaleDB license: apache
- Review schema additions were folded into base `20_market.sql`; the existing test database should be rebuilt before `verify-schema` is treated as current.
- Compression and retention policy DDL degrade gracefully under Apache license; 1m-to-1d helper materialized views use explicit `trading_day` grouping instead of Timescale continuous aggregates.

## Not Yet Implemented

RQData direct adapter, scheduler, realtime Redis stream, API/SDK, Parquet derived exporter, missing-bar checks, full contract-detail import, and production deployment are not implemented in this first cut.
