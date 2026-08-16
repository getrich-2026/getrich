-- ============================================================
-- Frontend mock data
-- ============================================================
-- 可重复执行的前端联调用 mock 数据。
-- 使用固定 UUID / code / order_no，保证主外键关系稳定且便于调试。

BEGIN;

-- ------- users -------
INSERT INTO frontend.users (
    id, username, display_name, avatar_url, bio, status, created_at, updated_at
) VALUES
    ('00000000-0000-4000-8000-000000000001', 'mq_admin', 'MillerQuant 研究员', 'https://cdn.getrich.com/mock/avatar-admin.png', '策略作者与内容管理员。', 1, '2026-04-01 09:00:00+08', '2026-04-28 09:00:00+08'),
    ('00000000-0000-4000-8000-000000000002', 'demo_member', '会员用户', 'https://cdn.getrich.com/mock/avatar-member.png', '用于验证会员、订阅和付费访问。', 1, '2026-04-02 09:00:00+08', '2026-04-28 09:00:00+08'),
    ('00000000-0000-4000-8000-000000000003', 'demo_free', '免费用户', 'https://cdn.getrich.com/mock/avatar-free.png', '用于验证免费内容、未读和解锁提示。', 1, '2026-04-03 09:00:00+08', '2026-04-28 09:00:00+08')
ON CONFLICT (id) DO UPDATE SET
    username = EXCLUDED.username,
    display_name = EXCLUDED.display_name,
    avatar_url = EXCLUDED.avatar_url,
    bio = EXCLUDED.bio,
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at;

INSERT INTO frontend.user_auth (
    id, user_id, auth_type, identifier, credential, verified, created_at
) VALUES
    (900001, '00000000-0000-4000-8000-000000000001', 'email', 'admin@getrich.local', '$mock$admin', TRUE, '2026-04-01 09:05:00+08'),
    (900002, '00000000-0000-4000-8000-000000000002', 'phone', '+8613800000002', NULL, TRUE, '2026-04-02 09:05:00+08'),
    (900003, '00000000-0000-4000-8000-000000000003', 'email', 'free@getrich.local', '$mock$free', TRUE, '2026-04-03 09:05:00+08')
ON CONFLICT (auth_type, identifier) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    credential = EXCLUDED.credential,
    verified = EXCLUDED.verified;

INSERT INTO frontend.verification_codes (
    id, target, code, purpose, expires_at, used_at, created_at
) VALUES
    (900001, '+8613800000002', '246810', 'login', '2026-04-28 10:15:00+08', NULL, '2026-04-28 10:05:00+08'),
    (900002, 'free@getrich.local', '135790', 'bind', '2026-04-28 10:20:00+08', '2026-04-28 10:08:00+08', '2026-04-28 10:00:00+08')
ON CONFLICT (id) DO UPDATE SET
    target = EXCLUDED.target,
    code = EXCLUDED.code,
    purpose = EXCLUDED.purpose,
    expires_at = EXCLUDED.expires_at,
    used_at = EXCLUDED.used_at;

INSERT INTO frontend.user_wechat (
    user_id, openid, unionid, nickname, avatar_url, session_key, refreshed_at
) VALUES
    ('00000000-0000-4000-8000-000000000002', 'mock_openid_member_002', 'mock_union_member_002', '会员用户', 'https://cdn.getrich.com/mock/wechat-member.png', 'mock_session_key_member', '2026-04-28 09:30:00+08')
ON CONFLICT (user_id) DO UPDATE SET
    openid = EXCLUDED.openid,
    unionid = EXCLUDED.unionid,
    nickname = EXCLUDED.nickname,
    avatar_url = EXCLUDED.avatar_url,
    session_key = EXCLUDED.session_key,
    refreshed_at = EXCLUDED.refreshed_at;

INSERT INTO frontend.user_sessions (
    id, user_id, device_info, ip_address, expires_at, revoked_at, created_at
) VALUES
    ('70000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002', '{"platform":"web","browser":"Chrome","device":"MacBook Pro"}', '10.10.1.20', '2026-05-28 09:30:00+08', NULL, '2026-04-28 09:30:00+08'),
    ('70000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000003', '{"platform":"mobile","os":"iOS","app_version":"1.0.0"}', '10.10.1.21', '2026-05-28 09:35:00+08', NULL, '2026-04-28 09:35:00+08')
ON CONFLICT (id) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    device_info = EXCLUDED.device_info,
    ip_address = EXCLUDED.ip_address,
    expires_at = EXCLUDED.expires_at,
    revoked_at = EXCLUDED.revoked_at;

-- ------- common tags -------
INSERT INTO frontend.tags (id, slug, name, tag_group) VALUES
    (101, 'a-shares', 'A股', 'market'),
    (102, 'futures', '期货', 'market'),
    (103, 'momentum', '动量', 'strategy_type'),
    (104, 'mean-reversion', '均值回归', 'strategy_type'),
    (105, 'macro', '宏观', 'topic'),
    (106, 'risk-control', '风控', 'topic')
ON CONFLICT (id) DO UPDATE SET
    slug = EXCLUDED.slug,
    name = EXCLUDED.name,
    tag_group = EXCLUDED.tag_group;

