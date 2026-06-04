# Project Brain

更新时间：2026-06-04

## getrich_data_import

- 新数据导入工程已落地，旧 `data_import`、`import_data` 不作为运行依赖。
- Providers：`yinhe`、`insight`。
- Market schema 已覆盖 index/future/option/stock/etf 的 1d、1m。
- 已支持 `export-bars`，并补充 duplicate key、缺交易日、expected-minute 质量检查。
- 已用 `/home/quant/data` 跑通 yinhe scan、load-metadata、`600000.SH` stock 1d 小范围导入和导出。
- 期货/期权扩展元数据入口已实现；当前 yinhe 数据 future/option 为 0。
- `docs/code-review-2026-06-04.done.md` 已完成，含附录 A。
- 本地 DB 已应用 `60_review_appendix_a.sql`，`verify-schema` 通过，`migrate-schema` 可幂等重跑。
- 最新验证：62 tests passed，ruff passed。

## 当前阻塞

- 默认 `/data` 目录未准备；当前需通过 `GETRICH_IMPORT__YINHE_DATA_DIR=/home/quant/data` 使用已有数据。
- `/home/quant/data` 暂无 `kline_min1`，分钟线后续再测。
