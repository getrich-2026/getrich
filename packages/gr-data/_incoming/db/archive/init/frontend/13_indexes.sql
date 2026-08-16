-- ============================================================
-- 非主键索引统一管理
-- ============================================================

-- ------- strategies -------
CREATE INDEX idx_strategies_category        ON frontend.strategies(category_id);
CREATE INDEX idx_strategies_asset_status    ON frontend.strategies(asset_class, pub_status)
    WHERE pub_status = 'published';
CREATE INDEX idx_strategies_type            ON frontend.strategies(type);
CREATE INDEX idx_strategies_run_status      ON frontend.strategies(run_status)
    WHERE run_status IN ('paper','live');
CREATE INDEX idx_strategies_author          ON frontend.strategies(author_id, created_at DESC);
CREATE INDEX idx_strategies_published       ON frontend.strategies(published_at DESC)
    WHERE pub_status = 'published';
-- 关键词搜索
CREATE INDEX idx_strategies_name_trgm       ON frontend.strategies USING GIN (name gin_trgm_ops);

-- ------- strategy_tags -------
CREATE INDEX idx_strategy_tags_tag          ON frontend.strategy_tags(tag_id);

-- ------- strategy_follows -------
CREATE INDEX idx_strategy_follows_strategy  ON frontend.strategy_follows(strategy_id);

-- ------- 时序表 -------
CREATE INDEX idx_equity_curve_strategy_date ON frontend.strategy_equity_curve(strategy_id, trade_date DESC);
CREATE INDEX idx_perf_snapshot_latest       ON frontend.strategy_performance_snapshot(strategy_id, snapshot_date DESC);
-- 支持"按最新快照排序策略列表"（sharpe 倒序、max_drawdown 升序等）
CREATE INDEX idx_perf_snapshot_sharpe       ON frontend.strategy_performance_snapshot(snapshot_date DESC, sharpe_ratio DESC);
CREATE INDEX idx_perf_snapshot_annual       ON frontend.strategy_performance_snapshot(snapshot_date DESC, annualized_return DESC);

-- ------- signals -------
CREATE INDEX idx_signals_strategy_time      ON frontend.signals(strategy_id, published_at DESC);
CREATE INDEX idx_signals_symbol_time        ON frontend.signals(symbol, published_at DESC);
CREATE INDEX idx_signals_access             ON frontend.signals(access_tier, published_at);
CREATE INDEX idx_signals_status_expire      ON frontend.signals(status, expire_at)
    WHERE status = 'active';
CREATE INDEX idx_signals_type_action        ON frontend.signals(type, action);
CREATE INDEX idx_signals_batch              ON frontend.signals(batch_id)
    WHERE batch_id IS NOT NULL;
CREATE INDEX idx_signals_parent             ON frontend.signals(parent_signal_id)
    WHERE parent_signal_id IS NOT NULL;

-- ------- signal_market_snapshot -------
CREATE INDEX idx_market_snapshot_signal     ON frontend.signal_market_snapshot(signal_id);

-- ------- 用户信号状态 -------
CREATE INDEX idx_signal_reads_user_time     ON frontend.user_signal_reads(user_id, read_at DESC);
-- 未读信号查询（需要 user_id + signal_id 不存在）基于 PK 就够
-- 按策略统计未读数：用 signals.strategy_id + LEFT JOIN user_signal_reads

-- ------- 订阅与授权 -------
CREATE INDEX idx_grants_user                ON frontend.strategy_access_grants(user_id);
CREATE INDEX idx_grants_strategy            ON frontend.strategy_access_grants(strategy_id);
CREATE INDEX idx_strategy_subs_user         ON frontend.user_strategy_subscriptions(user_id, status);
CREATE INDEX idx_strategy_subs_expire       ON frontend.user_strategy_subscriptions(expire_date)
    WHERE status = 'active' AND auto_renew = TRUE;

-- ------- 会员 -------
CREATE INDEX idx_memberships_user           ON frontend.user_memberships(user_id, expires_at);

-- ------- 订单 -------
CREATE INDEX idx_orders_user                ON frontend.orders(user_id, created_at DESC);
CREATE INDEX idx_orders_status              ON frontend.orders(status, created_at DESC)
    WHERE status = 'pending';
CREATE INDEX idx_order_items_order          ON frontend.order_items(order_id);
CREATE INDEX idx_order_items_type_item      ON frontend.order_items(item_type, item_id);

-- ------- 文章 / 评论 -------
CREATE INDEX idx_articles_author            ON frontend.articles(author_id, published_at DESC);
CREATE INDEX idx_articles_published         ON frontend.articles(published_at DESC)
    WHERE status = 'published';
CREATE INDEX idx_articles_access            ON frontend.articles(access_tier, published_at);
CREATE INDEX idx_comments_article           ON frontend.article_comments(article_id, created_at DESC);
CREATE INDEX idx_comments_parent            ON frontend.article_comments(parent_id)
    WHERE parent_id IS NOT NULL;

-- ------- 工具使用 -------
CREATE INDEX idx_tool_logs_user_time        ON frontend.tool_usage_logs(user_id, created_at DESC);
CREATE INDEX idx_tool_logs_tool_time        ON frontend.tool_usage_logs(tool_id, created_at DESC);

-- ------- 用户认证 -------
CREATE INDEX idx_user_sessions_user         ON frontend.user_sessions(user_id, expires_at);
CREATE INDEX idx_user_sessions_expire       ON frontend.user_sessions(expires_at)
    WHERE revoked_at IS NULL;
CREATE INDEX idx_verification_target        ON frontend.verification_codes(target, purpose, expires_at);
