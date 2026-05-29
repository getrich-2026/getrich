# 42. 基准与归因

> 基准比较（Alpha/Beta/TE/IR）与多维度归因（品种/行业/策略/因子/隔夜日内/费用/Greeks PnL）。对应原需求第 6 节"基准与归因"，整合了原"Greeks pnl"条目。

## 1. 基准（Benchmark）

### 1.1 内置基准

| 资产域 | 默认基准 |
| --- | --- |
| A 股 | 沪深 300（`000300.SH`） |
| A 股小盘 | 中证 500（`000905.SH`）/ 中证 1000（`000852.SH`） |
| 全市场 | 中证 800 / 万得全 A |
| 商品 | 南华商品指数（`NHCI`）/ 自定义品种加权 |
| 期权 | 标的指数 + 无风险利率合成 |
| 策略自定义 | 任意一个 portfolio 时间序列 |

### 1.2 自定义基准

```python
bm = Benchmark.from_symbol("000300.SH")
bm = Benchmark.from_basket({"600519.SH": 0.5, "000858.SZ": 0.5})
bm = Benchmark.from_strategy(another_strategy_result)
bm = Benchmark.cash(annual_rate=Decimal("0.018"))  # 现金基准 = 1.8% 年化
```

### 1.3 基准计算与对齐

- 频率自动对齐到回测主频率（分钟级回测下 1m 基准价用插值或最近 close）
- 缺失日：跳过该日 active return
- 起始 base：与策略 equity_0 对齐（同时归 1.0）

## 2. 基准对比指标

| 指标 | 公式 |
| --- | --- |
| `alpha_annual` | `α = annualized_strategy_return - rf - β × (annualized_bench_return - rf)` |
| `beta` | `Cov(r_strategy, r_bench) / Var(r_bench)` |
| `tracking_error` (TE) | `std(r_strategy - r_bench) × √(periods_per_year)` |
| `information_ratio` (IR) | `mean(r_strategy - r_bench) / std(r_strategy - r_bench) × √(periods_per_year)` |
| `treynor` | `(mean(r) - rf) / β` |
| `m2` (M-squared) | `rf + sharpe × σ_bench` |
| `up_capture` | `mean(r_strategy | r_bench > 0) / mean(r_bench | r_bench > 0)` |
| `down_capture` | `mean(r_strategy | r_bench < 0) / mean(r_bench | r_bench < 0)` |
| `hit_ratio` | `Σ (r_strategy > r_bench) / N` |
| `excess_max_drawdown` | 累计 `(equity_strategy - equity_bench)` 的最大回撤 |

## 3. 归因维度

归因层的核心问题："这部分 PnL 从哪来？" 6 个一级维度：

| 维度 | 拆分 |
| --- | --- |
| **资产类** | A 股 / 股指期货 / 商品期货 / 期权 / 期货期权 |
| **品种** | `RB`、`IF`、`510050.SH`、个股 |
| **行业** | 申万一级 / 中信一级（A 股） |
| **策略** | StrategyA / StrategyB |
| **因子** | 价值 / 动量 / 质量 / 反转 / 规模 / 波动 |
| **时段** | 隔夜 / 日内 / 集合竞价 |
| **成本** | 手续费 / 印花税 / 滑点 / 利息 |

每个一级维度内可继续向下分组（如品种 × 行业、策略 × 时段）。

## 4. Greeks PnL 拆解（期权专属）

把组合 PnL 按"风险因子变动 × 敞口"拆解，回答"这次涨跌是 Delta 赚的还是 Gamma 赚的"：

```
ΔPnL ≈ Δ × ΔS
     + ½ × Γ × (ΔS)²
     + V × Δσ
     + Θ × Δt
     + Ρ × Δr
     + residual
```

实现细节：

- 对每根 bar，取当时持仓的 Greeks 快照
- 用 `bar_close - bar_open` 作为 ΔS、`Δσ` 由 IV 时序得到
- 残差落 `unexplained`，理想 < 10%；> 30% 写入数据质量告警

输出：

```python
GreeksPnLBreakdown(
    delta_pnl=Decimal("12345.67"),
    gamma_pnl=Decimal("3456.78"),
    vega_pnl=Decimal("-2345.12"),
    theta_pnl=Decimal("-1234.56"),
    rho_pnl=Decimal("12.34"),
    unexplained=Decimal("23.45"),
)
```

按品种 / 策略 / 时段进一步分组。

## 5. 收益归因（Brinson / Custom）

### 5.1 Brinson 风格（适用于权益）

