-- ============================================================
-- 策略付费访问（两条路径并存）
--   1. PayG 一次性授权：strategy_access_grants（买断/限时，由 orders 生成）
--   2. 周期订阅：user_strategy_subscriptions（月/年续费，对应前端 4.8）
-- 两者由 can_access_content 函数统一判断
-- ============================================================

-- PayG 授权（和 membership tier 分离）
CREATE TABLE frontend.strategy_access_grants (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL REFERENCES frontend.users(id),
    strategy_id     UUID            NOT NULL REFERENCES frontend.strategies(id),
    source_order_id UUID            NOT NULL REFERENCES frontend.orders(id),
    expires_at      TIMESTAMPTZ,                            -- NULL=永久
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, strategy_id)                           -- 一个用户对同一策略只保留一条有效授权
);

-- 周期订阅（对应前端 4.8 POST /strategies/{id}/subscribe）
CREATE TABLE frontend.user_strategy_subscriptions (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID            NOT NULL REFERENCES frontend.users(id),
    strategy_id     UUID            NOT NULL REFERENCES frontend.strategies(id),

    plan_type       VARCHAR(16)     NOT NULL,               -- monthly|yearly|lifetime
    status          VARCHAR(16)     NOT NULL DEFAULT 'active',  -- pending_payment|active|expired|cancelled
    auto_renew      BOOLEAN         NOT NULL DEFAULT TRUE,

    start_date      DATE            NOT NULL,
    expire_date     DATE            NOT NULL,

    source_order_id UUID            REFERENCES frontend.orders(id),
    cancelled_at    TIMESTAMPTZ,
    cancel_reason   TEXT,

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_strategy_subs_plan_type_valid CHECK (plan_type IN ('monthly', 'yearly', 'lifetime')),
    CONSTRAINT chk_strategy_subs_status_valid
        CHECK (status IN ('pending_payment', 'active', 'expired', 'cancelled')),
    CONSTRAINT chk_strategy_subs_date_window CHECK (start_date <= expire_date)
);
-- 注：同一 (user_id, strategy_id) 可以存在多条历史订阅，靠 status + expire_date 判断当前是否有效
-- 避免 UNIQUE 约束把续费新订阅挡掉

-- 订阅取消时用的乐观 partial unique（仅 active 状态下唯一）
CREATE UNIQUE INDEX uq_strategy_sub_active
    ON frontend.user_strategy_subscriptions(user_id, strategy_id)
    WHERE status = 'active';
