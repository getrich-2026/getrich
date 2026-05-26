-- ============================================================
-- Frontend linked display data
-- ============================================================
-- 目的：
-- 1. 补齐 OpenAPI 中前端直接展示、但 frontend-data 暂未覆盖的关联数据。
-- 2. 只基于当前已有的 STR_IF_001 / DEMO_USER_001 / ORDER_IF_001 生成轻量 mock。
-- 3. 可重复执行；不清表，不影响其他策略和用户。

BEGIN;

-- ------- membership plans -------
-- /strategies/{id} 的访问控制、会员态提示、订阅页通常需要基础会员档位。
INSERT INTO frontend.membership_plans (
    name, level, price_monthly, features, is_active
) VALUES
    (
        'Basic',
        1,
        99.00,
        '{"signal_delay_hours":24,"max_tools":3,"ad_free":false}'::jsonb,
        TRUE
    ),
    (
        'Pro',
        2,
        299.00,
        '{"signal_delay_hours":0,"max_tools":10,"ad_free":true}'::jsonb,
        TRUE
    ),
    (
        'Elite',
        3,
        699.00,
        '{"signal_delay_hours":0,"max_tools":99,"priority_support":true}'::jsonb,
        TRUE
    )
ON CONFLICT (level) DO UPDATE SET
    name = EXCLUDED.name,
    price_monthly = EXCLUDED.price_monthly,
    features = EXCLUDED.features,
    is_active = EXCLUDED.is_active;

-- ------- strategy display price -------
-- frontend-data 当前未给订阅价格；OpenAPI 示例需要 subscription_price。
-- 这里用示例价做 mock，只在字段为空时填充。
UPDATE frontend.strategies
SET
    subscription_monthly = COALESCE(subscription_monthly, 99.00),
    subscription_yearly = COALESCE(subscription_yearly, 899.00),
    payg_price = COALESCE(payg_price, 299.00),
    payg_duration_days = COALESCE(payg_duration_days, 365),
    updated_at = NOW()
WHERE strategy_code = 'STR_IF_001';

-- ------- demo membership -------
-- 让 DEMO_USER_001 在会员态、订阅态、免费态页面都有可测数据。
INSERT INTO frontend.user_memberships (
    id, user_id, plan_id, started_at, expires_at, auto_renew, status, source_order_id
)
SELECT
    920001,
    u.id,
    p.id,
    '2026-05-22 00:00:00+08'::timestamptz,
    '2027-05-22 23:59:59+08'::timestamptz,
    TRUE,
    'active',
    NULL
FROM frontend.users u
JOIN frontend.membership_plans p ON p.level = 2
WHERE u.username = 'demo_user'
ON CONFLICT (id) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    plan_id = EXCLUDED.plan_id,
    started_at = EXCLUDED.started_at,
    expires_at = EXCLUDED.expires_at,
    auto_renew = EXCLUDED.auto_renew,
    status = EXCLUDED.status,
    source_order_id = EXCLUDED.source_order_id;

-- ------- follows -------
-- 支持策略详情页/列表页展示关注态和 follower_count。
INSERT INTO frontend.strategy_follows (user_id, strategy_id, created_at)
SELECT
    u.id,
    s.id,
    '2026-05-22 09:05:00+08'::timestamptz
FROM frontend.users u
JOIN frontend.strategies s ON s.strategy_code = 'STR_IF_001'
WHERE u.username = 'demo_user'
ON CONFLICT (user_id, strategy_id) DO NOTHING;

