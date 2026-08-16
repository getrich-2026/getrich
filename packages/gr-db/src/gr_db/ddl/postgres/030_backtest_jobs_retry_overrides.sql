-- 022_backtest_jobs_retry_overrides.sql
-- Per-job retry policy override columns.
--
-- Three nullable NUMERIC columns on ``backtest.backtest_jobs`` that let a
-- job request its own retry_base_seconds / retry_cap_seconds / retry_jitter_pct,
-- overriding the runner-level defaults. NULL means "use the runner default"
-- (preserves the P0 behavior for any jobs created before this migration).
--
-- Schema-qualified: the backend pool sets SET search_path=app,market,meta,public;
-- job_persistence.py references this table unprefixed.

CREATE SCHEMA IF NOT EXISTS backtest;

ALTER TABLE backtest.backtest_jobs
    ADD COLUMN IF NOT EXISTS retry_base_seconds NUMERIC,
    ADD COLUMN IF NOT EXISTS retry_cap_seconds  NUMERIC,
    ADD COLUMN IF NOT EXISTS retry_jitter_pct   NUMERIC;

COMMENT ON COLUMN backtest.backtest_jobs.retry_base_seconds IS
    'Per-job retry base interval (seconds). NULL = use runner default.';
COMMENT ON COLUMN backtest.backtest_jobs.retry_cap_seconds IS
    'Per-job retry cap interval (seconds). NULL = use runner default.';
COMMENT ON COLUMN backtest.backtest_jobs.retry_jitter_pct IS
    'Per-job retry jitter percentage (0.0..<1.0). NULL = use runner default.';
