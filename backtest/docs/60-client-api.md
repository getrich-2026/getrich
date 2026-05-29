# 60. 客户端接口

> 给"使用者"看的一份汇总：策略开发者、研究员、产品集成方都从这里入手。所有签名都聚合自前面分层文档；本文是**单页快查 + 完整最小可运行示例**。

## 1. 公开符号总览

```python
# 顶级入口
from getrich_backtest import (
    Backtest,           # 主回测器
    Strategy,           # 基类
    SignalStrategy,
    TargetPositionStrategy,
    EventStrategy,
    OrderIntent, OrderType, Side, TIF, TPSLDef,
    AssetClass,
    Universe,
    BarLoader,
    Calendar,
    Decimal,            # re-export decimal.Decimal
)

# 模型 / 配置（按需用）
from getrich_backtest.execution import (
    NextBarMatchingModel, IntraBarMatchingModel, ConservativeMatchingModel,
    SlippageModel, FeeModel, CapacityModel, AlgoStyle,
)
from getrich_backtest.account import Account, MarginPolicy
from getrich_backtest.risk import (
    RiskManager, ExposureLimit, Scope, Metric, Action,
)
from getrich_backtest.strategy import (
    Portfolio, EqualWeight, ScoreWeight, InverseVol, RiskParity,
    MeanVariance, BlackLitterman,
    Constraints, PeriodicRebalance, ThresholdRebalance, EventRebalance,
    PortfolioAllocator, FixedAllocator, RiskBudgetAllocator,
)
from getrich_backtest.analytics import (
    MetricsCalculator, AttributionEngine,
    FactorEvaluator, LayeredBacktest,
    StressTester, Scenario, Shock, ShockTarget, DeltaType,
)
from getrich_backtest.research import (
    WalkForward, GridSearch, RandomSearch, BayesianSearch, CmaesSearch,
    ParamSpace, P, Pareto, Metric as MetricSpec,
)
from getrich_backtest.runtime import (
    RunConfig, RunIdentity, Replayer, Checkpoint,
)
from getrich_backtest.report import Reporter, compare_runs
```

## 2. Backtest 主类

### 2.1 构造

```python
class Backtest:
    def __init__(
        self,
        *,
        start: datetime | str,
        end: datetime | str,
        freq: str,                                  # "1m" | "1d"
        universe: Universe,
        initial_capital: Decimal,
        # 可选模型
        bar_loader: BarLoader | None = None,        # 默认 PgBarLoader.from_env()
        calendar: Calendar | None = None,
        matching: MatchingModel | None = None,      # 默认 NextBarMatchingModel
        slippage: dict[AssetClass, SlippageModel] | SlippageModel | None = None,
        fees: dict[AssetClass, FeeModel] | FeeModel | None = None,
        capacity: CapacityModel | None = None,
        execution_lag_bars: int = 1,
        risk: RiskManager | list[ExposureLimit] | None = None,
        benchmark: str | Benchmark | None = None,
        allocator: PortfolioAllocator | None = None,
        seed: int | None = None,
        checkpoint: Checkpoint | None = None,
        resume_from: str | Path | None = None,
        snapshot_dir: str | Path = "runs/{run_id}/",
        config_path: str | Path | None = None,      # 仅用于记录引用
        base_currency: str = "CNY",
    ): ...

    @classmethod
    def from_config(cls, cfg: RunConfig) -> "Backtest": ...

    def add_strategy(
        self,
        strategy: Strategy,
        capital_weight: Decimal | None = None,      # 多策略时使用
        risk_overrides: list[ExposureLimit] | None = None,
        subaccount_mode: str = "isolated",          # "isolated" | "shared"
    ) -> None: ...

    def run(self, strategy: Strategy | None = None) -> "BacktestResult": ...
    def stream(self) -> Iterator["BarEvent"]: ...   # 调试/可视化用
```

### 2.2 BacktestResult

```python
class BacktestResult:
    identity: RunIdentity
    snapshot_dir: Path

    # 视图：合并 / 单策略
    @property
    def combined(self) -> "ResultView": ...
    def strategy(self, name: str) -> "ResultView": ...

class ResultView:
    def metrics(self) -> MetricsCalculator: ...
    def attribution(self) -> AttributionEngine: ...
    def equity_curve(self) -> pl.DataFrame: ...
    def trades(self) -> pl.DataFrame: ...
    def fills(self) -> pl.DataFrame: ...
    def positions_timeline(self) -> pl.DataFrame: ...
    def risk_timeline(self) -> pl.DataFrame: ...
    def greeks_timeline(self) -> pl.DataFrame: ...
    def ledger(self) -> pl.DataFrame: ...
    def tear_sheet(self) -> "TearSheet": ...
```

