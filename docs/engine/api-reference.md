# 引擎 API 参考

!!! info "Phase 2 文档"
    本页将由 [mkdocstrings](https://mkdocstrings.github.io/) 在 Phase 2 自动渲染 `src/getrich_backtest/` 下的所有公开类与函数。

## 计划内容

mkdocstrings 自动从 docstring 渲染以下模块：

- 顶层：`Backtest` / `RunConfig` / `BarContext` / `OrderIntent` / `BacktestResult`
- 策略：`Strategy` / `SignalStrategy` / `TargetPositionStrategy` / `Portfolio` / `WeightAllocator` 系列
- 数据：`DataFrameBarLoader` / `PgBarLoader` / `DuckDBBarLoader`
- 执行：`NextBarMatchingModel` / `Account` / `Position` / `MarginCalculator`
- 风险：`RiskManager` / `RiskConfig`
- 分析：`BacktestMetrics` / `compute_metrics` / 归因函数
- 优化：`SweepRunner` / `WalkForward` / `ParamSpace`
- 持久化：`PgBacktestResultStore` / `BacktestArtifact`
- 实盘：`SignalProducer` / `EvalSignalWriter` / `LiveDataProvider` / `LiveSignalRunner`
