# 32. 风险控制

> 事前 + 事后双层风控，覆盖单合约、单品种、组合三级。Greeks 暴露含 Cash Greeks（即原文 "¥ Greeks"）。对应原需求"风险控制"全部条目，并补全规范。

## 1. 风控层次

```text
                  ┌────────────────────┐
                  │  Portfolio Risk     │  (组合，全策略聚合)
                  └──┬─────────────────┘
                     │
                  ┌──┴─────────────────┐
                  │  Strategy Risk      │  (单策略子账户)
                  └──┬─────────────────┘
                     │
                  ┌──┴─────────────────┐
                  │  Position Risk      │  (单合约)
                  └────────────────────┘
```

任何风险维度（杠杆、Delta、单品种敞口等）都可在三个层次独立设定阈值；越上层越**保守 / 总览**，越下层越**细粒度 / 即时**。

## 2. 暴露度（Exposure）

### 2.1 名义暴露 (Notional Exposure)

```
notional_i = qty_i × price_i × multiplier_i
gross_notional = Σ |notional_i|
net_notional = Σ notional_i
```

衍生指标：

```
gross_leverage = gross_notional / equity
net_leverage = net_notional / equity
long_exposure = Σ notional_i (i ∈ long)
short_exposure = Σ |notional_i| (i ∈ short)
```

### 2.2 风险度（Risk Ratio）

期货 / 卖方期权：

```
risk_ratio = (sum(margin_held) + sum(short_option_unrealized_loss)) / equity
```

风控阈值（默认）：
- `risk_ratio >= 0.7` 警告
- `risk_ratio >= 0.9` 阻断新开仓
- `risk_ratio >= 0.95` margin call
- `risk_ratio >= 1.0` 触发强平（详见 `31-account-margin.md` §6）

### 2.3 单品种聚合

按 `product` 字段（如 `RB`/`IF`/`510050.SH`）聚合：

```python
product_exposure[p] = Σ |notional_i| for i in product == p
```

约束：`product_exposure[p] / equity <= max_product_exposure`（默认 0.30）。

## 3. Greeks（仅期权）

### 3.1 标准 Greeks

按 BSM / Black-76 / Binomial 计算：

| 希腊 | 含义 | 公式（BSM 简化） |
| --- | --- | --- |
| `Δ Delta` | 标的价格变动 1 单位时的期权价格变动 | `N(d1)` 看涨 |
| `Γ Gamma` | Delta 对标的的二阶导 | `φ(d1) / (S σ √T)` |
| `V Vega` | 对 IV 1% 变动的敏感度 | `S φ(d1) √T / 100` |
| `Θ Theta` | 时间衰减（按日，负值表示损失） | `-S φ(d1) σ / (2√T) - r K e^{-rT} N(d2)` |
| `Ρ Rho` | 对无风险利率的敏感度 | `K T e^{-rT} N(d2)` |
| `Vanna` | ∂Δ/∂σ | 二阶交叉项 |
| `Volga` | ∂V/∂σ | 二阶交叉项 |

各 Greek 都按"每张期权"返回；引擎聚合时乘 `qty × multiplier`。

### 3.2 Cash Greeks（¥ Greeks）

把希腊换算成"每单位标的价格 / 利率 / 波动率变动对组合带来的 PnL 金额"：

| 名 | 公式 | 单位 |
| --- | --- | --- |
| `$Δ` Cash Delta | `Δ × S × multiplier × qty` | 元 / (1 单位 ΔS) |
| `$Γ` Cash Gamma | `½ × Γ × S² × multiplier × qty × 0.0001` | 元 / (1% ΔS)² |
| `$V` Cash Vega | `V × multiplier × qty` (V 已按 1% 量纲) | 元 / 1% IV |
| `$Θ` Cash Theta | `Θ × multiplier × qty` | 元 / 日 |
| `$Ρ` Cash Rho | `Rho × multiplier × qty × 0.0001` | 元 / 1 bp 利率 |

Cash Greeks 是**直接可读 PnL 暴露**，远比裸 Greeks 更适合风险沟通。

