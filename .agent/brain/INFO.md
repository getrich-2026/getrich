# Frontend Signal 数据填充说明

## 背景

`sql/init/frontend_signal/` 是前端策略、信号、订阅、用户状态等业务表的主初始化目录。

`sql/init/import_data/` 只负责数据导入层对象，包括：

- `ref`：交易日历、跨供应商标的映射、统一标的视图。
- `rq`：RiceQuant 标的信息表。

不要再从 `import_data/src/import_data/schemas/postgresql_init_schema.sql` 初始化 frontend 业务表；该旧文件已删除。

## 当前可整理的数据

用户当前可以整理：

- 一个策略的日涨跌幅。
- 信号每日触发记录。

这些数据可以支撑部分表：

- `frontend.strategy_equity_curve`
- `frontend.strategy_performance_snapshot`
- `frontend.strategy_monthly_returns`
- `frontend.signals`

但还不足以完整填充 frontend 所有业务表。

## 最小可用数据集

若目标是让前端能展示一个策略详情、净值曲线和信号列表，至少需要：

- 策略基础信息：
  - `strategy_code`
  - `name`
  - `summary`
  - `description`
  - `category`
  - `type`
  - `asset_class`
  - `market`
  - `target_horizon`
  - `risk_level`
  - `pub_status`
  - `run_status`
  - `access_tier`
  - `backtest_start`
  - `backtest_end`
  - `config`
- 一个策略作者用户。
- 分类与标签。
- 日度净值或日收益率序列。
- 信号触发记录。

## 日度收益数据用途

策略日涨跌幅可以生成：

- `trade_date`
- `nav`
- `daily_return`
- `cumulative_return`
- `drawdown`
- `benchmark_nav`，可选。
- `position_ratio`，可选。

对应表：

- `frontend.strategy_equity_curve`
- `frontend.strategy_performance_snapshot`
- `frontend.strategy_monthly_returns`

## 信号触发记录字段

信号记录建议整理为：

- `signal_code`
- `strategy_code`
- `published_at` 或 `trigger_time`
- `symbol`
- `symbol_name`
- `exchange`
- `type`：`entry`、`exit`、`adjust`、`alert`
- `action`：`buy`、`sell`、`hold`、`close`、`open`、`add`、`reduce`
- `direction`：`long`、`short`、`neutral`
- `trigger_price`
- `target_price`
- `stop_loss_price`
- `suggested_quantity`
- `position_pct`
- `confidence`
- `urgency`：`low`、`normal`、`high`、`critical`
- `reason`
- `status`：`active`、`expired`、`cancelled`

对应表：

- `frontend.signal_batches`
- `frontend.signals`

## 可选但建议的数据

信号触发时刻行情快照：

- `open`
- `high`
- `low`
- `close`
- `volume`
- `turnover`
- `open_interest`，期货需要。
- `basis`，期货可选。
- `indicators`，例如 MA、RSI、ATR、价差 z-score。

对应表：

- `frontend.signal_market_snapshot`

## 权限与订阅数据

如果只展示公开策略，可以先设置：

- `frontend.strategies.access_tier = 0`

这样可以暂时不准备订阅、订单、授权和会员数据。

如果要验证付费访问、订阅状态、未读统计或执行反馈，还需要：

- `frontend.users`
- `frontend.user_auth_identities`
- `frontend.membership_plans`
- `frontend.user_memberships`
- `frontend.orders`
- `frontend.order_items`
- `frontend.user_strategy_subscriptions`
- `frontend.strategy_access_grants`
- `frontend.user_signal_reads`
- `frontend.user_signal_settings`
- `frontend.user_strategy_signal_settings`
