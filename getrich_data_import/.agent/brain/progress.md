# Progress

更新时间：2026-06-04

## 当前状态

- 新工程：`getrich_data_import`
- Providers：`yinhe`、`insight`
- CLI：`init-schema`、`migrate-schema`、`check-db`、`verify-schema`、`scan`、`load-metadata`、`import-bars`、`export-bars`
- DB：本地 PostgreSQL 16.14 + TimescaleDB 2.27.2，license `apache`
- Schema：`meta`、`market`、`realtime`、`ops`
- Market：index/future/option/stock/etf 的 1d、1m；option greeks
- Review：`docs/code-review-2026-06-04.done.md` 已全部完成，含附录 A
- Migration：`60_review_appendix_a.sql` 已应用；`migrate-schema` 可幂等重跑
- 质量增强：duplicate key、缺交易日、expected-minute、price jump
- 导出：PostgreSQL -> Parquet；DuckDB parquet 查询封装为可选依赖
- `/home/quant/data` smoke：scan、load-metadata、`600000.SH` stock 1d 小范围导入和导出已跑通
- 期货/期权扩展元数据入口已实现；当前 yinhe 数据中 future/option 为 0

## 验证

- `.venv/bin/python -m pytest tests`：62 passed
- `.venv/bin/ruff check src tests`：passed
- `getrich-import verify-schema`：passed
- `getrich-import migrate-schema`：00-60 全部 skipped
- `load-metadata` with `/home/quant/data`：23394 rows
- `import-bars --asset stock --freq 1d --symbol 600000.SH`：5 rows
- `export-bars`：已导出 `/tmp/getrich_600000_stock_1d_smoke.parquet`，5 rows，可读

## 注意

- 默认 yinhe 数据目录为 `/data`；当前测试临时使用 `/home/quant/data` 覆盖。
- `/home/quant/data` 暂无 `kline_min1`，分钟线后续再测。
- TimescaleDB apache license 下 compression/retention/continuous aggregate 会降级或跳过。
