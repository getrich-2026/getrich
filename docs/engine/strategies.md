# 策略开发

本节讲解如何编写自己的策略——从最简单的双均线到多因子组合。

---

## 1. 策略基类

所有策略必须继承 `getrich_backtest.strategy.base.Strategy`：

```python
from getrich_backtest import Strategy

class MyStrategy(Strategy):
    name = "my_strategy_v1"     # 注册名（可选）
    version = "1.0.0"           # 语义版本（可选）
    freq = "1d"                 # 偏好频率（多策略场景）

    def setup(self, ctx) -> None:
        """可选：每个 run 启动时调用一次。"""
        pass

    def on_bar(self, ctx) -> list[OrderIntent]:
        """必选：每根 bar 触发。"""
        return []  # 返回 OrderIntent 列表
```

### 1.1 钩子时机

| 钩子 | 触发时机 | 用途 |
|---|---|---|
| `setup(ctx)` | 每个 run 启动时 | 初始化 self.* 状态、读取配置 |
| `on_bar(ctx)` | 每根 bar 触发 | 计算信号、产出 OrderIntent |
| `on_fill(ctx, fill)` | 每笔成交后（可选） | 调整后续行为 |
| `teardown(ctx)` | 每个 run 结束 | 清理资源 |

> **不要在 `__init__` 里做依赖外部状态的操作**（如读文件、连接 DB）。`setup()` 是正确的地方。

---

## 2. 三种策略范式

### 2.1 事件型：`on_bar` 写 OrderIntent

最直接的范式——每根 bar 决策一次。

**示例：双均线交叉**

```python
from getrich_backtest import Strategy, OrderIntent, Side
from decimal import Decimal
import polars as pl

class MACross(Strategy):
    """快均线上穿慢均线 → 买入；下穿 → 卖出。"""

    def __init__(self, fast: int = 5, slow: int = 20) -> None:
        self.fast = fast
        self.slow = slow

    def on_bar(self, ctx) -> list[OrderIntent]:
        h = ctx.history.lookback(
            symbols=ctx.universe.symbols,
            columns=["close"],
            n=self.slow + 1,
        )
        sma = (
            h.group_by("symbol")
            .agg(
                fast=pl.col("close").tail(self.fast).mean(),
                slow=pl.col("close").tail(self.slow).mean(),
            )
            .with_columns(
                signal=pl.when(pl.col("fast") > pl.col("slow"))
                .then(pl.lit(1))
                .otherwise(pl.lit(-1))
            )
        )
        intents = []
        for row in sma.iter_rows(named=True):
            if row["signal"] == 1:
                intents.append(
                    OrderIntent(symbol=row["symbol"], side=Side.BUY, qty=Decimal("100"))
                )
            else:
                intents.append(
                    OrderIntent(symbol=row["symbol"], side=Side.SELL, qty=Decimal("100"))
                )
        return intents
```

