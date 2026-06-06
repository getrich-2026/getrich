# 多频率与重采样

> **本节讲解"同一 backtest 用多频率 bar"**。比如日线策略偶尔用 1h bar 看短期反转、分钟线策略同时调用日线因子。多频率在量化研究里是核心需求——短信号靠高频数据，长信号靠低频数据。

---

## 1. `Frequency` 枚举

> 源码：`src/getrich_backtest/types.py`

```python
class Frequency(str, Enum):
    ONE_MIN   = "1m"     # 1 分钟
    FIVE_MIN  = "5m"     # 5 分钟
    FIFTEEN_MIN = "15m"  # 15 分钟
    THIRTY_MIN  = "30m"  # 30 分钟
    SIXTY_MIN   = "60m"  # 60 分钟
    ONE_HOUR    = "1h"   # 1 小时（与 60m 等价）
    ONE_DAY     = "1d"   # 1 日
```

辅助：

```python
Frequency.is_valid("5m")     # True
Frequency.is_valid("3m")     # False
Frequency.all_values()       # frozenset({"1m", "5m", ...})

# 字典：frequency → 分钟数
FREQ_TO_MINUTES = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "60m": 60, "1h": 60, "1d": 1440,
}
```

粗细比较用 `FREQ_TO_MINUTES[a] < FREQ_TO_MINUTES[b]`（更细 = 分钟数小）。

---

## 2. 单频率 vs 多频率

### 2.1 单频率（最常见）

```python
from getrich_backtest import Backtest, DataFrameBarLoader, Frequency, RunConfig

cfg = RunConfig(
    freq="1d",          # 单一频率
    start=...,
    end=...,
    symbols=["A", "B"],
)
bt = Backtest(strategy=strategy, bar_loader=DataFrameBarLoader(bars), run_config=cfg)
```

策略只能访问 `ctx.history(freq="1d")`，因为 `freq` 是单一的。

### 2.2 多频率（`extra_freqs`）

```python
cfg = RunConfig(
    freq="1h",                            # 主频率（撮合粒度）
    extra_freqs=("1d",),                  # 同时携带日线
    start=...,
    end=...,
)
```

策略可以访问：

- `ctx.history("1h")` —— 主频率 bar 流
- `ctx.history("1d")` —— 日线 bar 流（从 `extra_freqs` 加载）

**两套数据严格按各自的日历走**，不互相污染。

### 2.3 常见组合

| 主频率 | extra_freqs | 典型策略 |
|---|---|---|
| `1d` | () | 纯日线（趋势跟踪、动量） |
| `1h` | ("1d",) | 短线择时 + 日线趋势过滤 |
| `5m` | ("1d", "1h") | 高频套利 + 中低频信号 |
| `1m` | ("5m", "1h", "1d") | 高频做市 + 多时间框架确认 |

---

## 3. `RunConfig.extra_freqs` 验证规则

`RunConfig.__post_init__` 校验：

1. `extra_freqs` 每个值必须是 `Frequency` 成员
2. `extra_freqs` 不能包含 `freq` 本身
3. `extra_freqs` 不能包含比 `freq` 更细的频率

```python
# 错误 1：extra_freqs 含主频率
RunConfig(freq="1d", extra_freqs=("1d",))  # ValueError

# 错误 2：extra_freqs 含更细频率
RunConfig(freq="1d", extra_freqs=("1h",))   # ValueError（1h 比 1d 细）
```

`fingerprint()` 用 `extra_freqs` 生成 SHA-256 的一部分，所以 **不同 extra_freqs 的 backtest 结果是不同 fingerprint**，可作为幂等键。

---

## 4. `resample_bars()` —— 实时重采样

> 源码：`src/getrich_backtest/data/resample.py`

引擎**不会**自动把细 bar 重采样为粗 bar；需要的话**显式调** `resample_bars`：

```python
from getrich_backtest import resample_bars
import polars as pl

# 把 1m bars 重采样为 1h
hourly = resample_bars(minute_bars, target_freq="1h", source_freq="1m")
# 输出：每根 hour bar 的
#   open = 该小时第 1 根 minute bar 的 open
#   high = max of all minute bar highs
#   low  = min of all minute bar lows
#   close = 该小时最后 1 根 minute bar 的 close
#   volume = sum of all minute bar volumes
```

