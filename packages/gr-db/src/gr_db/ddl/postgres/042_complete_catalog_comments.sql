-- 042_complete_catalog_comments.sql
-- 新库基线：显式补齐受管表的存量 catalog 注释，供静态门禁逐字段核对。
-- 2026-10-29 从一次性 PG18 初始化结果核对并展开原动态兜底；
-- 已有精确 COMMENT 保留在各定义文件，不再按通用列名猜测其他表或未来表。

-- app.order_items
COMMENT ON COLUMN app.order_items.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.order_items.duration_days IS 'order_items表的duration_days字段。';
COMMENT ON COLUMN app.order_items.id IS '记录的主键。';
COMMENT ON COLUMN app.order_items.item_id IS '关联的 item 标识。';
COMMENT ON COLUMN app.order_items.item_name IS 'order_items表的item_name字段。';
COMMENT ON COLUMN app.order_items.item_type IS 'order_items表的item_type字段。';
COMMENT ON COLUMN app.order_items.meta IS 'meta的结构化 JSON 数据。';
COMMENT ON COLUMN app.order_items.order_id IS '关联 app.orders 的订单 ID。';
COMMENT ON COLUMN app.order_items.plan_type IS 'order_items表的plan_type字段。';
COMMENT ON COLUMN app.order_items.quantity IS '数量。';
COMMENT ON COLUMN app.order_items.subtotal IS 'order_items表的subtotal字段。';
COMMENT ON COLUMN app.order_items.unit_price IS 'order_items表的unit_price字段。';

-- app.orders
COMMENT ON COLUMN app.orders.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.orders.currency IS '金额的币种代码。';
COMMENT ON COLUMN app.orders.expire_at IS '信号或订单失效时间。';
COMMENT ON COLUMN app.orders.id IS '记录的主键。';
COMMENT ON COLUMN app.orders.order_no IS 'orders表的order_no字段。';
COMMENT ON COLUMN app.orders.paid_at IS 'paid时间。';
COMMENT ON COLUMN app.orders.payment_ref IS 'orders表的payment_ref字段。';
COMMENT ON COLUMN app.orders.payment_source IS 'orders表的payment_source字段。';
COMMENT ON COLUMN app.orders.refunded_at IS 'refunded时间。';
COMMENT ON COLUMN app.orders.status IS '记录的当前状态。';
COMMENT ON COLUMN app.orders.subtotal IS 'orders表的subtotal字段。';
COMMENT ON COLUMN app.orders.total IS 'orders表的total字段。';
COMMENT ON COLUMN app.orders.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN app.orders.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- app.refresh_tokens
COMMENT ON COLUMN app.refresh_tokens.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.refresh_tokens.expires_at IS '记录或授权到期时间。';
COMMENT ON COLUMN app.refresh_tokens.id IS '记录的主键。';
COMMENT ON COLUMN app.refresh_tokens.token_hash IS 'refresh_tokens表的token_hash字段。';
COMMENT ON COLUMN app.refresh_tokens.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- app.signal_batches
COMMENT ON COLUMN app.signal_batches.batch_code IS 'signal_batches表的batch_code字段。';
COMMENT ON COLUMN app.signal_batches.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.signal_batches.id IS '记录的主键。';
COMMENT ON COLUMN app.signal_batches.note IS '人工备注。';
COMMENT ON COLUMN app.signal_batches.published_at IS '对外发布时间。';
COMMENT ON COLUMN app.signal_batches.strategy_id IS '关联 app.strategies 的策略 ID。';

-- app.signal_market_snapshot
COMMENT ON COLUMN app.signal_market_snapshot.basis IS 'signal_market_snapshot表的basis字段。';
COMMENT ON COLUMN app.signal_market_snapshot.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN app.signal_market_snapshot.greeks_snapshot IS '期权 Greeks 的 JSONB 快照。';
COMMENT ON COLUMN app.signal_market_snapshot.high IS '最高价。';
COMMENT ON COLUMN app.signal_market_snapshot.implied_vol IS 'signal_market_snapshot表的implied_vol字段。';
COMMENT ON COLUMN app.signal_market_snapshot.indicators IS '行情技术指标的 JSONB 快照。';
COMMENT ON COLUMN app.signal_market_snapshot.low IS '最低价。';
COMMENT ON COLUMN app.signal_market_snapshot.open IS '开盘价。';
COMMENT ON COLUMN app.signal_market_snapshot.open_interest IS '持仓量。';
COMMENT ON COLUMN app.signal_market_snapshot.signal_id IS '关联 app.signals 的信号 ID。';
COMMENT ON COLUMN app.signal_market_snapshot.snapshot_time IS 'snapshot_time时间戳。';
COMMENT ON COLUMN app.signal_market_snapshot.symbol IS '标的代码；格式与交易所后缀约定以所属业务表为准。';
COMMENT ON COLUMN app.signal_market_snapshot.turnover IS '换手额或成交额。';
COMMENT ON COLUMN app.signal_market_snapshot.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- app.signals
COMMENT ON COLUMN app.signals.access_tier IS 'signals表的access_tier字段。';
COMMENT ON COLUMN app.signals.action IS 'signals表的action字段。';
COMMENT ON COLUMN app.signals.batch_id IS '关联所属批次的唯一标识。';
COMMENT ON COLUMN app.signals.confidence IS '信号置信度。';
COMMENT ON COLUMN app.signals.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.signals.delay_free_hours IS 'signals表的delay_free_hours字段。';
COMMENT ON COLUMN app.signals.direction IS 'signals表的direction字段。';
COMMENT ON COLUMN app.signals.entry_high IS '建议入场价格区间上限。';
COMMENT ON COLUMN app.signals.entry_low IS '建议入场价格区间下限。';
COMMENT ON COLUMN app.signals.exchange IS '交易所代码；具体编码体系以所属表契约为准。';
COMMENT ON COLUMN app.signals.exit_price IS 'signals表的exit_price字段。';
COMMENT ON COLUMN app.signals.expire_at IS '信号或订单失效时间。';
COMMENT ON COLUMN app.signals.expiry_date IS '期权到期日。';
COMMENT ON COLUMN app.signals.greeks IS '期权 Greeks 的 JSONB 快照。';
COMMENT ON COLUMN app.signals.id IS '记录的主键。';
COMMENT ON COLUMN app.signals.logic_summary IS 'signals表的logic_summary字段。';
COMMENT ON COLUMN app.signals.market IS '所属市场。';
COMMENT ON COLUMN app.signals.option_type IS '期权类型：认购或认沽。';
COMMENT ON COLUMN app.signals.parent_signal_id IS '关联的 parent_signal 标识。';
COMMENT ON COLUMN app.signals.pnl_pct IS '盈亏百分比。';
COMMENT ON COLUMN app.signals.position_pct IS '建议仓位占比。';
COMMENT ON COLUMN app.signals.published_at IS '对外发布时间。';
COMMENT ON COLUMN app.signals.reason IS '信号或状态变更原因。';
COMMENT ON COLUMN app.signals.reason_detail IS '信号原因的结构化明细。';
COMMENT ON COLUMN app.signals.resolved_at IS 'resolved时间。';
COMMENT ON COLUMN app.signals.result IS 'signals表的result字段。';
COMMENT ON COLUMN app.signals.signal_code IS 'signals表的signal_code字段。';
COMMENT ON COLUMN app.signals.status IS '记录的当前状态。';
COMMENT ON COLUMN app.signals.stop_loss_price IS '止损价格。';
COMMENT ON COLUMN app.signals.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.signals.strike_price IS '期权行权价。';
COMMENT ON COLUMN app.signals.suggested_quantity IS 'signals表的suggested_quantity字段。';
COMMENT ON COLUMN app.signals.symbol IS '标的代码；格式与交易所后缀约定以所属业务表为准。';
COMMENT ON COLUMN app.signals.symbol_name IS '证券展示名称。';
COMMENT ON COLUMN app.signals.target_price IS '目标价格。';
COMMENT ON COLUMN app.signals.trigger_price IS '触发价格。';
COMMENT ON COLUMN app.signals.type IS '业务对象类型。';
COMMENT ON COLUMN app.signals.urgency IS 'signals表的urgency字段。';

-- app.strategies
COMMENT ON COLUMN app.strategies.asset_class IS '资产大类。';
COMMENT ON COLUMN app.strategies.author_id IS '关联的 author 标识。';
COMMENT ON COLUMN app.strategies.backtest_end IS 'backtest_end日期。';
COMMENT ON COLUMN app.strategies.backtest_start IS 'backtest_start日期。';
COMMENT ON COLUMN app.strategies.category_id IS '关联的 category 标识。';
COMMENT ON COLUMN app.strategies.cover_image IS 'strategies表的cover_image字段。';
COMMENT ON COLUMN app.strategies.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.strategies.description IS '文字说明。';
COMMENT ON COLUMN app.strategies.detail_html IS '经清洗后用于展示的详情 HTML。';
COMMENT ON COLUMN app.strategies.id IS '记录的主键。';
COMMENT ON COLUMN app.strategies.market IS '所属市场。';
COMMENT ON COLUMN app.strategies.name IS '展示名称。';
COMMENT ON COLUMN app.strategies.pub_status IS 'strategies表的pub_status字段。';
COMMENT ON COLUMN app.strategies.published_at IS '对外发布时间。';
COMMENT ON COLUMN app.strategies.risk_level IS '风险等级。';
COMMENT ON COLUMN app.strategies.run_status IS 'strategies表的run_status字段。';
COMMENT ON COLUMN app.strategies.strategy_code IS 'strategies表的strategy_code字段。';
COMMENT ON COLUMN app.strategies.subscriber_count IS 'strategies表的subscriber_count字段。';
COMMENT ON COLUMN app.strategies.subscription_monthly IS 'strategies表的subscription_monthly字段。';
COMMENT ON COLUMN app.strategies.subscription_yearly IS 'strategies表的subscription_yearly字段。';
COMMENT ON COLUMN app.strategies.summary IS '简要说明。';
COMMENT ON COLUMN app.strategies.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN app.strategies.web IS 'web的布尔状态标记。';

