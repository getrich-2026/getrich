# 01. 整体架构

## 1. 设计目标

构建一套支持**多资产、多频率、跨品种**回测的研究与生产前验证框架，覆盖：

- **资产**：A 股现货、A 股期权（含 ETF 期权与个股期权）、中国商品期货、股指期货、商品期货期权、股指期货期权
- **频率**：1m（分钟）、1d（日频）；预留 5m/15m/30m/60m 扩展位
- **使用形态**：
  - 单策略单品种快速回测（研究迭代）
  - 多策略多品种组合回测（生产前验证）
  - 因子研究（IC/分层回测）
  - 参数搜索与 Walk-forward
- **可复现**：同样的配置 + 数据快照 + 代码版本 + 随机种子，结果逐笔逐毫秒对账一致。

## 2. 分层架构

```text
┌──────────────────────────────────────────────────────────────┐
│ 60. Client API（Strategy / Backtest / Result / CLI）          │
├──────────────────────────────────────────────────────────────┤
│ 50. 研究层：参数搜索 · Walk-forward · 报告 · 配置/版本快照     │
├──────────────────────────────────────────────────────────────┤
│ 40. 分析层：收益指标 · 统计指标 · 归因 · 因子评估 · 压力测试   │
├──────────────────────────────────────────────────────────────┤
│ 32. 风控层：Greeks 暴露 · 单品种/全仓暴露 · 杠杆/风险度 · 风控阀│
├──────────────────────────────────────────────────────────────┤
│ 31. 账户层：现金/保证金/持仓/结算/强平/T+x/公司行为调整       │
├──────────────────────────────────────────────────────────────┤
│ 30. 执行层：订单生命周期 · 撮合 · 滑点 · 费率 · 容量 · 部分成交 │
├──────────────────────────────────────────────────────────────┤
│ 20/21. 策略层：策略 API · 信号 · 组合构建 · 调仓 · 多策略分配  │
├──────────────────────────────────────────────────────────────┤
│ 10/11/12. 数据层：PgSQL→Polars 长表 · 复权/质量 · 日历/可交易 │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向**：上层依赖下层；下层不感知上层。例如：执行层不知道是哪个策略下的单，只看到带元数据的订单意图。

## 3. 事件循环

回测以**事件驱动**为骨架。一个 bar 上的标准事件序列：

```text
SessionOpen(session)
   └── on_session_open(strategy)          # 策略可发盘前指令
BarTick(bar)
   ├── MarkToMarket(account, prev_bar)    # 用上一根 bar 估值（避免 look-ahead）
   ├── RiskPreCheck                       # 触发限额/强平判定
   ├── on_bar(strategy) → [OrderIntent]   # 策略产生意图
   ├── ExecutionEngine.match(intents, bar)
   │     ├── slippage / fee / capacity
   │     └── partial_fill?
   ├── on_fill(strategy, fill)            # 成交回调
   ├── RiskPostCheck                      # 事后风险监控
   └── AccountUpdate(balance, margin, pos)
SessionClose(session)
   └── on_session_close(strategy)
