# 43. 压力测试与情景分析

> 在历史回测之外，对组合做"极端事件 + 情景假设"的 PnL 估算。对应原需求第 7 节"压力测试与情景分析"。

## 1. 三类测试

| 类别 | 输入 | 输出 |
| --- | --- | --- |
| **历史情景重演** | 选定历史窗口（如 2015 股灾、2020 疫情、2022 商品暴跌） | 该情景下当前组合的瞬时 PnL |
| **假设情景** | 用户定义的 shock 向量 | 当前组合在 shock 下的瞬时 PnL |
| **统计风险** | 历史收益分布 | VaR / ES / Tail-VaR |

三类共用同一套 `Scenario` 抽象与 `StressTester` 引擎。

## 2. Scenario 数据结构

```python
@dataclass(frozen=True)
class Shock:
    target: ShockTarget          # PRICE / IV / RATE / MARGIN_RATIO / LIQUIDITY
    scope: str                   # 全局 "*" / underlying / product / sector
    delta_type: DeltaType        # PCT / ABS / SIGMA  (波动率倍数)
    delta: Decimal               # 大小

@dataclass(frozen=True)
class Scenario:
    name: str
    shocks: list[Shock]
    duration: timedelta | None   # None=瞬时；非 None=分布在持续时间内
    correlated: bool = True      # shock 间是否假设相关
```

### 2.1 内置 Scenario 库

| 名 | 内容 |
| --- | --- |
| `EQUITY_DOWN_10` | 全 A 股 -10%，HS300 -8%，IV +50% |
| `EQUITY_DOWN_20_2015` | 2015 股灾区间的实际跳幅与 IV |
| `COMMODITY_DOWN_15` | 黑色系 -15%，化工 -8%，IV +30% |
| `RATE_UP_50BP` | 利率曲线 +50bp，对债期 / 利率敏感期权重估 |
| `MARGIN_HIKE_50PCT` | 各品种保证金率 ×1.5 |
| `LIQUIDITY_HALVE` | bar volume 减半，滑点参数翻倍 |
| `VIX_SPIKE_2X` | 全市场 IV ×2 |
| `LIMIT_LOCK_3_DAY` | A 股连续跌停 3 日 |

可叠加：`Scenario.combine(EQUITY_DOWN_10, MARGIN_HIKE_50PCT)`。

## 3. PnL 估算

### 3.1 权益与期货（一阶 + 二阶可选）

```
ΔPnL_position ≈ qty × multiplier × ΔS
```

如果启用二阶（默认关闭）：

```
ΔPnL_position ≈ qty × multiplier × (ΔS + ½ × convexity × (ΔS)²)
```

### 3.2 期权（Greeks 展开）

详见 `42-benchmark-attribution.md` §4 公式：

```
ΔPnL ≈ Δ × ΔS + ½Γ(ΔS)² + V × Δσ + Θ × Δt + Ρ × Δr
```

参数 `ΔS`、`Δσ` 由 Shock 给出；`Δt` 由 `Scenario.duration` 决定（瞬时为 0）。

### 3.3 重估法（精确）