-- app.strategy_access_grants
COMMENT ON COLUMN app.strategy_access_grants.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.strategy_access_grants.expires_at IS '记录或授权到期时间。';
COMMENT ON COLUMN app.strategy_access_grants.id IS '记录的主键。';
COMMENT ON COLUMN app.strategy_access_grants.source_order_id IS '关联授权来源订单的 ID。';
COMMENT ON COLUMN app.strategy_access_grants.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.strategy_access_grants.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- app.strategy_categories
COMMENT ON COLUMN app.strategy_categories.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.strategy_categories.description IS '文字说明。';
COMMENT ON COLUMN app.strategy_categories.icon_url IS 'strategy_categories表的icon_url字段。';
COMMENT ON COLUMN app.strategy_categories.id IS '记录的主键。';
COMMENT ON COLUMN app.strategy_categories.name IS '展示名称。';
COMMENT ON COLUMN app.strategy_categories.sort_order IS 'strategy_categories表的sort_order字段。';

-- app.strategy_equity_curve
COMMENT ON COLUMN app.strategy_equity_curve.benchmark_nav IS 'strategy_equity_curve表的benchmark_nav字段。';
COMMENT ON COLUMN app.strategy_equity_curve.cumulative_return IS 'strategy_equity_curve表的cumulative_return字段。';
COMMENT ON COLUMN app.strategy_equity_curve.daily_return IS '单日收益率。';
COMMENT ON COLUMN app.strategy_equity_curve.drawdown IS 'strategy_equity_curve表的drawdown字段。';
COMMENT ON COLUMN app.strategy_equity_curve.nav IS '单位净值或策略净值。';
COMMENT ON COLUMN app.strategy_equity_curve.position_ratio IS '实际仓位占比。';
COMMENT ON COLUMN app.strategy_equity_curve.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.strategy_equity_curve.trade_date IS '成交或统计所属日期。';

-- app.strategy_monthly_returns
COMMENT ON COLUMN app.strategy_monthly_returns.month IS 'strategy_monthly_returns表的month字段。';
COMMENT ON COLUMN app.strategy_monthly_returns.monthly_return IS '单月收益率。';
COMMENT ON COLUMN app.strategy_monthly_returns.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.strategy_monthly_returns.year IS 'strategy_monthly_returns表的year字段。';

-- app.strategy_performance_snapshot
COMMENT ON COLUMN app.strategy_performance_snapshot.alpha IS '相对基准的 Alpha 收益。';
COMMENT ON COLUMN app.strategy_performance_snapshot.annualized_return IS '年化收益率。';
COMMENT ON COLUMN app.strategy_performance_snapshot.annualized_volatility IS '年化波动率。';
COMMENT ON COLUMN app.strategy_performance_snapshot.avg_holding_days IS 'strategy_performance_snapshot表的avg_holding_days字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.avg_loss IS 'strategy_performance_snapshot表的avg_loss字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.avg_win IS 'strategy_performance_snapshot表的avg_win字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.beta IS '相对基准的 Beta 系数。';
COMMENT ON COLUMN app.strategy_performance_snapshot.calmar_ratio IS '卡玛比率。';
COMMENT ON COLUMN app.strategy_performance_snapshot.cvar_95 IS 'strategy_performance_snapshot表的cvar_95字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.downside_deviation IS 'strategy_performance_snapshot表的downside_deviation字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.information_ratio IS 'strategy_performance_snapshot表的information_ratio字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.max_consecutive_losses IS 'strategy_performance_snapshot表的max_consecutive_losses字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.max_consecutive_wins IS 'strategy_performance_snapshot表的max_consecutive_wins字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.max_drawdown IS '最大回撤。';
COMMENT ON COLUMN app.strategy_performance_snapshot.max_drawdown_end IS 'max_drawdown_end日期。';
COMMENT ON COLUMN app.strategy_performance_snapshot.max_drawdown_recovery IS 'max_drawdown_recovery日期。';
COMMENT ON COLUMN app.strategy_performance_snapshot.max_drawdown_start IS 'max_drawdown_start日期。';
COMMENT ON COLUMN app.strategy_performance_snapshot.profit_factor IS 'strategy_performance_snapshot表的profit_factor字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.recent_1m_return IS 'strategy_performance_snapshot表的recent_1m_return字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.recent_1y_return IS 'strategy_performance_snapshot表的recent_1y_return字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.recent_3m_return IS 'strategy_performance_snapshot表的recent_3m_return字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.recent_6m_return IS 'strategy_performance_snapshot表的recent_6m_return字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.sharpe_ratio IS '夏普比率。';
COMMENT ON COLUMN app.strategy_performance_snapshot.snapshot_date IS 'snapshot日期。';
COMMENT ON COLUMN app.strategy_performance_snapshot.sortino_ratio IS '索提诺比率。';
COMMENT ON COLUMN app.strategy_performance_snapshot.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.strategy_performance_snapshot.total_return IS '累计收益率。';
COMMENT ON COLUMN app.strategy_performance_snapshot.total_trades IS 'strategy_performance_snapshot表的total_trades字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.var_95 IS 'strategy_performance_snapshot表的var_95字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.win_rate IS 'strategy_performance_snapshot表的win_rate字段。';
COMMENT ON COLUMN app.strategy_performance_snapshot.ytd_return IS 'strategy_performance_snapshot表的ytd_return字段。';

-- app.strategy_sub_account_mapping
COMMENT ON COLUMN app.strategy_sub_account_mapping.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.strategy_sub_account_mapping.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.strategy_sub_account_mapping.sub_account_id IS '关联的 sub_account 标识。';
COMMENT ON COLUMN app.strategy_sub_account_mapping.updated_at IS '记录最后更新时间。';

-- app.strategy_tags
COMMENT ON COLUMN app.strategy_tags.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.strategy_tags.tag_id IS '关联的 tag 标识。';

-- app.strategy_trades
COMMENT ON COLUMN app.strategy_trades.action IS 'strategy_trades表的action字段。';
COMMENT ON COLUMN app.strategy_trades.avg_cost IS 'strategy_trades表的avg_cost字段。';
COMMENT ON COLUMN app.strategy_trades.bar_dt IS 'K 线事件时间。';
COMMENT ON COLUMN app.strategy_trades.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.strategy_trades.cumulative_pnl IS 'strategy_trades表的cumulative_pnl字段。';
COMMENT ON COLUMN app.strategy_trades.executed_at IS '订单或成交实际执行时间。';
COMMENT ON COLUMN app.strategy_trades.fee IS '手续费金额。';
COMMENT ON COLUMN app.strategy_trades.id IS '记录的主键。';
COMMENT ON COLUMN app.strategy_trades.notional IS '名义金额。';
COMMENT ON COLUMN app.strategy_trades.price IS '价格。';
COMMENT ON COLUMN app.strategy_trades.quantity IS '数量。';
COMMENT ON COLUMN app.strategy_trades.realized_pnl IS '已实现盈亏。';
COMMENT ON COLUMN app.strategy_trades.signal_id IS '关联 app.signals 的信号 ID。';
COMMENT ON COLUMN app.strategy_trades.slippage IS '滑点成本。';
COMMENT ON COLUMN app.strategy_trades.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.strategy_trades.symbol IS '标的代码；格式与交易所后缀约定以所属业务表为准。';
COMMENT ON COLUMN app.strategy_trades.tag IS 'strategy_trades表的tag字段。';

-- app.tags
COMMENT ON COLUMN app.tags.id IS '记录的主键。';
COMMENT ON COLUMN app.tags.name IS '展示名称。';
COMMENT ON COLUMN app.tags.slug IS 'tags表的slug字段。';
COMMENT ON COLUMN app.tags.tag_group IS 'tags表的tag_group字段。';

-- app.user_auth
COMMENT ON COLUMN app.user_auth.auth_type IS 'user_auth表的auth_type字段。';
COMMENT ON COLUMN app.user_auth.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.user_auth.credential IS 'user_auth表的credential字段。';
COMMENT ON COLUMN app.user_auth.id IS '记录的主键。';
COMMENT ON COLUMN app.user_auth.identifier IS 'user_auth表的identifier字段。';
COMMENT ON COLUMN app.user_auth.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';
COMMENT ON COLUMN app.user_auth.verified IS '认证信息是否已验证。';

-- app.user_signal_reads
COMMENT ON COLUMN app.user_signal_reads.executed_at IS '订单或成交实际执行时间。';
COMMENT ON COLUMN app.user_signal_reads.executed_price IS 'user_signal_reads表的executed_price字段。';
COMMENT ON COLUMN app.user_signal_reads.executed_qty IS 'user_signal_reads表的executed_qty字段。';
COMMENT ON COLUMN app.user_signal_reads.is_executed IS '是否已经执行。';
COMMENT ON COLUMN app.user_signal_reads.note IS '人工备注。';
COMMENT ON COLUMN app.user_signal_reads.read_at IS 'read时间。';
COMMENT ON COLUMN app.user_signal_reads.signal_id IS '关联 app.signals 的信号 ID。';
COMMENT ON COLUMN app.user_signal_reads.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- app.user_signal_settings
COMMENT ON COLUMN app.user_signal_settings.channels IS '通知渠道配置。';
COMMENT ON COLUMN app.user_signal_settings.confidence_threshold IS 'user_signal_settings表的confidence_threshold字段。';
COMMENT ON COLUMN app.user_signal_settings.push_enabled IS '是否启用推送通知。';
COMMENT ON COLUMN app.user_signal_settings.quiet_hours IS '免打扰时间段配置。';
COMMENT ON COLUMN app.user_signal_settings.trading_hours_only IS 'trading_hours_only的布尔状态标记。';
COMMENT ON COLUMN app.user_signal_settings.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN app.user_signal_settings.urgency_filter IS 'user_signal_settings表的urgency_filter字段。';
COMMENT ON COLUMN app.user_signal_settings.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- app.user_strategy_signal_settings
COMMENT ON COLUMN app.user_strategy_signal_settings.confidence_threshold IS 'user_strategy_signal_settings表的confidence_threshold字段。';
COMMENT ON COLUMN app.user_strategy_signal_settings.notify_entry_only IS 'notify_entry_only的布尔状态标记。';
COMMENT ON COLUMN app.user_strategy_signal_settings.push_enabled IS '是否启用推送通知。';
COMMENT ON COLUMN app.user_strategy_signal_settings.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.user_strategy_signal_settings.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN app.user_strategy_signal_settings.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- app.user_strategy_subscriptions
COMMENT ON COLUMN app.user_strategy_subscriptions.auto_renew IS 'auto_renew的布尔状态标记。';
COMMENT ON COLUMN app.user_strategy_subscriptions.cancel_reason IS 'user_strategy_subscriptions表的cancel_reason字段。';
COMMENT ON COLUMN app.user_strategy_subscriptions.cancelled_at IS 'cancelled时间。';
COMMENT ON COLUMN app.user_strategy_subscriptions.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.user_strategy_subscriptions.expire_date IS 'expire日期。';
COMMENT ON COLUMN app.user_strategy_subscriptions.id IS '记录的主键。';
COMMENT ON COLUMN app.user_strategy_subscriptions.plan_type IS 'user_strategy_subscriptions表的plan_type字段。';
COMMENT ON COLUMN app.user_strategy_subscriptions.source_order_id IS '关联授权来源订单的 ID。';
COMMENT ON COLUMN app.user_strategy_subscriptions.start_date IS '数据或任务覆盖范围的起始日期。';
COMMENT ON COLUMN app.user_strategy_subscriptions.status IS '记录的当前状态。';
COMMENT ON COLUMN app.user_strategy_subscriptions.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN app.user_strategy_subscriptions.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN app.user_strategy_subscriptions.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- app.users
COMMENT ON TABLE app.users IS '应用业务表：users。';
COMMENT ON COLUMN app.users.created_at IS '记录创建时间。';
COMMENT ON COLUMN app.users.email IS 'users表的email字段。';
COMMENT ON COLUMN app.users.id IS '记录的主键。';
COMMENT ON COLUMN app.users.is_active IS '是否处于有效状态。';
COMMENT ON COLUMN app.users.name IS '展示名称。';
COMMENT ON COLUMN app.users.password IS 'users表的password字段。';
COMMENT ON COLUMN app.users.updated_at IS '记录最后更新时间。';

