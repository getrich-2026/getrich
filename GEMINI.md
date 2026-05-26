# GEMINI.md (getrich-database)

Repository-specific guidance for the `getrich-database` project.
Target: Gemini coding agents. This file supplements any global Gemini guidance.

## 1. Scope & Role

- **Positioning**: External **data ingestion layer** for the `getrich` quantitative investment platform.
- **Core Duties**: Provider adapters (AmazingData, RiceQuant, HDB, Wind, AKShare, iFinD), raw data capture, normalization, data quality checks, backfill/replay, and loading curated datasets into PostgreSQL / ClickHouse / DuckDB / Parquet.
- **Hard Boundary**: **Data infrastructure only**. Do not embed factor definitions, backtest assumptions, strategy logic, or trading decisions.

## 2. Tech Stack

| Layer | Technology | Role |
|---|---|---|
| Runtime | Python 3.10+ (import_data), Python 3.13+ (yinhe_data_fetcher) | Dual sub-projects |
| Package mgmt | `uv` | `uv sync` / `uv add` / `uv run` |
| Primary DB | PostgreSQL 16 | Transactional storage (frontend schema) |
| Analytical DB | ClickHouse (MergeTree, DateTime64(3, 'Asia/Shanghai')) | Market data bars, instruments |
| Ad-hoc / Validate | DuckDB | Parquet merge, validation |
| Cache / Landing | Parquet (zstd, atomic writes) | Local file cache |
| Format / Lint | ruff, pytest | |

## 3. Project Layout

```
getrich-database/
├── import_data/                  # Primary ETL: all sources → DB
│   ├── src/import_data/
│   │   ├── core/                 # config.py, logger.py, exceptions.py, utils.py
│   │   ├── db/
│   │   │   ├── postgres/pool.py          # psycopg3 AsyncConnectionPool
│   │   │   ├── clickhouse/database.py    # ClickHouseClient wrapper
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

## 4. Key Architectural Patterns

### 4.1 Fetcher Hierarchy (yinhe_data_fetcher)

```
BaseFetcher (ABC)
├── FullReplaceFetcher   # Wipe + full fetch (calendar, hist_code_list, backward_factor)
└── IncrementalFetcher   # Watermark-based delta sync
    └── KlineFetcher     # K-line specific (month-partitioned Parquet)
```

Adding a new source:
1. Create fetcher class in `fetchers/impl/`, extending the appropriate base
2. Set class attributes: `NAME`, `TYPE`, `CODE_CHUNK_SIZE`, `DATE_CHUNK_DAYS`
3. Implement `_fetch_one()` returning a DataFrame
4. Register in `registry.py` (`REGISTRY_CLASSES` list)
5. Toggle in `config.yaml`

### 4.2 ClickHouse Table Pattern (import_data)

- `ClickHouseTable` ABC: `create()`, `insert()`, `query()`, `count()`, `optimize()`, `truncate()`, `drop()`
- Implementations (e.g., `MinBarTable`, `DayBarTable`): define schema, ORDER BY, PARTITION BY, TTL, engine
- `ClickHouseClient`: connect, execute, query, insert, upsert

### 4.3 Data Sources & Data Flow

```
AmazingData (银河)  ──> yinhe_data_fetcher ──> Parquet (local) ──> [待接入 PostgreSQL]
RiceQuant (米筐)    ──> import_data/fromrq ──> ClickHouse (rq.*)
HDB (国泰君安)      ──> import_data/fromhdb ──> ClickHouse (market_data.*)
Wind (万得)         ──> import_data/jobs ──> ClickHouse (wind.*)
AKShare (开源)      ──> import_data/akshare ──> ClickHouse
iFinD (同花顺)      ──> import_data/ifind ──> ClickHouse
```

## 5. Data Integrity Rules

- Handle empty datasets, missing columns, duplicate keys, nulls, schema drift explicitly.
- Distinguish **event time** vs **publish time** vs **ingestion time**.
- Never mix naive and timezone-aware datetimes. All market data = `Asia/Shanghai`.
- Do not silently change units, currencies, or identifier mapping.
- Treat look-ahead leakage as a data-layer concern.

## 6. Storage Constraints

| Database | Allowed | Prohibited |
|---|---|---|
| PostgreSQL | DDL, DML, COPY, UPSERT, transactions | Heavy ORM (no SQLAlchemy full ORM) |
| ClickHouse | Batch insert, read-only analytics, TTL | Row-level UPDATE/DELETE, transactions |
| DuckDB | Ad-hoc query, Parquet merge, validation | Persistence as source of truth |
| Parquet | Landing / cache, zstd compression | Raw CSV commit to repo |

- **PostgreSQL**: Use `psycopg3` async pool + native SQL. Prefer `COPY` for bulk loads.
- **ClickHouse**: MergeTree engine only, `DateTime64(3, 'Asia/Shanghai')` for time columns.
- **Parquet**: Always atomic writes (UUID temp + `os.replace()`). Use `write_parquet()` from `yinhe_data_fetcher/src/utils.py`.

## 7. Ingestion Design Rules

- Keep **extraction → normalization → storage** clearly separated.
- Preserve raw source meaning first. Make mapping and transformation rules explicit.
- Make provider, dataset, date range, timezone explicit in code or config.
- Surface ambiguity — wrong normalization is worse than no normalization.

## 8. External API Rules

- Respect rate limits, pagination, vendor error behavior. Use `retry_call()`.
- Wrap I/O with error handling + structured logger. Do not log secrets.
- Surface provider contract changes; do not silently patch around.

## 9. Logging

- Use the project's structured logger. No `print()`-based output.
- Logs must identify: range / dataset / target processed.
- Preserve existing alerting hooks (Feishu, WeCom, email).

## 10. Safety (Ask Before Proceeding)

Seek explicit confirmation before:
- destructive backfills, bulk deletes, or replay jobs overwriting published data
- changing PostgreSQL / ClickHouse schema or retention behavior
- changing identifier mapping, symbol canonicalization, timezone conventions, or adjustment logic
- switching data vendors or changing authoritative upstream source
- modifying secrets handling, auth flows, request signing, or scheduled job behavior
- adding heavyweight dependencies or new infrastructure services

## 11. Verification (Definition of Done)

A task is done only when, where feasible:

1. `ruff check` + `pytest` pass for touched code
2. Dry-run or small-range import performed
3. Row-count / duplicate / schema checks on target store
4. Downstream read sanity check
5. No silent semantics change

If a check was skipped (no network, credentials, too expensive), state explicitly.

## 12. Don'ts (铁律)

- **Don't** embed strategy logic, factor definitions, or trading decisions in ingestion code.
- **Don't** query or write to the main `getrich` project's databases without explicit task scope.
- **Don't** commit `.env` files, raw API keys, or unredacted secrets.
- **Don't** use `print()` for operational logging — use the structured logger.
- **Don't** add heavy ORMs (SQLAlchemy full ORM, Django ORM).
- **Don't** store data > 100K rows in CSV; use Parquet (zstd).

## 13. Reporting

When reporting completion, state briefly:
1. **Scope**: datasets, providers, or job paths affected
2. **Verification**: what was checked (and what was not, with reason)
3. **Storage Impact**: primary PostgreSQL / analytical ClickHouse / staging / cache only
4. **Caveats**: unverified parts, remaining risks