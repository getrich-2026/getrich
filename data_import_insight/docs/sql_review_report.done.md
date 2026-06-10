# Database Schema & Performance Optimization Report: Backend SQL

- **Date**: 2026-06-04
- **Scope**: Backend SQL schema definitions in `/home/quant/project/getrich-database/getrich_data_import/sql/init/backend/`
  - `00_extensions.sql`
  - `10_meta.sql`
  - `20_market.sql`
  - `30_compress_ca.sql`
  - `40_realtime.sql`
  - `50_ops.sql`
- **Focus**: PostgreSQL 16 compliance, TimescaleDB hypertable optimization, compression configurations, continuous aggregate accuracy, constraints, index coverage, and general best practices.

---

## Executive Summary

The SQL schema definitions for the `getrich` platform's ingestion backend are well-structured, utilizing distinct schemas (`meta`, `market`, `realtime`, `ops`) and adopting sensible data types (e.g. `NUMERIC` for price columns to avoid floating-point drift). 

However, several critical issues and optimization opportunities were identified:
1. 🔴 **Continuous Aggregate View Syntax Errors**: The views in `30_compress_ca.sql` attempt to group by `trading_day` rather than a `time_bucket()` expression. This causes TimescaleDB to throw errors during execution, forcing a silent fallback to **regular materialized views**. This defeats the purpose of continuous aggregates (no incremental updates, no real-time query support).
2. 🔴 **Missing Stock & ETF Minute Compression**: Compression configurations in `30_compress_ca.sql` omit `market.stock_bar_1m` and `market.etf_bar_1m`—the two largest tables in the database. Omitting them leads to massive storage waste and performance bottlenecks.
3. 🟠 **Missing Continuous Aggregate Refresh Policies**: The continuous aggregates are created `WITH NO DATA` but have no scheduler policies attached, meaning they will remain empty unless manually populated.
4. 🟡 **Redundant Indexing**: `meta.symbol_map` contains a redundant index on `instrument_id` because it is already the prefix of a unique constraint index.
5. 🟡 **Missing Foreign Key Indexes**: Crucial foreign keys like `underlying_id` in `meta.option_contracts` and `user_id` in `ops.api_keys` lack index coverage, risking sequential scans during common queries.

---

## Detailed Findings & Recommendations

### 1. `00_extensions.sql`
* **Status**: ✅ **Good**
* **Analysis**: Properly installs `timescaledb` extension and boots the database schemas.

---

### 2. `10_meta.sql` (Metadata Layer)

#### A. Redundant Index on `meta.symbol_map`
* **Issue**: The table `meta.symbol_map` contains `UNIQUE (instrument_id, source)`, which implicitly creates a unique B-Tree index on `(instrument_id, source)`. Because `instrument_id` is the leading prefix, PostgreSQL can use this index for any query filtering by `instrument_id`. Therefore, `idx_symbol_map_instrument` on `(instrument_id)` is redundant.
* **Proposed Diff**:
```diff
-CREATE INDEX IF NOT EXISTS idx_symbol_map_instrument
-    ON meta.symbol_map (instrument_id);
```

#### B. Missing Index on Options `underlying_id`
* **Issue**: Option contracts are frequently queried or joined by their underlying asset (`underlying_id`). Foreign keys are not indexed by default in PostgreSQL.
* **Proposed Diff**:
```diff
+CREATE INDEX IF NOT EXISTS idx_option_contracts_underlying
+    ON meta.option_contracts (underlying_id);
```

#### C. Calendar Self-Referencing Constraints & Exchange Check
* **Issue**: `prev_trading_day` and `next_trading_day` lack referential integrity constraints, meaning invalid dates can be written. Also, `exchange` has no blank check constraint.
* **Proposed Diff**:
```diff
 CREATE TABLE IF NOT EXISTS meta.trading_calendar (
     exchange          VARCHAR(16) NOT NULL,
     trading_day       DATE NOT NULL,
     is_open           BOOLEAN NOT NULL DEFAULT true,
     has_night         BOOLEAN NOT NULL DEFAULT false,
     prev_trading_day  DATE,
     next_trading_day  DATE,
     updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
     PRIMARY KEY (exchange, trading_day),
+    CONSTRAINT chk_calendar_exchange_not_blank
+        CHECK (btrim(exchange) <> ''),
     CONSTRAINT chk_calendar_prev_before
         CHECK (prev_trading_day IS NULL OR prev_trading_day < trading_day),
-    CONSTRAINT chk_calendar_next_after
-        CHECK (next_trading_day IS NULL OR next_trading_day > trading_day)
+    CONSTRAINT chk_calendar_next_after
+        CHECK (next_trading_day IS NULL OR next_trading_day > trading_day),
+    CONSTRAINT fk_calendar_prev
+        FOREIGN KEY (exchange, prev_trading_day) REFERENCES meta.trading_calendar(exchange, trading_day) ON DELETE SET NULL,
+    CONSTRAINT fk_calendar_next
+        FOREIGN KEY (exchange, next_trading_day) REFERENCES meta.trading_calendar(exchange, trading_day) ON DELETE SET NULL
 );
```

