-- 023_backtest_jobs_request_hash.sql
-- P2+: store a deterministic sha256 of the canonical request payload so the
-- API layer can detect "same Idempotency-Key + different body" and return 409.
--
-- The canonical form is the output of ``body.model_dump(mode="json")`` with
-- server-stamped keys (``_idempotency_key``, legacy ``_user_id``) removed,
-- serialized via ``json.dumps(..., sort_keys=True, separators=(",",":"))``
-- and hashed with sha256 (hex). Storing the hash as a real column makes the
-- comparison O(1) and keeps the existing JSONB ``_idempotency_key`` lookup
-- path working unchanged. NULL = "row predates this migration" (legacy); the
-- service treats NULL as a permissive match to avoid breaking in-flight
-- idempotency keys at the cutover boundary.

CREATE SCHEMA IF NOT EXISTS frontend;

ALTER TABLE frontend.backtest_jobs
    ADD COLUMN IF NOT EXISTS request_hash CHAR(64);

COMMENT ON COLUMN frontend.backtest_jobs.request_hash IS
    'sha256-hex of the canonical request payload (idempotency-key + _user_id '
    'excluded). NULL for rows created before migration 023 — service treats '
    'NULL as permissive match (return existing).';

-- Hot path: (idempotency key, request hash) equality.
-- Partial index keeps size bounded — only rows that actually carry an
-- idempotency key are indexed; the legacy-NULL rows live in a separate
-- fallback path.
CREATE INDEX IF NOT EXISTS idx_backtest_jobs_idemkey_hash
    ON frontend.backtest_jobs (
        (request_json->>'_idempotency_key'),
        request_hash
    )
    WHERE request_json->>'_idempotency_key' IS NOT NULL;
