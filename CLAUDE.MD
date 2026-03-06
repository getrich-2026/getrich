# GetRich System-Level AI Standards

## 1. Role Definition

**Role**: Expert Quant Developer (Neo) & Financial Data Engineer.
**Goal**: Build high-performance, production-grade high-frequency factor research & backtesting systems.

---

## 2. Tech Stack Preferences

getrich has the following **strong preferences** on top of global standards:

- **Data Processing Priority**: `polars` (Preferred) > `numpy` vectorized > `numba.jit` > `pandas` (only for ETL/Compat).
- **Storage Format**: `parquet` (local cache) + `ClickHouse` (core database).
- **Database Driver**: `clickhouse-connect`.

---

## 3. Domain Rules (getrich-specific)

### 3.1 Timezone Hardcoding

- **Unified Timezone**: `Asia/Shanghai (UTC+8)` via `zoneinfo` or `pytz`.
- **ClickHouse Mapping**:
  - `DateTime64(n, 'Asia/Shanghai')` → aware `datetime`, use directly.
  - `Date` / `Date32` → naive `datetime.date`. **Must** call `.astimezone(tz).date()` before writing to avoid implicit UTC shifts.
  - Night session data (e.g., 23:00–02:30) must use `DateTime64`, never `Date`.

### 3.2 Naming Conventions

- Standard column names: `open, high, low, close, volume, vwap, oi, symbol, dt`.
- Use these names consistently — no ad-hoc abbreviations or variants.

### 3.3 Financial Math

- **Scalar monetary/PnL calculations**: Use `decimal.Decimal`.
- **Returns**: Strictly distinguish `log-return` vs `simple-return`; label explicitly in function names and docstrings.

### 3.4 Pre-trade Risk Checks

- Execution logic **must** include: price band validation, max order size limit, liquidity constraints.

### 3.5 Pandas Safety Rules (when used)

- Verify `df.index` alignment after joins.
- Detect gaps via `.diff()`.
- Use `.loc` / `.iloc` exclusively to avoid `SettingWithCopyWarning`.

---

## 4. ClickHouse Infrastructure

### 4.1 Engine & Schema Template

```sql
CREATE TABLE {table_name} (
    dt DateTime64(3, 'Asia/Shanghai'),
    symbol LowCardinality(String),
    price Float64 CODEC(ZSTD(1)),
    vol Float64 CODEC(ZSTD(1))
) ENGINE = MergeTree()          -- or ReplacingMergeTree for states
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
TTL dt + INTERVAL 5 YEAR;
```

### 4.2 Mandatory Requirements

- Persistent tables: `MergeTree` family engines **only**.
- Every table must include: `PARTITION BY`, `ORDER BY`, `TTL`.
- Numeric columns must use `CODEC(ZSTD(1))`.
- Symbol fields must use `LowCardinality(String)`.

---

## 5. Project Structure

```text
getrich/
├── src/getrich/
│   ├── apps/
│   │   ├── data/       # ETL, API Wrappers (ricequant, ifind), Schemas, Jobs
│   │   ├── gateway/    # Trade execution (CTP etc.)
│   │   ├── strategy/   # Strategy logic
│   │   └── web/        # Web services
│   ├── config/         # Settings, Constants
│   ├── libs/           # Common utilities (ClickHouse pools, helpers)
│   └── optionLib/      # Options pricing & risk (Greeks, IV surface)
├── tests/
└── local_packages/
```

### Module Boundaries

- `apps/data/`: All data fetching, cleaning, and ingestion. Strategy layer must never call external APIs directly.
- `apps/gateway/`: Broker adapter layer with standardized trade interfaces.
- `apps/strategy/`: Pure strategy logic; parameters injected via config.
- `libs/`: Cross-module reusable utilities and connection pool management.
- `optionLib/`: Options pricing and risk measurement, independent of strategy layer.

---

## 6. Commands

```bash
pytest tests/ -v | ruff format src/ | ruff check src/ --fix | pip install -e .
```
