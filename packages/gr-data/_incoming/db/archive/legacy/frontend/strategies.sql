CREATE TABLE strategies (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_code   VARCHAR(20)  UNIQUE NOT NULL,   -- STR-2024-001（展示用）
    author_id       UUID         NOT NULL REFERENCES users(id),
    name            VARCHAR(200) NOT NULL,

    -- 分类
    type            VARCHAR(30)  NOT NULL,  -- timing|stock_pick|hedge|arbitrage|macro
    asset_class     VARCHAR(30)  NOT NULL,  -- equity|futures|fx|crypto|mixed
    target_horizon  VARCHAR(20)  NOT NULL,  -- intraday|swing|position|long_term

    -- 内容（分层披露）
    summary         TEXT,                   -- 永远公开，一句话描述
    logic_overview  TEXT,                   -- tier >= 1 可见
    logic_detail    TEXT,                   -- tier >= access_tier 或 payg 授权可见
    backtest_report JSONB,                  -- {sharpe, max_dd, annual_return, equity_curve:[]}

    -- 访问控制（统一模型）
    access_tier     SMALLINT     NOT NULL DEFAULT 1,  -- 0公开 1/2/3需对应tier
    payg_price      NUMERIC(8,2),                     -- NULL=不支持单独购买
    payg_duration_days INT,                           -- NULL=永久; 30/90/365

    -- 双状态（发布状态 vs 运行状态分开）
    pub_status      VARCHAR(20)  NOT NULL DEFAULT 'draft',  -- draft|published|archived
    run_status      VARCHAR(20),                            -- backtest|paper|live|paused|retired

    -- 统计（denormalize，避免频繁 count）
    follower_count  INT          NOT NULL DEFAULT 0,
    signal_count    INT          NOT NULL DEFAULT 0,

    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE strategy_tags (
    strategy_id UUID     REFERENCES strategies(id) ON DELETE CASCADE,
    tag_id      SMALLINT REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (strategy_id, tag_id)
);

-- Payg 访问授权（和 membership tier 完全分离）
-- 判断能否访问: user.tier >= strategy.access_tier OR 存在有效 grant
CREATE TABLE strategy_access_grants (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES users(id),
    strategy_id     UUID        NOT NULL REFERENCES strategies(id),
    source_order_id UUID        NOT NULL,  -- 关联订单
    expires_at      TIMESTAMPTZ,           -- NULL=永久
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, strategy_id)
);

-- 关注策略（免费行为，用于推送通知，与付费无关）
CREATE TABLE strategy_follows (
    user_id     UUID REFERENCES users(id)       ON DELETE CASCADE,
    strategy_id UUID REFERENCES strategies(id)  ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, strategy_id)
);