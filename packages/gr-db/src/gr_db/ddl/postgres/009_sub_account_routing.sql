-- 001_sub_account_routing.sql
-- Adds strategy-to-sub-account mapping and (optionally) account_id to
-- live_positions when that table exists.
--
-- Run: psql -d getrich -f migrations/001_sub_account_routing.sql
--
-- Schema-qualified for the same reason as 002-004: the backend pool sets
-- `SET search_path=app,...`；本表被不带前缀地查询，故放 `app`。
--
-- The `live_positions` table does not currently exist in the production
-- schema (live state is loaded via `AccountStateLoader` into in-process
-- state, not persisted in a flat table). The original migration ALTER'd
-- that table; we now guard it with a DO block so the migration remains
-- idempotent and forward-compatible — if a future migration creates
-- `live_positions`, the `account_id` column will be added automatically.
-- If the table never exists, this block is a no-op and the runner
-- progresses normally.

CREATE SCHEMA IF NOT EXISTS app;

-- Mapping table: strategy UUID → sub-account ID in live_account_state
CREATE TABLE IF NOT EXISTS app.strategy_sub_account_mapping (
    strategy_id     VARCHAR(64)  NOT NULL PRIMARY KEY,
    sub_account_id  INT          NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE app.strategy_sub_account_mapping IS
    'Maps strategy UUIDs to sub-account IDs in live_account_state.';

-- Add account_id column to live_positions for sub-account filtering.
-- Existing rows default to 1 (global account).
-- Guarded with a DO block so the migration runner doesn't hard-fail when
-- `live_positions` is absent (it currently is in production).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'app' AND table_name = 'live_positions'
    ) THEN
        ALTER TABLE app.live_positions
            ADD COLUMN IF NOT EXISTS account_id INT DEFAULT 1;

        COMMENT ON COLUMN app.live_positions.account_id IS
            'Sub-account ID linking this position row to live_account_state.id.';
    END IF;
END
$$;