-- ------- membership -------
INSERT INTO frontend.membership_plans (
    id, name, level, price_monthly, features, is_active, created_at
) VALUES
    (1, 'Basic', 1, 99.00, '{"signal_delay_hours":24,"max_tools":3,"ad_free":false}', TRUE, '2026-04-01 08:00:00+08'),
    (2, 'Pro', 2, 299.00, '{"signal_delay_hours":0,"max_tools":10,"ad_free":true}', TRUE, '2026-04-01 08:00:00+08'),
    (3, 'Elite', 3, 699.00, '{"signal_delay_hours":0,"max_tools":99,"priority_support":true}', TRUE, '2026-04-01 08:00:00+08')
ON CONFLICT (level) DO UPDATE SET
    name = EXCLUDED.name,
    price_monthly = EXCLUDED.price_monthly,
    features = EXCLUDED.features,
    is_active = EXCLUDED.is_active;

-- ------- strategies -------
INSERT INTO frontend.strategy_categories (
    id, name, description, icon_url, sort_order, created_at
) VALUES
    ('CAT_TREND', '趋势跟踪', '捕捉中长期趋势行情。', 'https://cdn.getrich.com/mock/icons/trend.svg', 10, '2026-04-01 08:00:00+08'),
    ('CAT_MR', '均值回归', '识别短期偏离后的回归机会。', 'https://cdn.getrich.com/mock/icons/mean-reversion.svg', 20, '2026-04-01 08:00:00+08'),
    ('CAT_MACRO', '宏观配置', '基于宏观变量进行资产配置。', 'https://cdn.getrich.com/mock/icons/macro.svg', 30, '2026-04-01 08:00:00+08')
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    icon_url = EXCLUDED.icon_url,
    sort_order = EXCLUDED.sort_order;

INSERT INTO frontend.strategies (
    id, strategy_code, author_id, name, summary, description, detail_html, cover_image,
    category_id, type, asset_class, market, target_horizon, risk_level,
    access_tier, payg_price, payg_duration_days, subscription_monthly, subscription_yearly,
    backtest_start, backtest_end, pub_status, run_status,
    follower_count, subscriber_count, signal_count, config, version, version_reason,
    published_at, created_at, updated_at
) VALUES
    (
        '10000000-0000-4000-8000-000000000001', 'STR_A_TREND_001', '00000000-0000-4000-8000-000000000001',
        '沪深300趋势跟踪', '跟随沪深300中期趋势，适合验证公开策略详情。',
        '基于均线斜率、波动率和成交量过滤的趋势策略。',
        '<h2>策略逻辑</h2><p>趋势确认后分批建仓，并通过移动止损控制回撤。</p>',
        'https://cdn.getrich.com/mock/strategy/hs300-trend.png',
        'CAT_TREND', 'timing', 'stock', 'cn', 'position', 'medium',
        0, NULL, NULL, NULL, NULL,
        '2021-01-01', '2026-04-25', 'published', 'paper',
        1280, 0, 2, '{"benchmark":"沪深300","rebalance":"daily","universe":"CSI300"}', 'v1.2', '优化风控阈值',
        '2026-04-10 09:00:00+08', '2026-04-01 09:00:00+08', '2026-04-28 09:00:00+08'
    ),
    (
        '10000000-0000-4000-8000-000000000002', 'STR_FUT_MR_001', '00000000-0000-4000-8000-000000000001',
        '股指期货价差回归', '针对 IF/IC 价差偏离的短周期均值回归策略。',
        '监控股指期货跨品种价差，超过阈值后生成回归交易信号。',
        '<h2>策略逻辑</h2><p>使用 z-score 触发入场，价差回归或止损退出。</p>',
        'https://cdn.getrich.com/mock/strategy/futures-spread.png',
        'CAT_MR', 'arbitrage', 'future', 'cn', 'swing', 'high',
        2, 399.00, 90, 199.00, 1999.00,
        '2022-01-01', '2026-04-25', 'published', 'live',
        860, 42, 2, '{"benchmark":"中证500","spread_pair":["IF","IC"],"entry_z":2.0}', 'v2.0', '切换到实盘跟踪',
        '2026-04-12 09:00:00+08', '2026-04-02 09:00:00+08', '2026-04-28 09:00:00+08'
    ),
    (
        '10000000-0000-4000-8000-000000000003', 'STR_MACRO_ALLOC_001', '00000000-0000-4000-8000-000000000001',
        '宏观多资产配置', '根据增长、通胀和流动性状态调整多资产权重。',
        '适合前端验证高等级会员内容、年度订阅和文章联动。',
        '<h2>策略逻辑</h2><p>月度评估宏观状态并调整权益、债券和商品权重。</p>',
        'https://cdn.getrich.com/mock/strategy/macro-alloc.png',
        'CAT_MACRO', 'macro', 'mixed', 'cn', 'long_term', 'low',
        3, 999.00, NULL, 399.00, 3999.00,
        '2020-01-01', '2026-04-25', 'published', 'paper',
        520, 18, 1, '{"rebalance":"monthly","assets":["equity","bond","commodity"],"risk_budget":"medium"}', 'v1.0', '首版发布',
        '2026-04-15 09:00:00+08', '2026-04-03 09:00:00+08', '2026-04-28 09:00:00+08'
    )