设 `repricing="full"` 时，对期权头寸用 BSM/Black-76 在新 (S', σ', r') 下重新定价：

```
PnL_position = (P'(S', σ', r') - P) × qty × multiplier
```

精确但耗时；用于关键场景。

### 3.4 保证金冲击

保证金率上调：

```
new_margin_held = qty × price × multiplier × new_ratio
ΔMargin = new_margin_held - old_margin_held
post_shock_risk_ratio = (sum(new_margin_held) - ΔPnL) / equity
```

如果 `post_shock_risk_ratio > 1.0`，标记 `would_be_liquidated=True`。

### 3.5 流动性冲击

把所有 `CapacityModel.rate` 减半，运行一个"清仓模拟"：用当前持仓 ÷ 减半后的 bar volume 估算多少根 bar 才能清完，得到 `liquidation_days_estimate`。

## 4. StressTester 接口

```python
class StressTester:
    def __init__(self, account: Account, greeks: GreeksSnapshot,
                 instruments: InstrumentsView, repricing: str = "linear"): ...

    def run(self, scenario: Scenario) -> StressResult: ...
    def batch(self, scenarios: list[Scenario]) -> pl.DataFrame: ...

@dataclass(frozen=True)
class StressResult:
    scenario: Scenario
    pnl: Decimal
    pnl_pct: Decimal
    by_underlying: pl.DataFrame
    by_strategy: pl.DataFrame
    margin_impact: MarginImpact
    would_be_liquidated: bool
    liquidation_path: list[str] | None
```

## 5. VaR / ES

### 5.1 历史模拟法（默认）

- 取过去 N 日（默认 250）每日 PnL 序列
- `VaR_α = -quantile(pnl, 1-α)` （例如 α=0.95 取 5% 分位）
- `ES_α = -mean(pnl | pnl < quantile(pnl, 1-α))`

### 5.2 方差-协方差法

```
σ_portfolio = √(w^T Σ w)
VaR_α = z_α × σ_portfolio × equity
```

适用全权益线性组合，对期权偏差大。

### 5.3 Monte Carlo

- 参数模型：multivariate Normal / t-distribution / Student-t copula
- 模拟 10000 路径，分别给每路径估算 PnL，取分位数
- 用于复杂期权组合（如蝶式、跨式）

输出统一为：

```python
@dataclass(frozen=True)
class TailRisk:
    var_95_1d: Decimal
    var_99_1d: Decimal
    es_95_1d: Decimal
    es_99_1d: Decimal
    confidence: dict[str, Decimal]
    method: str
    sample_window: int
```

## 6. 历史窗口重演

```python
hist = StressTester.replay_history(
    account,
    window=("2015-06-12", "2015-08-26"),  # 股灾
    bar_loader=loader,
)
print(hist.daily_pnl)
print(hist.max_drawdown)
print(hist.would_be_liquidated)
```

实现：把当前持仓"凿"到历史窗口起点，沿历史行情逐 bar 模拟（不下新单，仅维持现状或按事先指定策略），得到 PnL 时序。

## 7. 日度/周度自动报告

回测结束后自动跑标准 Scenario 矩阵（`EQUITY_DOWN_10`/`COMMODITY_DOWN_15`/`RATE_UP_50BP`/...），输出 `stress_dashboard.html`，便于风控审阅。

## 8. 最小示例

```python
from getrich_backtest.analytics import StressTester, Scenario, Shock, ShockTarget, DeltaType

st = StressTester(account=result.account_end,
                  greeks=result.risk_snapshot_end,
                  instruments=result.instruments)

# 单情景
s = Scenario(
    name="HS300_-10pct_iv_up_50pct",
    shocks=[
        Shock(ShockTarget.PRICE, "510300.SH", DeltaType.PCT, Decimal("-0.10")),
        Shock(ShockTarget.IV, "510300.SH", DeltaType.PCT, Decimal("+0.50")),
    ],
)
res = st.run(s)
print(f"PnL: {res.pnl:,.0f} ({res.pnl_pct:.2%})")
print(f"Would liquidate: {res.would_be_liquidated}")

# 批量内置情景
df = st.batch([
    Scenario.preset.EQUITY_DOWN_10,
    Scenario.preset.EQUITY_DOWN_20_2015,
    Scenario.preset.COMMODITY_DOWN_15,
    Scenario.preset.MARGIN_HIKE_50PCT,
])
print(df)
```

## 9. 设计禁区

- **禁止**用线性 Greeks 估算高 Gamma 期权的极端 shock PnL——必须用 full repricing。
- **禁止**忽略相关 shock：单独 -10% 股价 与 +50% IV 同时发生时，不能简单相加。
- **禁止**用回测期间样本算 VaR 而不区分牛/熊/震荡市——分制度报告。
- **禁止**把压力测试结果与正常归因混在一起呈现给业务方——单独报告。