-- backtest.backtest_artifacts
COMMENT ON COLUMN backtest.backtest_artifacts.artifact_type IS 'backtest_artifacts表的artifact_type字段。';
COMMENT ON COLUMN backtest.backtest_artifacts.checksum IS '文件内容校验和。';
COMMENT ON COLUMN backtest.backtest_artifacts.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_artifacts.id IS '记录的主键。';
COMMENT ON COLUMN backtest.backtest_artifacts.meta IS 'meta的结构化 JSON 数据。';
COMMENT ON COLUMN backtest.backtest_artifacts.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN backtest.backtest_artifacts.uri IS '产物或文件的存储 URI。';

-- backtest.backtest_equity_points
COMMENT ON COLUMN backtest.backtest_equity_points.cash IS 'backtest_equity_points表的cash字段。';
COMMENT ON COLUMN backtest.backtest_equity_points.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_equity_points.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN backtest.backtest_equity_points.equity IS 'backtest_equity_points表的equity字段。';
COMMENT ON COLUMN backtest.backtest_equity_points.gross_exposure IS 'backtest_equity_points表的gross_exposure字段。';
COMMENT ON COLUMN backtest.backtest_equity_points.mtm_pnl IS 'backtest_equity_points表的mtm_pnl字段。';
COMMENT ON COLUMN backtest.backtest_equity_points.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN backtest.backtest_equity_points.strategy_name IS 'backtest_equity_points表的strategy_name字段。';
COMMENT ON COLUMN backtest.backtest_equity_points.total_fees IS 'backtest_equity_points表的total_fees字段。';
COMMENT ON COLUMN backtest.backtest_equity_points.trading_pnl IS 'backtest_equity_points表的trading_pnl字段。';

-- backtest.backtest_final_positions
COMMENT ON COLUMN backtest.backtest_final_positions.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_final_positions.position_json IS 'position_json的结构化 JSON 数据。';
COMMENT ON COLUMN backtest.backtest_final_positions.qty IS '数量。';
COMMENT ON COLUMN backtest.backtest_final_positions.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN backtest.backtest_final_positions.symbol IS '标的代码；格式与交易所后缀约定以所属业务表为准。';

-- backtest.backtest_jobs
COMMENT ON COLUMN backtest.backtest_jobs.completed_at IS '任务或计算完成时间。';
COMMENT ON COLUMN backtest.backtest_jobs.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_jobs.error_message IS '失败错误信息。';
COMMENT ON COLUMN backtest.backtest_jobs.job_id IS '关联的 job 标识。';
COMMENT ON COLUMN backtest.backtest_jobs.started_at IS '任务或计算开始时间。';
COMMENT ON COLUMN backtest.backtest_jobs.updated_at IS '记录最后更新时间。';

-- backtest.backtest_metrics
COMMENT ON COLUMN backtest.backtest_metrics.annualized_return IS '年化收益率。';
COMMENT ON COLUMN backtest.backtest_metrics.annualized_volatility IS '年化波动率。';
COMMENT ON COLUMN backtest.backtest_metrics.calmar_ratio IS '卡玛比率。';
COMMENT ON COLUMN backtest.backtest_metrics.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_metrics.log_return IS 'backtest_metrics表的log_return字段。';
COMMENT ON COLUMN backtest.backtest_metrics.max_drawdown IS '最大回撤。';
COMMENT ON COLUMN backtest.backtest_metrics.max_drawdown_duration IS 'backtest_metrics表的max_drawdown_duration字段。';
COMMENT ON COLUMN backtest.backtest_metrics.metrics_json IS 'metrics_json的结构化 JSON 数据。';
COMMENT ON COLUMN backtest.backtest_metrics.n_bars IS 'backtest_metrics表的n_bars字段。';
COMMENT ON COLUMN backtest.backtest_metrics.risk_free_rate IS 'backtest_metrics表的risk_free_rate字段。';
COMMENT ON COLUMN backtest.backtest_metrics.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN backtest.backtest_metrics.sharpe_ratio IS '夏普比率。';
COMMENT ON COLUMN backtest.backtest_metrics.sortino_ratio IS '索提诺比率。';
COMMENT ON COLUMN backtest.backtest_metrics.total_fees IS 'backtest_metrics表的total_fees字段。';
COMMENT ON COLUMN backtest.backtest_metrics.total_return IS '累计收益率。';
COMMENT ON COLUMN backtest.backtest_metrics.total_trades IS 'backtest_metrics表的total_trades字段。';
COMMENT ON COLUMN backtest.backtest_metrics.total_turnover IS 'backtest_metrics表的total_turnover字段。';
COMMENT ON COLUMN backtest.backtest_metrics.trading_days_per_year IS 'backtest_metrics表的trading_days_per_year字段。';
COMMENT ON COLUMN backtest.backtest_metrics.turnover_rate IS '换手率。';

-- backtest.backtest_runs
COMMENT ON COLUMN backtest.backtest_runs.benchmark_final_equity IS 'backtest_runs表的benchmark_final_equity字段。';
COMMENT ON COLUMN backtest.backtest_runs.completed_at IS '任务或计算完成时间。';
COMMENT ON COLUMN backtest.backtest_runs.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_runs.end_at IS 'end时间。';
COMMENT ON COLUMN backtest.backtest_runs.error_message IS '失败错误信息。';
COMMENT ON COLUMN backtest.backtest_runs.final_cash IS 'backtest_runs表的final_cash字段。';
COMMENT ON COLUMN backtest.backtest_runs.final_equity IS 'backtest_runs表的final_equity字段。';
COMMENT ON COLUMN backtest.backtest_runs.freq IS 'backtest_runs表的freq字段。';
COMMENT ON COLUMN backtest.backtest_runs.initial_cash IS 'backtest_runs表的initial_cash字段。';
COMMENT ON COLUMN backtest.backtest_runs.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN backtest.backtest_runs.start_at IS 'start时间。';
COMMENT ON COLUMN backtest.backtest_runs.status IS '记录的当前状态。';
COMMENT ON COLUMN backtest.backtest_runs.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN backtest.backtest_runs.strategy_name IS 'backtest_runs表的strategy_name字段。';
COMMENT ON COLUMN backtest.backtest_runs.strategy_names IS 'strategy_names的结构化 JSON 数据。';
COMMENT ON COLUMN backtest.backtest_runs.symbols IS 'symbols的结构化 JSON 数据。';
COMMENT ON COLUMN backtest.backtest_runs.updated_at IS '记录最后更新时间。';

-- backtest.backtest_sweep_trials
COMMENT ON COLUMN backtest.backtest_sweep_trials.completed_at IS '任务或计算完成时间。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.error_message IS '失败错误信息。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.param_fingerprint IS 'backtest_sweep_trials表的param_fingerprint字段。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.status IS '记录的当前状态。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.sweep_id IS '关联的 sweep 标识。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.trial_id IS '关联的 trial 标识。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.trial_index IS 'backtest_sweep_trials表的trial_index字段。';
COMMENT ON COLUMN backtest.backtest_sweep_trials.updated_at IS '记录最后更新时间。';

-- backtest.backtest_sweeps
COMMENT ON COLUMN backtest.backtest_sweeps.best_metric_value IS 'backtest_sweeps表的best_metric_value字段。';
COMMENT ON COLUMN backtest.backtest_sweeps.best_run_id IS '关联的 best_run 标识。';
COMMENT ON COLUMN backtest.backtest_sweeps.best_trial_id IS '关联的 best_trial 标识。';
COMMENT ON COLUMN backtest.backtest_sweeps.completed_at IS '任务或计算完成时间。';
COMMENT ON COLUMN backtest.backtest_sweeps.completed_trials IS 'backtest_sweeps表的completed_trials字段。';
COMMENT ON COLUMN backtest.backtest_sweeps.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_sweeps.failed_trials IS 'backtest_sweeps表的failed_trials字段。';
COMMENT ON COLUMN backtest.backtest_sweeps.maximize IS 'maximize的布尔状态标记。';
COMMENT ON COLUMN backtest.backtest_sweeps.search_type IS 'backtest_sweeps表的search_type字段。';
COMMENT ON COLUMN backtest.backtest_sweeps.select_metric IS 'backtest_sweeps表的select_metric字段。';
COMMENT ON COLUMN backtest.backtest_sweeps.status IS '记录的当前状态。';
COMMENT ON COLUMN backtest.backtest_sweeps.sweep_id IS '关联的 sweep 标识。';
COMMENT ON COLUMN backtest.backtest_sweeps.total_trials IS 'backtest_sweeps表的total_trials字段。';
COMMENT ON COLUMN backtest.backtest_sweeps.updated_at IS '记录最后更新时间。';

-- backtest.backtest_walk_forward_windows
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.best_run_id IS '关联的 best_run 标识。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.best_trial_id IS '关联的 best_trial 标识。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.completed_at IS '任务或计算完成时间。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.error_message IS '失败错误信息。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.status IS '记录的当前状态。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.train_end IS 'train_end时间戳。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.train_metric_value IS 'backtest_walk_forward_windows表的train_metric_value字段。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.train_start IS 'train_start时间戳。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.train_sweep_id IS '关联的 train_sweep 标识。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.val_end IS 'val_end时间戳。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.val_start IS 'val_start时间戳。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.validation_metric_value IS 'backtest_walk_forward_windows表的validation_metric_value字段。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.validation_run_id IS '关联的 validation_run 标识。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.walk_forward_id IS '关联的 walk_forward 标识。';
COMMENT ON COLUMN backtest.backtest_walk_forward_windows.window_index IS 'backtest_walk_forward_windows表的window_index字段。';