-- ------- order display -------
-- /user/orders 需要订单与订单行。这里把 ORDER_IF_001 补成有金额、有支付渠道的展示订单。
WITH target AS (
    SELECT
        u.id AS user_id,
        s.id AS strategy_id,
        s.name AS strategy_name,
        COALESCE(s.subscription_yearly, 899.00) AS yearly_price
    FROM frontend.users u
    CROSS JOIN frontend.strategies s
    WHERE u.username = 'demo_user'
      AND s.strategy_code = 'STR_IF_001'
),
order_row AS (
    INSERT INTO frontend.orders (
        id, order_no, user_id, subtotal, discount_amount, total, currency,
        payment_source, payment_channel, payment_ref, status, paid_at, expire_at,
        created_at
    )
    SELECT
        '93000000-0000-4000-8000-000000000001'::uuid,
        'ORDER_IF_001',
        user_id,
        yearly_price,
        0.00,
        yearly_price,
        'CNY',
        'wechat',
        'wechat_pay',
        'MOCK_PAY_ORDER_IF_001',
        'paid',
        '2026-05-22 09:10:00+08'::timestamptz,
        NULL,
        '2026-05-22 09:00:00+08'::timestamptz
    FROM target
    ON CONFLICT (order_no) DO UPDATE SET
        user_id = EXCLUDED.user_id,
        subtotal = EXCLUDED.subtotal,
        discount_amount = EXCLUDED.discount_amount,
        total = EXCLUDED.total,
        currency = EXCLUDED.currency,
        payment_source = EXCLUDED.payment_source,
        payment_channel = EXCLUDED.payment_channel,
        payment_ref = EXCLUDED.payment_ref,
        status = EXCLUDED.status,
        paid_at = EXCLUDED.paid_at,
        expire_at = EXCLUDED.expire_at
    RETURNING id
)
INSERT INTO frontend.order_items (
    id, order_id, item_type, item_id, item_name, unit_price, quantity, subtotal,
    plan_type, duration_days, meta
)
SELECT
    '93000000-0000-4000-8000-000000000002'::uuid,
    o.id,
    'strategy_subscription',
    t.strategy_id,
    t.strategy_name || '（年订阅）',
    t.yearly_price,
    1,
    t.yearly_price,
    'yearly',
    365,
    '{"source":"linked-display-data","strategy_code":"STR_IF_001"}'::jsonb
FROM target t
CROSS JOIN order_row o
WHERE NOT EXISTS (
    SELECT 1
    FROM frontend.order_items oi
    WHERE oi.order_id = o.id
      AND oi.item_type = 'strategy_subscription'
      AND oi.item_id = t.strategy_id
);

-- 把已有订阅关联到展示订单，保证 /strategies/{id}/subscription 与 /user/orders 可串起来。
UPDATE frontend.user_strategy_subscriptions us
SET
    source_order_id = o.id,
    status = 'active',
    updated_at = NOW()
FROM frontend.users u
JOIN frontend.strategies s ON s.strategy_code = 'STR_IF_001'
JOIN frontend.orders o ON o.order_no = 'ORDER_IF_001'
WHERE us.user_id = u.id
  AND us.strategy_id = s.id
  AND u.username = 'demo_user';

-- ------- trade pairing -------
-- /strategies/{id}/trades 由信号配对计算。
-- 当前数据中 2026-05-19 做空 IC 与 2026-05-22 平仓空头可形成一笔展示交易。
UPDATE frontend.signals exit_sig
SET
    parent_signal_id = entry_sig.id,
    trigger_price = COALESCE(exit_sig.trigger_price, 8380.0000),
    suggested_quantity = COALESCE(exit_sig.suggested_quantity, 1),
    status = 'expired',
    result = 'win',
    resolved_at = COALESCE(exit_sig.resolved_at, exit_sig.published_at)
FROM frontend.signals entry_sig
WHERE exit_sig.signal_code = 'SIG_STR_IF_001_20260522_001'
  AND entry_sig.signal_code = 'SIG_STR_IF_001_20260519_001';

UPDATE frontend.signals
SET
    suggested_quantity = COALESCE(suggested_quantity, 1),
    status = 'expired',
    result = 'win',
    exit_price = COALESCE(exit_price, 8380.0000),
    pnl_pct = COALESCE(pnl_pct, 0.0027),
    resolved_at = COALESCE(resolved_at, '2026-05-22 14:57:00+08'::timestamptz)
WHERE signal_code = 'SIG_STR_IF_001_20260519_001';

-- ------- denormalized counters -------
-- 前端列表页常直接读 strategies 的冗余计数字段。
UPDATE frontend.strategies s
SET
    follower_count = COALESCE(f.cnt, 0),
    subscriber_count = COALESCE(sub.cnt, 0),
    signal_count = COALESCE(sig.cnt, 0),
    updated_at = NOW()
FROM (
    SELECT id
    FROM frontend.strategies
    WHERE strategy_code = 'STR_IF_001'
) base
LEFT JOIN (
    SELECT strategy_id, COUNT(*)::int AS cnt
    FROM frontend.strategy_follows
    GROUP BY strategy_id
) f ON f.strategy_id = base.id
LEFT JOIN (
    SELECT strategy_id, COUNT(*)::int AS cnt
    FROM frontend.user_strategy_subscriptions
    WHERE status = 'active'
      AND expire_date >= CURRENT_DATE
    GROUP BY strategy_id
) sub ON sub.strategy_id = base.id
LEFT JOIN (
    SELECT strategy_id, COUNT(*)::int AS cnt
    FROM frontend.signals
    GROUP BY strategy_id
) sig ON sig.strategy_id = base.id
WHERE s.id = base.id;

COMMIT;
