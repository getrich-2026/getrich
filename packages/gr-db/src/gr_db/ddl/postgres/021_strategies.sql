-- 013_strategies.sql
-- Core strategy metadata table.
--
-- This table already exists in production (created outside the migration
-- runner) but has no migration file — a fresh environment would fail
-- because all strategy services query it.
--
-- Schema-qualified: the backend pool sets SET search_path=app,market,meta,public;
-- all strategy service references are unprefixed, so the table must
-- live in app.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.strategies (
    id                      UUID            PRIMARY KEY,
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
    author_id               UUID,                                          -- FK to app.users.id
    web                     BOOLEAN         DEFAULT TRUE,                  -- visible on web
    published_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    strategy_kind           VARCHAR(16),
    CONSTRAINT strategies_detail_html_length_chk
        CHECK (detail_html IS NULL OR char_length(detail_html) <= 50000),
    CONSTRAINT chk_strategies_strategy_kind
        CHECK (strategy_kind IS NULL OR strategy_kind IN ('pick', 'timing', 'combo'))
);

COMMENT ON TABLE app.strategies IS
    'Core strategy metadata — one row per strategy.';

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_strategies_code ON app.strategies(strategy_code);
CREATE INDEX IF NOT EXISTS idx_strategies_pub_status ON app.strategies(pub_status);
CREATE INDEX IF NOT EXISTS idx_strategies_author ON app.strategies(author_id);

COMMENT ON COLUMN app.strategies.strategy_kind IS
    '策略类型：pick=选股（产出每日标的池，走 /v1/pick-strategies）；timing=择时（产出买卖信号）；combo=组合。NULL 表示未分类，不会出现在选股接口里。';

CREATE INDEX IF NOT EXISTS idx_strategies_kind
    ON app.strategies(strategy_kind) WHERE strategy_kind IS NOT NULL;
COMMENT ON CONSTRAINT strategies_detail_html_length_chk ON app.strategies IS
    '详情 HTML 最长 50000 字符；仅限制长度，HTML 清洗仍由输入与展示边界负责。';
