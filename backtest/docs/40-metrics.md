# 40. 输出指标

> 把回测时序数据汇总为可读的标量与时间序列。对应原需求"Output 指标"全部条目。本文档**只覆盖标量收益与汇总统计**；归因（含 Greeks PnL 分解、按品种/因子拆分）见 `42-benchmark-attribution.md`。

## 1. 输入

```python
@dataclass(frozen=True)
class MetricsInput:
    equity: pl.DataFrame      # [dt, equity_total, equity_long, equity_short, cash, margin_held]
    fills: pl.DataFrame       # 全部成交流水
    positions: pl.DataFrame   # 每根 bar 收盘后的持仓时序
    benchmark: pl.DataFrame | None  # 基准曲线
    risk_timeline: pl.DataFrame | None
    freq: str                 # "1m" | "1d"
```

`equity` 时间频率与回测主频率一致（1m 或 1d）；日终指标自动 downsample。

## 2. 收益类（Return Metrics）

### 2.1 标量

| 指标 | 公式 | 备注 |
| --- | --- | --- |
| `total_return` | `equity_T / equity_0 - 1` | 简单总收益 |
| `total_return_log` | `ln(equity_T / equity_0)` | 对数总收益 |
| `annualized_return` | `(1 + total_return)^(252/N) - 1` | A 股按 252；商品按各交易所实际数 |
| `cagr` | `(equity_T / equity_0)^(1/years) - 1` | 复合年化 |
| `volatility_annual` | `std(daily_returns) × √252` | |
| `downside_vol` | `std(min(r-MAR, 0)) × √252` | MAR=0 默认 |

### 2.2 时序

| 指标 | 频率 |
| --- | --- |
| `daily_returns` | 日 |
| `monthly_returns` | 月（按交易日聚合） |
| `weekly_returns` | 周 |
| `bar_returns` | 与主频率一致 |

### 2.3 隔夜 vs 日内（Overnight vs Intraday）

按 **bar 起止** 自然切分（与原需求"每根 bar 都有隔夜和 bar 内收益"对齐）：

```
intra_bar_return_t = (close_t - open_t) / open_t
gap_return_t = (open_t - close_{t-1}) / close_{t-1}      # 跨 bar 缺口
overnight_return_d = (open_d_first_bar - close_{d-1}_last_bar) / close_{d-1}_last_bar
intraday_return_d = (close_d_last_bar - open_d_first_bar) / open_d_first_bar
```

汇总指标：

| 指标 | 含义 |
| --- | --- |
| `overnight_return_total` | 仅持有隔夜的累计收益（虚拟组合） |
| `intraday_return_total` | 仅持有日内的累计收益 |
| `overnight_intraday_ratio` | `overnight / intraday`（绝对值比，衡量持有时段 PnL 集中度） |

**注意**：以上对**单标的**自然定义；对**组合**则按"组合净值在隔夜段 / 日内段的变化"分解，分母为每段起点 equity。两种口径可同时输出，用 `BarLevelReturn` vs `EquityLevelReturn` 区分。

### 2.4 Greeks PnL（指针）

Greeks PnL 拆解（`Δ × ΔS`、`½Γ × (ΔS)²`、`V × Δσ`、`Θ × Δt`）属于**归因**，详见 `42-benchmark-attribution.md` §4。本文档不再展开。

## 3. 统计类（Risk-Adjusted）

| 指标 | 公式 |
| --- | --- |
| `sharpe` | `(mean(r) - rf) / std(r) × √(periods_per_year)` |
| `sortino` | `(mean(r) - MAR) / downside_std(r) × √(periods_per_year)` |
| `calmar` | `annualized_return / abs(max_drawdown)` |
| `omega(threshold)` | `Σ max(r-th, 0) / Σ max(th-r, 0)` |
| `gain_loss_ratio` | `mean(positive_returns) / mean(|negative_returns|)` |
| `skew` | `三阶矩` |
| `kurtosis` | `四阶矩 - 3`（超额峰度） |
| `tail_ratio_95_5` | `quantile(0.95) / |quantile(0.05)|` |

参数：
- `risk_free_rate`：默认年化 1.8%（约等于 1Y 国债），可注入时间序列
- `periods_per_year`：1d→252，1m→252×240（按实际交易分钟）

## 4. 分析类（Trading Behavior）

### 4.1 胜率 / 盈亏比

按**Trade**聚合（开仓 → 完全平仓为一笔 trade）：

```python
@dataclass(frozen=True)
class Trade:
    symbol: str
    strategy_name: str
    side: Side
    open_time: datetime
    close_time: datetime
    duration: timedelta
    qty: Decimal
    avg_open_price: Decimal
    avg_close_price: Decimal
    pnl: Decimal              # 含手续费
    pnl_pct: Decimal          # 相对开仓 notional
    max_favorable: Decimal    # MFE
    max_adverse: Decimal      # MAE
```