#### D. Auto-Updating `updated_at` Columns
* **Issue**: `updated_at` columns default to `now()` but are never updated during rows modifications unless manually specified.
* **Proposed Change**: Define a trigger helper and apply it to metadata tables:
```sql
CREATE OR REPLACE FUNCTION meta.trg_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_instruments_update BEFORE UPDATE ON meta.instruments
    FOR EACH ROW EXECUTE FUNCTION meta.trg_update_timestamp();

CREATE TRIGGER trg_symbol_map_update BEFORE UPDATE ON meta.symbol_map
    FOR EACH ROW EXECUTE FUNCTION meta.trg_update_timestamp();

CREATE TRIGGER trg_trading_calendar_update BEFORE UPDATE ON meta.trading_calendar
    FOR EACH ROW EXECUTE FUNCTION meta.trg_update_timestamp();
```

#### E. Standardizing PK Columns (Optional)
* **Optimization**: Modern PostgreSQL recommends `GENERATED BY DEFAULT AS IDENTITY` instead of `BIGSERIAL` for primary keys.
```diff
-    instrument_id BIGSERIAL PRIMARY KEY,
+    instrument_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
```

---

### 3. `20_market.sql` (Historical Market Facts)

#### A. Cross-Sectional Query Indexing
* **Issue**: The primary key on the hypertables is `(instrument_id, dt)`. This is perfect for time-series queries of a single instrument. However, for cross-sectional queries (e.g. fetching all stocks for a specific date/time), searching by `dt` or `trading_day` will be slow. Within each chunk, PostgreSQL must perform a sequential scan.
* **Optimization**: Since minute data is inserted chronologically, `dt` is highly ordered. A BRIN index on `dt` or a B-Tree index on `(dt, instrument_id)` should be added for 1m tables to support high-performance cross-sectional queries.
* **Proposed Diff**:
```diff
+CREATE INDEX IF NOT EXISTS idx_stock_bar_1m_dt ON market.stock_bar_1m USING brin (dt);
+CREATE INDEX IF NOT EXISTS idx_etf_bar_1m_dt ON market.etf_bar_1m USING brin (dt);
```

---

### 4. `30_compress_ca.sql` (TimescaleDB Compression & Aggregations)

#### A. [CRITICAL] Fix Continuous Aggregate Views
* **Issue**: Under TimescaleDB, a continuous aggregate **must** group by a `time_bucket()` expression referencing the partition time column (`dt`). Grouping by `trading_day` causes a syntax error. Although the exception handler falls back to a normal materialized view, the view loses all continuous aggregate benefits (real-time query support, incremental background updates).
* **Fix**: Include `time_bucket(INTERVAL '1 day', dt)` in the continuous aggregate SELECT and GROUP BY clauses. TimescaleDB 2.0+ allows additional columns in GROUP BY.
* **Proposed Code Examples**:

##### Index 1D Continuous Aggregate:
```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS market.index_bar_1d_ca
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket(INTERVAL '1 day', dt) AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount
FROM market.index_bar_1m
GROUP BY instrument_id, time_bucket(INTERVAL '1 day', dt), trading_day
WITH NO DATA;
```

##### Future 1D Continuous Aggregate:
```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS market.future_bar_1d_ca
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket(INTERVAL '1 day', dt) AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount,
       last(open_interest, dt) AS open_interest
FROM market.future_bar_1m
GROUP BY instrument_id, time_bucket(INTERVAL '1 day', dt), trading_day
WITH NO DATA;
```

##### Option 1D Continuous Aggregate:
```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS market.option_bar_1d_ca
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket(INTERVAL '1 day', dt) AS bucket_day,
       trading_day,
       first(open, dt) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, dt) AS close,
       sum(volume) AS volume,
       sum(amount) AS amount,
       last(open_interest, dt) AS open_interest
FROM market.option_bar_1m
GROUP BY instrument_id, time_bucket(INTERVAL '1 day', dt), trading_day
WITH NO DATA;
```