> 完整代码：[`getrich_backtest/strategies/ma_cross.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/strategies/ma_cross.py)

### 2.2 信号型：`SignalStrategy` + `compute_signal`

适合**截面策略**（同一时间对多个 symbol 排序后取 top/bottom）。

```python
from getrich_backtest import SignalStrategy, OrderIntent, Side
from decimal import Decimal
import polars as pl

class MomentumStrategy(SignalStrategy):
    """过去 N 日收益率排序，做多 top-k，做空 bottom-k。"""

    def __init__(self, lookback: int = 20, top_k: int = 5) -> None:
        self.lookback = lookback
        self.top_k = top_k

    def compute_signal(self, ctx) -> pl.DataFrame:
        """返回 [symbol, score] DataFrame。"""
        h = ctx.history.lookback(
            symbols=ctx.universe.symbols,
            columns=["close"],
            n=self.lookback + 1,
        )
        return (
            h.group_by("symbol")
            .agg(
                ret=pl.col("close").last() / pl.col("close").first() - 1
            )
            .rename({"ret": "score"})
            .sort("score", descending=True)
        )

    def on_signal(self, ctx, signal: pl.DataFrame) -> list[OrderIntent]:
        """可选：把 signal 转换成 OrderIntent。默认用 Portfolio.build_orders。"""
        ...
```

> 完整代码示例：[`tests/getrich_backtest/test_strategy_signal.py`](https://github.com/getrich/getrich/blob/main/tests/getrich_backtest/test_strategy_signal.py)

### 2.3 目标仓位型：`TargetPositionStrategy`

适合"**目标权重 / 目标股数**"类策略（如行业中性、目标波动率）。

```python
from getrich_backtest import TargetPositionStrategy, OrderIntent
from decimal import Decimal
import polars as pl

class EqualWeightStrategy(TargetPositionStrategy):
    """等权配置 universe，每 symbol 10% 仓位。"""

    def __init__(self, weight_per_symbol: Decimal = Decimal("0.1")):
        self.weight_per_symbol = weight_per_symbol

    def compute_target(self, ctx) -> pl.DataFrame:
        """返回 [symbol, target_weight] 或 [symbol, target_qty]。"""
        n = len(ctx.universe.symbols)
        return pl.DataFrame({
            "symbol": ctx.universe.symbols,
            "target_weight": [self.weight_per_symbol] * n,
        })
```

> 完整代码示例：[`tests/getrich_backtest/test_target_position.py`](https://github.com/getrich/getrich/blob/main/tests/getrich_backtest/test_target_position.py)

---

## 3. 状态管理

跨 bar 持久化状态用 `self.*` 或 `ctx.state`：

```python
class StatefulStrategy(Strategy):
    def setup(self, ctx) -> None:
        self._position_opened = {}  # symbol -> bool

    def on_bar(self, ctx) -> list[OrderIntent]:
        intents = []
        for sym in ctx.universe.symbols:
            if not self._position_opened.get(sym, False):
                intents.append(OrderIntent(symbol=sym, side=Side.BUY, qty=Decimal("100")))
                self._position_opened[sym] = True
        return intents
```

或者用 `ctx.state`（自动随 run 隔离）：

```python
def on_bar(self, ctx) -> list[OrderIntent]:
    opened = ctx.state.get("opened", set())
    intents = []
    for sym in ctx.universe.symbols:
        if sym not in opened:
            intents.append(OrderIntent(symbol=sym, side=Side.BUY, qty=Decimal("100")))
            opened.add(sym)
    ctx.state.set("opened", opened)
    return intents
```

> **`ctx.state` 在 run 结束时自动清理**，`self.*` 不会；多 run 并发时建议用 `ctx.state`。

---

## 4. 日志

`ctx.logger` 自动带上 `run_id` 前缀，可直接用：

```python
import logging

class LoggingStrategy(Strategy):
    def on_bar(self, ctx) -> list[OrderIntent]:
        ctx.logger.info(f"Processing {len(ctx.universe.symbols)} symbols")
        # 输出：2024-01-15 09:30:00 [bt-2024-q1] INFO: Processing 5 symbols
        return []
```

---

## 5. 随机性

需要随机数时**用 `ctx.rng`**，不要 `import random`：

```python
def on_bar(self, ctx) -> list[OrderIntent]:
    # ctx.rng 已 seed，结果可复现
    sample_size = ctx.rng.integers(0, len(ctx.universe.symbols))
    return []
```

> **CLAUDE.md §3 隐含规则**：`ctx.rng` 由 `RunConfig.random_seed` 决定；不同 run 给出不同 seed。

---

## 6. 访问因子

`ctx.factor(name)` 返回单个因子的长表：

```python
def on_bar(self, ctx) -> list[OrderIntent]:
    momentum = ctx.factor("momentum_20d")
    # momentum: [dt, symbol, value]
    return []
```

`ctx.factors` 一次性返回所有已加载因子：

```python
def on_bar(self, ctx) -> list[OrderIntent]:
    # ctx.factors: [dt, symbol, factor_name, value]
    top_momentum = (
        ctx.factors
        .filter(pl.col("factor_name") == "momentum_20d")
        .sort("value", descending=True)
        .head(5)
    )
    return []
```

---

## 7. 多频率策略

`Strategy.freq` 是个类属性，可以覆盖 `Backtest.freq`：

```python
class FastStrategy(Strategy):
    freq = "1m"  # 多策略场景下，按 1m 触发

class SlowStrategy(Strategy):
    freq = "1d"  # 按日触发
```

多策略并行时（`_run_multi`），每个 strategy 按自己的 `freq` 触发。详见 [多频率](multi-frequency.md)。

---

## 8. 内置策略库

引擎自带 2 个示例策略，可直接使用或 fork 改写：

### 8.1 `MACross`（双均线）

```python
from getrich_backtest import MACross

strategy = MACross(fast=5, slow=20)
```

**参数**：
- `fast` (int, default 5) — 快均线周期
- `slow` (int, default 20) — 慢均线周期

**适用**：趋势跟踪型；A 股、ETF、期货均可。

### 8.2 `BollingerMeanReversion`（布林均值回归）

```python
from getrich_backtest import BollingerMeanReversion

strategy = BollingerMeanReversion(period=20, std=2.0)
```

**参数**：
- `period` (int, default 20) — 布林带周期
- `std` (float, default 2.0) — 布林带宽度（倍数）

**适用**：震荡市；个股、ETF、数字货币。

---

## 9. 访问历史（多频）

```python
# 拉取最近 N 个 bar
h = ctx.history.lookback(
    symbols=["BTCUSDT", "ETHUSDT"],
    columns=["close", "volume"],
    n=20,
)

# 多频访问（lazy-cached）
h1h = ctx.history.resampled("1h")
h1d = ctx.history.resampled("1d")
```

> `resampled()` 是懒加载的，重复访问不会重算。详见 [多频率](multi-frequency.md)。

---

## 10. 测试你的策略

最小测试模板：

```python
import pytest
from decimal import Decimal
from datetime import datetime
from getrich_backtest import (
    Backtest, DataFrameBarLoader, MACross, ZeroFee, ZeroSlippage,
    get_shanghai_tz,
)
import polars as pl


def test_macross_generates_intents():
    # 准备数据
    bars = build_synthetic_bars(["A", "B"], n_days=30)

    # 配置
    bt = Backtest(
        strategy=MACross(fast=5, slow=20),
        bar_loader=DataFrameBarLoader(bars),
        symbols=["A", "B"],
        start=datetime(2024, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2024, 1, 30, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("100000"),
        fee_model=ZeroFee(),
        slippage_model=ZeroSlippage(),
        freq="1d",
        run_id="test-001",
    )

    # 运行
    result = bt.run()

    # 断言
    assert result.metrics().total_trades >= 0
    assert result.run_id == "test-001"
```

**典型坑**：

1. **naive datetime** → 用 `tzinfo=get_shanghai_tz()`
2. **run_id 重复** → 同一 `run_id` 复用会覆盖前次结果
3. **缺少 `Polars` 必需列** → 见 [数据加载器](data-loaders.md)

---

## 11. 调试技巧

### 11.1 用 `OnFill` 跟踪成交

```python
class DebugStrategy(Strategy):
    def on_fill(self, ctx, fill) -> None:
        ctx.logger.info(
            f"FILL: {fill.symbol} {fill.side} qty={fill.qty} price={fill.price}"
        )
```

### 11.2 临时禁用撮合（只看信号）

```python
bt = Backtest(
    strategy=MyStrategy(),
    bar_loader=loader,
    fee_model=ZeroFee(),         # 零费用
    slippage_model=ZeroSlippage(),  # 零滑点
    ...
)
```

### 11.3 强制全部回测只跑 1 根 bar

```python
bt = Backtest(
    start=datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
    end=datetime(2024, 1, 1, 9, 31, tzinfo=get_shanghai_tz()),
    ...
)
```

---

## 下一步

- 多策略组合：[组合与权重](portfolio-allocation.md)
- 订单撮合细节：[执行与账户](execution-accounting.md)
- 完整 API 索引：[API 参考](api-reference.md)
- 设计契约：[20 策略 API](../design-contracts/20-strategy-api.md)
