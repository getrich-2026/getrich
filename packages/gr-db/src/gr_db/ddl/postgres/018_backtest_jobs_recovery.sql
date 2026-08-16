-- Migration 010 — Backtest Job Stuck-Running Recovery (P2)
--
-- Adds a partial index that supports the "stuck-running recovery" branch
-- of ``claim_next_queued``. The recovery branch picks up ``running`` rows
-- whose ``updated_at`` is older than the stale-recovery threshold and
-- re-claims them. Without this index the recovery scan would fall back
-- to a sequential scan of all ``running`` rows, which is fine for a
-- small backlog but expensive at scale.
--
-- The index is partial on ``status = 'running'`` so it stays tiny
-- (only currently-running jobs are indexed) and is used exclusively
-- by the recovery branch.

CREATE INDEX IF NOT EXISTS idx_backtest_jobs_running_recovery
    ON backtest.backtest_jobs(job_type, status, updated_at)
    WHERE status = 'running';

COMMENT ON INDEX backtest.idx_backtest_jobs_running_recovery IS
    'Supports claim_next_queued''s stuck-running recovery branch (P2 #311).'