## 3. Strategy 简化签名

详细见 `20-strategy-api.md`；这里贴最常用的 3 个类型。

### 3.1 事件型

```python
class Strategy:
    name: str
    version: str = "0.1.0"

    def setup(self, ctx): ...
    def on_bar(self, ctx) -> Iterable[OrderIntent] | None: ...
    def on_fill(self, ctx, fill): ...
```

### 3.2 信号型

```python
class SignalStrategy(Strategy):
    portfolio: Portfolio        # 必填，决定信号 -> 头寸
    def compute_signal(self, ctx) -> pl.DataFrame:
        """返回 [symbol, score]"""
```

### 3.3 目标仓位型

```python
class TargetPositionStrategy(Strategy):
    def compute_target(self, ctx) -> pl.DataFrame:
        """返回 [symbol, target_qty] 或 [symbol, target_weight]"""
```

## 4. Context 接口

```python
class BarContext:
    # 时间 / 配置
    now: datetime
    run_id: str
    config: RunConfig

    # 数据
    bar: pl.DataFrame              # 当前 bar 横截面
    def lookback(self, symbols, columns, n) -> pl.DataFrame: ...
    def factor(self, name) -> pl.DataFrame: ...
    def session(self) -> Session: ...
    tradability: dict[str, dict[Side, Tradability]]

    # 账户 / 风险（只读）
    account: AccountView
    risk: RiskView

    # 行为
    def submit(self, intent: OrderIntent) -> None: ...
    def cancel(self, order_id) -> None: ...
    def cancel_all(self, symbol=None) -> None: ...
    def roll_position(self, from_sym, to_sym, qty=None) -> None: ...
    def exercise_option(self, symbol, qty) -> None: ...

    # 状态
    state: StrategyStateStore       # KV 存储
    logger: StrategyLogger
    rng: random.Random              # seeded
```

`AccountView` / `RiskView` 是只读快照，所有变更只能通过 `ctx.submit`。

## 5. OrderIntent

```python
OrderIntent(
    symbol: str,
    side: Side,
    qty: Decimal | None = None,
    weight: Decimal | None = None,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
    time_in_force: TIF = TIF.DAY,
    take_profit: TPSLDef | None = None,
    stop_loss: TPSLDef | None = None,
    tag: str | None = None,
    algo: AlgoStyle | None = None,
)

TPSLDef(
    trigger: Decimal,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    trailing: Decimal | None = None,
)
```

## 6. 端到端最小示例

### 6.1 事件型策略 — 双均线

```python
from decimal import Decimal
import polars as pl
from getrich_backtest import (
    Backtest, Strategy, OrderIntent, OrderType, Side,
    Universe, AssetClass,
)
from getrich_backtest.execution import SlippageModel, FeeModel, CapacityModel
from getrich_backtest.risk import RiskManager, ExposureLimit, Scope, Metric, Action

class MACross(Strategy):
    name = "ma_cross_v1"

    def __init__(self, fast=5, slow=20):
        self.fast = fast
        self.slow = slow

    def on_bar(self, ctx):
        h = ctx.lookback(ctx.universe.symbols, ["close"], n=self.slow + 1)
        sig = (
            h.group_by("symbol", maintain_order=True)
             .agg(
                 fast=pl.col("close").tail(self.fast).mean(),
                 slow=pl.col("close").tail(self.slow).mean(),
             )
             .with_columns(direction=pl.when(pl.col("fast") > pl.col("slow")).then(1).otherwise(-1))
        )
        for row in sig.iter_rows(named=True):
            sym = row["symbol"]
            current = ctx.account.position(sym).qty
            target = Decimal("100") * row["direction"]
            if current != target:
                yield OrderIntent(
                    symbol=sym,
                    side=Side.BUY if target > current else Side.SELL,
                    qty=abs(target - current),
                    order_type=OrderType.MARKET,
                    tag="ma_cross_signal",
                )

bt = Backtest(
    start="2023-01-01",
    end="2024-12-31",
    freq="1d",
    universe=Universe.from_symbols(["IF2412.CFE"]),
    initial_capital=Decimal("10_000_000"),
    slippage={AssetClass.INDEX_FUTURE: SlippageModel.fixed_tick(1)},
    fees={AssetClass.INDEX_FUTURE: FeeModel.index_future_default()},
    capacity=CapacityModel.bar_pct(0.05),
    risk=RiskManager([
        ExposureLimit(Scope.PORTFOLIO, Metric.GROSS_LEVERAGE,
                      upper=Decimal("3.0"), action=Action.BLOCK_NEW),
        ExposureLimit(Scope.PORTFOLIO, Metric.RISK_RATIO,
                      upper=Decimal("0.9"), action=Action.BLOCK_NEW),
    ]),
    benchmark="000300.SH",
    seed=20260528,
)
result = bt.run(MACross(fast=8, slow=30))

print(result.identity.run_id)
print(result.combined.metrics().all())
result.combined.tear_sheet().save(result.snapshot_dir, formats=["html", "parquet"])
```