ON CONFLICT (strategy_code) DO UPDATE SET
    author_id = EXCLUDED.author_id,
    name = EXCLUDED.name,
    summary = EXCLUDED.summary,
    description = EXCLUDED.description,
    detail_html = EXCLUDED.detail_html,
    cover_image = EXCLUDED.cover_image,
    category_id = EXCLUDED.category_id,
    type = EXCLUDED.type,
    asset_class = EXCLUDED.asset_class,
    market = EXCLUDED.market,
    target_horizon = EXCLUDED.target_horizon,
    risk_level = EXCLUDED.risk_level,
    access_tier = EXCLUDED.access_tier,
    payg_price = EXCLUDED.payg_price,
    payg_duration_days = EXCLUDED.payg_duration_days,
    subscription_monthly = EXCLUDED.subscription_monthly,
    subscription_yearly = EXCLUDED.subscription_yearly,
    backtest_start = EXCLUDED.backtest_start,
    backtest_end = EXCLUDED.backtest_end,
    pub_status = EXCLUDED.pub_status,
    run_status = EXCLUDED.run_status,
    follower_count = EXCLUDED.follower_count,
    subscriber_count = EXCLUDED.subscriber_count,
    signal_count = EXCLUDED.signal_count,
    config = EXCLUDED.config,
    version = EXCLUDED.version,
    version_reason = EXCLUDED.version_reason,
    published_at = EXCLUDED.published_at,
    updated_at = EXCLUDED.updated_at;

INSERT INTO frontend.strategy_tags (strategy_id, tag_id) VALUES
    ('10000000-0000-4000-8000-000000000001', 101),
    ('10000000-0000-4000-8000-000000000001', 103),
    ('10000000-0000-4000-8000-000000000002', 102),
    ('10000000-0000-4000-8000-000000000002', 104),
    ('10000000-0000-4000-8000-000000000003', 105),
    ('10000000-0000-4000-8000-000000000003', 106)
ON CONFLICT DO NOTHING;

INSERT INTO frontend.strategy_follows (user_id, strategy_id, created_at) VALUES
    ('00000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000001', '2026-04-20 10:00:00+08'),
    ('00000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002', '2026-04-20 10:05:00+08'),
    ('00000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000001', '2026-04-21 10:00:00+08')
ON CONFLICT DO NOTHING;

-- ------- strategy time series -------
INSERT INTO frontend.strategy_equity_curve (
    strategy_id, trade_date, nav, cumulative_return, daily_return, drawdown, benchmark_nav, position_ratio
) VALUES
    ('10000000-0000-4000-8000-000000000001', '2026-04-21', 1.186000, 0.186000, 0.003200, -0.018000, 1.094000, 0.7200),
    ('10000000-0000-4000-8000-000000000001', '2026-04-22', 1.192000, 0.192000, 0.005100, -0.012000, 1.101000, 0.7600),
    ('10000000-0000-4000-8000-000000000001', '2026-04-23', 1.188000, 0.188000, -0.003400, -0.015000, 1.098000, 0.7000),
    ('10000000-0000-4000-8000-000000000001', '2026-04-24', 1.205000, 0.205000, 0.014300, -0.002000, 1.112000, 0.8200),
    ('10000000-0000-4000-8000-000000000001', '2026-04-27', 1.211000, 0.211000, 0.005000, 0.000000, 1.116000, 0.8000),
    ('10000000-0000-4000-8000-000000000002', '2026-04-21', 1.328000, 0.328000, -0.002000, -0.036000, 1.084000, 0.3500),
    ('10000000-0000-4000-8000-000000000002', '2026-04-22', 1.341000, 0.341000, 0.009800, -0.024000, 1.088000, 0.4200),
    ('10000000-0000-4000-8000-000000000002', '2026-04-23', 1.359000, 0.359000, 0.013400, -0.011000, 1.091000, 0.4800),
    ('10000000-0000-4000-8000-000000000002', '2026-04-24', 1.351000, 0.351000, -0.005900, -0.017000, 1.087000, 0.3800),
    ('10000000-0000-4000-8000-000000000002', '2026-04-27', 1.366000, 0.366000, 0.011100, -0.006000, 1.092000, 0.4600),
    ('10000000-0000-4000-8000-000000000003', '2026-04-21', 1.098000, 0.098000, 0.001000, -0.009000, 1.044000, 0.5500),
    ('10000000-0000-4000-8000-000000000003', '2026-04-22', 1.101000, 0.101000, 0.002700, -0.006000, 1.046000, 0.5600),
    ('10000000-0000-4000-8000-000000000003', '2026-04-23', 1.106000, 0.106000, 0.004500, -0.002000, 1.048000, 0.5800),
    ('10000000-0000-4000-8000-000000000003', '2026-04-24', 1.104000, 0.104000, -0.001800, -0.004000, 1.047000, 0.5700),
    ('10000000-0000-4000-8000-000000000003', '2026-04-27', 1.109000, 0.109000, 0.004500, 0.000000, 1.050000, 0.5900)
ON CONFLICT (strategy_id, trade_date) DO UPDATE SET
    nav = EXCLUDED.nav,
    cumulative_return = EXCLUDED.cumulative_return,
    daily_return = EXCLUDED.daily_return,
    drawdown = EXCLUDED.drawdown,
    benchmark_nav = EXCLUDED.benchmark_nav,
    position_ratio = EXCLUDED.position_ratio;