| 指标 | 公式 |
| --- | --- |
| `win_rate` | `Σ trades.pnl > 0 / Σ trades` |
| `loss_rate` | `Σ trades.pnl < 0 / Σ trades` |
| `avg_win` | `mean(pnl|pnl>0)` |
| `avg_loss` | `mean(pnl|pnl<0)` |
| `profit_factor` | `Σ pnl>0 / |Σ pnl<0|` |
| `payoff_ratio` (盈亏比) | `avg_win / |avg_loss|` |
| `expectancy` | `win_rate × avg_win + loss_rate × avg_loss` |

### 4.2 最大回撤

```
drawdown_t = equity_t / running_max(equity_t) - 1
max_drawdown = min(drawdown)
max_drawdown_duration = (recovery_t - peak_t)
```

附加：
- `max_drawdown_dt`：发生时刻
- `recovery_dt`：恢复至前高的时刻（若未恢复，记 None）
- `time_under_water`：水下时长比例
- `top_k_drawdowns`：前 k 大独立回撤区间

### 4.3 换手率

```
turnover_t = sum(|fill.notional|) / equity_t   # 每根 bar 累计
turnover_daily = sum(|fill.notional| on day d) / equity_d
turnover_annual = mean(turnover_daily) × 252
```

按策略 / 标的 / 资产类分别输出。

### 4.4 成交统计

| 指标 | 含义 |
| --- | --- |
| `trade_count` | trade 笔数 |
| `fill_count` | fill 条数（多次部分成交计多） |
| `avg_trade_duration` | trade 平均持仓时长 |
| `avg_fill_size` | 每 fill 平均 qty |
| `slippage_total` | 累计滑点成本（Decimal） |
| `fee_total` | 累计手续费（含分项） |
| `commission_total`、`stamp_total`、`exchange_fee_total` | |

## 5. MetricsCalculator 接口

```python
class MetricsCalculator:
    def __init__(self, input: MetricsInput): ...

    # 标量
    def returns(self) -> ReturnMetrics: ...
    def stats(self, risk_free_rate: Decimal = ...) -> StatMetrics: ...
    def analytics(self) -> AnalyticsMetrics: ...
    def all(self) -> dict[str, Decimal | float]: ...

    # 时序
    def equity_curve(self) -> pl.DataFrame: ...
    def drawdown_curve(self) -> pl.DataFrame: ...
    def daily_returns(self) -> pl.DataFrame: ...
    def monthly_returns_heatmap(self) -> pl.DataFrame: ...
    def trades(self) -> pl.DataFrame: ...

    # 分组（按策略 / 资产类）
    def by_strategy(self) -> dict[str, "MetricsCalculator"]: ...
    def by_asset_class(self) -> dict[AssetClass, "MetricsCalculator"]: ...
```

## 6. 输出格式

```python
metrics = result.metrics()
metrics.all()
# {'total_return': Decimal('0.234'),
#  'annualized_return': Decimal('0.187'),
#  'sharpe': 1.42,
#  'max_drawdown': Decimal('-0.085'),
#  'win_rate': 0.534,
#  'payoff_ratio': 1.32,
#  ...}

metrics.equity_curve()  # pl.DataFrame[dt, equity, drawdown]
metrics.monthly_returns_heatmap()
# pl.DataFrame[year, m1, m2, ..., m12, annual]
```

## 7. 与基准、归因的衔接

- `Sharpe` 与 `Calmar` 只用策略自身收益，不涉及基准。
- 涉及基准的指标（`alpha`、`beta`、`tracking_error`、`info_ratio`、`win_rate_vs_bench`、`hit_ratio`）见 `42-benchmark-attribution.md`。
- 收益归因（隔夜 / 日内 / 手续费 / 滑点 / 品种 / Greeks PnL）在 `42` 中以**百分比贡献**形式展开。

## 8. 最小示例

```python
result = bt.run(strategy)
m = result.metrics()

print(f"Total: {m.returns().total_return:.2%}")
print(f"Annual: {m.returns().annualized_return:.2%}")
print(f"Sharpe: {m.stats().sharpe:.2f}")
print(f"Max DD: {m.analytics().max_drawdown:.2%}")
print(f"Win rate: {m.analytics().win_rate:.2%}")
print(f"Payoff: {m.analytics().payoff_ratio:.2f}")

eq = m.equity_curve()
eq.write_parquet("runs/abc/equity.parquet")
```

## 9. 设计禁区

- **禁止**用 1m bar 直接算 Sharpe（高频噪声导致波动率被放大）；自动 downsample 到日频。
- **禁止**把含手续费的 PnL 与不含手续费的 PnL 混在同一报告——必须分行展示。
- **禁止**用前复权价计算账户层 equity（详见 `11-data-quality.md` §2.3）。
- **禁止**把强平 fill 算作"策略主动 trade"；策略胜率/盈亏比剔除 `forced_liquidation` 标签的 fill。
