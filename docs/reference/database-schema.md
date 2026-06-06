# 数据库 Schema 参考

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。

## 计划内容

### PostgreSQL（25 张业务表）

`frontend.*` schema 下的表，按职责分组：

- 用户与认证：`users` / `user_auth` / `refresh_tokens`
- 策略与信号：`strategies` / `signals` / `signal_settings` / `subscriptions`
- 订单与交易：`orders` / `strategy_trades`
- 回测与作业：`backtest_jobs` / `backtest_runs` / `backtest_sweeps` / `backtest_walk_forwards`
- 性能与归因：`strategy_perf` / `signal_market_snapshot`
- 实盘账户：`live_positions` / `live_accounts`
- 计费：`payments` / `subscriptions_billing`
- 审计：`audit_log`

### ClickHouse（2 张时序表）

- `md_bars_1d` / `md_bars_1m` / `md_bars_5m` / ...（OHLCV + 复权）
- `md_factors`（长表 `(dt, symbol, factor, value)`）

迁移文件位置：[`migrations/`](https://github.com/getrich/getrich/tree/main/migrations) 与 [`migrations/clickhouse/`](https://github.com/getrich/getrich/tree/main/migrations/clickhouse)
