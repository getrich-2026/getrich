-- 025_signals_reason_length.sql
--
-- Cap `signals.reason` at 2,000 chars via a Postgres CHECK constraint.
--
-- The field is plain text (algorithmic explanation produced by the
-- live signal producer — e.g. "MA(5) crossed above MA(20) with
-- Z-score 2.3"). 2,000 chars is enough for a 5-10 sentence
-- explanation; anything longer is almost certainly a bug or an
-- injection attempt.
--
-- The bound is matched by:
--   - `services/sanitize.py::MAX_REASON_LENGTH` (backend normalizer)
--   - `services/signal.py::normalize_reason()` (called on read)
--   - The frontend `SignalDetail.tsx` React text-node render (XSS-safe
--     even before the backend normalizer runs).
--
-- This is a defensive backstop: the DB will reject oversized or
-- malformed writes even if both the form and the service are bypassed.
--
-- The migration is idempotent: ``ALTER TABLE ... ADD CONSTRAINT`` is
-- wrapped in ``DO $$ ... IF NOT EXISTS`` so re-running is safe.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'signals_reason_length_chk'
          AND conrelid = 'app.signals'::regclass
    ) THEN
        ALTER TABLE app.signals
            ADD CONSTRAINT signals_reason_length_chk
            CHECK (reason IS NULL OR char_length(reason) <= 2000);
    END IF;
END
$$;

COMMENT ON CONSTRAINT signals_reason_length_chk ON app.signals IS
    'Cap signals.reason at 2000 chars (plain text). Matched by services/sanitize.py::MAX_REASON_LENGTH. P0.2 defense-in-depth (P0.2).';
