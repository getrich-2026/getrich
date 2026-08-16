-- 016_subscriptions.sql
-- User strategy subscriptions and access grants tables.
--
-- Schema-qualified: the backend pool sets SET search_path=app,market,meta,public;
-- services/subscription.py references these tables unprefixed.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.user_strategy_subscriptions (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL,
    strategy_id     UUID            NOT NULL,
    plan_type       VARCHAR(16)     NOT NULL,
    status          VARCHAR(16)     NOT NULL DEFAULT 'active',
    auto_renew      BOOLEAN         NOT NULL DEFAULT TRUE,
    start_date      DATE            NOT NULL,
    expire_date     DATE,
    source_order_id UUID,
    cancelled_at    TIMESTAMPTZ,
    cancel_reason   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app.strategy_access_grants (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL,
    strategy_id     UUID            NOT NULL,
    source_order_id UUID            NOT NULL,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON app.user_strategy_subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_strategy ON app.user_strategy_subscriptions(strategy_id);
CREATE INDEX IF NOT EXISTS idx_access_grants_user ON app.strategy_access_grants(user_id, strategy_id);

COMMENT ON TABLE app.user_strategy_subscriptions IS
    'User strategy subscriptions — one row per user-strategy subscription.';
COMMENT ON TABLE app.strategy_access_grants IS
    'Pay-per-use access grants for strategies.';
