# 21. 组合构建与调仓

> 介于策略与执行之间的"翻译层"：把 `score / target_weight / target_qty` 转成最终下单意图。对应原需求第 3 节"组合构建与调仓"以及第 4 节"容量与流动性约束"中与目标头寸生成相关的部分。

## 1. 数据流

```text
Strategy.compute_signal  →  pl.DataFrame[symbol, score]
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. 预处理         │
                    │   - 去极值        │
                    │   - 标准化        │
                    │   - 中性化        │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 2. 权重生成       │
                    │   - 等权/IV/RP   │
                    │   - 多空切分      │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 3. 约束求解       │
                    │   - 行业/品种      │
                    │   - 最大单标的     │
                    │   - 杠杆           │
                    │   - 换手           │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 4. 头寸映射       │
                    │   - 现金资产: shares = w·NAV/price │
                    │   - 期货:    contracts = w·NAV/(price·multiplier·margin_ratio) │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 5. 调仓裁剪       │
                    │   - 阈值/定期      │
                    │   - 容量约束       │
                    └─────────────────┘
                              │
                              ▼
                  list[OrderIntent]
```

## 2. 预处理（Signal Preprocessing）

| 步骤 | 选项 | 说明 |
| --- | --- | --- |
| 缺失填充 | `drop` / `fill_mean` / `fill_zero` | 默认 `drop` |
| 去极值 | `mad(n=3)` / `quantile(0.01, 0.99)` / `none` | 默认 MAD 3 倍 |
| 标准化 | `zscore` / `rank` / `minmax` / `none` | 默认 `rank`，对厚尾稳健 |
| 中性化 | `industry` / `market_cap` / `style` / `none`（单选或组合） | 横截面回归取残差 |

```python
preproc = SignalPreprocessor(
    winsorize=Winsorize.mad(3),
    standardize=Standardize.rank(),
    neutralize=Neutralize.industry_size(),
)
clean = preproc.transform(raw_score, ctx)
```

## 3. 权重生成

```python
class Allocator(Protocol):
    def allocate(self, score: pl.DataFrame, ctx: Context) -> pl.DataFrame: ...
    # 返回 [symbol, weight]，sum(|weight|) <= leverage
```

内置实现：

| 类 | 说明 |
| --- | --- |
| `EqualWeight` | 选 top-k 多头 + bottom-k 空头各等权 |
| `ScoreWeight` | 按 score 大小线性映射，归一化到 `gross_exposure` |
| `InverseVol` | 头寸反波动率（用过去 N 日收益波动） |
| `RiskParity` | 各品种风险贡献相等（迭代求解） |
| `MeanVariance` | 给定预期收益与协方差，求解二次规划 |
| `BlackLitterman` | 结合先验市场组合 + 主观观点 |

多空切分：

- `long_only=True`：截断负权重为 0
- `dollar_neutral=True`：保证 `sum(weight)=0`
- `beta_neutral=True`：在权重生成前对市场 Beta 中性化

## 4. 约束求解

```python
constraints = Constraints(
    max_single_weight=Decimal("0.05"),
    max_industry_weight=Decimal("0.20"),
    max_product_weight=Decimal("0.30"),     # 期货按品种聚合
    gross_exposure=Decimal("1.0"),
    net_exposure_range=(Decimal("-0.1"), Decimal("0.1")),
    turnover_per_rebalance=Decimal("0.30"),
    forbidden=("ST", "*ST", "near_delist"),  # 标签过滤
)
```

约束求解策略：

- 软约束：用 QP solver（`scipy.optimize`）最小化与目标权重的 L2 距离
- 硬约束：先按软约束求解，再迭代裁剪超限项

## 5. 多策略资金分配

平台资金池由 `PortfolioAllocator` 在多策略间分配：

```python
class PortfolioAllocator:
    mode: AllocMode    # FIXED / RISK_BUDGET / ADAPTIVE

class FixedAllocator(PortfolioAllocator):
    def __init__(self, weights: dict[str, Decimal]): ...
        # {"StrategyA": Decimal("0.6"), "StrategyB": Decimal("0.4")}

class RiskBudgetAllocator(PortfolioAllocator):
    def __init__(self, target_vol: Decimal, lookback_days: int = 60): ...
        # 按策略历史波动率分配

class AdaptiveAllocator(PortfolioAllocator):
    """按动态 Sharpe / 回撤回看调整权重，需热启动状态。"""
```

### 5.1 资金隔离 vs 共享

| 模式 | 说明 |
| --- | --- |
| `isolated` | 每策略独立子账户，亏完即停，不互相补贴 |
| `shared` | 共用现金池，按权重分配可用资金；优势策略可借用劣势策略未用资金 |

默认 `isolated`，避免策略相互"借钱"导致归因失真。

### 5.2 风险约束聚合

多策略合并后的 Greeks/杠杆暴露按**组合层**聚合，单策略生成的意图可能因组合约束被裁剪（详见 `32-risk-control.md` §5）。

## 6. 调仓规则（Rebalance Rule）

```python
class RebalanceRule(Protocol):
    def should_rebalance(self, ctx: Context, last_rebalance: datetime | None) -> bool: ...
    def filter_orders(self, intents: list[OrderIntent], ctx: Context) -> list[OrderIntent]: ...
```

| 规则 | 说明 |
| --- | --- |
| `PeriodicRebalance(cron="0 9 * * MON")` | 每周一开盘调仓 |
| `ThresholdRebalance(weight_drift=0.02)` | 单标的权重偏离目标超阈值才调 |
| `EventRebalance(events=["index_change"])` | 指数成分调整、财报、宏观事件触发 |
| `Hybrid(rules=[...])` | 多个条件 OR |

### 6.1 换手约束

`turnover_per_rebalance=0.30` 表示单次调仓换手率不超过 30%。引擎按 score 排序，优先执行 top |Δw| 的订单，超出预算的拒绝。

## 7. 头寸映射

### 7.1 现金资产（A 股、ETF）

```
target_shares = round_to_lot(target_weight × NAV / price_t, lot_size=100)
```

最小手数与下取整由 `instruments_equity.lot_size` 决定。

### 7.2 期货 / 期权

```
notional = target_weight × NAV
contracts = round(notional / (price × multiplier))
```

期货按**名义本金**或**保证金本金**映射，由 `notional_basis="notional" | "margin"` 配置：

- `notional`：`target_weight` 表示对名义本金的暴露（Beta 角度）
- `margin`：`target_weight` 表示对保证金占用的暴露（资金占用角度）

### 7.3 取整规则

- `round_to_lot`（默认）：四舍五入到最小交易单位
- `floor`：保守取整，永远不超
- `ceil`：激进取整，可能略超

## 8. 与执行层的交接

`Portfolio.build_orders(target_positions, current_positions) -> list[OrderIntent]`：

- 计算 `delta = target - current`
- 拆分为单笔订单（默认每个 symbol 一笔；可按 capacity 拆分为 child orders）
- 标注 `tag = f"{strategy_name}:rebalance:{rebalance_id}"`

执行层接收后，按 §4 容量约束在多 bar 内分批撮合（详见 `30-execution-engine.md` §5 TWAP/VWAP 切片）。

## 9. 最小示例

```python
from getrich_backtest.strategy import (
    SignalStrategy, Portfolio,
    EqualWeight, Constraints, PeriodicRebalance,
)

class MomLongShort(SignalStrategy):
    name = "mom_ls_v1"

    portfolio = Portfolio(
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
        ...
```

`Portfolio` 是策略的成员；运行时由 runner 在 `SignalStrategy.on_bar` 默认实现里调用。
