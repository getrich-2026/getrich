-- 003_users.sql: Users table for authentication
-- Each user has a unique login email, a bcrypt password hash, and a display name.
-- IMPORTANT: backend pool.py 设置 `SET search_path=app,market,meta,public`，本表放 `app` schema。 We use schema-qualified names so the
-- migration is idempotent regardless of the caller's search_path.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255)    NOT NULL UNIQUE,
    password    VARCHAR(255)    NOT NULL,   -- bcrypt hash
    name        VARCHAR(128)    NOT NULL DEFAULT '',
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Seed a default demo user: demo@getrich.io / password
-- The bcrypt hash below is for the literal string "password" (cost=12).
INSERT INTO app.users (email, password, name)
VALUES (
    'demo@getrich.io',
    '$2b$12$c3lZxMMPPPn40Pg104gng.47ED584SS/eWbayiO7NoBLKtjKXUamK',
    'Demo User'
) ON CONFLICT (email) DO NOTHING;
