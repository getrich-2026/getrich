# INSIGHT Data Import Product Requirements

> Lead agent: product_manager
> Source document: `docs/华泰INSIGHT_数据封装_开发文档.md`
> Version: 0.1
> Updated: 2026-06-07
> Status: Draft

## 1. Background

`getrich_data_import` needs to import Huatai INSIGHT external market data into local storage so that other programs in the GetRich ecosystem can read stable, normalized datasets without depending directly on the INSIGHT SDK.

The current source document has already mapped INSIGHT data families, key API traps, symbol conventions, adjustment factors, timestamp behavior, and an initial storage direction. This PRD converts that material into product-level functionality, scope, priorities, and acceptance criteria.

## 2. Problem

Downstream programs need historical market data, metadata, and selected derived datasets with consistent symbols, timestamps, storage contracts, and data quality checks. Direct SDK usage creates several product risks:

- Every caller must handle INSIGHT-specific code suffixes, field drift, timestamp quirks, and permission differences.
- SDK query results cannot be reliably shared, audited, or replayed across jobs.
- Some data should become authoritative local data, while temporary validation or wide analytical snapshots should not pollute PostgreSQL.
- Point-in-time correctness, adjustment factor semantics, and trading-calendar alignment need one shared implementation instead of duplicated caller logic.

## 3. Product Goal

Build an INSIGHT import capability inside `getrich_data_import` that:

- Downloads selected INSIGHT datasets into local Parquet staging first.
- Imports validated Parquet staging files into PostgreSQL + TimescaleDB as the canonical local data layer.
- Uses DuckDB for validation, local snapshots, source comparison, and non-authoritative analytical outputs.
- Provides stable read contracts for other programs through tables, views, and eventually a lightweight Python query interface.
- Preserves raw source semantics while exposing normalized symbols, trading days, and bar times.
- Supports incremental backfill, replay, audit, and data quality checks.

## 4. Users

| User | Need |
|---|---|
| Data import operator | Configure INSIGHT credentials, run backfills, inspect failures, resume jobs. |
| Quant research program | Read normalized historical bars, calendars, metadata, index components, fund/ETF data, and selected daily derived datasets. |
| Data validation program | Compare INSIGHT with existing local sources, detect missing rows, duplicate keys, field drift, and adjustment inconsistencies. |
| Future realtime service | Subscribe to realtime K-line/tick streams and persist short-retention buffers or long-term tick data when enabled. |

## 5. Scope

### 5.1 In Scope for MVP

MVP focuses on historical, reusable, medium-frequency data.

| Capability | Product Requirement | Target Storage |
|---|---|---|
| INSIGHT connection profile | Support one or more named INSIGHT credential profiles without logging secrets. | Config only |
| Local Parquet staging | Fetch INSIGHT SDK responses into local Parquet files before canonical database import. | Local filesystem + PG manifest |
| Symbol metadata import | Import and normalize securities, exchanges, security types, lifecycle dates, and INSIGHT `htsc_code` mappings. | PostgreSQL |
| Trading calendar import | Import exchange calendars and provide sorted, queryable trading days. | PostgreSQL |
| Adjustment factor import | Import sparse `xdy`, `b_xdy`, `f_xdy` rows and expose them for query-time adjustment. | PostgreSQL / TimescaleDB |
| Historical K-line import | Import daily and minute K-line data for stock, index, fund/ETF, future, and option where available. | TimescaleDB hypertables |
| Daily basic and valuation import | Import stock daily basic and stock valuation data with clear raw/adjusted close semantics. | TimescaleDB hypertables |
| Index component import | Import time-aware index components and weights to avoid survivorship bias. | PostgreSQL / TimescaleDB |
| Fund/ETF daily import | Import fund daily data, NAV-derived data, ETF baskets, and ETF redemption lists when permissions and source coverage allow. | PostgreSQL / TimescaleDB |
| Data quality checks | Validate duplicate keys, null core fields, OHLC rules, trading-day alignment, timestamp normalization, and schema drift. | PostgreSQL ops tables |
| Import job audit | Record job parameters, row counts, source range, failures, warnings, and checkpoints. | PostgreSQL ops tables |
| DuckDB temp workspace | Materialize validation tables, source comparisons, adjustment reconciliation, and wide research extracts. | DuckDB |

