# 引擎 API 参考

> **本页面由 [mkdocstrings](https://mkdocstrings.github.io/) 从 `src/getrich_backtest/` 下的 docstring 自动渲染。** 任何对源代码的更新都会在下一次 `mkdocs build` 时反映到这里。修改时无需手动编辑本页 —— 改源码的 docstring 即可。
>
> **配置位置**：`mkdocs.yml` 的 `mkdocstrings` plugin 段。当前选项：google-style docstring、`show_source: true`（在源码中可看完整定义）、`signature_crossrefs: true`、filter 排除私有成员（`!^_`）。

---

## 1. 顶层入口

```python
from getrich_backtest import (
    Backtest,            # 主入口
    RunConfig,           # 不可变运行配置
    BarContext,          # 策略每根 bar 收到的上下文
    Context,             # 长生命周期上下文
    OrderIntent,         # 策略的输出（订单意图）
    Order,               # 撮合后的内部订单对象
    Fill,                # 成交回报
    BacktestResult,      # 一次 run 的完整结果
    CombinedResult,       # 多策略合并结果
    ResultView,          # 子策略的视图
    Side,                # BUY / SELL
    OrderType,           # MARKET / LIMIT / STOP
    TimeInForce,         # GTC / IOC / FOK / DAY
    OrderStatus,         # PENDING / ACCEPTED / FILLED / REJECTED / EXPIRED
    Exchange,            # SSE / SZSE / SHFE / ...
    AssetClass,          # STOCK / FUTURE / OPTION / FX / CRYPTO
    Symbol,              # 标的标识符
    Money,               # 高精度金额
    Quantity,            # 高精度数量
    Frequency,           # 1m / 5m / 1h / 1d / 1w
    BarLoader,           # bar 数据加载器协议
    NextBarMatchingModel,# 默认撮合模型
    TakeProfitStopLoss,  # 止盈止损辅助
    AccountView,         # 账户只读视图
    PositionView,        # 持仓只读视图
    HistoryView,         # K 线历史视图
    get_shanghai_tz,     # 时区工具
    ensure_shanghai_aware,        # 强制 Shanghai 感知
    require_shanghai_aware,       # 不符合时抛 TimezoneError
    normalize_datetime_range,     # 区间归一化
    validate_bar_schema,          # bar DataFrame 校验
)
```

> **Round #1146 优化**：仅 4 个最常查阅的"顶层入口"类开启 `show_source: true`（读者在文档站里就能看到完整源码，省去跳转 GitHub 的时间）。其余 ~90 个 `:::` 指令默认 `show_source: false`，单页从 4.7MB 缩到 < 700KB（约 -85%），搜索也能更精确地命中 docstring 而非被源码噪声稀释。

::: getrich_backtest.Backtest
    options:
      show_source: true

::: getrich_backtest.RunConfig
    options:
      show_source: true

::: getrich_backtest.BarContext
    options:
      show_source: true

::: getrich_backtest.Context
    options:
      show_source: true

---

## 2. 策略

### 2.1 策略基类

::: getrich_backtest.strategy.base.Strategy

### 2.2 三种策略范式

::: getrich_backtest.strategy.signal.SignalStrategy

::: getrich_backtest.strategy.target_position.TargetPositionStrategy

### 2.3 组合构建（Portfolio + Constraints + Allocator）

::: getrich_backtest.strategy.portfolio.Portfolio

::: getrich_backtest.strategy.portfolio.Constraints

::: getrich_backtest.strategy.portfolio.EqualWeight

::: getrich_backtest.strategy.portfolio.PeriodicRebalance

### 2.4 权重分配器（WeightAllocator 协议）

::: getrich_backtest.strategy.alloc_weight.ScoreWeight

::: getrich_backtest.strategy.alloc_weight.InverseVol

::: getrich_backtest.strategy.alloc_weight.RiskParity

::: getrich_backtest.strategy.alloc_weight.MeanVariance

::: getrich_backtest.strategy.alloc_weight.BlackLitterman

### 2.5 固定权重分配器

::: getrich_backtest.strategy.allocator.FixedAllocator

### 2.6 信号预处理

::: getrich_backtest.strategy.preprocessor.SignalPreprocessor

::: getrich_backtest.strategy.preprocessor.MissingValue

::: getrich_backtest.strategy.preprocessor.Winsorize

::: getrich_backtest.strategy.preprocessor.Standardize

::: getrich_backtest.strategy.preprocessor.Neutralize

### 2.7 内置策略

参考源码：
- [`src/getrich_backtest/strategies/ma_cross.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/strategies/ma_cross.py)
- [`src/getrich_backtest/strategies/bollinger_mr.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/strategies/bollinger_mr.py)

---

## 3. 数据加载器（BarLoader 协议 + 实现）

::: getrich_backtest.data.DataFrameBarLoader

::: getrich_backtest.data.PgBarLoader

::: getrich_backtest.data.DuckDBBarLoader

### 3.1 工具函数

::: getrich_backtest.data.resample_bars

::: getrich_backtest.data.validate_corp_actions_schema

::: getrich_backtest.data.validate_factor_schema

---

## 4. 执行撮合

::: getrich_backtest.execution.NextBarMatchingModel

### 4.1 撮合错误

::: getrich_backtest.exceptions.ExecutionError

---

## 5. 账户与保证金

### 5.1 账户

::: getrich_backtest.account.Account

::: getrich_backtest.account.SubAccount

::: getrich_backtest.account.SubAccountSnapshot

### 5.2 账户工具

::: getrich_backtest.account.daily_settle

::: getrich_backtest.account.get_settlement_prices

### 5.3 保证金

::: getrich_backtest.margin.MarginCalculator

---

## 6. 风险控制

::: getrich_backtest.risk.RiskConfig

::: getrich_backtest.risk.RiskManager

::: getrich_backtest.risk.LiquidationEvent

---

## 7. 成本模型

### 7.1 费用（FeeModel 协议）

::: getrich_backtest.cost.FeeModel

::: getrich_backtest.cost.ZeroFee

::: getrich_backtest.cost.FixedFee

::: getrich_backtest.cost.PercentageFee

::: getrich_backtest.cost.PerShareFee

::: getrich_backtest.cost.CompositeFee

### 7.2 滑点（SlippageModel 协议）

::: getrich_backtest.cost.SlippageModel

::: getrich_backtest.cost.ZeroSlippage

::: getrich_backtest.cost.FixedSlippage

::: getrich_backtest.cost.BpsSlippage

---

## 8. 指标与归因

### 8.1 指标

::: getrich_backtest.metrics.BacktestMetrics

::: getrich_backtest.metrics.compute_metrics

::: getrich_backtest.metrics.monthly_returns_heatmap

### 8.2 基准对比

::: getrich_backtest.benchmark.Benchmark

::: getrich_backtest.benchmark.compute_benchmark_comparison

### 8.3 因子评估

::: getrich_backtest.analytics.compute_ic

::: getrich_backtest.analytics.compute_rank_ic

::: getrich_backtest.analytics.factor_evaluation_report

### 8.4 归因

::: getrich_backtest.attribution.compute_brinson_attribution

::: getrich_backtest.attribution.compute_factor_regression

::: getrich_backtest.attribution.compute_pnl_attribution

::: getrich_backtest.attribution.compute_cost_attribution

::: getrich_backtest.attribution.compute_trade_journal

::: getrich_backtest.attribution.compute_session_attribution

### 8.5 日历

::: getrich_backtest.calendar.Calendar

---

## 9. 报告与可视化

::: getrich_backtest.report.TearSheet

::: getrich_backtest.report.Reporter

---

## 10. 参数扫描与 Walk-Forward

### 10.1 参数空间与 GridSearch

::: getrich_backtest.sweep.ParamSpace

::: getrich_backtest.sweep.P

::: getrich_backtest.sweep.GridSearch

### 10.2 SweepRunner

::: getrich_backtest.sweep.SweepRunner

::: getrich_backtest.sweep.SweepResult

::: getrich_backtest.sweep.SweepTrial

::: getrich_backtest.sweep.SweepTrialResult

### 10.3 Walk-Forward

::: getrich_backtest.walk_forward.WalkForward

::: getrich_backtest.walk_forward.WalkForwardResult

::: getrich_backtest.walk_forward.WalkForwardRunSpec

::: getrich_backtest.walk_forward.WalkForwardWindow

::: getrich_backtest.walk_forward.WalkForwardWindowResult

### 10.4 WalkForwardReport

::: getrich_backtest.walk_forward_report.WalkForwardReport

---

## 11. 持久化

### 11.1 Backtest 结果存储

::: getrich_backtest.persistence.PgBacktestResultStore

::: getrich_backtest.persistence.BacktestArtifact

::: getrich_backtest.persistence.artifacts_from_report_dir

### 11.2 Sweep 持久化

::: getrich_backtest.sweep_persistence.PgSweepResultStore

### 11.3 Walk-Forward 持久化

::: getrich_backtest.walk_forward_persistence.PgWalkForwardResultStore

::: getrich_backtest.walk_forward_persistence.walk_forward_windows_to_frame

### 11.4 Job 持久化

::: getrich_backtest.job_persistence.PgBacktestJobStore

---

## 12. 异常类层级

引擎的异常根类是 [`BacktestError`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/exceptions.py)，以下是完整层级：

```text
BacktestError                          # 根异常（不要直接 catch 此异常）
├── DataLoadError
│   ├── BarSchemaError                  # 列名缺失/类型错
│   ├── TimezoneError                   # naive datetime
│   └── MissingDataError                # 时间窗口内无数据
├── StrategyError
│   ├── OnBarSignatureError             # on_bar 签名错
│   ├── SignalError                     # 信号计算错
│   └── OrderIntentError                # OrderIntent 字段非法
├── ExecutionError
│   ├── InsufficientCashError           # 现金不足
│   └── LimitHitError                   # 触及涨跌停
├── AccountError
├── CorporateActionError
├── MarginError                         # 保证金不足
├── AttributionError
├── MetricsError
├── BacktestPersistenceError
├── BacktestJobError
├── SweepPersistenceError
├── WalkForwardPersistenceError
├── LiveSignalError
├── SignalProductionError
├── PreprocessingError                  # SignalPreprocessor 链错
└── LiveDataError

# 非 BacktestError 子类
RetryableError                         # 触发自动重试
TerminalError                          # 跳过重试，立刻 mark_failed
```

---

## 13. 时区与时间工具

::: getrich_backtest.time.get_shanghai_tz

::: getrich_backtest.time.ensure_shanghai_aware

::: getrich_backtest.time.require_shanghai_aware

::: getrich_backtest.time.normalize_datetime_range

---

## 14. 实时信号生成

::: getrich_backtest.live.SignalProducer

::: getrich_backtest.live.EvalSignalWriter

::: getrich_backtest.live.SignalWriter

::: getrich_backtest.live.Signal

---

## 15. 重采样 / 频率

::: getrich_backtest.data.resample.resample_bars

`FREQ_TO_MINUTES` 字典映射 `Frequency` enum → 分钟数。

---

## 16. 平台层（apps/strategy/、apps/worker/）

平台层模块在 `src/getrich/apps/` 下，**不在 `getrich_backtest` 公共 API 内**。它们依赖 `getrich_backtest` 的核心原语，但加上 PG 持久化、Celery 调度、HTTP API 等平台特性。详见：

- [架构总览](../platform/architecture.md)（Phase 2 文档）
- [`src/getrich/apps/strategy/`](https://github.com/getrich/getrich/tree/main/src/getrich/apps/strategy/)
- [`src/getrich/apps/worker/`](https://github.com/getrich/getrich/tree/main/src/getrich/apps/worker/)

主要类：

- `BacktestJobRunner`（`getrich.apps.strategy.backtest_job_runner`）—— P0 收尾后的运行入口
- `BacktestJobOp`、`BacktestOneShotOp`、`BacktestJobRunResult` —— 同模块
- `BacktestExecutionService`（`getrich.apps.web.services.backtest_execution`）—— 平台 API 入口
- `WorkerCancelListener`（`getrich.apps.worker.cancel_listener`）—— 跨进程取消探测

---

## 17. 阅读指引

- **5 分钟跑通第一个 backtest**：[快速开始 / 第一个回测](../getting-started/first-backtest.md)
- **5 分钟引擎上手**：[引擎 / 5 分钟上手](getting-started.md)
- **核心抽象深入**：[核心概念](concepts.md)
- **数据加载器详解**：[数据加载器](data-loaders.md)
- **策略开发详解**：[策略开发](strategies.md)
- **组合与权重分配**：[组合与权重](portfolio-allocation.md)
- **执行、账户、风险**：[执行与账户](execution-accounting.md)
- **多频率回测**：[多频率与重采样](multi-frequency.md)
- **分析与报告**：[分析与报告](analysis-reporting.md)
- **参数优化**：[参数扫描与优化](parameter-optimization.md)
- **持久化**：[持久化与 artifact](persistence.md)
- **实盘信号生成**：[实盘信号生成](live-signals.md)