### 6.2 信号型 + 组合 — 横截面动量

```python
from getrich_backtest import SignalStrategy, Universe
from getrich_backtest.strategy import (
    Portfolio, EqualWeight, Constraints, PeriodicRebalance,
    SignalPreprocessor, Winsorize, Standardize, Neutralize,
)

class Mom20(SignalStrategy):
    name = "mom20_csi500"

    portfolio = Portfolio(
        preprocessor=SignalPreprocessor(
            winsorize=Winsorize.mad(3),
            standardize=Standardize.rank(),
            neutralize=Neutralize.industry_size(),
        ),
        allocator=EqualWeight(top_k=50, bottom_k=50, dollar_neutral=True),
        constraints=Constraints(
            max_single_weight=Decimal("0.02"),
            max_industry_weight=Decimal("0.15"),
            gross_exposure=Decimal("1.0"),
            turnover_per_rebalance=Decimal("0.30"),
        ),
        rebalance=PeriodicRebalance(every="W-MON"),
    )

    def compute_signal(self, ctx):
        h = ctx.lookback(ctx.universe.symbols, ["close"], n=21)
        return (
            h.group_by("symbol", maintain_order=True)
             .agg(score=(pl.col("close").last() / pl.col("close").first() - 1))
        )

bt = Backtest(
    start="2022-01-01", end="2024-12-31", freq="1d",
    universe=Universe.csi_500(),
    initial_capital=Decimal("100_000_000"),
    benchmark="000905.SH",
    seed=20260528,
)
result = bt.run(Mom20())
result.combined.tear_sheet().save(result.snapshot_dir)
```

### 6.3 多策略组合

```python
bt = Backtest(
    start="2022-01-01", end="2024-12-31", freq="1d",
    universe=Universe.union(Universe.csi_300(), Universe.from_symbols(["IF2412.CFE"])),
    initial_capital=Decimal("100_000_000"),
    allocator=FixedAllocator({"ma_cross_v1": Decimal("0.4"), "mom20_csi500": Decimal("0.6")}),
)
bt.add_strategy(MACross(fast=8, slow=30), capital_weight=Decimal("0.4"))
bt.add_strategy(Mom20(),                  capital_weight=Decimal("0.6"))

result = bt.run()
result.strategy("ma_cross_v1").tear_sheet().save(...)
result.strategy("mom20_csi500").tear_sheet().save(...)
result.combined.tear_sheet().save(result.snapshot_dir / "combined")
```

### 6.4 因子研究

```python
from getrich_backtest.analytics import FactorEvaluator

fe = FactorEvaluator(factor_store, bar_loader)
ic = fe.ic("mom20", Universe.csi_500(), "2022-01-01", "2024-12-31", H=5, method="rank")
decay = fe.decay("mom20", Universe.csi_500(), "2022-01-01", "2024-12-31", horizons=[1,5,10,20,60])
layered = fe.layered("mom20", Universe.csi_500(), "2022-01-01", "2024-12-31", k=10)

fe.report("mom20", Universe.csi_500(), "2022-01-01", "2024-12-31") \
   .save_html("runs/factor_mom20.html")
```

### 6.5 Walk-forward

```python
from getrich_backtest.research import WalkForward, GridSearch, ParamSpace, P

space = ParamSpace({
    "fast": P.int_range(3, 20, step=2),
    "slow": P.int_range(20, 100, step=10),
}).add_constraint(lambda c: c["fast"] < c["slow"])

wf = WalkForward(
    train_months=18, val_months=3, step_months=3,
    sweep=GridSearch(space),
    select_metric="sharpe",
    refit="rolling",
)
result = wf.run(
    strategy_cls=MACross,
    bt_template={
        "universe": Universe.from_symbols(["IF2412.CFE"]),
        "freq": "1d",
        "initial_capital": Decimal("10_000_000"),
    },
    start="2018-01-01", end="2024-12-31",
)
result.report().save_html("runs/ma_wf.html")
```

### 6.6 压力测试

