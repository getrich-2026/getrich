-- ============================================================
-- 策略模块
-- ============================================================

-- 策略分类（对应前端接口 4.1 GET /strategies/categories）
CREATE TABLE frontend.strategy_categories (
    id              VARCHAR(16)     PRIMARY KEY,            -- CAT_TREND / CAT_MR / CAT_ARB ...
    name            VARCHAR(64)     NOT NULL,
    description     VARCHAR(256),
    icon_url        TEXT,
    sort_order      INT             NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_strategy_categories_id_not_blank CHECK (btrim(id) <> ''),
    CONSTRAINT chk_strategy_categories_name_not_blank CHECK (btrim(name) <> '')
);

-- 策略主表
CREATE TABLE frontend.strategies (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_code   VARCHAR(32)     UNIQUE NOT NULL,        -- STR_FUT_001（对外展示 / URL slug）
    author_id       UUID            NOT NULL REFERENCES frontend.users(id),

    -- 基本信息
    name            VARCHAR(200)    NOT NULL,
    summary         TEXT,                                   -- 一句话描述（永远公开）
    description     TEXT,                                   -- 策略简介（Markdown）
    detail_html     TEXT,                                   -- 详细介绍富文本（tier >= access_tier 可见）
    cover_image     TEXT,                                   -- 封面图 URL

    -- 分类 / 属性
    category_id     VARCHAR(16)     REFERENCES frontend.strategy_categories(id),
    type            VARCHAR(30)     NOT NULL,               -- timing|stock_pick|hedge|arbitrage|macro
    asset_class     VARCHAR(30)     NOT NULL,               -- stock|future|option|equity|fx|crypto|mixed
    market          VARCHAR(16)     NOT NULL DEFAULT 'cn',  -- cn|hk|us
    target_horizon  VARCHAR(20),                            -- intraday|swing|position|long_term
    risk_level      VARCHAR(8)      NOT NULL DEFAULT 'medium',  -- low|medium|high

    -- 访问控制（三套并存，由 can_access_content 统一判断）
    access_tier     SMALLINT        NOT NULL DEFAULT 1,     -- 0公开 / 1/2/3 需对应 tier
    payg_price      NUMERIC(10,2),                          -- NULL=不支持单独购买（一次性）
    payg_duration_days INT,                                 -- NULL=永久；30/90/365

    -- 订阅价格（续费型，对应前端 4.8 POST /subscribe）
    subscription_monthly  NUMERIC(10,2),
    subscription_yearly   NUMERIC(10,2),

    -- 回测区间
    backtest_start  DATE,
    backtest_end    DATE,

    -- 双状态（发布状态 vs 运行状态分开）
    pub_status      VARCHAR(20)     NOT NULL DEFAULT 'draft',   -- draft|published|archived
    run_status      VARCHAR(20),                                -- backtest|paper|live|paused|retired

    -- 统计冗余（定时任务刷新，避免列表页 count 聚合）
    follower_count  INT             NOT NULL DEFAULT 0,
    subscriber_count INT            NOT NULL DEFAULT 0,
    signal_count    INT             NOT NULL DEFAULT 0,

    -- 对外展示配置（如 benchmark / universe / 佣金设置）
    config          JSONB           NOT NULL DEFAULT '{}',

    -- 版本管理
    version         VARCHAR(16)     NOT NULL DEFAULT 'v1.0',
    version_reason  VARCHAR(64),

    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_strategies_code_not_blank CHECK (btrim(strategy_code) <> ''),
    CONSTRAINT chk_strategies_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT chk_strategies_type_valid CHECK (type IN ('timing', 'stock_pick', 'hedge', 'arbitrage', 'macro')),
    CONSTRAINT chk_strategies_asset_class_valid
        CHECK (asset_class IN ('stock', 'future', 'option', 'equity', 'fx', 'crypto', 'mixed')),
    CONSTRAINT chk_strategies_market_valid CHECK (market IN ('cn', 'hk', 'us')),
    CONSTRAINT chk_strategies_target_horizon_valid
        CHECK (target_horizon IS NULL OR target_horizon IN ('intraday', 'swing', 'position', 'long_term')),
    CONSTRAINT chk_strategies_risk_level_valid CHECK (risk_level IN ('low', 'medium', 'high')),
    CONSTRAINT chk_strategies_access_tier_non_negative CHECK (access_tier >= 0),
    CONSTRAINT chk_strategies_payg_price_non_negative CHECK (payg_price IS NULL OR payg_price >= 0),
    CONSTRAINT chk_strategies_payg_duration_positive
        CHECK (payg_duration_days IS NULL OR payg_duration_days > 0),
    CONSTRAINT chk_strategies_subscription_monthly_non_negative
        CHECK (subscription_monthly IS NULL OR subscription_monthly >= 0),
    CONSTRAINT chk_strategies_subscription_yearly_non_negative
        CHECK (subscription_yearly IS NULL OR subscription_yearly >= 0),
    CONSTRAINT chk_strategies_backtest_window
        CHECK (backtest_start IS NULL OR backtest_end IS NULL OR backtest_start <= backtest_end),
    CONSTRAINT chk_strategies_pub_status_valid CHECK (pub_status IN ('draft', 'published', 'archived')),
    CONSTRAINT chk_strategies_run_status_valid
        CHECK (run_status IS NULL OR run_status IN ('backtest', 'paper', 'live', 'paused', 'retired')),
    CONSTRAINT chk_strategies_counts_non_negative
        CHECK (follower_count >= 0 AND subscriber_count >= 0 AND signal_count >= 0)
);

-- 策略标签关联（使用 tags 表，适合"按 tag 查策略"）
CREATE TABLE frontend.strategy_tags (
    strategy_id     UUID            REFERENCES frontend.strategies(id) ON DELETE CASCADE,
    tag_id          SMALLINT        REFERENCES frontend.tags(id) ON DELETE CASCADE,
    PRIMARY KEY (strategy_id, tag_id)
);

-- 关注（免费行为，仅用于消息推送目标过滤）
CREATE TABLE frontend.strategy_follows (
    user_id         UUID            REFERENCES frontend.users(id) ON DELETE CASCADE,
    strategy_id     UUID            REFERENCES frontend.strategies(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, strategy_id)
);
