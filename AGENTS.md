# AGENTS.md

Repository-specific guidance for the `getrich-database` project.
Target: Codex / general-purpose coding agents. This file supplements any global agent guidance.

## 1. Scope & Role

- **getrich-database** is the external **data ingestion layer** for the `getrich` quantitative investment platform.
- **Primary responsibilities**: provider adapters (AmazingData, RiceQuant, HDB, Wind, AKShare, iFinD), raw data capture, normalization, data quality checks, backfill/replay jobs, and loading curated datasets into PostgreSQL / ClickHouse / DuckDB / Parquet.
- **Hard boundary**: data infrastructure only. No factor definitions, backtest assumptions, strategy logic, or trading decisions.

## 2. Tech Stack

| Category | Technology |
|---|---|
| Runtime | Python 3.10+ (import_data), Python 3.13+ (yinhe_data_fetcher) |
| Package mgmt | `uv` (uv sync / uv add / uv run) |
| Primary DB | PostgreSQL 16 (psycopg3 async pool, native SQL) |
| Analytical DB | ClickHouse (MergeTree, DateTime64(3, 'Asia/Shanghai')) |
| Ad-hoc / Validate | DuckDB |
| Cache / Landing | Parquet (zstd, atomic writes) |
| Format / Lint | ruff, pytest |

## 3. Project Layout

```
getrich-database/
├── import_data/                  # Primary ETL: all sources → DB
│   ├── src/import_data/
│   │   ├── core/                 # config.py, logger.py, exceptions.py, utils.py
│   │   ├── db/
│   │   │   ├── postgres/pool.py          # Async PG connection pool
│   │   │   ├── clickhouse/database.py    # ClickHouseClient
│   │   │   ├── clickhouse/table.py       # ClickHouseTable ABC
│   │   │   ├── tables/bar.py            # MinBarTable, DayBarTable
│   │   │   └── repositories/            # Repository pattern for PG
│   │   ├── cleaners/             # Data cleaning framework
│   │   ├── etl/                  # Source ETL modules
│   │   │   ├── akshare/          # 9+ adapter modules
│   │   │   ├── fromrq/           # RiceQuant instruments
│   │   │   ├── fromhdb/          # HDB bars
│   │   │   └── transforms.py     # Shared transformation utils
│   │   ├── gateways/             # Vendor SDK wrappers (ricequant, ifind)
│   │   └── jobs/                 # Runnable orchestration
│   ├── config.yaml
│   └── tests/
├── yinhe_data_fetcher/           # AmazingData (银河证券) fetcher
│   ├── src/
│   │   ├── fetchers/base/        # BaseFetcher, FullReplace, Incremental, Kline ABCs
│   │   ├── fetchers/impl/        # calendar, hist_code_list, backward_factor, kline_day/min5/min1
│   │   ├── config.py, client.py, runner.py, registry.py, utils.py
│   │   └── logger.py
│   ├── config.yaml, main.py
│   ├── data/                     # Local Parquet output (gitignored)
│   └── tests/
├── sql/init/frontend_signal/     # PG migrations (00-14)
├── sql/legacy/                   # Older schema files
├── reference/                    # Design docs, API specs, spreadsheets
└── wheel/                        # AmazingData-1.1.6, tgw-1.0.8.7 wheels
```

## 4. Key Patterns to Follow

### 4.1 Adding a New Data Source (yinhe_data_fetcher)

1. Create a fetcher class in `fetchers/impl/`, extending `FullReplaceFetcher` or `IncrementalFetcher` (or `KlineFetcher` for k-line data)
2. Set class attributes: `NAME`, `TYPE`, `CODE_CHUNK_SIZE`, `DATE_CHUNK_DAYS`
3. Implement `_fetch_one()` — single task unit that returns a DataFrame
4. Register in `registry.py` (`REGISTRY_CLASSES` list)
5. Toggle in `config.yaml` under `fetchers`

### 4.2 Adding a New ClickHouse Table (import_data)

1. Create a class extending `ClickHouseTable` in `db/tables/`
2. Define: `table_name`, `schema` (columns), `engine`, `ORDER BY`, `PARTITION BY`, `TTL`, `settings`
3. Create / drop / write via `ClickHouseClient`

### 4.3 Adding a New ETL Path (import_data)

1. Add source-specific module under `etl/` or `gateways/`
2. Connect raw data → normalize via `transforms.py` utils → write to target DB
3. Wire into `jobs/` as a runnable job class

### 4.4 Parquet I/O Best Practices

- Use `write_parquet()` from `yinhe_data_fetcher/src/utils.py` — handles DuckDB merge dedup + atomic write + pandas fallback
- Partition k-line data by code + year-month: `data/<NAME>/<code>/<yyyy-mm>.parquet`
- Use `read_parquet_if_exists()` / `last_index_date()` for incremental watermarking

## 5. Data Integrity Rules

- Handle empty datasets, missing columns, duplicate keys, nulls, schema drift explicitly
- Never mix naive and timezone-aware datetimes; all market data = `Asia/Shanghai`
- Do not silently change units, currencies, or identifier mapping
- Distinguish event time vs publish time vs ingestion time

## 6. DB Constraints

| Database | Allowed Operations | Prohibited |
|---|---|---|
| PostgreSQL | DDL, DML, COPY, UPSERT, transactions | Heavy ORM |
| ClickHouse | Batch insert, read-only analytics, TTL | Row-level UPDATE/DELETE, transactions |
| DuckDB | Ad-hoc query, Parquet merge, validation | Persistence as source of truth |

## 7. External API Rules

- Respect rate limits, pagination, vendor error behavior. Use `retry_call()` from utils.
- Wrap I/O with error handling + structured logging. Do not log secrets.
- Surface provider contract changes; do not silently patch around.

## 8. Agent Dispatch

| Task | Subagent |
|---|---|
| New ETL/fetcher, schema work, bug fix, DB migration | `code-dev` |
| Code review, correctness audit, integrity check | `code-review` |
| README, changelog, technical docs | `writer` |

Ambiguous task → ask user before dispatching.

## 9. Safety (Ask First)

Seek confirmation before:
- destructive backfills, bulk deletes, replay jobs
- schema / retention changes to PostgreSQL or ClickHouse
- changing symbol canonicalization, timezone, or adjustment logic
- switching data vendors or authoritative upstream source
- modifying auth flows, secrets handling, or scheduled jobs
- adding heavy dependencies or new infrastructure services

## 10. Verification Checklist

- [ ] `ruff check` + `pytest` pass on touched code
- [ ] dry-run or small-range import verified
- [ ] row count / duplicate / schema checks on target
- [ ] downstream read sanity check
- [ ] no silent semantics change

If a check was skipped, state why in the report.

## 11. Reporting

Final report format:
- **Scope**: datasets, providers, job paths affected
- **Verification**: what was checked (and what was not, with reason)
- **Storage impact**: primary PG / analytical CH / staging / cache only
- **Caveats**: unverified parts, remaining risks