-- backtest.backtest_walk_forwards
COMMENT ON COLUMN backtest.backtest_walk_forwards.completed_at IS '任务或计算完成时间。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.completed_windows IS 'backtest_walk_forwards表的completed_windows字段。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.created_at IS '记录创建时间。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.failed_windows IS 'backtest_walk_forwards表的failed_windows字段。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.maximize IS 'maximize的布尔状态标记。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.mean_validation_metric IS 'backtest_walk_forwards表的mean_validation_metric字段。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.refit IS 'backtest_walk_forwards表的refit字段。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.search_type IS 'backtest_walk_forwards表的search_type字段。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.select_metric IS 'backtest_walk_forwards表的select_metric字段。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.status IS '记录的当前状态。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.total_windows IS 'backtest_walk_forwards表的total_windows字段。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN backtest.backtest_walk_forwards.walk_forward_id IS '关联的 walk_forward 标识。';

-- classify.industry_node
COMMENT ON COLUMN classify.industry_node.updated_at IS '记录最后更新时间。';

-- classify.instrument_industry
COMMENT ON COLUMN classify.instrument_industry.available_at IS '该行业归属可供下游使用的时间；回溯归因不得早于此时刻使用。';
COMMENT ON COLUMN classify.instrument_industry.source IS '行业归属数据来源。';
COMMENT ON COLUMN classify.instrument_industry.updated_at IS '记录最后更新时间。';

-- classify.instrument_category
COMMENT ON COLUMN classify.instrument_category.updated_at IS '记录最后更新时间。';

-- classify.scheme
COMMENT ON COLUMN classify.scheme.updated_at IS '记录最后更新时间。';

-- diag.data_version
COMMENT ON COLUMN diag.data_version.created_at IS '记录创建时间。';
COMMENT ON COLUMN diag.data_version.data_version_id IS '关联的 data_version 标识。';
COMMENT ON COLUMN diag.data_version.schemas_covered IS 'data_version表的schemas_covered字段。';
COMMENT ON COLUMN diag.data_version.snapshot_at IS 'snapshot时间。';

-- diag.diagnosis_run
COMMENT ON TABLE diag.diagnosis_run IS '持仓诊断数据表：diagnosis_run。';
COMMENT ON COLUMN diag.diagnosis_run.computed_at IS 'computed时间。';
COMMENT ON COLUMN diag.diagnosis_run.created_at IS '记录创建时间。';
COMMENT ON COLUMN diag.diagnosis_run.data_fingerprint IS 'diagnosis_run表的data_fingerprint字段。';
COMMENT ON COLUMN diag.diagnosis_run.data_quality IS 'data_quality的结构化 JSON 数据。';
COMMENT ON COLUMN diag.diagnosis_run.error_reason IS 'diagnosis_run表的error_reason字段。';
COMMENT ON COLUMN diag.diagnosis_run.payload_schema_version IS 'diagnosis_run表的payload_schema_version字段。';
COMMENT ON COLUMN diag.diagnosis_run.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN diag.diagnosis_run.spec_version IS 'diagnosis_run表的spec_version字段。';
COMMENT ON COLUMN diag.diagnosis_run.status IS '记录的当前状态。';

-- diag.portfolio_plan
COMMENT ON TABLE diag.portfolio_plan IS '持仓诊断数据表：portfolio_plan。';
COMMENT ON COLUMN diag.portfolio_plan.label IS 'portfolio_plan表的label字段。';
COMMENT ON COLUMN diag.portfolio_plan.plan_id IS '关联的 plan 标识。';
COMMENT ON COLUMN diag.portfolio_plan.plan_index IS 'portfolio_plan表的plan_index字段。';
COMMENT ON COLUMN diag.portfolio_plan.snapshot_id IS '关联的 snapshot 标识。';

-- diag.portfolio_snapshot
COMMENT ON TABLE diag.portfolio_snapshot IS '持仓诊断数据表：portfolio_snapshot。';
COMMENT ON COLUMN diag.portfolio_snapshot.created_at IS '记录创建时间。';
COMMENT ON COLUMN diag.portfolio_snapshot.expires_at IS '记录或授权到期时间。';
COMMENT ON COLUMN diag.portfolio_snapshot.idempotency_key IS 'portfolio_snapshot表的idempotency_key字段。';
COMMENT ON COLUMN diag.portfolio_snapshot.request_hash IS 'portfolio_snapshot表的request_hash字段。';
COMMENT ON COLUMN diag.portfolio_snapshot.requested_as_of_date IS 'requested_as_of日期。';
COMMENT ON COLUMN diag.portfolio_snapshot.requested_intent IS 'portfolio_snapshot表的requested_intent字段。';
COMMENT ON COLUMN diag.portfolio_snapshot.requested_payload IS 'requested_payload的结构化 JSON 数据。';
COMMENT ON COLUMN diag.portfolio_snapshot.requested_spec_version IS 'portfolio_snapshot表的requested_spec_version字段。';
COMMENT ON COLUMN diag.portfolio_snapshot.resolved_as_of_date IS 'resolved_as_of日期。';
COMMENT ON COLUMN diag.portfolio_snapshot.resolved_intent IS 'portfolio_snapshot表的resolved_intent字段。';
COMMENT ON COLUMN diag.portfolio_snapshot.resolved_spec_version IS 'portfolio_snapshot表的resolved_spec_version字段。';
COMMENT ON COLUMN diag.portfolio_snapshot.user_id IS '应用用户标识；具体类型及是否有外键由所属表定义。';

-- diag.share_token
COMMENT ON TABLE diag.share_token IS '持仓诊断数据表：share_token。';
COMMENT ON COLUMN diag.share_token.created_at IS '记录创建时间。';
COMMENT ON COLUMN diag.share_token.created_by IS 'share_token表的created_by字段。';
COMMENT ON COLUMN diag.share_token.expires_at IS '记录或授权到期时间。';
COMMENT ON COLUMN diag.share_token.revoked_at IS 'revoked时间。';
COMMENT ON COLUMN diag.share_token.snapshot_id IS '关联的 snapshot 标识。';
COMMENT ON COLUMN diag.share_token.token IS 'share_token表的token字段。';

-- diag.snapshot_run
COMMENT ON TABLE diag.snapshot_run IS '持仓诊断数据表：snapshot_run。';
COMMENT ON COLUMN diag.snapshot_run.created_at IS '记录创建时间。';
COMMENT ON COLUMN diag.snapshot_run.plan_index IS 'snapshot_run表的plan_index字段。';
COMMENT ON COLUMN diag.snapshot_run.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN diag.snapshot_run.snapshot_id IS '关联的 snapshot 标识。';

-- diag.spec_version
COMMENT ON TABLE diag.spec_version IS '持仓诊断数据表：spec_version。';
COMMENT ON COLUMN diag.spec_version.created_at IS '记录创建时间。';
COMMENT ON COLUMN diag.spec_version.effective_from IS 'effective_from日期。';
COMMENT ON COLUMN diag.spec_version.effective_to IS 'effective_to日期。';
COMMENT ON COLUMN diag.spec_version.factor_model_version IS 'spec_version表的factor_model_version字段。';
COMMENT ON COLUMN diag.spec_version.is_active IS '是否处于有效状态。';
COMMENT ON COLUMN diag.spec_version.spec_version IS 'spec_version表的spec_version字段。';

-- factor.covariance
COMMENT ON COLUMN factor.covariance.updated_at IS '记录最后更新时间。';

-- factor.exposure
COMMENT ON COLUMN factor.exposure.updated_at IS '记录最后更新时间。';

-- factor.factor_return
COMMENT ON COLUMN factor.factor_return.updated_at IS '记录最后更新时间。';

-- factor.model
COMMENT ON COLUMN factor.model.updated_at IS '记录最后更新时间。';

-- factor.model_run
COMMENT ON COLUMN factor.model_run.created_at IS '记录创建时间。';

-- factor.specific_return
COMMENT ON COLUMN factor.specific_return.updated_at IS '记录最后更新时间。';

-- factor.specific_risk
COMMENT ON COLUMN factor.specific_risk.updated_at IS '记录最后更新时间。';

-- factor.import_checkpoint
COMMENT ON TABLE factor.import_checkpoint IS '风险模型专用的观察级采集／导入检查点；绑定配置身份与成功收据，不代表通用采集水位。';
COMMENT ON COLUMN factor.import_checkpoint.dataset_name IS '供应商数据集名称。';
COMMENT ON COLUMN factor.import_checkpoint.partition_key IS 'import_checkpoint表的partition_key字段。';
COMMENT ON COLUMN factor.import_checkpoint.provider IS '数据供应商标识。';
COMMENT ON COLUMN factor.import_checkpoint.state IS '处理进度或运行状态。';
COMMENT ON COLUMN factor.import_checkpoint.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN factor.import_checkpoint.watermark_ts IS 'watermark_ts时间戳。';

-- fundamental.indicator_q
COMMENT ON COLUMN fundamental.indicator_q.updated_at IS '记录最后更新时间。';

-- fundamental.valuation_1d
COMMENT ON COLUMN fundamental.valuation_1d.updated_at IS '记录最后更新时间。';

-- market.adj_factor_ts
COMMENT ON COLUMN market.adj_factor_ts.updated_at IS '记录最后更新时间。';

