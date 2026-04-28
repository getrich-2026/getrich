# AGENTS.md

Repository-specific guidance for the `getrich-database` project.
This file supplements the global guidance in `~/.codex/AGENTS.md`.

## Scope

- `getrich-database` is the external data ingestion layer for the broader `getrich` stack.
- Primary responsibilities: provider adapters, raw data capture, normalization, data quality checks, backfill/replay jobs, and loading curated datasets into PostgreSQL, with ClickHouse, DuckDB, or file-based outputs used as secondary paths when needed.
- Treat this repository as data infrastructure, not strategy logic. Do not embed factor definitions, backtest assumptions, or trading decisions into ingestion code.

## Stack

- Python 3.10+
- PostgreSQL
- ClickHouse
- DuckDB
- Parquet
- Bash
- `uv` for environment and command execution

## Workflow defaults

- Prefer `uv sync` for environment setup and dependency sync.
- Prefer `uv add` for adding or updating external Python packages.
- Avoid `uv pip` unless `uv add` is not suitable for the task.
- Prefer `uv run` for repository commands.
- Keep code, schema names, logs, and technical docs in English.

## Ingestion design rules

- Keep source extraction, normalization, and storage logic reasonably clear and separated.
- Preserve raw source meaning first. Make important mapping and transformation rules explicit.
- Make provider, dataset, date range, and timezone explicit in code or configuration when relevant.
- Avoid silent dropping, filling, or rewriting of problematic records without a clear rule.

## Data integrity rules

- Handle common data-quality issues explicitly, especially empty datasets, missing columns, duplicate keys, nulls, and schema drift.
- Distinguish clearly between source event time, publish time, and ingestion time when those fields exist.
- Never mix naive and timezone-aware datetimes.
- Do not silently change units, currencies, or identifier mapping logic.

## PostgreSQL, ClickHouse, DuckDB, and storage rules

- PostgreSQL is the default primary database unless the task explicitly says otherwise.
- ClickHouse and DuckDB are secondary tools for analytics, local validation, or special workloads.
- Be explicit about target database, schema, table names, keys, and dedup/upsert behavior before changing load logic.
- Do not change schema or retention behavior unless the task explicitly requires it.
- Use Parquet as a cache or landing format when it is useful.

## External API and connector rules

- Respect source rate limits, pagination, and vendor-specific error behavior.
- Wrap network and file I/O with basic error handling and useful logs.
- Do not log secrets or full sensitive payloads.
- Surface provider contract or schema changes explicitly instead of silently patching around them.

## Logging and operations

- Use the project's structured logger; do not add `print()`-based operational output.
- Keep logs sufficient to understand what range, dataset, and target were processed.
- Preserve existing alerting hooks such as Feishu, WeCom, or email if the repository already uses them.

## Ask before proceeding

Seek explicit confirmation before:

- destructive backfills, bulk deletes, or replay jobs that can overwrite published data
- changing PostgreSQL or ClickHouse schema or retention behavior
- changing identifier mapping, symbol canonicalization, timezone conventions, or adjustment logic
- switching data vendors or changing the authoritative upstream source for an existing dataset
- modifying secrets handling, auth flows, request signing, or scheduled job behavior
- adding heavyweight dependencies or new infrastructure services

## Verification

Before marking a task complete, do the relevant checks that are feasible:

- targeted lint, type, and test checks that match the touched code
- a dry-run or small-range import when possible
- basic row-count, duplicate-key, or schema checks when relevant
- a downstream read sanity check against written data when relevant

Prefer focused verification on the affected dataset and job path.

Do not claim imports or checks were run unless they actually were.

## Done means

A task is done only when, where feasible:

- the requested ingestion or data-pipeline change is implemented
- data semantics are not silently changed
- relevant validation or dry-runs were performed
- the result is easy to review and roll back

## Reporting

In the final update, state briefly:

- which datasets, providers, or job paths were affected
- what was verified
- whether PostgreSQL primary tables, secondary analytical stores, staging tables, or only raw/cache outputs were changed
- remaining caveats or unverified parts