INSERT INTO frontend.strategy_performance_snapshot (
    strategy_id, snapshot_date, total_return, annualized_return, ytd_return,
    recent_1m_return, recent_3m_return, recent_6m_return, recent_1y_return,
    max_drawdown, max_drawdown_start, max_drawdown_end, max_drawdown_recovery,
    annualized_volatility, downside_deviation, sharpe_ratio, sortino_ratio,
    calmar_ratio, information_ratio, total_trades, win_rate, profit_factor,
    avg_win, avg_loss, max_consecutive_wins, max_consecutive_losses,
    avg_holding_days, var_95, cvar_95, beta, alpha
) VALUES
    ('10000000-0000-4000-8000-000000000001', '2026-04-27', 0.211000, 0.128000, 0.062000, 0.021000, 0.048000, 0.091000, 0.137000, -0.086000, '2025-08-12', '2025-09-03', '2025-11-18', 0.142000, 0.091000, 1.2400, 1.7100, 1.4900, 0.4200, 96, 0.5720, 1.3800, 0.018000, -0.012000, 7, 4, 8.40, -0.021000, -0.033000, 0.8200, 0.032000),
    ('10000000-0000-4000-8000-000000000002', '2026-04-27', 0.366000, 0.214000, 0.088000, 0.037000, 0.064000, 0.112000, 0.238000, -0.132000, '2025-06-19', '2025-07-08', '2025-08-20', 0.218000, 0.146000, 1.4800, 2.0300, 1.6200, 0.5800, 148, 0.6150, 1.7400, 0.026000, -0.015000, 9, 5, 3.20, -0.035000, -0.049000, 0.4300, 0.071000),
    ('10000000-0000-4000-8000-000000000003', '2026-04-27', 0.109000, 0.081000, 0.034000, 0.012000, 0.026000, 0.041000, 0.076000, -0.052000, '2025-10-10', '2025-10-31', '2025-12-15', 0.086000, 0.054000, 1.1100, 1.5200, 1.5600, 0.3100, 24, 0.5830, 1.2900, 0.014000, -0.009000, 5, 2, 21.50, -0.014000, -0.021000, 0.6400, 0.018000)
ON CONFLICT (strategy_id, snapshot_date) DO UPDATE SET
    total_return = EXCLUDED.total_return,
    annualized_return = EXCLUDED.annualized_return,
    ytd_return = EXCLUDED.ytd_return,
    recent_1m_return = EXCLUDED.recent_1m_return,
    recent_3m_return = EXCLUDED.recent_3m_return,
    recent_6m_return = EXCLUDED.recent_6m_return,
    recent_1y_return = EXCLUDED.recent_1y_return,
    max_drawdown = EXCLUDED.max_drawdown,
    sharpe_ratio = EXCLUDED.sharpe_ratio,
    sortino_ratio = EXCLUDED.sortino_ratio,
    total_trades = EXCLUDED.total_trades,
    win_rate = EXCLUDED.win_rate;

INSERT INTO frontend.strategy_monthly_returns (strategy_id, year, month, monthly_return) VALUES
    ('10000000-0000-4000-8000-000000000001', 2026, 1, 0.018000),
    ('10000000-0000-4000-8000-000000000001', 2026, 2, -0.006000),
    ('10000000-0000-4000-8000-000000000001', 2026, 3, 0.027000),
    ('10000000-0000-4000-8000-000000000001', 2026, 4, 0.023000),
    ('10000000-0000-4000-8000-000000000002', 2026, 1, 0.031000),
    ('10000000-0000-4000-8000-000000000002', 2026, 2, 0.014000),
    ('10000000-0000-4000-8000-000000000002', 2026, 3, -0.011000),
    ('10000000-0000-4000-8000-000000000002', 2026, 4, 0.054000),
    ('10000000-0000-4000-8000-000000000003', 2026, 1, 0.009000),
    ('10000000-0000-4000-8000-000000000003', 2026, 2, 0.004000),
    ('10000000-0000-4000-8000-000000000003', 2026, 3, 0.012000),
    ('10000000-0000-4000-8000-000000000003', 2026, 4, 0.009000)
ON CONFLICT (strategy_id, year, month) DO UPDATE SET
    monthly_return = EXCLUDED.monthly_return;

-- ------- orders, memberships, access -------
INSERT INTO frontend.orders (
    id, order_no, user_id, subtotal, discount_amount, total, currency,
    payment_source, payment_channel, payment_ref, status, paid_at, refunded_at,
    refund_reason, expire_at, created_at
) VALUES
    ('40000000-0000-4000-8000-000000000001', 'MOCK-ORD-20260420-0001', '00000000-0000-4000-8000-000000000002', 299.00, 0.00, 299.00, 'CNY', 'wechat', 'wechat_pay', 'mock_pay_ref_0001', 'paid', '2026-04-20 10:10:00+08', NULL, NULL, NULL, '2026-04-20 10:00:00+08'),
    ('40000000-0000-4000-8000-000000000002', 'MOCK-ORD-20260421-0002', '00000000-0000-4000-8000-000000000002', 199.00, 0.00, 199.00, 'CNY', 'alipay', 'alipay', 'mock_pay_ref_0002', 'paid', '2026-04-21 11:10:00+08', NULL, NULL, NULL, '2026-04-21 11:00:00+08'),
    ('40000000-0000-4000-8000-000000000003', 'MOCK-ORD-20260422-0003', '00000000-0000-4000-8000-000000000003', 399.00, 40.00, 359.00, 'CNY', 'wechat', 'wechat_pay', 'mock_pay_ref_0003', 'paid', '2026-04-22 11:10:00+08', NULL, NULL, NULL, '2026-04-22 11:00:00+08'),
    ('40000000-0000-4000-8000-000000000004', 'MOCK-ORD-20260428-0004', '00000000-0000-4000-8000-000000000003', 399.00, 0.00, 399.00, 'CNY', 'wechat', 'wechat_pay', NULL, 'pending', NULL, NULL, NULL, '2026-04-28 23:59:00+08', '2026-04-28 15:00:00+08')
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
    refunded_at = EXCLUDED.refunded_at,
    refund_reason = EXCLUDED.refund_reason,
    expire_at = EXCLUDED.expire_at;

