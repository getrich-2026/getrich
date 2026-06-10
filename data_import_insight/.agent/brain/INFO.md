# INFO

更新时间：2026-06-09

本文件记录稳定事实：栈、目录、约定、架构决策和策略类信息。进度、版本和阅读顺序见 `PROGRESS.md`；任务见 `TODO.md`。

## 项目边界

- `getrich_data_import` 是新的 GetRich 数据导入工程，不依赖旧 `data_import` 或 `import_data`。
- INSIGHT 数据路径：先落本地 Parquet，再导入数据库；需要长期权威保存的数据进入 PostgreSQL + TimescaleDB，需要临时验证或本地分析的数据进入 DuckDB。
- RiceQuant provider 已实现第一版 `rqdatac` 适配器，目标路径同样是先落本地 Parquet，再导入 canonical 数据库；RiceQuant 凭证不能写入代码或文档。
- RiceQuant 当前仍是试用期来源。INSIGHT 保持主要行情来源；RiceQuant 优先用于 instruments、trading calendar/trading day 和少量行情补充验证。
- ClickHouse 25 已纳入目标数据库环境，用于后续 tick、逐笔和其他高频/大规模不可变历史数据。
- `yinhe_data_fetcher` 仍是独立 Parquet 下载项目；本工程只消费其输出。
- 默认 Yinhe 数据目录为 `/data`；本地历史测试数据在 `/home/quant/data`，通过环境变量覆盖。

## 技术栈

- Python 3.10+。
- 依赖和虚拟环境使用 `uv` 管理。
- 数据处理主库：pandas、pyarrow、polars。
- 关系和时序权威库：PostgreSQL 17 + TimescaleDB。
- 临时分析和本地快照：DuckDB。
- 高频长期存储目标：ClickHouse 25。

## 目录约定

- `.agent/brain/`：AI 工作记忆首读区。
- `src/getrich_data_import/`：导入工程源码。
- `sql/`：数据库端 schema 和初始化 SQL。
- `docs/`：项目级 PRD、架构和详细评审文档。
- `tests/`：单元测试和本地 pipeline 回归测试。

## 当前数据库环境

- 本地 PostgreSQL 主版本：17。
- TimescaleDB：已随 PostgreSQL 17 环境更新，精确 patch 版本待命令确认。
- ClickHouse 主版本：25。
- 当前 PostgreSQL 数据库：`getrich`。
- 当前 PostgreSQL 用户：`quant`。
- 当前 PostgreSQL 端口：`5432`。
- 本地开发阶段允许清理并重建数据库；进入稳定阶段后应改用 additive migrations。

## 架构决策

- INSIGHT 数据先落本地 Parquet，再从 Parquet 导入数据库，支持失败后不重复调用 INSIGHT SDK。
- RiceQuant 也必须先落本地 Parquet，再导入数据库；多源对比先进入 DuckDB，不直接覆盖 canonical 表。
- PostgreSQL 只记录 Parquet manifest 和 canonical 数据，不保存 raw parquet payload。
- 当前 market bar 表主键不含 `source`，只适合一份 canonical 行；`source` 字段记录最终选中数据的来源。若要同时长期保存 INSIGHT 和 RiceQuant 同时间戳观测，需要另行设计 source-qualified 表或 schema migration。
- ETF 和普通 fund 分表，不能混入同一 canonical table。
- `stock_adj_factor` 是 sparse factor event，不直接当作调整后价格；`end_date` 暂留 `raw_payload`。
- 分钟线优先使用交易日历推导 `trading_day`；当本地日历缺失且 staged parquet 已有完整 `trading_day` 时，可保留源交易日作为导入兜底。

## 当前实现状态

- CLI 已覆盖：`init-schema`、`migrate-schema`、`check-db`、`verify-schema`、`scan`、`load-metadata`、`fetch-dataset`、`load-dataset`、`import-dataset`、`import-bars`、`export-bars`、审计查询命令。
- Provider：`yinhe`、可选 `insight`、可选 `ricequant`；实时 provider 尚未实现。
- PostgreSQL schema：`meta`、`market`、`realtime`、`ops`、`staging`。
- Market bar 表：index、stock、ETF、future、option 的 `1d` 和 `1m`。
- INSIGHT P1 ready 数据集：`stock_adj_factor`、`stock_daily_basic`、`stock_valuation`、`index_component`、`etf_daily`、`etf_nav`、`fund_daily`、`fund_nav`、`etf_basket`。
- Review SQL 已合并进基础 DDL；schema 清单不再依赖独立 `60_review_appendix_a.sql` 或 `70_review_followup.sql`。
- 1m 到 1d 辅助物化视图按 `trading_day` 聚合，不使用连续聚合，避免夜盘被自然日切分。

## 最近验证

- `stock_adj_factor`：`000001.SZ`，`2020-01-01` 到 `2026-06-04`，fetch 8 行，load 8 行。
- ETF：`510300.SH`，`2026-06-04`，`etf_daily` 1 行、`etf_nav` 1 行、`etf_basket` 300 行。
- 期货：`CU00.SHF`，`2026-06-04`，`future_bar_1d` 1 行、`future_bar_1m` 224 行。
- 期权：`10010317.SH`，`2026-06-04`，`option_bar_1d` 1 行、`option_bar_1m` 242 行。
- Yinhe 历史 smoke：metadata、stock/ETF/index 1d 小样本、stock 1m SH/SZ 小样本、Parquet 导出读回均已跑通。
- 最新完整测试：`.venv/bin/ruff check src tests` 通过，`.venv/bin/pytest tests -q` 为 105 passed。

## 注意事项

- 不要把 INSIGHT 用户名、密码、数据库密码写入代码或文档。
- 不要把 RiceQuant license 写入代码或文档。
- 本地测试库可重建，但 drop/delete 前仍需要用户明确确认。
- 交易日历为空时，分钟线 loader 可保留 staged parquet 自带的 `trading_day`；这只是可导入兜底，不替代生产级交易日历。
