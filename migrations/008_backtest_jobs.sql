-- NOTE: backend pool sets `SET search_path=frontend`; tables must live in the `frontend` schema.
CREATE SCHEMA IF NOT EXISTS frontend;

-- 008_backtest_jobs.sql
-- PostgreSQL-backed backtest job tracking (P0).
-- Stores lifecycle metadata for backtest / sweep / walk_forward tasks executed by
-- the BacktestJobRunner. ClickHouse/DuckDB are intentionally not used here.
--
-- Run: psql -d getrich -f migrations/008_backtest_jobs.sql

CREATE TABLE IF NOT EXISTS frontend.backtest_jobs (
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

COMMENT ON TABLE frontend.backtest_jobs IS
    'Lifecycle tracker for long-running backtest / sweep / walk_forward jobs.';
COMMENT ON COLUMN frontend.backtest_jobs.job_type IS
    'Job category: backtest | sweep | walk_forward.';
COMMENT ON COLUMN frontend.backtest_jobs.ref_id IS
    'Associated run_id / sweep_id / walk_forward_id produced by the job.';
COMMENT ON COLUMN frontend.backtest_jobs.status IS
    'Lifecycle status: queued | running | completed | failed | cancelled.';
COMMENT ON COLUMN frontend.backtest_jobs.request_json IS
    'Immutable request snapshot serialized as JSONB. Decimal values encoded as strings.';
COMMENT ON COLUMN frontend.backtest_jobs.progress IS
    'Coarse-grained progress 0-100 reported by the runner.';

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_status_created
    ON frontend.backtest_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_type_status
    ON frontend.backtest_jobs(job_type, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_ref
    ON frontend.backtest_jobs(job_type, ref_id);