INSERT INTO frontend.order_items (
    id, order_id, item_type, item_id, item_name, unit_price, quantity,
    subtotal, plan_type, duration_days, meta
) VALUES
    ('41000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000001', 'membership', '41000000-0000-4000-8000-000000000101', 'Pro 月度会员', 299.00, 1, 299.00, 'monthly', 30, '{"plan_id":2,"level":2}'),
    ('41000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000002', 'strategy_subscription', '10000000-0000-4000-8000-000000000002', '股指期货价差回归月度订阅', 199.00, 1, 199.00, 'monthly', 30, '{"strategy_code":"STR_FUT_MR_001"}'),
    ('41000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000003', 'strategy_payg', '10000000-0000-4000-8000-000000000002', '股指期货价差回归90天访问权', 399.00, 1, 399.00, NULL, 90, '{"strategy_code":"STR_FUT_MR_001","discount":"mock_coupon"}'),
    ('41000000-0000-4000-8000-000000000004', '40000000-0000-4000-8000-000000000004', 'strategy_subscription', '10000000-0000-4000-8000-000000000003', '宏观多资产配置月度订阅', 399.00, 1, 399.00, 'monthly', 30, '{"strategy_code":"STR_MACRO_ALLOC_001"}')
ON CONFLICT (id) DO UPDATE SET
    order_id = EXCLUDED.order_id,
    item_type = EXCLUDED.item_type,
    item_id = EXCLUDED.item_id,
    item_name = EXCLUDED.item_name,
    unit_price = EXCLUDED.unit_price,
    quantity = EXCLUDED.quantity,
    subtotal = EXCLUDED.subtotal,
    plan_type = EXCLUDED.plan_type,
    duration_days = EXCLUDED.duration_days,
    meta = EXCLUDED.meta;

INSERT INTO frontend.user_memberships (
    id, user_id, plan_id, started_at, expires_at, auto_renew, status, source_order_id, created_at
) VALUES
    (900001, '00000000-0000-4000-8000-000000000002', 2, '2026-04-20 10:10:00+08', '2026-05-20 23:59:59+08', TRUE, 'active', '40000000-0000-4000-8000-000000000001', '2026-04-20 10:10:00+08'),
    (900002, '00000000-0000-4000-8000-000000000003', 1, '2026-03-01 10:10:00+08', '2026-03-31 23:59:59+08', FALSE, 'expired', NULL, '2026-03-01 10:10:00+08')
ON CONFLICT (id) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    plan_id = EXCLUDED.plan_id,
    started_at = EXCLUDED.started_at,
    expires_at = EXCLUDED.expires_at,
    auto_renew = EXCLUDED.auto_renew,
    status = EXCLUDED.status,
    source_order_id = EXCLUDED.source_order_id;

INSERT INTO frontend.strategy_access_grants (
    id, user_id, strategy_id, source_order_id, expires_at, created_at
) VALUES
    ('42000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000003', '2026-07-21 23:59:59+08', '2026-04-22 11:10:00+08')
ON CONFLICT (user_id, strategy_id) DO UPDATE SET
    source_order_id = EXCLUDED.source_order_id,
    expires_at = EXCLUDED.expires_at,
    created_at = EXCLUDED.created_at;

INSERT INTO frontend.user_strategy_subscriptions (
    id, user_id, strategy_id, plan_type, status, auto_renew, start_date,
    expire_date, source_order_id, cancelled_at, cancel_reason, created_at, updated_at
) VALUES
    ('43000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002', 'monthly', 'active', TRUE, '2026-04-21', '2026-05-21', '40000000-0000-4000-8000-000000000002', NULL, NULL, '2026-04-21 11:10:00+08', '2026-04-21 11:10:00+08'),
    ('43000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000003', 'monthly', 'pending_payment', FALSE, '2026-04-28', '2026-05-28', '40000000-0000-4000-8000-000000000004', NULL, NULL, '2026-04-28 15:00:00+08', '2026-04-28 15:00:00+08')
ON CONFLICT DO NOTHING;

-- ------- signals -------
INSERT INTO frontend.signal_batches (
    id, strategy_id, batch_code, note, published_at, created_at
) VALUES
    ('20000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', 'MOCK-STR-A-TREND-20260424-B01', '趋势策略本周调仓批次。', '2026-04-24 09:35:00+08', '2026-04-24 09:35:00+08'),
    ('20000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002', 'MOCK-STR-FUT-MR-20260427-B01', '价差回归实盘信号批次。', '2026-04-27 09:45:00+08', '2026-04-27 09:45:00+08'),
    ('20000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000003', 'MOCK-STR-MACRO-20260428-B01', '月度宏观配置调整。', '2026-04-28 09:40:00+08', '2026-04-28 09:40:00+08')
ON CONFLICT (batch_code) DO UPDATE SET
    strategy_id = EXCLUDED.strategy_id,
    note = EXCLUDED.note,
    published_at = EXCLUDED.published_at;

