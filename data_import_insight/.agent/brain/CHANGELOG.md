# CHANGELOG

## 2026-06-09

- 文档记忆拆分为 `TODO.md`、`INFO.md`、`CHANGELOG.md`，便于后续持续更新。
- 记录当前数据库环境主版本：PostgreSQL 17 + TimescaleDB、ClickHouse 25。

## 2026-06-08

- 启用 INSIGHT `stock_adj_factor` canonical transform 和 ready 状态。
- 修复 P1 区间数据过滤逻辑：`begin_date` 优先于 `end_date`，避免复权因子最后一期被错误过滤。
- 分钟线导入在交易日历缺失但 staged parquet 已有完整 `trading_day` 时，保留源交易日。
- 使用 `uv` 增加 `polars` 依赖。
- 完成 INSIGHT ETF、期货、期权小样本导入验证。

## 2026-06-06

- 完成本地 PostgreSQL/TimescaleDB schema 重建和 `verify-schema` 验证。
- 跑通 Yinhe Parquet 路径的 metadata、stock/ETF/index 日线、stock 分钟线小样本导入和导出验证。
- PostgreSQL upsert 成功写入后立即 drop 临时 staging 表，降低大事务内 temp table 锁累积风险。
- 将 review SQL 合并进基础 DDL，不再依赖独立 review appendix SQL。
