-- NOTE: backend pool sets `SET search_path=app,market,meta,public`; 本文件的表全部放 `backtest` schema，SQL 里显式写 `backtest.` 前缀。
CREATE SCHEMA IF NOT EXISTS backtest;

-- 008_backtest_jobs.sql
-- PostgreSQL-backed backtest job tracking (P0).
-- Stores lifecycle metadata for backtest / sweep / walk_forward tasks executed by
-- the BacktestJobRunner. ClickHouse/DuckDB are intentionally not used here.
--
-- Run: psql -d getrich -f migrations/008_backtest_jobs.sql

CREATE TABLE IF NOT EXISTS backtest.backtest_jobs (
    job_id          VARCHAR(64)     PRIMARY KEY,
    job_type        VARCHAR(16)     NOT NULL,
    ref_id          VARCHAR(128)    NOT NULL,
    status          VARCHAR(16)     NOT NULL DEFAULT 'queued',
    request_json    JSONB           NOT NULL DEFAULT '{}'::jsonb,
    progress        INT             NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE backtest.backtest_jobs IS
    'Lifecycle tracker for long-running backtest / sweep / walk_forward jobs.';
COMMENT ON COLUMN backtest.backtest_jobs.job_type IS
    'Job category: backtest | sweep | walk_forward.';
COMMENT ON COLUMN backtest.backtest_jobs.ref_id IS
    'Associated run_id / sweep_id / walk_forward_id produced by the job.';
COMMENT ON COLUMN backtest.backtest_jobs.status IS
    'Lifecycle status: queued | running | completed | failed | cancelled.';
COMMENT ON COLUMN backtest.backtest_jobs.request_json IS
    'Immutable request snapshot serialized as JSONB. Decimal values encoded as strings.';
COMMENT ON COLUMN backtest.backtest_jobs.progress IS
    'Coarse-grained progress 0-100 reported by the runner.';

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_status_created
    ON backtest.backtest_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_type_status
    ON backtest.backtest_jobs(job_type, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_ref
    ON backtest.backtest_jobs(job_type, ref_id);