INSERT INTO frontend.signals (
    id, signal_code, strategy_id, batch_id, parent_signal_id, market, exchange,
    symbol, symbol_name, type, action, direction, entry_low, entry_high,
    trigger_price, target_price, stop_loss_price, suggested_quantity,
    position_pct, confidence, urgency, reason, reason_detail, logic_summary,
    option_type, strike_price, expiry_date, greeks, access_tier, delay_free_hours,
    status, expire_at, published_at, result, exit_price, pnl_pct, resolved_at, created_at
) VALUES
    ('30000000-0000-4000-8000-000000000001', 'MOCK-SIG-20260424-0001', '10000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000001', NULL, 'A股', 'SZSE', '300750.SZ', '宁德时代', 'entry', 'buy', 'long', 185.0000, 189.0000, 187.2000, 205.0000, 178.0000, 100, 0.1200, 0.76, 'normal', '价格重新站上20日均线。', '{"ma20":184.7,"volume_ratio":1.35,"trigger_rule":"close_above_ma20"}', '趋势恢复，建议分批建立底仓。', NULL, NULL, NULL, NULL, 0, NULL, 'active', '2026-05-08 15:00:00+08', '2026-04-24 09:40:00+08', NULL, NULL, NULL, NULL, '2026-04-24 09:40:00+08'),
    ('30000000-0000-4000-8000-000000000002', 'MOCK-SIG-20260427-0002', '10000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000002', NULL, '期货', 'CFFEX', 'IF2506', '沪深300股指期货2506', 'entry', 'open', 'short', 3860.0000, 3880.0000, 3872.0000, 3790.0000, 3915.0000, 2, 0.1800, 0.82, 'high', 'IF/IC 价差 z-score 高于入场阈值。', '{"spread_current":1.84,"z_score":2.18,"entry_z":2.0}', '价差进入高位区间，建议开仓等待回归。', NULL, NULL, NULL, NULL, 2, NULL, 'active', '2026-04-30 15:15:00+08', '2026-04-27 09:50:00+08', NULL, NULL, NULL, NULL, '2026-04-27 09:50:00+08'),
    ('30000000-0000-4000-8000-000000000003', 'MOCK-SIG-20260427-0003', '10000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000002', '期货', 'CFFEX', 'IF2506', '沪深300股指期货2506', 'exit', 'close', 'short', NULL, NULL, 3806.0000, NULL, NULL, 2, 0.0000, 0.73, 'normal', '价差回归到目标区间。', '{"spread_current":0.42,"z_score":0.38,"exit_rule":"spread_reverted"}', '价差已回归，建议平仓锁定收益。', NULL, NULL, NULL, NULL, 2, NULL, 'expired', '2026-04-28 15:15:00+08', '2026-04-28 10:20:00+08', 'win', 3806.0000, 0.0170, '2026-04-28 10:20:00+08', '2026-04-28 10:20:00+08'),
    ('30000000-0000-4000-8000-000000000004', 'MOCK-SIG-20260428-0004', '10000000-0000-4000-8000-000000000003', '20000000-0000-4000-8000-000000000003', NULL, 'A股', 'SSE', '510300.SH', '沪深300ETF', 'adjust', 'add', 'long', NULL, NULL, 4.1200, 4.3500, 3.9800, 5000, 0.0800, 0.68, 'normal', '宏观状态切换到温和复苏。', '{"growth":"recovering","inflation":"stable","liquidity":"neutral"}', '权益权重小幅上调，验证高等级内容锁定。', NULL, NULL, NULL, NULL, 3, 24, 'active', '2026-05-28 15:00:00+08', '2026-04-28 09:45:00+08', NULL, NULL, NULL, NULL, '2026-04-28 09:45:00+08')
ON CONFLICT (signal_code) DO UPDATE SET
    strategy_id = EXCLUDED.strategy_id,
    batch_id = EXCLUDED.batch_id,
    parent_signal_id = EXCLUDED.parent_signal_id,
    market = EXCLUDED.market,
    exchange = EXCLUDED.exchange,
    symbol = EXCLUDED.symbol,
    symbol_name = EXCLUDED.symbol_name,
    type = EXCLUDED.type,
    action = EXCLUDED.action,
    direction = EXCLUDED.direction,
    trigger_price = EXCLUDED.trigger_price,
    target_price = EXCLUDED.target_price,
    stop_loss_price = EXCLUDED.stop_loss_price,
    confidence = EXCLUDED.confidence,
    urgency = EXCLUDED.urgency,
    reason = EXCLUDED.reason,
    reason_detail = EXCLUDED.reason_detail,
    logic_summary = EXCLUDED.logic_summary,
    access_tier = EXCLUDED.access_tier,
    delay_free_hours = EXCLUDED.delay_free_hours,
    status = EXCLUDED.status,
    expire_at = EXCLUDED.expire_at,
    result = EXCLUDED.result,
    exit_price = EXCLUDED.exit_price,
    pnl_pct = EXCLUDED.pnl_pct,
    resolved_at = EXCLUDED.resolved_at;

INSERT INTO frontend.signal_market_snapshot (
    signal_id, symbol, snapshot_time, open, high, low, close, volume, turnover,
    open_interest, basis, indicators, implied_vol, greeks_snapshot
) VALUES
    ('30000000-0000-4000-8000-000000000001', '300750.SZ', '2026-04-24 09:40:00+08', 184.8000, 188.6000, 184.2000, 187.2000, 32680000, 6110000000.0000, NULL, NULL, '{"ma5":184.1,"ma20":184.7,"rsi_14":61.2,"atr_14":5.8}', NULL, NULL),
    ('30000000-0000-4000-8000-000000000002', 'IF2506', '2026-04-27 09:50:00+08', 3864.2000, 3878.6000, 3858.4000, 3872.0000, 84210, 32590000000.0000, 112540, 18.4000, '{"ma5":3858.2,"ma20":3826.7,"rsi_14":67.9,"spread_z":2.18}', NULL, NULL),
    ('30000000-0000-4000-8000-000000000003', 'IF2506', '2026-04-28 10:20:00+08', 3820.0000, 3826.8000, 3798.2000, 3806.0000, 92500, 35210000000.0000, 109880, 4.2000, '{"ma5":3832.1,"ma20":3829.4,"rsi_14":48.6,"spread_z":0.38}', NULL, NULL),
    ('30000000-0000-4000-8000-000000000004', '510300.SH', '2026-04-28 09:45:00+08', 4.0800, 4.1300, 4.0700, 4.1200, 208000000, 856000000.0000, NULL, NULL, '{"ma5":4.08,"ma20":4.02,"rsi_14":58.4,"macd":0.03}', NULL, NULL)
