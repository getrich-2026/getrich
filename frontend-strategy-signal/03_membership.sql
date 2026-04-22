-- ============================================================
-- 会员体系（全站统一 Tier：1/2/3）
-- 与"按策略订阅"并存：用户能访问某内容的条件为
--   user.tier >= resource.access_tier
--   OR 存在有效的 strategy_access_grants
--   OR 存在有效的 user_strategy_subscriptions
-- ============================================================

-- 会员套餐定义
CREATE TABLE membership_plans (
    id              SMALLSERIAL     PRIMARY KEY,
    name            VARCHAR(50)     NOT NULL,
    level           SMALLINT        NOT NULL UNIQUE,        -- 1 | 2 | 3
    price_monthly   NUMERIC(10,2)   NOT NULL,
    features        JSONB           NOT NULL DEFAULT '{}',  -- {"signal_delay_hours":24, "max_tools":5, "ad_free":true}
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- 用户会员记录（历史记录保留）
CREATE TABLE user_memberships (
    id              BIGSERIAL       PRIMARY KEY,
    user_id         UUID            NOT NULL REFERENCES users(id),
    plan_id         SMALLINT        NOT NULL REFERENCES membership_plans(id),
    started_at      TIMESTAMPTZ     NOT NULL,
    expires_at      TIMESTAMPTZ     NOT NULL,
    auto_renew      BOOLEAN         NOT NULL DEFAULT FALSE,
    status          VARCHAR(20)     NOT NULL DEFAULT 'active',  -- active|expired|cancelled
    source_order_id UUID,                                   -- 关联支付订单（回填）
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
