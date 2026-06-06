# 参数扫描与优化

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。相关设计契约见 [设计契约 / 50 参数搜索](../design-contracts/50-param-search.md)。

## 计划内容

- `GridSearch` 与 `ParamSpace`
- `SweepRunner`（含 `on_progress` / `is_cancelled` / 限流）
- `WalkForward`（rolling / anchored）
- 取消、重试、幂等（`RetryableError` / `TerminalError` / `request_hash`）
- 过拟合检测