```python
from getrich_backtest.analytics import StressTester, Scenario

st = StressTester.from_result(result)
df = st.batch([
    Scenario.preset.EQUITY_DOWN_10,
    Scenario.preset.EQUITY_DOWN_20_2015,
    Scenario.preset.MARGIN_HIKE_50PCT,
])
print(df)

# 自定义
my_scenario = Scenario(
    name="hs300_-10_iv+50",
    shocks=[
        Shock(ShockTarget.PRICE, "510300.SH", DeltaType.PCT, Decimal("-0.10")),
        Shock(ShockTarget.IV,    "510300.SH", DeltaType.PCT, Decimal("+0.50")),
    ],
)
print(st.run(my_scenario).pnl_pct)
```

### 6.7 从 YAML 配置启动

```bash
getrich-bt run config/ma_cross_v1.yaml --seed 42 --override strategy.params.fast=8
```

或 Python：

```python
from getrich_backtest.runtime import RunConfig
cfg = RunConfig.from_yaml("config/ma_cross_v1.yaml")
result = Backtest.from_config(cfg).run()
```

### 6.8 复跑校验

```python
from getrich_backtest.runtime import Replayer
replay = Replayer("runs/9f3c8b1a/")
new_result = replay.rerun()
assert replay.diff(new_result).is_empty()
```

## 7. CLI 汇总

```bash
getrich-bt run        <config.yaml> [--seed N] [--override path=value] [--strict]
getrich-bt sweep      <config.yaml> --space space.yaml --backend mp --workers 8
getrich-bt walk       <config.yaml> --space space.yaml --train 18m --val 3m --step 3m
getrich-bt factor     <factor_cfg.yaml>
getrich-bt stress     <run_id> --scenarios preset:standard
getrich-bt replay     <run_id> [--strict]
getrich-bt report     <run_id> [--kind tear|risk|factor|walk] [--format html|pdf]
getrich-bt compare    <run_id1> <run_id2>  ...
getrich-bt diff-config <runA> <runB>
getrich-bt prune-runs --older-than 90d --keep-tagged production
```

## 8. 与平台数据库的对接（PgSQL）

默认 `PgBarLoader.from_env()` 读取下列环境变量（与 GetRich 平台 `pool.py` 一致）：

```bash
GETRICH_PG_HOST=...
GETRICH_PG_PORT=5432
GETRICH_PG_DB=getrich
GETRICH_PG_USER=...
GETRICH_PG_PASSWORD=...
GETRICH_PG_TZ=Asia/Shanghai
```

如需切到其它后端（Parquet 仓、DuckDB 文件、远程 API）：

```python
from getrich_backtest import Backtest
from my_custom_loaders import ParquetBarLoader

bt = Backtest(
    ...,
    bar_loader=ParquetBarLoader(root="/data/bars/"),
)
```

实现 `BarLoader` 协议即可（详见 `10-data-layer.md` §4）。

## 9. 性能与并发

- **进程内**：策略 `on_bar` 用 Polars 表达式；耗时计算放 `setup` 一次预算
- **多策略**：单进程顺序运行（保留账户/风控一致性）
- **多回测（Sweep / WF）**：`backend="multiprocessing" | "ray" | "dask"`
- **大数据集**：`bar_loader.iter_bars(chunk="month")` 流式处理，控内存

## 10. 错误码索引

| Error | 触发 | 处理建议 |
| --- | --- | --- |
| `BarSchemaError` | 数据列/类型不符 | 检查数据源 |
| `TimezoneError` | naive datetime 进入引擎 | 全程 `Asia/Shanghai` aware |
| `InsufficientFundsError` | precheck 资金不足 | 改用 precheck 日志而非异常 |
| `MarginCallEvent` | 维持保证金不足 | `on_margin_call` 主动减仓 |
| `ForcedLiquidationEvent` | 风险度 ≥ 强平阈值 | 引擎自动平仓 |
| `ReplayMismatchError` | 复跑结果不一致 | 检查 `code_diff.patch`、`data_version` |
| `TestSetLeakageWarning` | 多次访问 Test 集 | 重新切分 |
| `AttributionMismatchError` | 归因加和 ≠ 总 PnL | 排查 `unexplained`、数据缺口 |
| `ReportConsistencyError` | 报告数值与底层 parquet 不一致 | 重生成报告，必要时清缓存 |

## 11. 进一步阅读

按角色：

- **策略开发者**：`20-strategy-api.md` → `21-portfolio-construction.md` → `30-execution-engine.md`
- **因子研究员**：`41-factor-eval.md` → `50-param-search.md` → `42-benchmark-attribution.md`
- **风控**：`32-risk-control.md` → `43-stress-test.md` → `31-account-margin.md`
- **平台 / MLOps**：`51-config-versioning.md` → `52-report-visualization.md` → `01-architecture.md`
- **新人通读**：`01-architecture.md` → `10-data-layer.md` → `20-strategy-api.md` → `30-execution-engine.md` → `40-metrics.md`
