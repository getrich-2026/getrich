-- 011 — Promote backtest user ownership from JSONB to a real column.
--
-- Before this migration, the backtest job owner was only stored inside
-- ``backtest_jobs.request_json->>'_user_id'``. This left runs / sweeps /
-- walk-forwards without an owner field, and the JSONB lookup was
-- non-indexable. Promote it to a real ``user_id`` column on every parent
-- table, backfill from the JSONB value when present, and add a partial
-- index for the common owner-scoped query path.
--
-- Old rows with no recorded owner remain ``NULL`` and are treated as
-- "unowned / system" — they are invisible to the new owner-scoped read
-- endpoints until a separate backfill migration is written.

-- ---------------------------------------------------------------------------
-- backtest_jobs
-- ---------------------------------------------------------------------------

ALTER TABLE backtest.backtest_jobs
  ADD COLUMN IF NOT EXISTS user_id TEXT;

UPDATE backtest.backtest_jobs j
SET user_id = j.request_json->>'_user_id'
WHERE j.user_id IS NULL
  AND j.request_json ? '_user_id';

CREATE INDEX IF NOT EXISTS ix_backtest_jobs_user_id
  ON backtest.backtest_jobs (user_id)
  WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- backtest_runs
-- ---------------------------------------------------------------------------

ALTER TABLE backtest.backtest_runs
  ADD COLUMN IF NOT EXISTS user_id TEXT;

UPDATE backtest.backtest_runs r
SET user_id = j.user_id
FROM backtest.backtest_jobs j
WHERE j.ref_id = r.run_id
  AND j.job_type = 'backtest'
  AND r.user_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_backtest_runs_user_id
  ON backtest.backtest_runs (user_id)
  WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- backtest_sweeps
-- ---------------------------------------------------------------------------

ALTER TABLE backtest.backtest_sweeps
  ADD COLUMN IF NOT EXISTS user_id TEXT;

UPDATE backtest.backtest_sweeps s
SET user_id = j.user_id
FROM backtest.backtest_jobs j
WHERE j.ref_id = s.sweep_id
  AND j.job_type = 'sweep'
  AND s.user_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_backtest_sweeps_user_id
  ON backtest.backtest_sweeps (user_id)
  WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- backtest_walk_forwards
-- ---------------------------------------------------------------------------

ALTER TABLE backtest.backtest_walk_forwards
  ADD COLUMN IF NOT EXISTS user_id TEXT;

UPDATE backtest.backtest_walk_forwards w
SET user_id = j.user_id
FROM backtest.backtest_jobs j
WHERE j.ref_id = w.walk_forward_id
  AND j.job_type = 'walk_forward'
  AND w.user_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_backtest_walk_forwards_user_id
  ON backtest.backtest_walk_forwards (user_id)
  WHERE user_id IS NOT NULL;
