CREATE TABLE orders (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    order_no        VARCHAR(50)  UNIQUE NOT NULL,   -- ORD-20240315-00001
    user_id         UUID         NOT NULL REFERENCES users(id),

    subtotal        NUMERIC(10,2) NOT NULL,
    discount_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
    total           NUMERIC(10,2) NOT NULL,
    currency        VARCHAR(10)  NOT NULL DEFAULT 'CNY',

    payment_channel VARCHAR(30),      -- wechat_pay|alipay|stripe
    payment_ref     VARCHAR(200),     -- 第三方支付流水号（wx_order_id 等）

    status          VARCHAR(20)  NOT NULL DEFAULT 'pending', -- pending|paid|refunded|failed
    paid_at         TIMESTAMPTZ,
    refunded_at     TIMESTAMPTZ,
    refund_reason   TEXT,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 订单行项目（每种商品类型各一条）
CREATE TABLE order_items (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id     UUID         NOT NULL REFERENCES orders(id),

    item_type    VARCHAR(30)  NOT NULL,  -- 'membership' | 'strategy_payg'
    item_id      UUID         NOT NULL,  -- plan_id 或 strategy_id（类型由 item_type 决定）
    item_name    VARCHAR(200),           -- 购买时名称快照
    unit_price   NUMERIC(10,2) NOT NULL,
    quantity     SMALLINT     NOT NULL DEFAULT 1,
    subtotal     NUMERIC(10,2) NOT NULL,

    -- 会员专用
    duration_days INT,

    meta         JSONB        -- 购买时的其他快照（tier level、payg_duration 等）
);

-- 判断用户能否访问某内容（access_tier + delay_free + payg grant）
CREATE OR REPLACE FUNCTION can_access_content(
    p_user_id     UUID,
    p_access_tier SMALLINT,
    p_delay_free  INT,
    p_published   TIMESTAMPTZ,
    p_strategy_id UUID DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_user_tier SMALLINT := 0;
BEGIN
    -- 取用户当前有效 tier
    SELECT mp.level INTO v_user_tier
    FROM user_memberships um
    JOIN membership_plans mp ON mp.id = um.plan_id
    WHERE um.user_id = p_user_id
      AND um.status = 'active'
      AND um.expires_at > NOW()
    ORDER BY mp.level DESC
    LIMIT 1;

    -- 1. 公开内容
    IF p_access_tier = 0 THEN RETURN TRUE; END IF;

    -- 2. 延迟免费（时间到了就全部开放）
    IF p_delay_free IS NOT NULL
       AND p_published + (p_delay_free || ' hours')::INTERVAL < NOW()
    THEN RETURN TRUE; END IF;

    -- 3. Tier 满足
    IF COALESCE(v_user_tier, 0) >= p_access_tier THEN RETURN TRUE; END IF;

    -- 4. Payg 授权（仅策略）
    IF p_strategy_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM strategy_access_grants
        WHERE user_id = p_user_id
          AND strategy_id = p_strategy_id
          AND (expires_at IS NULL OR expires_at > NOW())
    ) THEN RETURN TRUE; END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

