# PRD

更新时间：2026-06-09

本文件是项目级 PRD 入口。INSIGHT 导入详细需求见 `insight_import_product_requirements.md`。

## 目标

构建 `getrich_data_import`，把外部数据源标准化导入 GetRich 本地数据层，供其他程序稳定调用。

核心路径：

- INSIGHT SDK 数据先下载为本地 Parquet。
- 经过 schema、质量和字段规范化校验后，权威数据导入 PostgreSQL + TimescaleDB。
- 临时验证、源对比、宽表快照和本地分析放入 DuckDB。
- 后续 tick、逐笔、委托等高频历史数据进入 ClickHouse 25。

## 用户

- 数据导入和运维程序：需要可重跑、可审计、可恢复的导入流程。
- 量化研究程序：需要稳定读取股票、ETF、基金、指数、期货、期权等历史数据。
- 后续实时/高频消费者：需要 Redis/ClickHouse 路线支持 tick 和逐笔数据。

## 当前范围

- PostgreSQL/TimescaleDB schema、迁移和检查命令。
- Yinhe Parquet provider。
- INSIGHT provider。
- Parquet staging manifest。
- bar 数据导入：index、stock、ETF、future、option 的 `1d` 和 `1m`。
- INSIGHT P1 数据集：复权因子、股票日基础、股票估值、指数成分、ETF/fund daily/nav、ETF basket。
- job audit、checkpoint、质量检查和基础查询视图。

## 暂不包含

- 完整实时数据流。
- ClickHouse 25 高频 schema 和导入实现。
- `etf_redemption` ready loader。
- 财务报表 PIT schema。
- 对外 API/SDK 读取层。

## 验收标准

- 数据可按 provider、dataset、symbol、date range 重复导入且幂等。
- Parquet staging 文件可在不重新调用 SDK 的情况下重载。
- 目标表主键、数据质量检查和 job audit 可追踪导入结果。
- 其他程序可以通过 PostgreSQL/TimescaleDB 查询 canonical 数据，通过 DuckDB 使用临时验证或快照数据。