-- market.etf_bar_1d
COMMENT ON TABLE market.etf_bar_1d IS '市场行情与参考数据表：etf_bar_1d。';
COMMENT ON COLUMN market.etf_bar_1d.adj_factor IS '复权因子。';
COMMENT ON COLUMN market.etf_bar_1d.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.etf_bar_1d.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.etf_bar_1d.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.etf_bar_1d.high IS '最高价。';
COMMENT ON COLUMN market.etf_bar_1d.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.etf_bar_1d.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.etf_bar_1d.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.etf_bar_1d.low IS '最低价。';
COMMENT ON COLUMN market.etf_bar_1d.open IS '开盘价。';
COMMENT ON COLUMN market.etf_bar_1d.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.etf_bar_1d.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.etf_bar_1d.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.etf_bar_1d.trading_status IS '交易状态。';
COMMENT ON COLUMN market.etf_bar_1d.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.etf_bar_1d.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.etf_bar_1m
COMMENT ON COLUMN market.etf_bar_1m.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.etf_bar_1m.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.etf_bar_1m.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.etf_bar_1m.high IS '最高价。';
COMMENT ON COLUMN market.etf_bar_1m.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.etf_bar_1m.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.etf_bar_1m.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.etf_bar_1m.low IS '最低价。';
COMMENT ON COLUMN market.etf_bar_1m.open IS '开盘价。';
COMMENT ON COLUMN market.etf_bar_1m.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.etf_bar_1m.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.etf_bar_1m.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.etf_bar_1m.trading_status IS '交易状态。';
COMMENT ON COLUMN market.etf_bar_1m.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.etf_bar_1m.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.etf_basket
COMMENT ON TABLE market.etf_basket IS '市场行情与参考数据表：etf_basket。';
COMMENT ON COLUMN market.etf_basket.cash_substitute_amount IS 'etf_basket表的cash_substitute_amount字段。';
COMMENT ON COLUMN market.etf_basket.cash_substitute_flag IS 'etf_basket表的cash_substitute_flag字段。';
COMMENT ON COLUMN market.etf_basket.cash_substitute_rate IS 'etf_basket表的cash_substitute_rate字段。';
COMMENT ON COLUMN market.etf_basket.component_instrument_id IS '关联的 component_instrument 标识。';
COMMENT ON COLUMN market.etf_basket.component_symbol IS 'etf_basket表的component_symbol字段。';
COMMENT ON COLUMN market.etf_basket.component_type IS 'etf_basket表的component_type字段。';
COMMENT ON COLUMN market.etf_basket.etf_instrument_id IS '关联的 etf_instrument 标识。';
COMMENT ON COLUMN market.etf_basket.pub_date IS 'pub日期。';
COMMENT ON COLUMN market.etf_basket.quantity IS '数量。';
COMMENT ON COLUMN market.etf_basket.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.etf_basket.redemption_substitute_amount IS 'etf_basket表的redemption_substitute_amount字段。';
COMMENT ON COLUMN market.etf_basket.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.etf_basket.sub_component_list IS 'etf_basket表的sub_component_list字段。';
COMMENT ON COLUMN market.etf_basket.subscription_substitute_amount IS 'etf_basket表的subscription_substitute_amount字段。';
COMMENT ON COLUMN market.etf_basket.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.etf_basket.unit IS 'etf_basket表的unit字段。';
COMMENT ON COLUMN market.etf_basket.updated_at IS '记录最后更新时间。';

-- market.etf_daily
COMMENT ON TABLE market.etf_daily IS '市场行情与参考数据表：etf_daily。';
COMMENT ON COLUMN market.etf_daily.accumulated_nav IS '累计净值。';
COMMENT ON COLUMN market.etf_daily.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.etf_daily.amplitude IS '日内振幅。';
COMMENT ON COLUMN market.etf_daily.backward_adjusted_close IS 'etf_daily表的backward_adjusted_close字段。';
COMMENT ON COLUMN market.etf_daily.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.etf_daily.day_change IS 'etf_daily表的day_change字段。';
COMMENT ON COLUMN market.etf_daily.day_change_rate IS 'etf_daily表的day_change_rate字段。';
COMMENT ON COLUMN market.etf_daily.delisting_date IS 'delisting日期。';
COMMENT ON COLUMN market.etf_daily.discount IS 'etf_daily表的discount字段。';
COMMENT ON COLUMN market.etf_daily.discount_rate IS 'etf_daily表的discount_rate字段。';
COMMENT ON COLUMN market.etf_daily.discount_ratio IS 'etf_daily表的discount_ratio字段。';
COMMENT ON COLUMN market.etf_daily.high IS '最高价。';
COMMENT ON COLUMN market.etf_daily.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.etf_daily.low IS '最低价。';
COMMENT ON COLUMN market.etf_daily.num_trades IS 'etf_daily表的num_trades字段。';
COMMENT ON COLUMN market.etf_daily.open IS '开盘价。';
COMMENT ON COLUMN market.etf_daily.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.etf_daily.premium_rate IS 'etf_daily表的premium_rate字段。';
COMMENT ON COLUMN market.etf_daily.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.etf_daily.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.etf_daily.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.etf_daily.trading_state IS '当日交易状态。';
COMMENT ON COLUMN market.etf_daily.turnover_rate IS '换手率。';
COMMENT ON COLUMN market.etf_daily.unit_nav IS '单位净值。';
COMMENT ON COLUMN market.etf_daily.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.etf_daily.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.etf_nav
COMMENT ON TABLE market.etf_nav IS '市场行情与参考数据表：etf_nav。';
COMMENT ON COLUMN market.etf_nav.accumulated_nav IS '累计净值。';
COMMENT ON COLUMN market.etf_nav.adjusted_nav IS 'etf_nav表的adjusted_nav字段。';
COMMENT ON COLUMN market.etf_nav.beta IS '相对基准的 Beta 系数。';
COMMENT ON COLUMN market.etf_nav.end_date IS '数据或任务覆盖范围的结束日期。';
COMMENT ON COLUMN market.etf_nav.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.etf_nav.jensen IS 'etf_nav表的jensen字段。';
COMMENT ON COLUMN market.etf_nav.nav_volatility IS 'etf_nav表的nav_volatility字段。';
COMMENT ON COLUMN market.etf_nav.r_squared IS 'etf_nav表的r_squared字段。';
COMMENT ON COLUMN market.etf_nav.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.etf_nav.return_1d IS 'etf_nav表的return_1d字段。';
COMMENT ON COLUMN market.etf_nav.return_1m IS 'etf_nav表的return_1m字段。';
COMMENT ON COLUMN market.etf_nav.return_1m_rank IS 'etf_nav表的return_1m_rank字段。';
COMMENT ON COLUMN market.etf_nav.return_1w IS 'etf_nav表的return_1w字段。';
COMMENT ON COLUMN market.etf_nav.return_1w_rank IS 'etf_nav表的return_1w_rank字段。';
COMMENT ON COLUMN market.etf_nav.return_1y IS 'etf_nav表的return_1y字段。';
COMMENT ON COLUMN market.etf_nav.return_1y_rank IS 'etf_nav表的return_1y_rank字段。';
COMMENT ON COLUMN market.etf_nav.return_3m IS 'etf_nav表的return_3m字段。';
COMMENT ON COLUMN market.etf_nav.return_3m_rank IS 'etf_nav表的return_3m_rank字段。';
COMMENT ON COLUMN market.etf_nav.return_3y IS 'etf_nav表的return_3y字段。';
COMMENT ON COLUMN market.etf_nav.return_5y IS 'etf_nav表的return_5y字段。';
COMMENT ON COLUMN market.etf_nav.return_6m IS 'etf_nav表的return_6m字段。';
COMMENT ON COLUMN market.etf_nav.return_6m_rank IS 'etf_nav表的return_6m_rank字段。';
COMMENT ON COLUMN market.etf_nav.return_since_listing IS 'etf_nav表的return_since_listing字段。';
COMMENT ON COLUMN market.etf_nav.return_ytd IS 'etf_nav表的return_ytd字段。';
COMMENT ON COLUMN market.etf_nav.return_ytd_rank IS 'etf_nav表的return_ytd_rank字段。';
COMMENT ON COLUMN market.etf_nav.sharpe IS 'etf_nav表的sharpe字段。';
COMMENT ON COLUMN market.etf_nav.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.etf_nav.treynor IS 'etf_nav表的treynor字段。';
COMMENT ON COLUMN market.etf_nav.unit_nav IS '单位净值。';
COMMENT ON COLUMN market.etf_nav.updated_at IS '记录最后更新时间。';

-- market.etf_redemption
COMMENT ON TABLE market.etf_redemption IS '市场行情与参考数据表：etf_redemption。';
COMMENT ON COLUMN market.etf_redemption.cash_difference IS 'etf_redemption表的cash_difference字段。';
COMMENT ON COLUMN market.etf_redemption.creation_limit IS 'etf_redemption表的creation_limit字段。';
COMMENT ON COLUMN market.etf_redemption.creation_redemption_unit IS 'etf_redemption表的creation_redemption_unit字段。';
COMMENT ON COLUMN market.etf_redemption.estimated_cash_difference IS 'etf_redemption表的estimated_cash_difference字段。';
COMMENT ON COLUMN market.etf_redemption.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.etf_redemption.iopv IS 'etf_redemption表的iopv字段。';
COMMENT ON COLUMN market.etf_redemption.max_cash_ratio IS 'etf_redemption表的max_cash_ratio字段。';
COMMENT ON COLUMN market.etf_redemption.nav_per_unit IS 'etf_redemption表的nav_per_unit字段。';
COMMENT ON COLUMN market.etf_redemption.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.etf_redemption.redemption_limit IS 'etf_redemption表的redemption_limit字段。';
COMMENT ON COLUMN market.etf_redemption.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.etf_redemption.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.etf_redemption.updated_at IS '记录最后更新时间。';