### 4.1 聚合规则

| 字段 | 聚合 |
|---|---|
| `open` | bucket 内第 1 根 bar 的 open |
| `high` | bucket 内所有 bar 的 max |
| `low` | bucket 内所有 bar 的 min |
| `close` | bucket 内最后 1 根 bar 的 close |
| `volume` | bucket 内所有 bar 的 sum |
| `vwap`（若有） | bucket 内 `Σ(vwap × volume) / Σ(volume)` |

排序后输出 `(dt, symbol)`。

### 4.2 夜盘与 session-aware 重采样

A 股有夜盘（商品期货：21:00 ~ 次日 02:30），跨日夜盘需要**按交易时段切分**，不能简单按 UTC 切：

```python
from getrich_backtest import resample_bars, Session
from datetime import time

# 商品期货夜盘：21:00 ~ 23:00, 09:00 ~ 10:15, 10:30 ~ 11:30, 13:30 ~ 15:00
sessions = (
    Session(start=time(9, 0),   end=time(10, 15),  name="morning_1"),
    Session(start=time(10, 30), end=time(11, 30),  name="morning_2"),
    Session(start=time(13, 30), end=time(15, 0),   name="afternoon"),
    Session(start=time(21, 0),  end=time(23, 0),   name="evening"),
)

hourly = resample_bars(
    minute_bars,
    target_freq="1h",
    source_freq="1m",
    sessions=sessions,  # 桶边界对齐到 session 起点
)
```

不带 `sessions` 时，桶边界是 wall-clock（`09:00`, `10:00`, `11:00`, ...），夜盘的 21:00 桶会把次日凌晨的 02:00 bar 错误归到 21:00 桶（因为 dt 看起来是"今天 21:00"开始的）。

### 4.3 `HistoryView.resampled()` —— 懒缓存

策略中常用的模式是"我需要日线数据但只有 1m 数据"——引擎可以**自动**提供：

```python
class MyStrategy(Strategy):
    def on_bar(self, ctx: BarContext) -> list:
        # 拿 1d 数据（如果 RunConfig.extra_freqs=("1d",)，直接返回；否则从当前 freq 重采样）
        daily = ctx.history("1d")
        if daily.is_empty():
            return []
        sma_20 = daily.sma(20)
        # ...
```

`ctx.history(target_freq)` 的实现：

1. `target_freq in extra_freqs`？→ 直接返回已加载的 bar
2. 否则用 `resample_bars(ctx.bars_for(target_freq), target_freq, source_freq=ctx.freq)` 重采样（**懒缓存**，同一根 bar 多次调只重采样一次）

---

## 5. `BarContext.extra_history` 注入

`BarContext` 暴露主频率 + extra_freqs 的访问：

```python
class BarContext:
    history(self, freq: str | None = None) -> HistoryView:
        """默认 freq=None → 主频率；可显式指定 extra_freq"""
```

```python
class MyStrategy(Strategy):
    def on_bar(self, ctx: BarContext) -> list:
        main = ctx.history()                  # 主频率（RunConfig.freq）
        daily = ctx.history("1d")            # 日线（来自 extra_freqs）
        hourly = ctx.history("1h")            # 小时线（如果 RunConfig 含 1h）
```

`HistoryView` 提供：

- `.sma(n)` / `.ema(n)` / `.rsi(n)` —— 简单技术指标
- `.returns(n)` —— 滚动 N bar 收益率
- `.vol(n)` / `.vol(method='std')` —— 波动率
- `.atr(n)` —— Average True Range
- `.resampled(target_freq)` —— 在 HistoryView 层重采样（懒缓存）

---

## 6. Per-strategy 频率

Round #243-#247：每个 strategy 可以独立声明偏好频率：

```python
class FastStrategy(Strategy):
    freq = "1m"   # 偏好分钟线

class SlowStrategy(Strategy):
    freq = "1d"   # 偏好日线
```

`RunConfig.strategy_freqs`：