> **量纲约定**：
> - `$Γ` 默认按"标的价格 1% 变动"为基准；如需"1 元变动"基准，参数化 `gamma_bump_pct=1`。
> - `$V` 默认按"IV 1 个百分点变动"为基准。
> - `$Ρ` 默认按"1 bp = 0.0001"为基准。
> 配置：`RiskConfig.cash_greeks_basis = "pct" | "abs"`。

### 3.3 Greeks 聚合

```python
class GreeksAggregator:
    def by_position(self, account) -> pl.DataFrame: ...
    def by_underlying(self, account) -> pl.DataFrame: ...   # 按标的聚合
    def by_strategy(self, account) -> pl.DataFrame: ...
    def portfolio(self, account) -> GreeksSnapshot: ...     # 全仓
```

**关键细节**：Delta 跨标的不能简单相加（无意义），按 `underlying` 维度聚合后再看美元 Delta。引擎用 `$Δ` 做全组合 Delta 暴露的统一度量。

### 3.4 计算与缓存

- 每根 bar 收盘时刷新所有期权 Greeks，写入 `runs/{run_id}/greeks_timeline.parquet`
- IV 由 `IVStore` 求解后缓存；后续 Greeks 用缓存 IV
- 利率默认 `risk_free_rate = 0.018`，可时变（接入 1Y CGB 收益率序列）

## 4. 风险限额（ExposureLimit）

```python
@dataclass(frozen=True)
class ExposureLimit:
    scope: Scope             # POSITION / STRATEGY / PORTFOLIO
    metric: Metric           # GROSS_LEVERAGE / NET_LEVERAGE / PRODUCT_EXP / DELTA / CASH_DELTA / VEGA / ...
    key: str | None          # metric=PRODUCT_EXP 时填品种代码；DELTA 时填 underlying
    upper: Decimal | None
    lower: Decimal | None
    action: Action           # WARN / BLOCK_NEW / REDUCE / LIQUIDATE
    cooldown: timedelta = timedelta(minutes=5)
```

示例：

```python
limits = [
    ExposureLimit(Scope.PORTFOLIO, Metric.GROSS_LEVERAGE,
                  upper=Decimal("3.0"), action=Action.BLOCK_NEW),
    ExposureLimit(Scope.STRATEGY, Metric.PRODUCT_EXP, key="IF",
                  upper=Decimal("0.5"), action=Action.BLOCK_NEW),
    ExposureLimit(Scope.PORTFOLIO, Metric.CASH_DELTA, key="510050.SH",
                  upper=Decimal("500_000"), lower=Decimal("-500_000"),
                  action=Action.WARN),
    ExposureLimit(Scope.POSITION, Metric.SINGLE_NOTIONAL, key=None,
                  upper=Decimal("2_000_000"), action=Action.BLOCK_NEW),
]
```

## 5. 风险检查流程

### 5.1 事前检查（Pre-trade）

订单从策略提交后、撮合前：

```python
def precheck(self, order: Order, account: Account) -> CheckResult:
    # 1) 资金 / 保证金可用性
    if not account.can_reserve(order):
        return Reject("INSUFFICIENT_FUNDS")
    # 2) 单合约 notional 限额
    if exceeds(SINGLE_NOTIONAL, order, account):
        return Reject("LIMIT_SINGLE_NOTIONAL")
    # 3) 单品种 / Delta 限额（含本订单 hypothetical 影响）
    if exceeds(PRODUCT_EXP | CASH_DELTA, order, account):
        return Reject("LIMIT_PRODUCT_OR_DELTA")
    # 4) 流动性检查（参与率预估）
    if intraday_participation(order) > capacity.rate:
        return DownsizeTo(...)
    # 5) Tradability（涨跌停/停牌/休市）
    if not tradability.can_submit(order):
        return Reject(tradability.reason)
    return Accept()
```

事前 reject 直接转 `on_order_rejected(reason)`；事前 downsize 自动修改 `order.qty` 后放行（策略可订阅 `on_order_downsized`）。

### 5.2 事后扫描（Post-trade / EOD）

- 每根 bar 结算后：检查 `Portfolio` / `Strategy` 层 metric 是否越限
- 越限时按 `action`：
  - `WARN`：写入 `risk_alerts.parquet`
  - `BLOCK_NEW`：标记 `strategy.blocked_until = now + cooldown`，期间事前 reject 所有新开仓
  - `REDUCE`：生成"降仓建议单"，标签 `risk_reduction`，交由策略 `on_risk_reduction` 决定是否执行
  - `LIQUIDATE`：直接接管，按强平流程清仓违规品种

