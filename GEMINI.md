# GEMINI.md (getrich-database)

This is the project-specific guidance for `getrich-database`. It supplements the global `GEMINI.md` and focuses on the unique requirements of the data ingestion and normalization layer.

## Scope & Role

- **Positioning**: This repository is the external data ingestion layer for the `getrich` ecosystem.
- **Core Duties**: Handling provider adapters, raw data capture, normalization, and quality checks.
- **Logic Separation**: Keep this repo focused on **data infrastructure**. Strategy logic, factor definitions, or trading decisions must not be embedded here.

## Technical Stack & Environment

- **Runtime**: Python 3.10+.
- **Environment**: Optimized for **Ubuntu** and **Docker**.
- **Primary Database**: **PostgreSQL** (default for curated datasets).
- **Secondary Stores**: **ClickHouse** and **DuckDB** for analytics, minute-level market data performance, and local validation.
- **Storage**: Use **Parquet** for landing or caching layers.
- **Package Management**:
  - Always use `uv`.
  - Prefer `uv sync` for setup and `uv add` for dependencies.
  - Only use `uv pip` when strictly required by the specific project environment.

## Data Integrity & Design Rules

- **Time Precision**: Explicitly distinguish between event time, publish time, and ingestion time.
- **Timezone Safety**: Never mix naive and timezone-aware datetimes.
- **Normalization**:
  - Keep source extraction and storage logic separate.
  - Maintain explicit mapping for units, currencies, and identifiers.
  - Avoid silent data manipulation; failures like empty datasets or schema drifts must be handled explicitly.
- **Documentation**: All technical artifacts, schemas, and logs must be in **English**.

## Safety & Destructive Operations

**Always ask for explicit confirmation before:**
- Performing destructive backfills, bulk deletes, or data replays.
- Modifying PostgreSQL or ClickHouse schemas/retention policies.
- Changing authoritative data sources or vendor connectors.
- Altering secrets handling or authentication flows.

## Verification (Definition of Done)

A task is considered complete only after:
1. **Checks**: Relevant linters, type checks, and targeted tests have passed.
2. **Dry-runs**: A small-range import or dry-run has been performed to verify ingestion logic.
3. **Data Sanity**: Row counts, duplicate keys, and schema consistency are verified against the target store.
4. **Visibility**: Operations are logged via the project's structured logger (no `print` statements).

## Reporting Structure

When reporting completion, follow this concise format:
1. **Scope**: Which datasets, providers, or paths were affected.
2. **Verification**: Summary of checks performed (e.g., row counts, schema validation).
3. **Storage Impact**: Specify if changes affected PostgreSQL (primary), ClickHouse (analytical), or only staging/cache.
4. **Caveats**: Any unverified parts or potential risks.