-- market.fund_daily
COMMENT ON TABLE market.fund_daily IS '市场行情与参考数据表：fund_daily。';
COMMENT ON COLUMN market.fund_daily.accumulated_nav IS '累计净值。';
COMMENT ON COLUMN market.fund_daily.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.fund_daily.amplitude IS '日内振幅。';
COMMENT ON COLUMN market.fund_daily.backward_adjusted_close IS 'fund_daily表的backward_adjusted_close字段。';
COMMENT ON COLUMN market.fund_daily.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.fund_daily.day_change IS 'fund_daily表的day_change字段。';
COMMENT ON COLUMN market.fund_daily.day_change_rate IS 'fund_daily表的day_change_rate字段。';
COMMENT ON COLUMN market.fund_daily.delisting_date IS 'delisting日期。';
COMMENT ON COLUMN market.fund_daily.discount IS 'fund_daily表的discount字段。';
COMMENT ON COLUMN market.fund_daily.discount_rate IS 'fund_daily表的discount_rate字段。';
COMMENT ON COLUMN market.fund_daily.discount_ratio IS 'fund_daily表的discount_ratio字段。';
COMMENT ON COLUMN market.fund_daily.high IS '最高价。';
COMMENT ON COLUMN market.fund_daily.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.fund_daily.low IS '最低价。';
COMMENT ON COLUMN market.fund_daily.num_trades IS 'fund_daily表的num_trades字段。';
COMMENT ON COLUMN market.fund_daily.open IS '开盘价。';
COMMENT ON COLUMN market.fund_daily.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.fund_daily.premium_rate IS 'fund_daily表的premium_rate字段。';
COMMENT ON COLUMN market.fund_daily.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.fund_daily.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.fund_daily.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.fund_daily.trading_state IS '当日交易状态。';
COMMENT ON COLUMN market.fund_daily.turnover_rate IS '换手率。';
COMMENT ON COLUMN market.fund_daily.unit_nav IS '单位净值。';
COMMENT ON COLUMN market.fund_daily.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.fund_daily.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.fund_nav
COMMENT ON TABLE market.fund_nav IS '市场行情与参考数据表：fund_nav。';
COMMENT ON COLUMN market.fund_nav.accumulated_nav IS '累计净值。';
COMMENT ON COLUMN market.fund_nav.adjusted_nav IS 'fund_nav表的adjusted_nav字段。';
COMMENT ON COLUMN market.fund_nav.beta IS '相对基准的 Beta 系数。';
COMMENT ON COLUMN market.fund_nav.end_date IS '数据或任务覆盖范围的结束日期。';
COMMENT ON COLUMN market.fund_nav.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.fund_nav.jensen IS 'fund_nav表的jensen字段。';
COMMENT ON COLUMN market.fund_nav.nav_volatility IS 'fund_nav表的nav_volatility字段。';
COMMENT ON COLUMN market.fund_nav.r_squared IS 'fund_nav表的r_squared字段。';
COMMENT ON COLUMN market.fund_nav.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.fund_nav.return_1d IS 'fund_nav表的return_1d字段。';
COMMENT ON COLUMN market.fund_nav.return_1m IS 'fund_nav表的return_1m字段。';
COMMENT ON COLUMN market.fund_nav.return_1m_rank IS 'fund_nav表的return_1m_rank字段。';
COMMENT ON COLUMN market.fund_nav.return_1w IS 'fund_nav表的return_1w字段。';
COMMENT ON COLUMN market.fund_nav.return_1w_rank IS 'fund_nav表的return_1w_rank字段。';
COMMENT ON COLUMN market.fund_nav.return_1y IS 'fund_nav表的return_1y字段。';
COMMENT ON COLUMN market.fund_nav.return_1y_rank IS 'fund_nav表的return_1y_rank字段。';
COMMENT ON COLUMN market.fund_nav.return_3m IS 'fund_nav表的return_3m字段。';
COMMENT ON COLUMN market.fund_nav.return_3m_rank IS 'fund_nav表的return_3m_rank字段。';
COMMENT ON COLUMN market.fund_nav.return_3y IS 'fund_nav表的return_3y字段。';
COMMENT ON COLUMN market.fund_nav.return_5y IS 'fund_nav表的return_5y字段。';
COMMENT ON COLUMN market.fund_nav.return_6m IS 'fund_nav表的return_6m字段。';
COMMENT ON COLUMN market.fund_nav.return_6m_rank IS 'fund_nav表的return_6m_rank字段。';
COMMENT ON COLUMN market.fund_nav.return_since_listing IS 'fund_nav表的return_since_listing字段。';
COMMENT ON COLUMN market.fund_nav.return_ytd IS 'fund_nav表的return_ytd字段。';
COMMENT ON COLUMN market.fund_nav.return_ytd_rank IS 'fund_nav表的return_ytd_rank字段。';
COMMENT ON COLUMN market.fund_nav.sharpe IS 'fund_nav表的sharpe字段。';
COMMENT ON COLUMN market.fund_nav.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.fund_nav.treynor IS 'fund_nav表的treynor字段。';
COMMENT ON COLUMN market.fund_nav.unit_nav IS '单位净值。';
COMMENT ON COLUMN market.fund_nav.updated_at IS '记录最后更新时间。';

-- market.future_bar_1d
COMMENT ON TABLE market.future_bar_1d IS '市场行情与参考数据表：future_bar_1d。';
COMMENT ON COLUMN market.future_bar_1d.adj_factor IS '复权因子。';
COMMENT ON COLUMN market.future_bar_1d.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.future_bar_1d.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.future_bar_1d.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.future_bar_1d.high IS '最高价。';
COMMENT ON COLUMN market.future_bar_1d.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.future_bar_1d.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.future_bar_1d.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.future_bar_1d.low IS '最低价。';
COMMENT ON COLUMN market.future_bar_1d.open IS '开盘价。';
COMMENT ON COLUMN market.future_bar_1d.open_interest IS '持仓量。';
COMMENT ON COLUMN market.future_bar_1d.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.future_bar_1d.pre_settle IS '前一交易日结算价。';
COMMENT ON COLUMN market.future_bar_1d.settle IS '结算价。';
COMMENT ON COLUMN market.future_bar_1d.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.future_bar_1d.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.future_bar_1d.trading_status IS '交易状态。';
COMMENT ON COLUMN market.future_bar_1d.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.future_bar_1d.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.future_bar_1m
COMMENT ON COLUMN market.future_bar_1m.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.future_bar_1m.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.future_bar_1m.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.future_bar_1m.high IS '最高价。';
COMMENT ON COLUMN market.future_bar_1m.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.future_bar_1m.is_dominant IS '是否dominant的布尔标记。';
COMMENT ON COLUMN market.future_bar_1m.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.future_bar_1m.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.future_bar_1m.low IS '最低价。';
COMMENT ON COLUMN market.future_bar_1m.open IS '开盘价。';
COMMENT ON COLUMN market.future_bar_1m.open_interest IS '持仓量。';
COMMENT ON COLUMN market.future_bar_1m.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.future_bar_1m.pre_settle IS '前一交易日结算价。';
COMMENT ON COLUMN market.future_bar_1m.settle IS '结算价。';
COMMENT ON COLUMN market.future_bar_1m.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.future_bar_1m.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.future_bar_1m.trading_status IS '交易状态。';
COMMENT ON COLUMN market.future_bar_1m.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.future_bar_1m.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.index_bar_1d
COMMENT ON TABLE market.index_bar_1d IS '市场行情与参考数据表：index_bar_1d。';
COMMENT ON COLUMN market.index_bar_1d.adj_factor IS '复权因子。';
COMMENT ON COLUMN market.index_bar_1d.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.index_bar_1d.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.index_bar_1d.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.index_bar_1d.high IS '最高价。';
COMMENT ON COLUMN market.index_bar_1d.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.index_bar_1d.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.index_bar_1d.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.index_bar_1d.low IS '最低价。';
COMMENT ON COLUMN market.index_bar_1d.open IS '开盘价。';
COMMENT ON COLUMN market.index_bar_1d.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.index_bar_1d.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.index_bar_1d.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.index_bar_1d.trading_status IS '交易状态。';
COMMENT ON COLUMN market.index_bar_1d.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.index_bar_1d.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.index_bar_1m
COMMENT ON COLUMN market.index_bar_1m.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.index_bar_1m.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.index_bar_1m.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.index_bar_1m.high IS '最高价。';
COMMENT ON COLUMN market.index_bar_1m.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.index_bar_1m.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.index_bar_1m.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.index_bar_1m.low IS '最低价。';
COMMENT ON COLUMN market.index_bar_1m.open IS '开盘价。';
COMMENT ON COLUMN market.index_bar_1m.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.index_bar_1m.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.index_bar_1m.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.index_bar_1m.trading_status IS '交易状态。';
COMMENT ON COLUMN market.index_bar_1m.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.index_bar_1m.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.index_component
COMMENT ON TABLE market.index_component IS '市场行情与参考数据表：index_component。';
COMMENT ON COLUMN market.index_component.component_instrument_id IS '关联的 component_instrument 标识。';
COMMENT ON COLUMN market.index_component.in_date IS 'in日期。';
COMMENT ON COLUMN market.index_component.index_instrument_id IS '关联的 index_instrument 标识。';
COMMENT ON COLUMN market.index_component.out_date IS 'out日期。';
COMMENT ON COLUMN market.index_component.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.index_component.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.index_component.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.index_component.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.index_component.weight IS '权重。';

-- market.option_bar_1d
COMMENT ON TABLE market.option_bar_1d IS '市场行情与参考数据表：option_bar_1d。';
COMMENT ON COLUMN market.option_bar_1d.adj_factor IS '复权因子。';
COMMENT ON COLUMN market.option_bar_1d.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.option_bar_1d.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.option_bar_1d.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.option_bar_1d.high IS '最高价。';
COMMENT ON COLUMN market.option_bar_1d.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.option_bar_1d.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.option_bar_1d.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.option_bar_1d.low IS '最低价。';
COMMENT ON COLUMN market.option_bar_1d.open IS '开盘价。';
COMMENT ON COLUMN market.option_bar_1d.open_interest IS '持仓量。';
COMMENT ON COLUMN market.option_bar_1d.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.option_bar_1d.pre_settle IS '前一交易日结算价。';
COMMENT ON COLUMN market.option_bar_1d.settle IS '结算价。';
COMMENT ON COLUMN market.option_bar_1d.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.option_bar_1d.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.option_bar_1d.trading_status IS '交易状态。';
COMMENT ON COLUMN market.option_bar_1d.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.option_bar_1d.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.option_bar_1m
COMMENT ON COLUMN market.option_bar_1m.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.option_bar_1m.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.option_bar_1m.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.option_bar_1m.high IS '最高价。';
COMMENT ON COLUMN market.option_bar_1m.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.option_bar_1m.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.option_bar_1m.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.option_bar_1m.low IS '最低价。';
COMMENT ON COLUMN market.option_bar_1m.open IS '开盘价。';
COMMENT ON COLUMN market.option_bar_1m.open_interest IS '持仓量。';
COMMENT ON COLUMN market.option_bar_1m.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.option_bar_1m.pre_settle IS '前一交易日结算价。';
COMMENT ON COLUMN market.option_bar_1m.settle IS '结算价。';
COMMENT ON COLUMN market.option_bar_1m.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.option_bar_1m.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.option_bar_1m.trading_status IS '交易状态。';
COMMENT ON COLUMN market.option_bar_1m.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.option_bar_1m.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.option_greeks_1d
COMMENT ON TABLE market.option_greeks_1d IS '市场行情与参考数据表：option_greeks_1d。';
COMMENT ON COLUMN market.option_greeks_1d.delta IS '期权 Delta。';
COMMENT ON COLUMN market.option_greeks_1d.gamma IS '期权 Gamma。';
COMMENT ON COLUMN market.option_greeks_1d.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.option_greeks_1d.iv IS '隐含波动率。';
COMMENT ON COLUMN market.option_greeks_1d.rho IS '期权 Rho。';
COMMENT ON COLUMN market.option_greeks_1d.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.option_greeks_1d.theta IS '期权 Theta。';
COMMENT ON COLUMN market.option_greeks_1d.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.option_greeks_1d.underlying_px IS 'option_greeks_1d表的underlying_px字段。';
COMMENT ON COLUMN market.option_greeks_1d.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.option_greeks_1d.vega IS '期权 Vega。';

