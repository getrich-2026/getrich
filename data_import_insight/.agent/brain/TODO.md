# TODO

更新时间：2026-06-09

## P1 收尾

- 补齐 INSIGHT 交易日历导入验证，尤其是期货交易所日历。当前分钟线可在 staged parquet 自带完整 `trading_day` 时落库，但生产环境仍应优先依赖权威交易日历处理夜盘归属。
- 继续确认 `etf_redemption` 的 INSIGHT 参数或权限；当前仍未标记为 ready。
- 明确 OTC 公募基金 NAV 代码规范：裸代码、带交易所后缀，还是 source-qualified symbol。
- 交叉验证复权价来源：`get_kline(fq=)`、`stock_daily_basic.backward_adjusted_closing_price`、`stock_valuation`、`stock_adj_factor`。
- 增加 DuckDB 验证/快照产物记录；临时分析数据放 DuckDB，不污染 PostgreSQL canonical 表。

## P2 数据覆盖

- 扩展 money flow、trade distribution、chip distribution、margin data。
- 设计并实现 Barra 因子长表导入。
- 设计财务报表和公司事件 PIT schema。
- 为 ClickHouse 25 设计 tick、逐笔、委托等高频长期存储 schema。

## 工程化

- 增加调度、失败续跑和 checkpoint 策略的生产化配置。
- 给普通物化视图补 refresh 策略。
- 增加 API/SDK 读取层，让其他程序稳定调用 PostgreSQL/TimescaleDB、DuckDB、未来 ClickHouse 数据。
- 明确本地数据库可重建阶段结束点；之后 schema 变更改走 additive migrations。
- 评估 import job 的 chunk/commit 边界是否需要提升为显式配置，便于生产回放和失败续跑。