### 5.3 杠杆动态调整

接入"波动率回看"机制：组合波动率超过阈值时自动 down-leverage：

```python
DynamicLeverageRule(
    target_vol_annual=Decimal("0.15"),
    lookback_days=30,
    rebalance_freq="W-MON",
)
```

按 `target_leverage = target_vol / realized_vol` 等比例缩放策略下达的目标头寸。

## 6. RiskManager 接口

```python
class RiskManager:
    def __init__(self, limits: list[ExposureLimit], greeks_aggregator: GreeksAggregator): ...

    def precheck(self, order: Order, account: Account) -> CheckResult: ...
    def post_bar_scan(self, account: Account, dt: datetime) -> list[RiskAlert]: ...
    def eod_scan(self, account: Account, dt: date) -> list[RiskAlert]: ...
    def snapshot(self, account: Account) -> RiskSnapshot: ...

    # 视图（策略只读）
    def view(self, strategy_name: str) -> RiskView: ...
```

## 7. 与策略层的契约

策略可声明 `risk_overrides`：

```python
class MyStrategy(Strategy):
    risk_overrides = [
        # 该策略子账户允许 1.5x 杠杆
        ExposureLimit(Scope.STRATEGY, Metric.GROSS_LEVERAGE,
                      upper=Decimal("1.5"), action=Action.BLOCK_NEW),
    ]
```

但策略 override **不能放宽** 组合层限额：runner 在合并时取**更严格者**。

## 8. RiskSnapshot 数据结构

```python
@dataclass(frozen=True)
class RiskSnapshot:
    dt: datetime
    gross_leverage: Decimal
    net_leverage: Decimal
    risk_ratio: Decimal
    cash_delta_by_underlying: dict[str, Decimal]
    cash_gamma_by_underlying: dict[str, Decimal]
    cash_vega_by_underlying: dict[str, Decimal]
    cash_theta_total: Decimal
    product_exposure: dict[str, Decimal]
    var_95_1d: Decimal | None
    es_95_1d: Decimal | None
    breaches: list[RiskAlert]
```

每根 bar 收盘后追加到 `runs/{run_id}/risk_timeline.parquet`。

## 9. VaR / ES（与压力测试共用）

风险层提供两类 VaR 估计：

- **历史模拟法**：用过去 N 日收益的 1% 分位数 × 当前持仓敞口
- **方差-协方差法**：用 Cash Greeks × 因子协方差矩阵

详细情景重演与压力 P&L 见 `43-stress-test.md`。

## 10. 最小示例

```python
from getrich_backtest.risk import (
    RiskManager, ExposureLimit, Scope, Metric, Action,
)

risk = RiskManager(
    limits=[
        ExposureLimit(Scope.PORTFOLIO, Metric.GROSS_LEVERAGE,
                      upper=Decimal("3.0"), action=Action.BLOCK_NEW),
        ExposureLimit(Scope.PORTFOLIO, Metric.RISK_RATIO,
                      upper=Decimal("0.9"), action=Action.BLOCK_NEW),
        ExposureLimit(Scope.PORTFOLIO, Metric.CASH_DELTA,
                      key="510050.SH",
                      upper=Decimal("1_000_000"),
                      lower=Decimal("-1_000_000"),
                      action=Action.WARN),
        ExposureLimit(Scope.STRATEGY, Metric.PRODUCT_EXP, key="IF",
                      upper=Decimal("0.5"), action=Action.REDUCE),
    ],
)
```

## 11. 设计禁区

- **禁止**风控层修改 `Account` 状态（除强平触发时）；它是观察者+裁判。
- **禁止**用裸 Δ 跨标的相加做组合 Delta 风险——必须聚合到 `$Δ`。
- **禁止**在 `precheck` 内做长耗时计算（如 IV 求解）；用上一根 bar 的缓存。
- **禁止**忽略卖方期权未实现亏损对保证金的吞噬（见 §2.2 risk_ratio 公式）。
- **禁止**让策略级 override 放宽组合限额。
