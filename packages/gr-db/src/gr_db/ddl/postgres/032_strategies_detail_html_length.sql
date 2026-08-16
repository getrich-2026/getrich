-- 024_strategies_detail_html_length.sql
-- Cap the user-supplied `strategies.detail_html` column at 50,000 chars
-- and pre-flight truncate any existing rows that exceed the limit.
--
-- Rationale: this is the **last** of three layers of XSS defense on
-- `strategies.detail_html`:
--   1. Form layer       — `frontend/src/pages/StrategyEdit.tsx` rejects
--                          >50K char inputs via zod `.max(50_000)`.
--   2. Pydantic layer   — `apps/web/routers/strategies.py` rejects via
--                          `Field(None, max_length=50_000)`.
--   3. Service layer    — `apps/web/services/sanitize.py` runs bleach.
--   4. **Schema (this)** — Postgres `CHECK` constraint. Even if a
--                          direct INSERT/UPDATE bypasses the API, the DB
--                          will refuse to store more than 50K chars.
--
-- The precheck + RAISE NOTICE keeps prod rollouts observable: a row
-- that was somehow written outside the API (e.g. a one-off psql
-- script) will be auto-truncated to the limit and a NOTICE will
-- surface the count, instead of failing the migration.

CREATE SCHEMA IF NOT EXISTS app;

-- Precheck: log any overlong rows, then truncate them. Idempotent.
DO $$
DECLARE
    overlong_count INT;
BEGIN
    SELECT COUNT(*) INTO overlong_count
      FROM app.strategies
     WHERE detail_html IS NOT NULL
       AND char_length(detail_html) > 50000;

    IF overlong_count > 0 THEN
        RAISE NOTICE 'detail_html length: truncating % strategies row(s) over 50K chars',
            overlong_count;
        UPDATE app.strategies
           SET detail_html = LEFT(detail_html, 50000)
         WHERE detail_html IS NOT NULL
           AND char_length(detail_html) > 50000;
    ELSE
        RAISE NOTICE 'detail_html length: no overlong rows found, constraint applied cleanly';
    END IF;
END $$;

-- Constraint: refuse inserts/updates with detail_html > 50K chars. The
-- DO block swallows `duplicate_object` so re-running the migration is
-- a no-op (matching the pattern in 011/012/013/etc.).
DO $$
BEGIN
    ALTER TABLE app.strategies
        ADD CONSTRAINT strategies_detail_html_length_chk
        CHECK (detail_html IS NULL OR char_length(detail_html) <= 50000);
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END $$;

COMMENT ON CONSTRAINT strategies_detail_html_length_chk ON app.strategies IS
    'detail_html is capped at 50,000 chars to match the Pydantic max_length in routers/strategies.py, the bleach truncation in services/sanitize.py, and the frontend zod schema in StrategyEdit.tsx. See .agent/brain/NOTES.md round 1011 (Stored XSS hardening).';