```
Total return = Allocation + Selection + Interaction
Allocation = Σ (w_p - w_bp) × r_bp
Selection  = Σ w_bp × (r_p - r_bp)
Interaction = Σ (w_p - w_bp) × (r_p - r_bp)
```

按行业 p 计算，`w_p`、`r_p` 为策略组合权重/收益，`w_bp`、`r_bp` 为基准。

### 5.2 因子归因

回归 `r_strategy_t = α + β_1 × factor_1_t + ... + ε`：

- 因子库：MoM / Value / Size / Quality / LowVol / BAB（A 股版）
- 输出每因子 Beta、t-stat、贡献 PnL
- 残差 = α + 特异性

### 5.3 时段归因

每根 bar 的 PnL 按"持仓时段类型"归到隔夜 / 日内 / 集合竞价：

```
PnL_overnight = equity_open_d - equity_close_{d-1}
PnL_intraday  = equity_close_d - equity_open_d - PnL_auction
PnL_auction   = fill_in_auction × (fill_price - prev_close)
```

附加：把当 bar 各持仓的 ΔS 进一步细分（持有 vs 当 bar 新开）。

### 5.4 成本归因

把"理论无成本 PnL"与"实际 PnL"做差：

```
gross_pnl = Σ (close_t - avg_cost) × qty × multiplier   # 理论
fee_drag = -Σ fee
slippage_drag = -Σ (fill_price - intent_price) × qty × multiplier × sign(side)
net_pnl = gross_pnl + fee_drag + slippage_drag
```

输出：`fee_attribution`, `slippage_attribution`, `borrowing_interest_attribution`。

## 6. AttributionEngine 接口

```python
class AttributionEngine:
    def __init__(self, fills, equity, positions, risk_timeline,
                 industry_map, factor_loadings, benchmark): ...

    def by_dimension(self, dim: str) -> pl.DataFrame: ...
        # dim ∈ {"asset_class", "symbol", "industry", "strategy",
        #        "factor", "session_type", "cost"}

    def greeks_pnl(self, grouping: list[str] = None) -> pl.DataFrame: ...
    def brinson(self) -> BrinsonResult: ...
    def factor_regression(self, factors: list[str]) -> FactorRegResult: ...
    def benchmark_compare(self) -> BenchmarkCompareResult: ...
    def all(self) -> AttributionReport: ...
```

## 7. 输出格式

```python
attr = result.attribution()

# 按品种
attr.by_dimension("symbol").head()
# pl.DataFrame
# │ symbol  │ pnl       │ pnl_pct │ fee_pct │ slippage_pct │
# │ IF2412  │ 234567.8  │ 0.023   │ 0.001   │ 0.0005       │
# │ RB2412  │ 123456.7  │ 0.012   │ 0.001   │ 0.0008       │

# Greeks
attr.greeks_pnl(grouping=["underlying", "strategy"])
# │ underlying │ strategy │ delta_pnl │ gamma_pnl │ vega_pnl │ theta_pnl │ unexpl │

# 基准比较
bc = attr.benchmark_compare()
print(bc.alpha_annual, bc.beta, bc.tracking_error, bc.information_ratio)
```

## 8. 不变量与对账

```
total_pnl = sum(attribution_by_symbol.pnl) ≡ sum(attribution_by_strategy.pnl)
                                           ≡ sum(greeks_pnl_breakdown) (期权部分)
                                           ≡ equity_end - equity_start - net_external_flows
```

引擎在生成报告前做一致性断言；不等触发 `AttributionMismatchError` 并 dump 调试数据。

## 9. 最小示例

```python
result = bt.run(strategy)
attr = result.attribution()

bc = attr.benchmark_compare()
print(f"Alpha (ann): {bc.alpha_annual:.2%}")
print(f"Beta: {bc.beta:.2f}")
print(f"IR: {bc.information_ratio:.2f}")
print(f"TE (ann): {bc.tracking_error:.2%}")

print(attr.by_dimension("industry").sort("pnl", descending=True).head(10))
print(attr.greeks_pnl(["underlying"]).sort("delta_pnl", descending=True).head())

attr.all().save_parquet("runs/abc/attribution.parquet")
```

## 10. 设计禁区

- **禁止**把 Greeks PnL 当作普通收益指标——它属于归因。
- **禁止**用前复权价计算成本归因（fill_price 与 intent_price 必须同口径）。
- **禁止**忽略 `unexplained` 项；超阈值要排查。
- **禁止**用 1m bar 直接做 Brinson 行业归因（噪声过大）；先 downsample 到日频。
- **禁止**在跨资产组合里只挑一个基准——必须对每个子组合用合适基准（A 股部分用 HS300，商品部分用 NHCI），再加权合成基准。
