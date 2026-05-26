# CLAUDE.md

Repository-specific guidance for the `getrich-database` project.
This file supplements the global guidance in `~/.claude/CLAUDE.md`.

## 1. Scope & Role

- **getrich-database** is the external **data ingestion layer** for the broader `getrich` quantitative investment platform.
- **Primary responsibilities**: provider adapters (AmazingData, RiceQuant, HDB, Wind, AKShare, iFinD), raw data capture, normalization, data quality checks, backfill/replay jobs, and loading curated datasets into PostgreSQL / ClickHouse / DuckDB / Parquet.
- **Hard boundary**: This repo is **data infrastructure only**. Do not embed factor definitions, backtest assumptions, strategy logic, or trading decisions into ingestion code. Those belong in the main `getrich` project.

## 2. Stack

| Layer | Technology | Role |
|---|---|---|
| Runtime | Python 3.10+ (import_data), Python 3.13+ (yinhe_data_fetcher) | Dual sub-projects |
| Primary DB | PostgreSQL 16 | Transactional storage (frontend schema) |
| Analytical DB | ClickHouse | Market data bars (bars_1m, bars_1d), instruments |
| Local / Ad-hoc | DuckDB | Parquet merge/dedup, validation |
| Cache / Landing | Parquet (zstd) | Local file cache, atomic writes |
| Env mgmt | `uv` | `uv sync` / `uv add` / `uv run` |

## 3. Project Structure

```
getrich-database/
├── import_data/                  # Primary ETL package (all data sources)
│   ├── src/import_data/
│   │   ├── core/                 # Config, logger, utils
│   │   ├── db/                   # DB connections, tables, repositories
│   │   │   ├── postgres/pool.py          # psycopg3 AsyncConnectionPool
│   │   │   ├── clickhouse/database.py    # ClickHouseClient wrapper
│   │   │   ├── clickhouse/table.py       # ClickHouseTable ABC
│   │   │   └── tables/bar.py            # MinBarTable, DayBarTable
│   │   ├── etl/                  # Source-specific ETL modules
│   │   │   ├── akshare/          # AKShare adapters (stock, macro, fund, futures, ...)
│   │   │   ├── fromrq/           # RiceQuant instruments ETL
│   │   │   └── fromhdb/          # HDB day/min bar ETL
│   │   ├── gateways/             # Data vendor SDK wrappers
│   │   │   ├── ricequant/client.py
│   │   │   └── ifind/client.py
│   │   └── jobs/                 # Runnable orchestration jobs
│   └── tests/
├── yinhe_data_fetcher/           # AmazingData (银河证券) market data fetcher
│   ├── src/
│   │   ├── fetchers/base/        # BaseFetcher ABC, FullReplaceFetcher, IncrementalFetcher, KlineFetcher
│   │   ├── fetchers/impl/        # calendar, hist_code_list, backward_factor, kline_day/min5/min1
│   │   ├── client.py             # AmazingDataClient (login, BaseData/MarketData)
│   │   ├── runner.py             # Fetcher orchestrator
│   │   └── utils.py              # Parquet I/O, date utils, retry
│   └── tests/
├── sql/init/frontend_signal/     # PostgreSQL migration (00-14, ordered)
├── reference/                    # Design docs, API specs
└── wheel/                        # Pre-built SDK wheels (AmazingData, tgw)
```

## 4. Key Architectural Patterns

### 4.1 Fetcher Hierarchy (yinhe_data_fetcher)

```
BaseFetcher (ABC)
├── FullReplaceFetcher   # Wipe + full fetch (calendar, hist_code_list, backward_factor)
└── IncrementalFetcher   # Watermark-based delta sync
    └── KlineFetcher     # K-line specific (month-partitioned Parquet)
```

- New fetchers: create a class in `fetchers/impl/`, register in `registry.py`
- Config-driven: `config.yaml` controls which fetchers run
- Atomic Parquet writes via UUID temp file + `os.replace()`
- DuckDB merge for dedup on append, pandas fallback

### 4.2 ClickHouse Table Pattern (import_data)

- `ClickHouseTable` ABC provides: `create()`, `insert()`, `query()`, `count()`, `optimize()`, `truncate()`, `drop()`
- Table implementations (e.g., `MinBarTable`, `DayBarTable`) define: schema columns, ORDER BY, PARTITION BY, TTL, engine
- `ClickHouseClient` handles session-level: connect, execute, query, insert, upsert

### 4.3 Data Sources & Data Flow