-- market.stock_adj_factor
COMMENT ON TABLE market.stock_adj_factor IS '市场行情与参考数据表：stock_adj_factor。';
COMMENT ON COLUMN market.stock_adj_factor.b_xdy IS 'stock_adj_factor表的b_xdy字段。';
COMMENT ON COLUMN market.stock_adj_factor.begin_date IS 'begin日期。';
COMMENT ON COLUMN market.stock_adj_factor.f_xdy IS 'stock_adj_factor表的f_xdy字段。';
COMMENT ON COLUMN market.stock_adj_factor.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.stock_adj_factor.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.stock_adj_factor.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.stock_adj_factor.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.stock_adj_factor.xdy IS 'stock_adj_factor表的xdy字段。';

-- market.stock_bar_1d
COMMENT ON TABLE market.stock_bar_1d IS '市场行情与参考数据表：stock_bar_1d。';
COMMENT ON COLUMN market.stock_bar_1d.adj_factor IS '复权因子。';
COMMENT ON COLUMN market.stock_bar_1d.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.stock_bar_1d.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.stock_bar_1d.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.stock_bar_1d.high IS '最高价。';
COMMENT ON COLUMN market.stock_bar_1d.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.stock_bar_1d.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.stock_bar_1d.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.stock_bar_1d.low IS '最低价。';
COMMENT ON COLUMN market.stock_bar_1d.open IS '开盘价。';
COMMENT ON COLUMN market.stock_bar_1d.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.stock_bar_1d.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.stock_bar_1d.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.stock_bar_1d.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.stock_bar_1d.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.stock_bar_1m
COMMENT ON COLUMN market.stock_bar_1m.amount IS '成交额，单位为元。';
COMMENT ON COLUMN market.stock_bar_1m.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.stock_bar_1m.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN market.stock_bar_1m.high IS '最高价。';
COMMENT ON COLUMN market.stock_bar_1m.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.stock_bar_1m.limit_down IS '跌停参考价。';
COMMENT ON COLUMN market.stock_bar_1m.limit_up IS '涨停参考价。';
COMMENT ON COLUMN market.stock_bar_1m.low IS '最低价。';
COMMENT ON COLUMN market.stock_bar_1m.open IS '开盘价。';
COMMENT ON COLUMN market.stock_bar_1m.pre_close IS '前一交易日收盘价。';
COMMENT ON COLUMN market.stock_bar_1m.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.stock_bar_1m.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.stock_bar_1m.trading_status IS '交易状态。';
COMMENT ON COLUMN market.stock_bar_1m.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN market.stock_bar_1m.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- market.stock_valuation
COMMENT ON TABLE market.stock_valuation IS '市场行情与参考数据表：stock_valuation。';
COMMENT ON COLUMN market.stock_valuation.avg_amount_per_trade IS 'stock_valuation表的avg_amount_per_trade字段。';
COMMENT ON COLUMN market.stock_valuation.avg_price IS '平均成交价。';
COMMENT ON COLUMN market.stock_valuation.avg_volume_per_trade IS 'stock_valuation表的avg_volume_per_trade字段。';
COMMENT ON COLUMN market.stock_valuation.back_adjusted_close IS 'stock_valuation表的back_adjusted_close字段。';
COMMENT ON COLUMN market.stock_valuation.close IS '收盘价或最新收盘价。';
COMMENT ON COLUMN market.stock_valuation.float_market_cap IS 'stock_valuation表的float_market_cap字段。';
COMMENT ON COLUMN market.stock_valuation.front_adjusted_close IS 'stock_valuation表的front_adjusted_close字段。';
COMMENT ON COLUMN market.stock_valuation.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN market.stock_valuation.pb IS '市净率。';
COMMENT ON COLUMN market.stock_valuation.pc IS 'stock_valuation表的pc字段。';
COMMENT ON COLUMN market.stock_valuation.pc_ttm IS 'stock_valuation表的pc_ttm字段。';
COMMENT ON COLUMN market.stock_valuation.pe IS '市盈率。';
COMMENT ON COLUMN market.stock_valuation.pe_ttm IS '滚动市盈率。';
COMMENT ON COLUMN market.stock_valuation.ps IS '市销率。';
COMMENT ON COLUMN market.stock_valuation.ps_ttm IS 'stock_valuation表的ps_ttm字段。';
COMMENT ON COLUMN market.stock_valuation.raw_payload IS '保留供应商原始字段的 JSONB 载荷。';
COMMENT ON COLUMN market.stock_valuation.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN market.stock_valuation.total_market_cap IS 'stock_valuation表的total_market_cap字段。';
COMMENT ON COLUMN market.stock_valuation.trading_day IS '所属交易日。';
COMMENT ON COLUMN market.stock_valuation.updated_at IS '记录最后更新时间。';

-- meta.future_contracts
COMMENT ON TABLE meta.future_contracts IS '合约、代码映射与交易日历元数据表：future_contracts。';
COMMENT ON COLUMN meta.future_contracts.delivery_date IS 'delivery日期。';
COMMENT ON COLUMN meta.future_contracts.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN meta.future_contracts.last_trade_date IS 'last_trade日期。';
COMMENT ON COLUMN meta.future_contracts.list_date IS 'list日期。';
COMMENT ON COLUMN meta.future_contracts.multiplier IS 'future_contracts表的multiplier字段。';
COMMENT ON COLUMN meta.future_contracts.price_tick IS 'future_contracts表的price_tick字段。';
COMMENT ON COLUMN meta.future_contracts.underlying IS 'future_contracts表的underlying字段。';

-- meta.instruments
COMMENT ON TABLE meta.instruments IS '合约、代码映射与交易日历元数据表：instruments。';
COMMENT ON COLUMN meta.instruments.asset IS '金融资产品种。';
COMMENT ON COLUMN meta.instruments.created_at IS '记录创建时间。';
COMMENT ON COLUMN meta.instruments.delist_date IS 'delist日期。';
COMMENT ON COLUMN meta.instruments.exchange IS '交易所代码；具体编码体系以所属表契约为准。';
COMMENT ON COLUMN meta.instruments.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN meta.instruments.list_date IS 'list日期。';
COMMENT ON COLUMN meta.instruments.name IS '展示名称。';
COMMENT ON COLUMN meta.instruments.status IS '记录的当前状态。';
COMMENT ON COLUMN meta.instruments.symbol IS '带交易所后缀的规范证券代码。';
COMMENT ON COLUMN meta.instruments.updated_at IS '记录最后更新时间。';

-- meta.option_contracts
COMMENT ON TABLE meta.option_contracts IS '合约、代码映射与交易日历元数据表：option_contracts。';
COMMENT ON COLUMN meta.option_contracts.exercise_date IS 'exercise日期。';
COMMENT ON COLUMN meta.option_contracts.exercise_style IS 'option_contracts表的exercise_style字段。';
COMMENT ON COLUMN meta.option_contracts.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN meta.option_contracts.last_trade_date IS 'last_trade日期。';
COMMENT ON COLUMN meta.option_contracts.list_date IS 'list日期。';
COMMENT ON COLUMN meta.option_contracts.multiplier IS 'option_contracts表的multiplier字段。';
COMMENT ON COLUMN meta.option_contracts.option_type IS '期权类型：认购或认沽。';
COMMENT ON COLUMN meta.option_contracts.strike IS '期权行权价。';
COMMENT ON COLUMN meta.option_contracts.underlying_id IS '关联的 underlying 标识。';

-- meta.symbol_map
COMMENT ON COLUMN meta.symbol_map.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN meta.symbol_map.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN meta.symbol_map.source_symbol IS '供应商原始证券代码。';
COMMENT ON COLUMN meta.symbol_map.updated_at IS '记录最后更新时间。';

-- meta.trading_calendar
COMMENT ON TABLE meta.trading_calendar IS '合约、代码映射与交易日历元数据表：trading_calendar。';
COMMENT ON COLUMN meta.trading_calendar.exchange IS '交易所代码；具体编码体系以所属表契约为准。';
COMMENT ON COLUMN meta.trading_calendar.has_night IS 'has_night的布尔状态标记。';
COMMENT ON COLUMN meta.trading_calendar.is_open IS '该日是否开市。';
COMMENT ON COLUMN meta.trading_calendar.next_trading_day IS 'next_trading_day日期。';
COMMENT ON COLUMN meta.trading_calendar.prev_trading_day IS 'prev_trading_day日期。';
COMMENT ON COLUMN meta.trading_calendar.trading_day IS '所属交易日。';
COMMENT ON COLUMN meta.trading_calendar.updated_at IS '记录最后更新时间。';

-- ops.api_keys
COMMENT ON TABLE ops.api_keys IS '数据接入与平台运维表：api_keys。';
COMMENT ON COLUMN ops.api_keys.api_key_hash IS 'api_keys表的api_key_hash字段。';
COMMENT ON COLUMN ops.api_keys.created_at IS '记录创建时间。';
COMMENT ON COLUMN ops.api_keys.expires_at IS '记录或授权到期时间。';
COMMENT ON COLUMN ops.api_keys.key_id IS '关联的 key 标识。';
COMMENT ON COLUMN ops.api_keys.rate_limit IS 'api_keys表的rate_limit字段。';
COMMENT ON COLUMN ops.api_keys.revoked IS '是否已撤销。';
COMMENT ON COLUMN ops.api_keys.scopes IS 'api_keys表的scopes字段。';
COMMENT ON COLUMN ops.api_keys.user_id IS '关联 ops.users.user_id 的运维用户 ID。';

-- ops.data_quality_check
COMMENT ON TABLE ops.data_quality_check IS '跨供应商、跨数据集的通用质量结果与证据；不是风险模型专用表。';
COMMENT ON COLUMN ops.data_quality_check.check_id IS '本条质量记录的自增主键。';
COMMENT ON COLUMN ops.data_quality_check.created_at IS '记录创建时间。';
COMMENT ON COLUMN ops.data_quality_check.detail IS '检查或运行明细。';
COMMENT ON COLUMN ops.data_quality_check.rule IS '应用定义的质量检查规则标识；具体判定及否决语义由对应写入和消费代码约定。';
COMMENT ON COLUMN ops.data_quality_check.run_id IS '可空外键，关联 ops.etl_job_run.run_id；不是 factor.model_run 的 UUID。';
COMMENT ON COLUMN ops.data_quality_check.severity IS '质量记录级别：info／warn／error；此列本身不执行业务阻断。';

