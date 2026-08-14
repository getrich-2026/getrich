-- 013_strategies.sql
-- Core strategy metadata table.
--
-- This table already exists in production (created outside the migration
-- runner) but has no migration file — a fresh environment would fail
-- because all strategy services query it.
--
-- Schema-qualified: the backend pool sets SET search_path=frontend;
-- all strategy service references are unprefixed, so the table must
-- live in frontend.

CREATE SCHEMA IF NOT EXISTS frontend;

CREATE TABLE IF NOT EXISTS frontend.strategies (
    id                      VARCHAR(64)     PRIMARY KEY,                   -- UUID
    strategy_code           VARCHAR(64)     NOT NULL UNIQUE,               -- human-readable code (e.g. STR_IF_001)
    name                    VARCHAR(255)    NOT NULL,
    summary                 TEXT,
    description             TEXT,
    detail_html             TEXT,
    category_id             VARCHAR(64),                                   -- FK to strategy_categories.id
    asset_class             VARCHAR(32),                                   -- 'futures' | 'stock' | 'crypto' | etc.
    market                  VARCHAR(32),                                   -- 'cn' | 'hk' | 'us' | etc.
    risk_level              VARCHAR(16),                                   -- 'low' | 'medium' | 'high'
    cover_image             VARCHAR(512),                                  -- URL to cover image
    subscriber_count        INT             NOT NULL DEFAULT 0,
    subscription_monthly    DECIMAL(12,2),                                 -- monthly subscription price (CNY)
    subscription_yearly     DECIMAL(12,2),                                 -- yearly subscription price (CNY)
    run_status              VARCHAR(16)     DEFAULT 'paper',               -- 'paper' | 'live' | 'paused' | 'retired'
    pub_status              VARCHAR(16)     DEFAULT 'published',           -- 'draft' | 'published' | 'archived'
    backtest_start          DATE,                                          -- backtest range start
    backtest_end            DATE,                                          -- backtest range end
    author_id               VARCHAR(64),                                   -- FK to users.id
    web                     BOOLEAN         DEFAULT TRUE,                  -- visible on web
    published_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE frontend.strategies IS
    'Core strategy metadata — one row per strategy.';

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_strategies_code ON frontend.strategies(strategy_code);
CREATE INDEX IF NOT EXISTS idx_strategies_pub_status ON frontend.strategies(pub_status);
CREATE INDEX IF NOT EXISTS idx_strategies_author ON frontend.strategies(author_id);