#### B. [CRITICAL] Add Compression Settings for Stocks and ETFs
* **Issue**: Stock and ETF minute bar tables (`market.stock_bar_1m` and `market.etf_bar_1m`) represent 90%+ of total data volume, but are completely omitted from the compression definitions in this file.
* **Fix**: Apply TimescaleDB compression parameters and policies to them.
* **Proposed Code Snippets**:
```sql
DO $$
BEGIN
    ALTER TABLE market.stock_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.stock_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.stock_bar_1m: %', SQLERRM;
END $$;

DO $$
BEGIN
    ALTER TABLE market.etf_bar_1m SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'instrument_id',
        timescaledb.compress_orderby = 'dt DESC'
    );
    PERFORM add_compression_policy('market.etf_bar_1m', INTERVAL '7 days', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping compression for market.etf_bar_1m: %', SQLERRM;
END $$;
```

#### C. Add Continuous Aggregate Refresh Policies
* **Issue**: The three continuous aggregate views are created `WITH NO DATA`. Without scheduling policies, they will never be populated.
* **Fix**: Define automated refresh policies.
* **Proposed Code Snippet**:
```sql
SELECT add_continuous_aggregate_policy('market.index_bar_1d_ca',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('market.future_bar_1d_ca',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('market.option_bar_1d_ca',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);
```

---

### 5. `40_realtime.sql` (Realtime Buffer)

#### A. Enable Compression on Tick Buffer
* **Issue**: Tick-level data is highly voluminous. The retention policy keeps the past 7 days of ticks. Since real-time writing only targets the current trading day, chunks older than 2 days are read-only and prime candidates for compression.
* **Optimization**: Enable compression on `realtime.tick_buffer` with a policy to compress chunks older than 2 days. This saves up to 80% storage on the remaining 5 days of tick data.
* **Proposed Diff**:
```diff
 SELECT create_hypertable('realtime.tick_buffer', 'dt', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
+
+DO $$
+BEGIN
+    ALTER TABLE realtime.tick_buffer SET (
+        timescaledb.compress,
+        timescaledb.compress_segmentby = 'instrument_id',
+        timescaledb.compress_orderby = 'dt DESC'
+    );
+    PERFORM add_compression_policy('realtime.tick_buffer', INTERVAL '2 days', if_not_exists => TRUE);
+EXCEPTION WHEN OTHERS THEN
+    RAISE NOTICE 'Skipping compression for realtime.tick_buffer: %', SQLERRM;
+END $$;
```

---

### 6. `50_ops.sql` (Operations & Quality Control)

#### A. Unique Constraint and Indexing on API Keys
* **Issue**: `api_key_hash` in `ops.api_keys` lacks a unique constraint. Duplicate hashes could lead to authorization ambiguity. Also, `user_id` lacks an index.
* **Proposed Diff**:
```diff
 CREATE TABLE IF NOT EXISTS ops.api_keys (
     key_id       BIGSERIAL PRIMARY KEY,
-    user_id      BIGINT REFERENCES ops.users(user_id),
-    api_key_hash VARCHAR(128) NOT NULL,
+    user_id      BIGINT REFERENCES ops.users(user_id) ON DELETE CASCADE,
+    api_key_hash VARCHAR(128) UNIQUE NOT NULL,
     scopes       TEXT[],
     rate_limit   INT NOT NULL DEFAULT 600,
     expires_at   TIMESTAMPTZ,
     revoked      BOOLEAN NOT NULL DEFAULT false,
     created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
  );
+
+CREATE INDEX IF NOT EXISTS idx_api_keys_user_id
+    ON ops.api_keys (user_id);
```

#### B. ETL Job Run Chronology Constraint
* **Issue**: Job run records should enforce that `finished_at` occurs after `started_at`.
* **Proposed Diff**:
```diff
 CREATE TABLE IF NOT EXISTS ops.etl_job_run (
     run_id       BIGSERIAL PRIMARY KEY,
     job_name     VARCHAR(64) NOT NULL,
     trading_day  DATE,
     asset        VARCHAR(16),
     freq         VARCHAR(8),
     status       VARCHAR(16) NOT NULL,
     rows_written BIGINT NOT NULL DEFAULT 0,
     started_at   TIMESTAMPTZ,
     finished_at  TIMESTAMPTZ,
     error        TEXT,
-    CONSTRAINT chk_etl_job_status CHECK (status IN ('running', 'success', 'failed', 'partial'))
+    CONSTRAINT chk_etl_job_status CHECK (status IN ('running', 'success', 'failed', 'partial')),
+    CONSTRAINT chk_etl_job_run_timestamps CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
 );
```

#### C. GIN Index on Data Quality Detail
* **Issue**: The `detail` column in `ops.data_quality_check` is type `JSONB`. If the operations dashboard or alerts frequently query this column using JSON path operations, it will result in table scans.
* **Proposed Diff**:
```diff
  CREATE INDEX IF NOT EXISTS idx_quality_run_severity
      ON ops.data_quality_check (run_id, severity);
+
+CREATE INDEX IF NOT EXISTS idx_quality_check_detail
+    ON ops.data_quality_check USING gin (detail);
```
