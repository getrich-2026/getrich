-- 004_refresh_tokens.sql
-- Refresh token table: stores SHA-256 hashes, never raw tokens.
-- Run: psql -d getrich -f migrations/004_refresh_tokens.sql
--
-- Schema-qualified for the same reason as 003_users.sql: the backend pool
-- sets `SET search_path=app,...`; keeping the table there means the
-- migration is idempotent and works whether the runner is schema-aware or not.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.refresh_tokens (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID            NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64)     NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ     NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user
    ON app.refresh_tokens(user_id);

COMMENT ON TABLE app.refresh_tokens IS
    'Stores SHA-256 hashes of refresh tokens. Raw tokens are never persisted.';