DailySettle                                # 期货每日盯市结算
RolloverCheck                              # 期货换月、期权到期处理
```

**两条强约束**：
1. **决策与执行隔离**：策略只能基于 `bar.close_time <= now` 的信息生成意图；意图在**下一根 bar** 才能执行（默认 `execution_lag_bars=1`）。可配 `lag=0` 用于日频收盘价回测，但默认禁止以防 look-ahead。
2. **估值用上一根 bar**：mark-to-market 用 `t-1` 收盘价，避免用未实现的当前 bar 收盘价"提前知道"PnL。

## 4. 模块清单与文档映射

| 层 | 模块 | 文档 | 关键产物 |
| --- | --- | --- | --- |
| 数据 | 行情访问 | `10-data-layer.md` | `BarLoader`, `Universe` |
| 数据 | 复权 / 质量 | `11-data-quality.md` | `AdjustmentPolicy`, `ContinuousContract` |
| 数据 | 日历 / 可交易 | `12-calendar-tradability.md` | `Calendar`, `Tradability` |
| 策略 | 策略 API | `20-strategy-api.md` | `Strategy`, `Context`, `BarContext` |
| 策略 | 组合 / 调仓 | `21-portfolio-construction.md` | `Portfolio`, `Allocator`, `RebalanceRule` |
| 执行 | 撮合 / 滑点 / 费率 | `30-execution-engine.md` | `ExecutionEngine`, `SlippageModel`, `FeeModel`, `CapacityModel` |
| 账户 | 资金 / 保证金 / 结算 | `31-account-margin.md` | `Account`, `MarginRule`, `Settlement` |
| 风控 | 风险阀 / Greeks | `32-risk-control.md` | `RiskManager`, `ExposureLimit`, `GreeksAggregator` |
| 分析 | 收益 / 统计 / 分析 | `40-metrics.md` | `MetricsCalculator` |
| 分析 | 因子 | `41-factor-eval.md` | `FactorEvaluator`, `LayeredBacktest` |
| 分析 | 归因 / 基准 | `42-benchmark-attribution.md` | `AttributionEngine` |
| 分析 | 压力测试 | `43-stress-test.md` | `StressTester`, `Scenario` |
| 研究 | 参数搜索 | `50-param-search.md` | `ParamSweep`, `WalkForward` |
| 基础 | 配置 / 版本 | `51-config-versioning.md` | `RunConfig`, `Snapshot` |
| 基础 | 报告 | `52-report-visualization.md` | `TearSheet`, `Report` |
| 客户端 | 入口 | `60-client-api.md` | `Backtest`, `Strategy` 入口符号 |

## 5. 相对原需求的重组说明

原始需求按"策略模拟/账户/风控/Output/因子评估 + 10 个补充项"组织。下面是我做的几条专业取舍，原因写在每条之后。

1. **从"策略模拟"中拆出"执行引擎"**
   - 原文把"下单/止盈止损/撮合/滑点/手续费/资金占用/爆仓/成交价格/成交时间"放一起。
   - 重组：止盈止损是**策略意图**的一种（属策略层）；撮合、滑点、手续费、容量是**执行机制**（属执行层）；资金占用是**账户记账**（属账户层）；爆仓的触发判定属**风控**、执行属**账户**。
   - 原因：策略代码不应依赖具体撮合假设；不同回测/实盘可换执行后端，策略代码零改动。

2. **Greeks PnL 归类到"归因"，不归"收益"**
   - 原文把"Greeks pnl"放在"收益类指标"。
   - 重组：收益指标只承载标量收益；Greeks PnL 是把 PnL 按 ΔSΔt、½Γ(ΔS)² 等分解，本质是**归因**问题，归 `42-benchmark-attribution.md`。

3. **拆出独立的"数据质量"与"日历可交易"模块**
   - 原文把"数据质量/复权"与"交易日历/可交易性"放在补充项里。
   - 重组：这两个模块是 look-ahead 与停牌/涨跌停处理的关键，提升为数据层一等公民模块。

4. **"风险控制"扩为完整风控层并引入 Cash Greeks**
   - 原文 `¥ Greeks` 表述含糊。
   - 规范：明确为 **Cash Greeks**——`$Δ = Δ × S × 合约乘数`、`$Γ = Γ × S² × 合约乘数 × 0.01`（百分点定义）等；含义、单位、聚合方式见 `32-risk-control.md` §3。

5. **"参数搜索/样本外/配置版本/报告"独立为研究层与基础设施层**
   - 原文混在补充项里。
   - 重组：参数搜索是策略研究的元层；配置版本是平台基础设施；报告是输出。三者解耦，便于在 CI/批量回测中各自演进。

6. **新增"组合构建"为一等模块**
   - 原文"组合构建与调仓"是补充项第 3 条。
   - 重组：信号 → 权重 → 目标头寸的转换是组合管理的核心；它在策略与执行之间，独立成 `21-portfolio-construction.md`。

7. **"基准与归因"合并为一个文档**
   - 基准选择与归因强耦合（归因要算 Alpha/Beta/TE），合并 `42-benchmark-attribution.md` 减少跳转。

8. **新增"决策/执行延迟"概念**
   - 原文未明示。所有策略默认 `execution_lag_bars=1`；日频可降为 0 但需显式声明并通过事前检查（详见 `30-execution-engine.md` §4）。

9. **"多策略资金分配"归组合构建**
   - 原文"多策略共享资金池和资金分配"放在容量约束的上一条。
   - 重组：多策略分配是组合层（高于单策略）问题，归 `21-portfolio-construction.md` §5。

## 6. 关键设计原则

- **决策 → 意图 → 执行**：策略只输出 `OrderIntent`，执行引擎决定**是否、何时、以何价**成交。策略代码不直接写"成交价 = 当前 close"。
- **mark-to-market 用 t-1 close**：避免 look-ahead，与实盘一致。
- **金额用 Decimal，价格/收益用 Float64**：详见 `00-index.md` 约定。
- **Polars 长表为唯一行情载体**：所有跨模块行情数据按列名规范流转，禁止 dict-of-dataframes。
- **时区统一 Asia/Shanghai aware**：禁止 naive datetime；落 PgSQL 用 `timestamptz`、落 Parquet 用 `timestamp[ms, Asia/Shanghai]`、Polars 用 `Datetime("ms", "Asia/Shanghai")`。
- **可复现 = (Config, DataVersion, CodeRev, Seed)**：四元组完整保存到 `runs/{run_id}/snapshot/`。
- **事前 + 事后双风控**：事前在 `on_bar` 之后、撮合之前拦截违规意图；事后在结算后触发限额报警与强平。
- **Loader 接口对存储中立**：默认用 PgSQL，但 `BarLoader` 协议 (`load_bars(...) -> pl.DataFrame`) 与存储无关，未来引入 Parquet 仓、DuckDB 文件或其它后端只需替换实现类，策略/执行/分析层零改动。

## 7. Python / 依赖约定

- **Python**: 3.13（如平台 `pyproject.toml` 仍锁 3.12，此模块在自身 `pyproject.toml` 内显式声明 3.13 兼容；过渡期允许 3.12+）。
- **核心库**：`polars`、`psycopg[binary,pool]`、`numpy`、`scipy`、`numba`（可选热路径）、`pyarrow`、`pydantic`。
- **可视化**：`plotly`（Tear sheet HTML），`pyecharts` 可选。
- **配置**：`pydantic` + YAML 入口。
- **测试**：`pytest`、`hypothesis`（属性测试，针对账户/撮合一致性）。
- **禁用**：重型 ORM、`pandas` 作为主数据结构（只允许在与外部库交互时短暂转换）。

## 8. 目录结构（实现层建议）

```text
backtest/
├── docs/                       # 本目录
├── src/getrich_backtest/
│   ├── data/                   # 10/11/12
│   │   ├── loader.py
│   │   ├── adjustment.py
│   │   ├── continuous.py
│   │   ├── calendar.py
│   │   └── tradability.py
│   ├── strategy/               # 20/21
│   │   ├── base.py
│   │   ├── context.py
│   │   ├── portfolio.py
│   │   └── allocator.py
│   ├── execution/              # 30
│   │   ├── engine.py
│   │   ├── order.py
│   │   ├── slippage.py
│   │   ├── fee.py
│   │   └── capacity.py
│   ├── account/                # 31
│   │   ├── account.py
│   │   ├── margin.py
│   │   └── settlement.py
│   ├── risk/                   # 32
│   │   ├── manager.py
│   │   ├── greeks.py
│   │   └── exposure.py
│   ├── analytics/              # 40/41/42/43
│   │   ├── metrics.py
│   │   ├── factor.py
│   │   ├── attribution.py
│   │   └── stress.py
│   ├── research/               # 50
│   │   ├── sweep.py
│   │   └── walkforward.py
│   ├── runtime/                # 51 + 事件循环
│   │   ├── config.py
│   │   ├── snapshot.py
│   │   ├── events.py
│   │   └── runner.py
│   ├── report/                 # 52
│   │   ├── tearsheet.py
│   │   └── exporter.py
│   └── api.py                  # 60 入口
├── tests/
├── scripts/
└── pyproject.toml
```