### 5.2 Out of Scope for MVP

- Strategy signals, factor definitions beyond importing raw INSIGHT-provided Barra values, backtest assumptions, or trading decisions.
- Long-term tick and transaction/order storage in ClickHouse.
- Order book reconstruction from tick or transaction/order streams.
- Self-built futures main-contract continuous series.
- Financial statement import unless explicitly prioritized after market-data MVP.
- Production scheduler, realtime streaming, and external API service hardening.

## 6. Product Functional Design

### 6.1 Data Domain Catalog

The product should expose an INSIGHT data catalog so callers can see what can be imported, what is already imported, and what is unavailable due to permission or source coverage.

Required catalog fields:

- Dataset name.
- INSIGHT API family and function name.
- Asset class.
- Frequency.
- Required permission tier.
- Storage destination.
- Latest imported range.
- Supported import mode: full replace, incremental, date-range replay, or stream.
- Known limitations.

### 6.2 Import Configuration

Operators should be able to define import plans without changing code.

Required configuration dimensions:

- INSIGHT profile name.
- Parquet staging root.
- Dataset group.
- Asset class: stock, index, fund, ETF, future, option.
- Symbol include/exclude list.
- Exchange include/exclude list.
- Date range.
- Frequency.
- Import mode.
- Batch size and retry policy.
- Destination: local Parquet staging, PostgreSQL/TimescaleDB canonical tables, or DuckDB temp.

Acceptance criteria:

- Invalid combinations are rejected before execution.
- Missing optional datasets can be skipped with a recorded reason.
- Secrets are never emitted in logs, job rows, or exception messages.

### 6.3 Local Parquet Staging

INSIGHT SDK fetch and canonical database load should be separated by a local Parquet staging layer.

Required features:

- Write SDK responses to deterministic local paths such as `/home/quant/data/insight/{dataset}/{asset}/{freq}/...`.
- Record each Parquet file in PostgreSQL with provider, dataset, path, content hash, row count, date range, partition key, schema fingerprint, status, and related job run ids.
- Support reloading PostgreSQL/TimescaleDB from existing Parquet without calling INSIGHT again.
- Keep raw or lightly normalized source columns in Parquet for audit and transform replay.
- Mark superseded or failed staging files instead of deleting records silently.

Acceptance criteria:

- A failed database load can be retried from local Parquet.
- A fetch job can be audited without opening the Parquet file.
- Parquet staging is reproducible from recorded job parameters and source dataset.
- PostgreSQL stores the manifest and canonical data, not the raw Parquet payload itself.

### 6.4 Metadata Foundation

Metadata is the first required layer because all downstream imports depend on stable symbol, exchange, and calendar mapping.

Required features:

- Maintain `htsc_code`, canonical symbol, exchange, security type, and lifecycle dates.
- Preserve INSIGHT suffix conventions, including `.SH`, `.SZ`, `.BJ`, `.HKSC`, `.HGHQ`, `.CF`, `.SHF`, `.DCE`, `.ZCE`, and `.INE`.
- Maintain independent trading calendars by exchange.
- Track unresolved symbols and mapping conflicts.
- Keep futures and options contract-detail gaps explicit instead of fabricating missing fields.

Acceptance criteria:

- Every market fact row must resolve to a known instrument or be rejected into an auditable error path.
- Calendar imports must be sorted ascending before use.
- Import jobs fail clearly when a required trading calendar is missing.

### 6.5 Historical Market Import

The market import capability should load normalized historical data while preserving raw INSIGHT fields that matter for reconciliation.

Required datasets:

- Daily K-line.
- Minute K-line.
- Stock daily basic.
- Stock valuation.
- Index daily data.
- Index components.
- Fund/ETF daily data.
- ETF basket and redemption data where available.

Product rules:

- Store original unadjusted prices and adjustment factors separately.
- Do not persist adjusted OHLC as canonical facts until adjustment-source reconciliation is complete.
- Generate normalized `trading_day` and `bar_start` fields; do not use INSIGHT raw `time` as the primary bar key.
- Store raw source time separately for reconciliation.
- Use nullable superset fields for cross-asset differences such as `num_trades`, `open_interest`, and `settle`.

Acceptance criteria:

- Re-running the same import range is idempotent.
- Duplicate primary keys are resolved by deterministic upsert behavior.
- Core OHLCV fields are checked for nulls and invalid values.
- Import output can be read by downstream SQL clients without SDK dependency.

### 6.6 Adjustment and Valuation Data

Adjustment data must be treated as a first-class product capability because INSIGHT has multiple adjustment-related sources.

Required features:

- Import sparse adjustment factors from `get_adj_factor`.
- Import valuation close fields from `get_stock_valuation`.
- Import `get_daily_basic.backward_adjusted_closing_price` as source data, not as the canonical adjustment rule.
- Provide a validation workflow that compares adjustment sources before exposing adjusted-price views as trusted.

Acceptance criteria:

- The system can identify symbols and dates where adjustment sources disagree beyond tolerance.
- Query-time adjusted-price views are marked experimental until the reconciliation workflow passes.
- Raw unadjusted bar data remains available regardless of adjustment workflow status.

### 6.7 Point-in-Time Datasets

Datasets with publish dates must preserve point-in-time behavior.

Required features:

- Store `pub_date` and report period fields when importing financial or company-event data.
- Mark PIT-capable datasets in the catalog.
- Ensure future-facing query helpers filter by publish date rather than report end date.

MVP note:

Financial statements are not part of first MVP unless the import roadmap is expanded. The product requirement is included now to prevent later schema or query design from introducing look-ahead bias.

### 6.8 DuckDB Temporary Workspace

DuckDB should be used for non-authoritative local work that benefits from columnar reads or temporary wide tables. It is not the primary raw staging layer; local Parquet is.

DuckDB use cases:

- INSIGHT-vs-existing-source comparison tables.
- Adjustment reconciliation outputs.
- Temporary raw SDK response samples when Parquet inspection is not enough.
- Wide research extracts exported from PostgreSQL/TimescaleDB.
- Large validation joins that do not need durable relational storage.

DuckDB rules:

- DuckDB is not the source of truth.
- DuckDB artifacts must be reproducible from PostgreSQL/TimescaleDB, source Parquet, or a recorded import job.
- Temporary DuckDB tables should have retention or cleanup rules.
- If downstream programs depend on a DuckDB snapshot, its generation parameters must be recorded.

### 6.9 Downstream Access

The first downstream contract should be SQL-first.

Required access surfaces:

- Canonical PostgreSQL/TimescaleDB tables.
- Stable read views for common datasets.
- Dataset catalog table or view.
- Job and data quality status tables.
- Optional local DuckDB files for named snapshots.

Future access surfaces:

- Lightweight Python reader API.
- Parquet export command.
- Realtime read buffer.
- Internal service API if multiple processes need controlled access.

Acceptance criteria:

- A downstream program can discover available date ranges and symbols without calling INSIGHT.
- A downstream program can read bars by symbol, asset class, date range, and frequency through stable SQL.
- Failed or partial imports are visible through ops metadata.

### 6.10 Operations and Recovery

Required operational features:

- Import dry run.
- Import execution.
- Incremental checkpoint.
- Date-range replay.
- Failed-job retry.
- Row-count and range summary.
- Warning classification for skipped optional datasets, permission limits, schema drift, and missing calendars.

Acceptance criteria:

