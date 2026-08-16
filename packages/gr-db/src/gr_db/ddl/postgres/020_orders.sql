-- 012_orders.sql
-- Orders and order_items tables for user subscriptions and payments.
--
-- These tables already exist in production (created outside the migration
-- runner) but have no migration file — a fresh environment would fail
-- because the order service queries them.
--
-- Schema-qualified: the backend pool sets SET search_path=app,market,meta,public;
-- services/order.py and services/payment.py reference the tables
-- unprefixed, so they must live in app.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.orders (
    id              VARCHAR(64)     PRIMARY KEY,                   -- UUID
    order_no        VARCHAR(64)     NOT NULL UNIQUE,               -- human-readable order number
    user_id         VARCHAR(64)     NOT NULL,                      -- FK to users.id
    status          VARCHAR(16)     NOT NULL DEFAULT 'pending',    -- pending | paid | failed | refunded
    subtotal        DECIMAL(20,4)   NOT NULL DEFAULT 0,
    total           DECIMAL(20,4)   NOT NULL DEFAULT 0,            -- total amount
    currency        VARCHAR(8)      NOT NULL DEFAULT 'CNY',
    payment_source  VARCHAR(32),                                   -- 'alipay' | 'wechat' | 'stripe' | etc.
    payment_ref     VARCHAR(255),                                  -- external payment reference
    expire_at       TIMESTAMPTZ,                                   -- payment QR expiry
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    paid_at         TIMESTAMPTZ,
    refunded_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE app.orders IS
    'User orders — one row per purchase (strategy subscription, PAYG, etc.).';

CREATE TABLE IF NOT EXISTS app.order_items (
    id              VARCHAR(64)     PRIMARY KEY,                   -- UUID
    order_id        VARCHAR(64)     NOT NULL REFERENCES app.orders(id),
    item_type       VARCHAR(32)     NOT NULL,                      -- 'strategy_subscription' | 'strategy_payg'
    item_id         VARCHAR(64),                                   -- FK to strategies.id (nullable for non-strategy items)
    item_name       VARCHAR(255)    NOT NULL,
    unit_price      DECIMAL(20,4)   NOT NULL DEFAULT 0,
    quantity        INT             NOT NULL DEFAULT 1,
    subtotal        DECIMAL(20,4)   NOT NULL DEFAULT 0,
    plan_type       VARCHAR(16),                                   -- 'monthly' | 'yearly' | 'payg'
    duration_days   INT,                                           -- subscription duration
    meta            JSONB,                                         -- free-form metadata
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE app.order_items IS
    'Line items within an order — each row represents one purchased item/service.';

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_orders_user ON app.orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_payment_ref ON app.orders(payment_ref);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON app.order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_type ON app.order_items(item_type);
