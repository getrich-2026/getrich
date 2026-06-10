# AGENTS.md

Repository-specific guidance for the `getrich-database` project.
This is the single canonical guidance file for all coding agents (Claude, Codex, Gemini, etc.).

## 1. Scope & Role

- **getrich-database** is the external **data ingestion layer** for the broader `getrich` quantitative investment platform.
- **Primary responsibilities**: provider adapters (AmazingData/银河, RiceQuant/米筐, INSIGHT/华泰), raw data capture, normalization, data quality checks, and loading curated datasets into PostgreSQL / TimescaleDB.
- **Hard boundary**: This repo is **data infrastructure only**. Do not embed factor definitions, backtest assumptions, strategy logic, or trading decisions into ingestion code. Those belong in the main `getrich` project.

## 2. Stack

| Layer | Technology | Role |
|---|---|---|
| Runtime | Python 3.10+ | Single package `getrich_data` |
| Primary DB | PostgreSQL 16 + TimescaleDB | Authoritative store (meta/market/realtime/ops/staging) |
| Landing / cache | Parquet (zstd) | raw layer output under `/opt/raw_parquet` (atomic writes) |
| Env mgmt | `uv` | `uv sync` / `uv add` / `uv run` |

> ClickHouse and DuckDB are **removed**. The platform is PostgreSQL/TimescaleDB only; parquet merge/dedup uses pandas.

## 3. Project Structure

Single package, **layer-first then provider** (see `docs/architecture.md`):

```
getrich-database/
├── src/getrich_data/
│   ├── common/         # Shared kernel: config, logging, paths, parquet, db (pool/copy),
│   │                   #   contracts (canonical columns), quality, ownership, migrate, retry
│   ├── raw/            # Download layer: vendor SDK -> /opt/raw_parquet (NO normalization)
│   │   ├── base.py     #   BaseFetcher + RawContext
│   │   ├── yinhe/      #   client.py (SDK protocol + AmazingDataClient) + fetchers/
│   │   ├── ricequant/  #   client.py (rqdatac) + fetchers/
│   │   └── insight/    #   client.py (insight_python) + fetchers/
│   ├── ingest/         # Ingest layer: parquet -> normalize -> PostgreSQL
│   │   ├── base.py     #   BaseImporter (ownership + quality + COPY upsert + etl_job_run)
│   │   ├── resolve.py  #   instrument_id resolution via symbol_map / instruments
│   │   ├── yinhe/      #   adapter.py + symbols.py + importers/
│   │   ├── ricequant/  #   adapter.py + importers/
│   │   └── insight/    #   adapter.py + importers/
│   ├── stream/         # Realtime layer: market stream -> realtime.tick_buffer
│   │   ├── base.py     #   TickEvent, CallbackBridge, BaseStreamHandler
│   │   ├── writer.py   #   PgTickWriter
│   │   ├── yinhe/  insight/   # per-provider handlers
│   └── cli.py          # `getrich raw|ingest|stream <provider>`, `db migrate|status`, `own ...`
├── db/
│   ├── ddl/            # Ordered DDL 00_extensions .. 70_ownership
│   ├── migrations/     # Incremental migrations (run after ddl)
│   └── archive/        # Old frontend/legacy SQL (read-only)
├── docs/               # Conventions, layer guides, provider notes, runbook
├── reference/          # API lists, openapi, design docs (assets, not code)
└── tests/              # common / raw (FakeSDK) / ingest (docker PG) / stream
```

## 4. Key Architectural Patterns

### 4.1 Fetcher Hierarchy (raw)

`BaseFetcher` subclasses per dataset, registered in each provider's `fetchers/__init__.py::REGISTRY`.
- Full-replace datasets (calendar, instruments, hist_code_list, backward_factor): overwrite each run.
- Incremental K-line: read local watermark from latest month-partition, fetch delta, dedup-append by code+month.
- SDK access is behind a **client protocol** (dependency-injected) so tests use a Fake without real SDK/network.
- Atomic Parquet writes via UUID temp + `os.replace()`; pandas merge for append dedup (`keep='last'`, new wins).

### 4.2 Importer Pattern (ingest)

`BaseImporter.run()` (single transaction): claim ownership → `build()` (read raw + normalize to canonical) →
quality check → `upsert_rows` (temp table + COPY + ON CONFLICT) → record `ops.etl_job_run`.
Canonical columns live in `common/contracts` and must stay aligned with `db/ddl`.

### 4.3 Provider Ownership (single source per table)

**A target table is written by exactly one provider.** Enforced via `ops.table_ownership` and
`common/ownership.py::OwnershipManager`, checked before every ingest/stream write. Transfer requires
explicit `force`/`release`. See `docs/conventions/provider-ownership.md`.

### 4.4 Data Sources & Data Flow

```
AmazingData (银河) ──> raw/yinhe     ──> /opt/raw_parquet/yinhe/*     ──> ingest/yinhe     ──> PostgreSQL
RiceQuant (米筐)   ──> raw/ricequant ──> /opt/raw_parquet/ricequant/* ──> ingest/ricequant ──> PostgreSQL
INSIGHT (华泰)     ──> raw/insight   ──> /opt/raw_parquet/insight/*   ──> ingest/insight   ──> PostgreSQL
INSIGHT / 银河 实时 ──> stream/<provider> ───────────────────────────────────────────────> realtime.tick_buffer
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

- **PostgreSQL / TimescaleDB**: the only authoritative store. Use `psycopg3` + native SQL (no heavy ORM). Bulk loads via `COPY` into a temp table then `INSERT ... ON CONFLICT` (see `common/db/copy.py`). Minute/realtime time columns are `TIMESTAMPTZ`; use TimescaleDB hypertables/compression as defined in `db/ddl`.
- **Parquet**: raw landing/cache format under `/opt/raw_parquet`. Always `zstd`, atomic writes (temp + rename). Merge/dedup on append uses pandas. Never commit data to the repo.

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

## 15. Iteration Log (MANDATORY)

**Every iteration MUST append an entry to [ITER.md](ITER.md) — this is not optional.**
Before reporting an iteration as done, write the log entry. No entry = iteration incomplete.

- Newest entry on top.
- Heading format (precise to the minute, local time Asia/Shanghai):
  `## YYYY-MM-DD HH:MM — <事件标题>`
  e.g. `## 2026-06-10 19:32 — 移除 DuckDB，parquet 改用 pandas 合并`
- Body: keep concise — background, what changed, what was verified (and what was not, with reason).
- One entry per iteration; do not retroactively rewrite past entries (append a new one instead).