```
AmazingData (银河)  ──> yinhe_data_fetcher ──> Parquet (local) ──> [待接入 PostgreSQL]
RiceQuant (米筐)    ──> import_data/fromrq ──> ClickHouse (rq.*)
HDB (国泰君安)      ──> import_data/fromhdb ──> ClickHouse (market_data.*)
Wind (万得)         ──> import_data/jobs ──> ClickHouse (wind.*)
AKShare (开源)      ──> import_data/akshare ──> ClickHouse
iFinD (同花顺)      ──> import_data/ifind ──> ClickHouse
```

## 5. Ingestion Design Rules

- Keep **extraction → normalization → storage** clearly separated.
- Preserve raw source meaning first. Make mapping and transformation rules explicit.
- Make **provider, dataset, date range, and timezone** explicit in code or configuration.
- Avoid silent dropping, filling, or rewriting of problematic records. Surface ambiguity instead of guessing — wrong normalization is worse than no normalization.

## 6. Data Integrity Rules

- Handle common quality issues explicitly: empty datasets, missing columns, duplicate keys, nulls, schema drift.
- Distinguish **event time** vs **publish time** vs **ingestion time** when those fields exist.
- Never mix naive and timezone-aware datetimes. All market data timestamps use `Asia/Shanghai`.
- Do not silently change units, currencies, or identifier mapping.
- Treat look-ahead leakage as a data-layer concern: when timestamps drive downstream joins, make time semantics unambiguous in column names and docs.

## 7. Storage Rules

- **PostgreSQL**: default for transactional data. Use `psycopg3` async pool + native SQL (no heavy ORM). Prefer `COPY` for bulk loads.
- **ClickHouse**: analytical queries only. No transactional updates. Use `MergeTree` engines with `PARTITION BY`, `ORDER BY`, `TTL`. All time columns use `DateTime64(3, 'Asia/Shanghai')`.
- **DuckDB**: ad-hoc / validation only. Not a persistence layer.
- **Parquet**: landing and cache format. Always `zstd` compression. Use atomic writes (temp + rename). Never commit raw CSV to the repo.

## 8. External API Rules

- Respect source rate limits, pagination, and vendor-specific error behavior.
- Wrap network and file I/O with error handling and useful logs. Do not log secrets or full payloads.
- Surface provider contract or schema changes explicitly — do not silently patch around them.
- When a vendor response shape is ambiguous, capture a small raw sample (secrets redacted) for review.

## 9. Logging & Operations

- Use the project's structured logger; no `print()`-based output.
- Logs must be sufficient to understand: what range / dataset / target was processed.
- Preserve existing alerting hooks (Feishu, WeCom, email) if present.

## 10. Agent Dispatch

| Task | Agent to route to |
|---|---|
| New ETL module, data cleaning, schema changes, fetcher implementation | `code-dev` |
| Ingestion correctness review, data integrity audit | `code-review` |
| Technical documentation, data flow docs | `writer` |

For ambiguous tasks, ask the user before dispatching.

## 11. Ask Before Proceeding

Seek explicit confirmation before:
- destructive backfills, bulk deletes, or replay jobs that overwrite published data
- changing PostgreSQL / ClickHouse schema or retention behavior
- changing identifier mapping, symbol canonicalization, timezone conventions, or adjustment logic
- switching data vendors or changing the authoritative upstream for an existing dataset
- modifying secrets handling, auth flows, request signing, or scheduled job behavior
- adding heavyweight dependencies or new infrastructure services

When asking, state: what will change, blast radius, and how to roll back.

## 12. Verification (Definition of Done)

A task is done only when, where feasible:

- [ ] targeted lint (`ruff`), type check, and test (`pytest`) pass for touched code
- [ ] dry-run or small-range import performed
- [ ] basic row-count, duplicate-key, or schema checks against target store
- [ ] downstream read sanity check against written data
- [ ] no silent semantics changes

Do not claim checks were run unless they actually were. If skipped (no network, credentials, or too expensive), state explicitly in the report.

## 13. Don'ts (铁律)

- **Don't** embed strategy logic, factor definitions, or trading decisions in ingestion code.
- **Don't** query or write to the main `getrich` project's PostgreSQL or ClickHouse databases without explicit task scope.
- **Don't** commit `.env` files, raw third-party API keys, or unredacted secrets to git.
- **Don't** use `print()` for operational logging — always use the structured logger.
- **Don't** add heavy ORMs (SQLAlchemy full ORM, Django ORM) to the dependency tree.
- **Don't** store data in CSV format for datasets > 100K rows; use Parquet (zstd).

## 14. Reporting

In the final update, state briefly:
- which datasets, providers, or job paths were affected
- what was verified (and what was not, with reason)
- whether PostgreSQL primary tables, secondary analytical stores, staging tables, or only raw/cache outputs were changed
- remaining caveats or unverified parts