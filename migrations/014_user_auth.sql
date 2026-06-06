-- 014_user_auth.sql
-- Multi-provider authentication table — one row per auth method per user.
--
-- This table already exists in production (created outside the migration
-- runner) but has no migration file — a fresh environment would fail
-- because routers/auth.py now queries it as the primary auth source.
--
-- Production schema (discovered 2026-06-04):
--   id          BIGSERIAL   PK
--   user_id     UUID        NOT NULL  → FK to users.id
--   auth_type   VARCHAR(32) NOT NULL  → 'email' | 'phone' | 'wechat' | etc.
--   identifier  VARCHAR(255) NOT NULL → email address or phone number
--   credential  TEXT                  → bcrypt hash (NULL for OAuth-only)
--   verified    BOOLEAN     NOT NULL DEFAULT FALSE
--   created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
--   UNIQUE (auth_type, identifier)
--
-- Schema-qualified: the backend pool sets SET search_path=frontend;
-- routers/auth.py references the table unprefixed, so it must live in
-- the frontend schema.

CREATE SCHEMA IF NOT EXISTS frontend;

CREATE TABLE IF NOT EXISTS frontend.user_auth (
    id          BIGSERIAL       PRIMARY KEY,
    user_id     UUID            NOT NULL,       -- FK to users.id
    auth_type   VARCHAR(32)     NOT NULL,       -- 'email' | 'phone' | 'wechat' | etc.
    identifier  VARCHAR(255)    NOT NULL,       -- email address or phone number
    credential  TEXT,                           -- bcrypt hash (NULL for OAuth-only users)
    verified    BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (auth_type, identifier)
);

COMMENT ON TABLE frontend.user_auth IS
    'Multi-provider authentication — one row per auth method per user.';

CREATE INDEX IF NOT EXISTS idx_user_auth_user
    ON frontend.user_auth(user_id);
CREATE INDEX IF NOT EXISTS idx_user_auth_lookup
    ON frontend.user_auth(auth_type, identifier);