```python
cfg = RunConfig(
    freq="1m",  # 全局主频率
    strategy_freqs={
        "FastStrategy": "1m",
        "SlowStrategy": "1d",
    },
)
```

引擎在多策略 `_run_multi` 时按 strategy 自己的频率推 bar 流，但撮合粒度用 `cfg.freq`（最低延迟 = `min(strategies.freq)`）。

---

## 7. BacktestResult 暴露 extra_history

`BacktestResult.extra_bars` 是 dict[freq -> pl.DataFrame]：

```python
result = bt.run()
result.extra_bars  # {"1d": <pl.DataFrame>, "1h": <pl.DataFrame>}
result.bars        # 主频率的 bars
```

TearSheet 会渲染 `extra_freqs` 的 equity 曲线（每个频率一条），方便对比不同时间尺度的策略表现。

---

## 8. 完整示例：1h 策略 + 1d 因子

```python
from decimal import Decimal
import polars as pl
from getrich_backtest import (
    Backtest, DataFrameBarLoader, Strategy, BarContext,
    OrderIntent, Side, RunConfig, Frequency,
)

class TrendFollowing(Strategy):
    """1h 频率执行入场/出场，1d 频率做趋势过滤。"""

    def on_bar(self, ctx: BarContext) -> list:
        # 1d 趋势：close > SMA(20)
        daily = ctx.history("1d")
        if daily.is_empty():
            return []
        daily_sma = daily.sma(20)
        if daily_sma is None:
            return []
        daily_close = daily["close"][-1]

        # 1h 短期：当前 bar 收盘价
        bar = ctx.bar
        h1_close = bar["close"][0]

        held = ctx.account.position("A").qty

        if daily_close > daily_sma and held == 0:
            # 多头：1d 上行 + 1h 触发
            return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))]
        if daily_close < daily_sma and held > 0:
            return [OrderIntent(symbol="A", side=Side.SELL, qty=held)]
        return []


# 1. 准备 1h + 1d 两套 bar
hourly_bars = load_bars("1h", symbols=["A", "B"])
daily_bars = load_bars("1d", symbols=["A", "B"])

# 2. RunConfig
cfg = RunConfig(
    freq="1h",
    extra_freqs=("1d",),                # 关键：1d 来自 extra_freqs
    start=...,
    end=...,
    symbols=["A", "B"],
)

# 3. 用 1h bar 作为主加载器，1d 通过 extra_freqs 路径加载
bt = Backtest(
    strategy=TrendFollowing(),
    bar_loader=DataFrameBarLoader(hourly_bars, extra_bars={"1d": daily_bars}),
    run_config=cfg,
)
result = bt.run()
```

---

## 9. 常见错误

| 症状 | 原因 | 修法 |
|---|---|---|
| `ValueError: target_freq must be coarser than source_freq` | 重采样方向反了 | 检查 `target_freq > source_freq`（分钟数） |
| 夜盘数据被错误归到次日桶 | 没用 `sessions` 参数 | 传入 `sessions=(Session(...), ...)` |
| `ctx.history("1d")` 总是空 | `extra_freqs` 没含 `1d` | `RunConfig.extra_freqs=("1d",)` |
| `RunConfig` 抛 `ValueError: extra_freqs contains main freq` | extra_freqs 重复了 `freq` | 移除重复 |
| `RunConfig` 抛 `ValueError: extra_freqs is finer than main freq` | extra_freqs 里有比 `freq` 更细的 | 用 coarser（更大分钟数） |
| `BarContext` 报 `KeyError: "1d"` | bar_loader 没提供 1d 数据 | `DataFrameBarLoader(extra_bars={"1d": ...})` |

---

## 10. 进一步阅读

- 设计契约：[12 日历与可交易性](../design-contracts/12-calendar-tradability.md)
- API 详情：
    - [Frequency](api-reference.md#getrich_backtest.types.Frequency)
    - [resample_bars](api-reference.md#getrich_backtest.data.resample.resample_bars)
    - [HistoryView](api-reference.md#getrich_backtest.HistoryView)
- 源码：
    - [`src/getrich_backtest/types.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/types.py)
    - [`src/getrich_backtest/data/resample.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/data/resample.py)