-- ops.dataset_catalog
COMMENT ON TABLE ops.dataset_catalog IS '数据接入与平台运维表：dataset_catalog。';
COMMENT ON COLUMN ops.dataset_catalog.asset IS '金融资产品种。';
COMMENT ON COLUMN ops.dataset_catalog.dataset_name IS '供应商数据集名称。';
COMMENT ON COLUMN ops.dataset_catalog.description IS '文字说明。';
COMMENT ON COLUMN ops.dataset_catalog.freq IS 'dataset_catalog表的freq字段。';
COMMENT ON COLUMN ops.dataset_catalog.permission_tier IS 'dataset_catalog表的permission_tier字段。';
COMMENT ON COLUMN ops.dataset_catalog.phase IS 'dataset_catalog表的phase字段。';
COMMENT ON COLUMN ops.dataset_catalog.provider IS '数据供应商标识。';
COMMENT ON COLUMN ops.dataset_catalog.source_method IS 'dataset_catalog表的source_method字段。';
COMMENT ON COLUMN ops.dataset_catalog.status IS '记录的当前状态。';
COMMENT ON COLUMN ops.dataset_catalog.storage IS 'dataset_catalog表的storage字段。';
COMMENT ON COLUMN ops.dataset_catalog.supports_incremental IS 'supports_incremental的布尔状态标记。';
COMMENT ON COLUMN ops.dataset_catalog.target IS 'dataset_catalog表的target字段。';
COMMENT ON COLUMN ops.dataset_catalog.updated_at IS '记录最后更新时间。';

-- ops.etl_job_run
COMMENT ON TABLE ops.etl_job_run IS '数据接入与平台运维表：etl_job_run。';
COMMENT ON COLUMN ops.etl_job_run.asset IS '金融资产品种。';
COMMENT ON COLUMN ops.etl_job_run.checkpoint IS '增量任务检查点的结构化状态。';
COMMENT ON COLUMN ops.etl_job_run.dataset_name IS '供应商数据集名称。';
COMMENT ON COLUMN ops.etl_job_run.end_date IS '数据或任务覆盖范围的结束日期。';
COMMENT ON COLUMN ops.etl_job_run.error IS '失败错误信息。';
COMMENT ON COLUMN ops.etl_job_run.finished_at IS '任务或计算结束时间。';
COMMENT ON COLUMN ops.etl_job_run.freq IS 'etl_job_run表的freq字段。';
COMMENT ON COLUMN ops.etl_job_run.job_name IS 'etl_job_run表的job_name字段。';
COMMENT ON COLUMN ops.etl_job_run.provider IS '数据供应商标识。';
COMMENT ON COLUMN ops.etl_job_run.request IS '任务请求参数的结构化快照。';
COMMENT ON COLUMN ops.etl_job_run.rows_written IS '本次写入的记录行数。';
COMMENT ON COLUMN ops.etl_job_run.run_id IS '关联本次计算、导入或模型运行的唯一标识。';
COMMENT ON COLUMN ops.etl_job_run.start_date IS '数据或任务覆盖范围的起始日期。';
COMMENT ON COLUMN ops.etl_job_run.started_at IS '任务或计算开始时间。';
COMMENT ON COLUMN ops.etl_job_run.status IS '记录的当前状态。';
COMMENT ON COLUMN ops.etl_job_run.trading_day IS '所属交易日。';
COMMENT ON COLUMN ops.etl_job_run.warning_count IS '本次处理产生的警告数量。';

-- ops.schema_migrations
COMMENT ON TABLE ops.schema_migrations IS '数据接入与平台运维表：schema_migrations。';
COMMENT ON COLUMN ops.schema_migrations.applied_at IS 'applied时间。';
COMMENT ON COLUMN ops.schema_migrations.checksum IS '文件内容校验和。';
COMMENT ON COLUMN ops.schema_migrations.file_name IS 'schema_migrations表的file_name字段。';

-- ops.table_ownership
COMMENT ON COLUMN ops.table_ownership.channel IS 'table_ownership表的channel字段。';
COMMENT ON COLUMN ops.table_ownership.provider IS '数据供应商标识。';
COMMENT ON COLUMN ops.table_ownership.target IS 'table_ownership表的target字段。';
COMMENT ON COLUMN ops.table_ownership.updated_at IS '记录最后更新时间。';

-- ops.users
COMMENT ON TABLE ops.users IS '数据接入与平台运维表：users。';
COMMENT ON COLUMN ops.users.created_at IS '记录创建时间。';
COMMENT ON COLUMN ops.users.role IS '用户权限角色。';
COMMENT ON COLUMN ops.users.user_id IS '运维用户自身的主键；与 app.users 的用户身份独立。';
COMMENT ON COLUMN ops.users.username IS 'users表的username字段。';

-- pick.batch
COMMENT ON COLUMN pick.batch.batch_id IS '关联所属批次的唯一标识。';
COMMENT ON COLUMN pick.batch.created_at IS '记录创建时间。';
COMMENT ON COLUMN pick.batch.note IS '人工备注。';
COMMENT ON COLUMN pick.batch.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN pick.batch.status IS '记录的当前状态。';
COMMENT ON COLUMN pick.batch.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN pick.batch.trading_day IS '所属交易日。';
COMMENT ON COLUMN pick.batch.uploaded_by IS 'batch表的uploaded_by字段。';

-- pick.item
COMMENT ON COLUMN pick.item.asset_class IS '资产大类。';
COMMENT ON COLUMN pick.item.batch_id IS '关联所属批次的唯一标识。';
COMMENT ON COLUMN pick.item.created_at IS '记录创建时间。';
COMMENT ON COLUMN pick.item.entry_date IS 'entry日期。';
COMMENT ON COLUMN pick.item.entry_date_source IS 'item表的entry_date_source字段。';
COMMENT ON COLUMN pick.item.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN pick.item.option_type IS '期权类型：认购或认沽。';
COMMENT ON COLUMN pick.item.product_code IS 'item表的product_code字段。';
COMMENT ON COLUMN pick.item.rank IS 'item表的rank字段。';
COMMENT ON COLUMN pick.item.reason_text IS 'item表的reason_text字段。';
COMMENT ON COLUMN pick.item.strategy_id IS '关联 app.strategies 的策略 ID。';
COMMENT ON COLUMN pick.item.suggest_weight IS '建议配置权重。';
COMMENT ON COLUMN pick.item.symbol IS '不含交易所后缀的证券／合约代码；与 exchange 联合识别标的。';
COMMENT ON COLUMN pick.item.symbol_name IS '证券展示名称。';
COMMENT ON COLUMN pick.item.trading_day IS '所属交易日。';

-- realtime.tick_buffer
COMMENT ON TABLE realtime.tick_buffer IS '实时行情缓冲表：tick_buffer。';
COMMENT ON COLUMN realtime.tick_buffer.amount IS '成交额，单位为元。';
COMMENT ON COLUMN realtime.tick_buffer.ask1 IS '卖一价。';
COMMENT ON COLUMN realtime.tick_buffer.ask_vol1 IS '卖一数量。';
COMMENT ON COLUMN realtime.tick_buffer.bid1 IS '买一价。';
COMMENT ON COLUMN realtime.tick_buffer.bid_vol1 IS '买一数量。';
COMMENT ON COLUMN realtime.tick_buffer.dt IS '行情事件时间；分钟行情使用带时区时间戳。';
COMMENT ON COLUMN realtime.tick_buffer.instrument_id IS '关联 meta.instruments 的标的 ID。';
COMMENT ON COLUMN realtime.tick_buffer.last IS '最新成交价。';
COMMENT ON COLUMN realtime.tick_buffer.open_interest IS '持仓量。';
COMMENT ON COLUMN realtime.tick_buffer.source IS '产生或提供该记录的数据源标识。';
COMMENT ON COLUMN realtime.tick_buffer.trading_day IS '所属交易日。';
COMMENT ON COLUMN realtime.tick_buffer.updated_at IS '记录最后更新时间。';
COMMENT ON COLUMN realtime.tick_buffer.volume IS '成交量；股票与 ETF 单位为股，期货与期权单位为手。';

-- staging.parquet_file
COMMENT ON TABLE staging.parquet_file IS '数据入库中转表：parquet_file。';
COMMENT ON COLUMN staging.parquet_file.asset IS '金融资产品种。';
COMMENT ON COLUMN staging.parquet_file.content_hash IS '内容哈希，用于去重和变更识别。';
COMMENT ON COLUMN staging.parquet_file.created_at IS '记录创建时间。';
COMMENT ON COLUMN staging.parquet_file.dataset_name IS '供应商数据集名称。';
COMMENT ON COLUMN staging.parquet_file.end_date IS '数据或任务覆盖范围的结束日期。';
COMMENT ON COLUMN staging.parquet_file.error IS '失败错误信息。';
COMMENT ON COLUMN staging.parquet_file.fetch_run_id IS '关联的 fetch_run 标识。';
COMMENT ON COLUMN staging.parquet_file.file_id IS '关联的 file 标识。';
COMMENT ON COLUMN staging.parquet_file.file_size_bytes IS '文件大小，单位为字节。';
COMMENT ON COLUMN staging.parquet_file.freq IS 'parquet_file表的freq字段。';
COMMENT ON COLUMN staging.parquet_file.load_run_id IS '关联的 load_run 标识。';
COMMENT ON COLUMN staging.parquet_file.loaded_at IS 'loaded时间。';
COMMENT ON COLUMN staging.parquet_file.metadata IS '结构化扩展元数据。';
COMMENT ON COLUMN staging.parquet_file.partition_key IS 'parquet_file表的partition_key字段。';
COMMENT ON COLUMN staging.parquet_file.provider IS '数据供应商标识。';
COMMENT ON COLUMN staging.parquet_file.row_count IS '文件或数据集包含的记录行数。';
COMMENT ON COLUMN staging.parquet_file.schema_fingerprint IS 'parquet_file表的schema_fingerprint字段。';
COMMENT ON COLUMN staging.parquet_file.source_path IS 'parquet_file表的source_path字段。';
COMMENT ON COLUMN staging.parquet_file.start_date IS '数据或任务覆盖范围的起始日期。';
COMMENT ON COLUMN staging.parquet_file.status IS '记录的当前状态。';
