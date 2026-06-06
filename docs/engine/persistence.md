# 持久化与 artifact

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。

## 计划内容

- `RunConfig.fingerprint` SHA-256 幂等键
- `PgBacktestResultStore` save/load/get_metrics
- `BacktestArtifact`（manifest / equity.parquet / fills.parquet / tear_sheet.html）
- 4 张 PG 表 + 2 CH 表
- 流式写 vs 一次性写
- TTL / `prune-runs` 命令