ON CONFLICT (signal_id, symbol, snapshot_time) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    turnover = EXCLUDED.turnover,
    open_interest = EXCLUDED.open_interest,
    basis = EXCLUDED.basis,
    indicators = EXCLUDED.indicators,
    implied_vol = EXCLUDED.implied_vol,
    greeks_snapshot = EXCLUDED.greeks_snapshot;

INSERT INTO frontend.user_signal_reads (
    user_id, signal_id, read_at, is_executed, executed_price, executed_qty, executed_at, note
) VALUES
    ('00000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000001', '2026-04-24 10:05:00+08', FALSE, NULL, NULL, NULL, '已读公开信号。'),
    ('00000000-0000-4000-8000-000000000002', '30000000-0000-4000-8000-000000000002', '2026-04-27 10:00:00+08', TRUE, 3870.5000, 2, '2026-04-27 10:02:00+08', '跟随执行，滑点较小。'),
    ('00000000-0000-4000-8000-000000000003', '30000000-0000-4000-8000-000000000001', '2026-04-24 11:00:00+08', FALSE, NULL, NULL, NULL, '免费用户已读。')
ON CONFLICT (user_id, signal_id) DO UPDATE SET
    read_at = EXCLUDED.read_at,
    is_executed = EXCLUDED.is_executed,
    executed_price = EXCLUDED.executed_price,
    executed_qty = EXCLUDED.executed_qty,
    executed_at = EXCLUDED.executed_at,
    note = EXCLUDED.note;

INSERT INTO frontend.user_signal_settings (
    user_id, push_enabled, channels, confidence_threshold, urgency_filter,
    quiet_hours, trading_hours_only, updated_at
) VALUES
    ('00000000-0000-4000-8000-000000000002', TRUE, '{"app_push":true,"sms":false,"email":true,"wechat_service":true,"websocket":true}', 0.60, ARRAY['normal','high','critical'], '{"enabled":true,"start":"22:30","end":"08:45"}', TRUE, '2026-04-28 09:00:00+08'),
    ('00000000-0000-4000-8000-000000000003', TRUE, '{"app_push":true,"sms":false,"email":false,"wechat_service":false,"websocket":true}', 0.70, ARRAY['high','critical'], '{"enabled":false,"start":"22:00","end":"08:30"}', FALSE, '2026-04-28 09:05:00+08')
ON CONFLICT (user_id) DO UPDATE SET
    push_enabled = EXCLUDED.push_enabled,
    channels = EXCLUDED.channels,
    confidence_threshold = EXCLUDED.confidence_threshold,
    urgency_filter = EXCLUDED.urgency_filter,
    quiet_hours = EXCLUDED.quiet_hours,
    trading_hours_only = EXCLUDED.trading_hours_only,
    updated_at = EXCLUDED.updated_at;

INSERT INTO frontend.user_strategy_signal_settings (
    user_id, strategy_id, push_enabled, confidence_threshold, notify_entry_only, updated_at
) VALUES
    ('00000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002', TRUE, 0.65, FALSE, '2026-04-28 09:10:00+08'),
    ('00000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000001', TRUE, NULL, TRUE, '2026-04-28 09:12:00+08')
ON CONFLICT (user_id, strategy_id) DO UPDATE SET
    push_enabled = EXCLUDED.push_enabled,
    confidence_threshold = EXCLUDED.confidence_threshold,
    notify_entry_only = EXCLUDED.notify_entry_only,
    updated_at = EXCLUDED.updated_at;

-- ------- articles -------
INSERT INTO frontend.articles (
    id, author_id, title, summary, content, cover_url, type, access_tier,
    delay_free_hours, view_count, like_count, status, published_at, created_at, updated_at
) VALUES
    ('50000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000001', '如何阅读策略净值曲线', '介绍净值、回撤和基准对比的阅读方式。', '净值曲线用于观察策略长期收益和风险变化。', 'https://cdn.getrich.com/mock/articles/equity-curve.png', 'knowledge', 0, NULL, 2380, 128, 'published', '2026-04-18 09:00:00+08', '2026-04-15 09:00:00+08', '2026-04-18 09:00:00+08'),
    ('50000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001', '股指期货价差周报', '本周 IF/IC 价差波动扩大，关注回归机会。', '价差偏离来自市场风格切换和短期资金冲击。', 'https://cdn.getrich.com/mock/articles/spread-weekly.png', 'weekly_review', 2, 48, 860, 42, 'published', '2026-04-26 20:00:00+08', '2026-04-25 18:00:00+08', '2026-04-26 20:00:00+08')