- A failed import can be resumed without manually deleting successful rows.
- Missing data can be skipped only when configured and must be recorded.
- Each job records input parameters, source dataset, affected date range, row counts, warnings, and errors.

## 7. Storage Product Rules

| Data Type | PostgreSQL + TimescaleDB | DuckDB |
|---|---|---|
| Symbol metadata | Canonical | No |
| Trading calendar | Canonical | Optional export only |
| Parquet staging manifest | Canonical metadata in `staging.parquet_file` | No |
| Raw INSIGHT SDK responses | Manifest only; raw rows stay in local Parquet | Optional sample only |
| Historical daily/minute bars | Canonical hypertables | Optional snapshot |
| Adjustment factors | Canonical | Validation snapshot |
| Index components | Canonical | Optional snapshot |
| Fund/ETF daily and basket data | Canonical | Optional snapshot |
| Import job audit | Canonical | No |
| Data quality results | Canonical | Optional analytical copy |
| Raw SDK response scratch data | Only if required for audit | Preferred temp storage |
| Source comparison outputs | Optional summary only | Preferred |
| Wide research extracts | No, unless promoted | Preferred |

## 8. Prioritization

### P0: Feasibility and Core Contract

- INSIGHT credential profile and SDK connection smoke test.
- Local Parquet staging path convention and file manifest.
- Dataset catalog draft.
- Metadata import for symbols and calendars.
- Daily K-line import for stock, index, fund/ETF where available.
- TimescaleDB upsert and job audit.
- Basic downstream SQL read examples.

### P1: Production-Useful Historical Import

- Minute K-line import.
- Adjustment factor import.
- Daily basic and valuation import.
- Index component import.
- Fund/ETF daily and ETF basket/redemption import where available.
- Data quality checks and failed-job retry.
- DuckDB validation workspace for source comparison and adjustment reconciliation.

### P2: Expanded Data Coverage

- Money flow, trade distribution, chip distribution, margin data.
- Barra raw factor import as long table.
- Financial statement and company-event import with PIT guarantees.
- Futures and options market data with explicit metadata gap handling.

### P3: Realtime and High-Frequency Roadmap

- Realtime K-line subscription.
- Tick playback and subscription.
- Transaction/order streams for advanced permission tier.
- ClickHouse long-term high-frequency storage.
- Realtime buffer and stream consumers.

## 9. MVP Acceptance Criteria

MVP is acceptable when:

- At least one INSIGHT historical data group can be imported end-to-end into PostgreSQL/TimescaleDB.
- The import path can run as `INSIGHT SDK -> local Parquet -> PostgreSQL/TimescaleDB`.
- Parquet staging files are registered in PostgreSQL before canonical load.
- Metadata and calendar prerequisites are imported before fact data.
- Repeated import of the same range is idempotent.
- Import job audit and data quality results are queryable.
- Downstream SQL can read normalized bars without importing or initializing the INSIGHT SDK.
- Temporary validation outputs can be written to DuckDB without becoming required canonical storage.
- Missing optional datasets can be skipped with explicit warnings.

## 10. Open Questions

These items should be confirmed before architecture and implementation are finalized:

- Which INSIGHT permission tier is available, especially for tick depth, transaction/order streams, and advanced data.
- SDK rate limits, concurrency limits, and maximum query batch sizes.
- Earliest available date for daily and minute K-line by asset class.
- Whether INSIGHT timestamps are already normalized to Beijing time.
- Which adjustment source should become the trusted query-time adjusted-price basis after reconciliation.
- Whether financial statements are needed in the first implementation wave.
- Whether downstream callers need only SQL access first, or also a Python reader API in MVP.
- Whether DuckDB snapshots should live under a fixed local path, per-job path, or caller-provided path.

## 11. Next Recommended Step

Hand this PRD to the `architect` stage to produce:

- Dataset-to-table mapping.
- Import workflow design.
- PostgreSQL/TimescaleDB schema changes.
- DuckDB workspace conventions.
- Dependency-ordered WBS for implementation.
