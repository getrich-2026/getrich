# Current State

更新时间：2026-06-06

## 边界

- `getrich_data_import` 是新的数据导入工程，不依赖旧 `data_import` 或 `import_data`。
- `yinhe_data_fetcher` 继续作为独立 Parquet 下载项目；本工程只消费其输出。
- 默认 Yinhe 数据目录为 `/data`；当前真实测试数据在 `/home/quant/data`，通过环境变量覆盖。
- 不包含 `import_insight`；`insight` 是可选 provider，直接走运行环境里的 Insight SDK。
- `/home/quant/data` 当前有 `kline_day` 与部分 `kline_min1` 数据；future/option instruments 暂未发现，相关测试先跳过。

## 当前进度

- CLI 已覆盖：`init-schema`、`migrate-schema`、`check-db`、`verify-schema`、`scan`、`load-metadata`、`import-bars`、`export-bars`。
- Provider 已有：`yinhe`、可选 `insight`；实时 provider 尚未实现。
- PostgreSQL/TimescaleDB schema：`meta`、`market`、`realtime`、`ops`。
- Market 表：index/stock/ETF/future/option 的 `1d`、`1m`，以及 `option_greeks_1d`。
- Review SQL 已合并进基础 DDL：schema 清单仅保留 `00_extensions.sql` 到 `50_ops.sql`，不再使用独立 `60_review_appendix_a.sql` 或 `70_review_followup.sql`。
- TimescaleDB：1m 表尝试 compression policy；1m 到 1d 辅助物化视图按 `trading_day` 聚合，不使用连续聚合，避免夜盘被自然日切分。
- 数据质量：duplicate key、OHLC、非负数、`adj_factor`、缺交易日、expected-minute、price jump 检查已覆盖核心路径。
- P0 已完成：本地 `getrich` 库清理后重新执行 `migrate-schema`，`verify-schema` 通过。
- `/home/quant/data` P1 smoke 已跑通：scan、load-metadata、stock/ETF/index 1d 小样本导入和 Parquet 导出。
- stock 1m 的 SH/SZ 小样本导入已跑通；Yinhe 只有单侧 A 股日历文件时会显式补齐 SH/SZ 日历覆盖。
- PostgreSQL upsert 已在成功写入后立即 drop 临时 staging 表，降低大事务内 temp table 锁累积风险。

## 已验证

- `check-db`：PostgreSQL 16.14、TimescaleDB 2.27.2、license `apache`。
- `verify-schema`：missing tables、hypertables、migrations 均为空。
- `load-metadata`：写入 23394 rows。
- 1d 小样本：
  - `market.stock_bar_1d`：397 rows，100 instruments，2026-06-01 到 2026-06-04，重复键 0，核心 OHLCV 空值 0。
  - `market.etf_bar_1d`：200 rows，50 instruments，2026-06-01 到 2026-06-04，重复键 0，核心 OHLCV 空值 0。
  - `market.index_bar_1d`：200 rows，50 instruments，2026-06-01 到 2026-06-04，重复键 0，核心 OHLCV 空值 0。
- 1m 小样本：
  - `market.stock_bar_1m`：1440 rows，3 SH instruments + 3 SZ instruments，2026-06-04，重复键 0，核心 OHLCV 空值 0。
- 扩大样本：
  - `market.stock_bar_1d`：500-symbol 单日导入成功，新增 500 rows，未再触发 PostgreSQL temp table 锁错误。
- 导出文件已读回：
  - `/tmp/getrich_p1_stock_1d_20260601_20260605.parquet`
  - `/tmp/getrich_p1_etf_1d_20260601_20260605.parquet`
  - `/tmp/getrich_p1_index_1d_20260601_20260605.parquet`
  - `/tmp/getrich_p1_stock_sh_1m_20260604.parquet`
- `.venv/bin/ruff check src tests`：passed。
- `.venv/bin/pytest tests -q`：75 passed。

## 下一步

1. 扩大 `/home/quant/data` 的 stock/ETF/index 1d 导入范围，优先按日期或 symbol chunk 逐步放大，不直接跳到长期全量。
2. 扫描 ETF/index 是否存在可用 1m 文件；有数据后补对应分钟线 smoke。
3. 评估是否需要把 import job 的 chunk/commit 边界提升为显式配置，便于生产回放和失败续跑。
4. 等 future/option 数据到位后验证合约扩展元数据和对应 bar 导入。
5. 普通物化视图暂未接自动 refresh job；后续如果要查询这些 helper view，需要补刷新策略。

## 注意事项

- 不要改动或回滚 `yinhe_data_fetcher` 的未归属改动。
- 本地测试库可重建，但执行 drop/delete 前需要用户明确确认。
- 普通物化视图暂未接自动 refresh job；后续如果要查询这些 helper view，需要补刷新策略。
- 本地 DB 里保留了 P1 过程中的历史失败审计记录：一次全量 stock 1d 锁不足失败、一次修复前 SZ stock 1m 缺日历失败。