ON CONFLICT (id) DO UPDATE SET
    author_id = EXCLUDED.author_id,
    title = EXCLUDED.title,
    summary = EXCLUDED.summary,
    content = EXCLUDED.content,
    cover_url = EXCLUDED.cover_url,
    type = EXCLUDED.type,
    access_tier = EXCLUDED.access_tier,
    delay_free_hours = EXCLUDED.delay_free_hours,
    view_count = EXCLUDED.view_count,
    like_count = EXCLUDED.like_count,
    status = EXCLUDED.status,
    published_at = EXCLUDED.published_at,
    updated_at = EXCLUDED.updated_at;

INSERT INTO frontend.article_tags (article_id, tag_id) VALUES
    ('50000000-0000-4000-8000-000000000001', 106),
    ('50000000-0000-4000-8000-000000000002', 102),
    ('50000000-0000-4000-8000-000000000002', 104)
ON CONFLICT DO NOTHING;

INSERT INTO frontend.article_likes (user_id, article_id, created_at) VALUES
    ('00000000-0000-4000-8000-000000000002', '50000000-0000-4000-8000-000000000001', '2026-04-18 10:00:00+08'),
    ('00000000-0000-4000-8000-000000000003', '50000000-0000-4000-8000-000000000001', '2026-04-18 10:05:00+08'),
    ('00000000-0000-4000-8000-000000000002', '50000000-0000-4000-8000-000000000002', '2026-04-26 21:00:00+08')
ON CONFLICT DO NOTHING;

INSERT INTO frontend.article_comments (
    id, article_id, user_id, parent_id, content, like_count, status, created_at, updated_at
) VALUES
    ('80000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002', NULL, '净值和回撤的示例很适合新用户理解。', 1, 1, '2026-04-18 10:10:00+08', '2026-04-18 10:10:00+08'),
    ('80000000-0000-4000-8000-000000000002', '50000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000001', '80000000-0000-4000-8000-000000000001', '后续会补充排序指标的使用说明。', 0, 1, '2026-04-18 10:20:00+08', '2026-04-18 10:20:00+08'),
    ('80000000-0000-4000-8000-000000000003', '50000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000003', NULL, '免费用户看到摘要后可以用于验证解锁提示。', 0, 1, '2026-04-26 21:20:00+08', '2026-04-26 21:20:00+08')
ON CONFLICT (id) DO UPDATE SET
    article_id = EXCLUDED.article_id,
    user_id = EXCLUDED.user_id,
    parent_id = EXCLUDED.parent_id,
    content = EXCLUDED.content,
    like_count = EXCLUDED.like_count,
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at;

INSERT INTO frontend.comment_likes (user_id, comment_id, created_at) VALUES
    ('00000000-0000-4000-8000-000000000003', '80000000-0000-4000-8000-000000000001', '2026-04-18 10:30:00+08')
ON CONFLICT DO NOTHING;

-- ------- tools -------
INSERT INTO frontend.tools (
    id, slug, name, description, type, config, access_tier, is_active, created_at
) VALUES
    ('60000000-0000-4000-8000-000000000001', 'position-size-calculator', '仓位计算器', '根据账户规模、止损和风险预算计算建议仓位。', 'calculator', '{"default_risk_pct":0.01,"markets":["stock","future"]}', 0, TRUE, '2026-04-01 08:00:00+08'),
    ('60000000-0000-4000-8000-000000000002', 'signal-scanner', '信号扫描器', '按策略、市场、置信度扫描近期信号。', 'scanner', '{"min_confidence":0.6,"default_window_days":7}', 2, TRUE, '2026-04-01 08:00:00+08')
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    type = EXCLUDED.type,
    config = EXCLUDED.config,
    access_tier = EXCLUDED.access_tier,
    is_active = EXCLUDED.is_active;

INSERT INTO frontend.tool_usage_logs (
    id, tool_id, user_id, params, created_at
) VALUES
    (900001, '60000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000003', '{"symbol":"300750.SZ","capital":100000,"risk_pct":0.01}', '2026-04-28 10:00:00+08'),
    (900002, '60000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000002', '{"strategy_id":"10000000-0000-4000-8000-000000000002","min_confidence":0.7}', '2026-04-28 10:05:00+08')
ON CONFLICT (id) DO UPDATE SET
    tool_id = EXCLUDED.tool_id,
    user_id = EXCLUDED.user_id,
    params = EXCLUDED.params,
    created_at = EXCLUDED.created_at;

-- 避免显式写入 serial/bigserial 后，后续默认序列值撞到 mock 主键。
SELECT setval(pg_get_serial_sequence('frontend.user_auth', 'id'), GREATEST((SELECT MAX(id) FROM frontend.user_auth), 1), TRUE);
SELECT setval(pg_get_serial_sequence('frontend.verification_codes', 'id'), GREATEST((SELECT MAX(id) FROM frontend.verification_codes), 1), TRUE);
SELECT setval(pg_get_serial_sequence('frontend.tags', 'id'), GREATEST((SELECT MAX(id) FROM frontend.tags), 1), TRUE);
SELECT setval(pg_get_serial_sequence('frontend.membership_plans', 'id'), GREATEST((SELECT MAX(id) FROM frontend.membership_plans), 1), TRUE);
SELECT setval(pg_get_serial_sequence('frontend.user_memberships', 'id'), GREATEST((SELECT MAX(id) FROM frontend.user_memberships), 1), TRUE);
SELECT setval(pg_get_serial_sequence('frontend.tool_usage_logs', 'id'), GREATEST((SELECT MAX(id) FROM frontend.tool_usage_logs), 1), TRUE);

COMMIT;
