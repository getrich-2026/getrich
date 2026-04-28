-- ============================================================
-- 订单 & 支付
-- ============================================================

CREATE TABLE frontend.orders (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    order_no        VARCHAR(50)     UNIQUE NOT NULL,        -- ORD-20260415-00001
    user_id         UUID            NOT NULL REFERENCES frontend.users(id),

    subtotal        NUMERIC(10,2)   NOT NULL,
    discount_amount NUMERIC(10,2)   NOT NULL DEFAULT 0,
    total           NUMERIC(10,2)   NOT NULL,
    currency        VARCHAR(10)     NOT NULL DEFAULT 'CNY',

    -- 支付信息
    payment_source  VARCHAR(20),                            -- wechat|alipay|bank|apple_pay|stripe
    payment_channel VARCHAR(30),                            -- 兼容字段：wechat_pay|alipay|stripe
    payment_ref     VARCHAR(200),                           -- 第三方支付流水号

    status          VARCHAR(20)     NOT NULL DEFAULT 'pending',  -- pending|paid|refunded|failed|cancelled
    paid_at         TIMESTAMPTZ,
    refunded_at     TIMESTAMPTZ,
    refund_reason   TEXT,

    -- 订单过期时间（未支付自动取消，对应前端 payment.expire_time）
    expire_at       TIMESTAMPTZ,

    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- 订单行项目
CREATE TABLE frontend.order_items (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID            NOT NULL REFERENCES frontend.orders(id) ON DELETE CASCADE,

    item_type       VARCHAR(30)     NOT NULL,               -- membership|strategy_payg|strategy_subscription|tool
    item_id         UUID            NOT NULL,               -- 对应 plan_id / strategy_id 等（由 item_type 决定）
    item_name       VARCHAR(200),                           -- 购买时名称快照
    unit_price      NUMERIC(10,2)   NOT NULL,
    quantity        SMALLINT        NOT NULL DEFAULT 1,
    subtotal        NUMERIC(10,2)   NOT NULL,

    -- 周期性：会员 / 策略订阅共用
    plan_type       VARCHAR(16),                            -- monthly|yearly|lifetime（策略订阅用）
    duration_days   INT,                                    -- 会员或 payg 时长

    -- 购买时的快照信息（tier level / payg_duration / 折扣原因等）
    meta            JSONB           NOT NULL DEFAULT '{}'
);
