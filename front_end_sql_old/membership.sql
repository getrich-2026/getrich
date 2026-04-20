CREATE TABLE membership_plans (
    id              SMALLSERIAL PRIMARY KEY,
    name            VARCHAR(50)  NOT NULL,
    level           SMALLINT     NOT NULL UNIQUE,   -- 1 | 2 | 3
    price_monthly   NUMERIC(10,2) NOT NULL,
    features        JSONB        NOT NULL DEFAULT '{}',
    -- features 示例: {"signal_delay_hours": 24, "max_tools": 5, "ad_free": true}
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 用户会员记录（历史都留着）
CREATE TABLE user_memberships (
    id              BIGSERIAL    PRIMARY KEY,
    user_id         UUID         NOT NULL REFERENCES users(id),
    plan_id         SMALLINT     NOT NULL REFERENCES membership_plans(id),
    started_at      TIMESTAMPTZ  NOT NULL,
    expires_at      TIMESTAMPTZ  NOT NULL,
    auto_renew      BOOLEAN      NOT NULL DEFAULT FALSE,
    status          VARCHAR(20)  NOT NULL DEFAULT 'active', -- active|expired|cancelled
    source_order_id UUID,        -- 关联支付订单，订单创建后回填
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
