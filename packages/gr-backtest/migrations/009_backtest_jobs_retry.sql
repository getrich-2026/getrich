-- 009_backtest_jobs_retry.sql
-- P1 retry / backoff columns for backtest_jobs.
-- Adds attempt counter, max_attempts ceiling, and next_retry_at scheduling
-- timestamp so the runner can claim only jobs whose backoff window has
-- expired.
--
-- Run: psql -d getrich -f migrations/009_backtest_jobs_retry.sql

ALTER TABLE frontend.backtest_jobs
    ADD COLUMN IF NOT EXISTS attempt INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS max_attempts INT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

-- Claim 过滤器：next_retry_at 已到期（或 NULL）才可被 claim。
-- 部分索引仅覆盖 queued 行，避免 bloat 增长。
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_claim
    ON frontend.backtest_jobs(job_type, status, next_retry_at NULLS FIRST, created_at)
    WHERE status = 'queued';

COMMENT ON COLUMN frontend.backtest_jobs.attempt IS
    'Current attempt number (1-indexed). Increments on each retry.';
COMMENT ON COLUMN frontend.backtest_jobs.max_attempts IS
    'Max retry attempts; default 1 means no retry.';
COMMENT ON COLUMN frontend.backtest_jobs.next_retry_at IS
    'Earliest claim time after a retryable failure; NULL means immediately claimable.';
