# 核心概念

本节建立引擎的心智模型（mental model）。理解这些抽象后，90% 的使用场景都能 self-service。

---

## 1. Strategy（策略基类）

`Strategy` 是用户编写的核心逻辑。所有策略必须继承 `Strategy` 并实现 `on_bar(ctx)` 钩子。

```python
from getrich_backtest import Strategy, OrderIntent, Side
from decimal import Decimal

class MyStrategy(Strategy):
    name = "my_strategy_v1"      # 注册名（可选，默认类名）
    version = "1.0.0"            # 语义版本（可选）
    freq = "1d"                  # 该策略偏好的 bar 频率（多策略场景用）

    def setup(self, ctx) -> None:
        """可选：每个 run 启动时调用一次；用于初始化状态。"""
        self._entry_threshold = Decimal("0.02")

    def on_bar(self, ctx) -> list[OrderIntent]:
        """必选：每根 bar 触发，返回 OrderIntent 列表（可空）。"""
        # 读取历史
        h = ctx.history.lookback(ctx.universe.symbols, ["close"], n=20)

        # 计算信号
        sma = h.group_by("symbol").agg(pl.col("close").mean())

        # 产出订单意图
        intents = []
        for row in sma.iter_rows(named=True):
            if row["close"] > row["close"] * Decimal("1.02"):
                intents.append(OrderIntent(
                    symbol=row["symbol"],
                    side=Side.BUY,
                    qty=Decimal("100"),
                    tag="breakout",
                ))
        return intents

    def teardown(self, ctx) -> None:
        """可选：每个 run 结束调用一次。"""
```

### 1.1 钩子时机

| 钩子 | 触发时机 | 用途 |
|---|---|---|
| `setup(ctx)` | `Backtest.run()` 开始时（每个 run_id 一次） | 初始化状态、读取配置、注册指标 |
| `on_bar(ctx)` | 每根 bar 触发（每 bar 一次） | 计算信号、产出 `OrderIntent[]` |
| `on_fill(ctx, fill)` | 每笔成交后（可选实现） | 跟踪持仓、统计滑点、调整策略 |
| `teardown(ctx)` | `Backtest.run()` 结束时（每个 run_id 一次） | 关闭连接、清理资源 |

> **重要**：`on_bar` 内的状态必须存到 `self`（或 `ctx.state`）上，跨 bar 持久化。

### 1.2 多频率场景

`Strategy.freq` 是个类属性，可以覆盖 `Backtest.freq`：

```python
class FastStrategy(Strategy):
    freq = "1m"  # 即使 Backtest.freq="1d"，该策略也按 1m 触发
```

详见 [多频率](multi-frequency.md)。

---

## 2. Context（长生命周期上下文）

`Context` 在 `setup()` → `on_bar()...on_bar() → teardown()` 整个生命周期内有效。

```python
class Context:
    now: datetime              # 当前时间（上海时区）
    run_id: str                # 本次 run 唯一 ID
    account: AccountView       # 只读账户视图（见 §6）
    instruments: pl.DataFrame  # 标的元信息（symbol, asset_class, multiplier, margin_ratio）
    calendar: Calendar         # 交易日历
    corp_actions: pl.DataFrame # 公司行为
    factors: pl.DataFrame      # 因子数据
    factor(name: str) -> pl.DataFrame  # 获取单个因子
    history: HistoryView       # 多频历史（见 §2.2）
    state: StateView           # 跨 bar 状态存储
    logger: Logger             # 带 run_id 前缀的 logger
    rng: numpy.random.Generator  # 已 seed 的随机数（结果可复现）
```

### 2.1 BarContext（每 bar 重建）

`on_bar` 接收的是 `BarContext`，比 `Context` 多：

```python
class BarContext(Context):
    bar: pl.DataFrame          # 当前 bar（多 symbol 一行一个）
    universe: Universe         # 当前 universe（symbol 列表）
    submit(intents) -> None    # 提交 OrderIntent（替代 return）
```

### 2.2 HistoryView（多频历史）

```python
# 拉取最近 N 个 bar 的 close
h = ctx.history.lookback(
    symbols=["BTCUSDT", "ETHUSDT"],
    columns=["close", "volume"],
    n=20,
)
# h: pl.DataFrame with columns [dt, symbol, close, volume]

# 多频访问
h1h = ctx.history.resampled("1h")
# h1h: pl.DataFrame with columns [dt, symbol, close_1h, volume_1h, ...]
```

---

## 3. OrderIntent（订单意图）

策略**不直接下单**，而是产 `OrderIntent`。`OrderIntent` 是"声明式的"，由 `execution` 层在下一根 bar 撮合。

```python
@dataclass
class OrderIntent:
    symbol: str                # 必填
    side: Side                 # 必填：BUY/SELL/OPEN_LONG/OPEN_SHORT/CLOSE_LONG/CLOSE_SHORT
    qty: Decimal | None        # 与 weight 二选一
    weight: Decimal | None     # 组合权重（0-1）
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tag: str | None = None     # 标记（用于归因）

# 示例
intent = OrderIntent(
    symbol="BTCUSDT",
    side=Side.BUY,
    qty=Decimal("0.1"),
    order_type=OrderType.MARKET,
    tag="breakout_2024Q1",
)
```

> **重要约束**：`qty` 和 `weight` 必须二选一；同时给会抛 `OrderIntentError`。

---

## 4. Order vs Fill

| 概念 | 含义 | 触发时机 |
|---|---|---|
| `Order` | 撮合前的挂单 | 策略提交后立即生成 |
| `Fill` | 撮合后的成交 | `execution_lag_bars=1` 后，撮合成功时生成 |

```python
@dataclass
class Order:
    order_id: str
    intent: OrderIntent
    status: OrderStatus  # PENDING / ACCEPTED / FILLED / REJECTED / EXPIRED
    created_at: datetime
    accepted_at: datetime | None
    filled_at: datetime | None
    reject_reason: str | None

@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal          # 实际成交价（含撮合规则）
    fee: Decimal            # 手续费
    slippage_bps: Decimal   # 滑点（bp）
    filled_at: datetime
```

---

## 5. Bar（K 线 schema）

`Bar` 是 Polars DataFrame，每行一根 K 线：

```python
# 必需列（不可缺）
required_columns = ["dt", "symbol", "open", "high", "low", "close", "volume"]

# 可选列
optional_columns = [
    "asset_class",   # AssetClass 枚举
    "exchange",      # Exchange 枚举
    "vwap",          # 量加权平均价
    "oi",            # 持仓量（期货）
    "amount",        # 成交额
    "settlement",    # 结算价（期货日终）
    "adj_factor",    # 复权因子
    "limit_up",      # 涨停价
    "limit_down",    # 跌停价
    "is_suspended",  # 是否停牌
    "session",       # Session 名称
]
```

> **CLAUDE.md §3.2 铁律**：列名严格遵循 `open, high, low, close, volume, vwap, oi, symbol, dt`；不允许任何缩写或变体。

---

## 6. Account（账户状态）

`Account` 持有现金、持仓、冻结资金、保证金。

```python
@dataclass
class Account:
    initial_cash: Decimal
    cash: Decimal
    positions: dict[str, Position]   # symbol → Position
    frozen_cash: Decimal             # 预冻结（待撮合）
    margin_state: MarginState        # 保证金状态（仅期货）
    sub_accounts: dict[str, SubAccountSnapshot]  # 子账户快照

# 估值（mark-to-market）
account.equity  # 当前权益 = cash + sum(pos.qty * last_price)
account.gross_exposure  # 总敞口
account.total_realized_pnl  # 累计已实现盈亏
```

> **`Account` 在 on_bar 内部**不可见**；策略只能通过 `ctx.account` 看到只读的 `AccountView`。

---

## 7. Frequency（频率）

引擎支持 6 种频率，统一由 `Frequency` 枚举管理。

```python
from getrich_backtest import Frequency

# 6 种频率
Frequency.ONE_MINUTE   # "1m"
Frequency.FIVE_MINUTES # "5m"
Frequency.FIFTEEN_MINUTES  # "15m"
Frequency.THIRTY_MINUTES   # "30m"
Frequency.ONE_HOUR     # "1h"
Frequency.ONE_DAY      # "1d"

# 工具方法
Frequency.all_values()  # 返回所有合法字符串
Frequency.is_valid("1d")  # True
Frequency.ONE_DAY.minutes  # 1440
```

`FREQ_TO_MINUTES: dict[str, int]` 是模块级常量，提供字符串到分钟数的映射。

> **CLAUDE.md §3.1 铁律**：所有 `dt` 字段必须 `Asia/Shanghai (UTC+8)` 时区感知；夜盘（21:00 - 次日 02:30）必须用 `DateTime64(3, 'Asia/Shanghai')`，严禁用 `Date`（日期类型会跨夜时丢失）。

---

## 8. RunConfig（运行配置）

`RunConfig` 是不可变 dataclass，决定一次回测的**全部配置**。`fingerprint()` 生成 SHA-256 哈希作为幂等键。

```python
from getrich_backtest import RunConfig, Frequency, get_shanghai_tz
from datetime import datetime
from decimal import Decimal

cfg = RunConfig(
    run_id="bt-2024-q1",
    strategy_name="MACross",
    symbols=["BTCUSDT", "ETHUSDT"],
    start=datetime(2024, 1, 1, tzinfo=get_shanghai_tz()),
    end=datetime(2024, 4, 1, tzinfo=get_shanghai_tz()),
    initial_cash=Decimal("100000"),
    freq="1d",
    extra_freqs=("15m", "1h"),   # 多频率注入到 BarContext.extra_history
    execution_lag_bars=1,
    strategy_params={"fast": 5, "slow": 20},
    risk_config=RiskConfig(margin_call_threshold=0.3),
)
cfg.fingerprint()  # SHA-256 hex
```

> 详细字段见 [API 参考](api-reference.md#runconfig)。

---

## 9. Error 层级

```text
BacktestError
├── DataLoadError
│   ├── BarSchemaError       # 列名缺失/类型错
│   ├── TimezoneError        # naive datetime
│   └── MissingDataError     # 时间窗口内无数据
├── StrategyError
│   ├── OnBarSignatureError  # on_bar 签名错
│   ├── SignalError          # 信号计算错
│   └── OrderIntentError     # OrderIntent 字段非法
├── ExecutionError
│   ├── InsufficientCashError  # 现金不足
│   └── LimitHitError          # 触及涨跌停
├── AccountError
├── MarginError
├── RiskError                # 触发风控规则
├── LiveDataError
├── SignalProductionError
└── PersistenceError
```

每个 `Error` 子类有明确触发条件 + 处理建议。详见 [参考 / 错误码](../reference/error-codes.md)。

---

## 10. 一次性心智模型图

```mermaid
graph LR
    Bars[BarLoader<br/>PG/DuckDB/DF] -->|dt, symbol, OHLCV| Strat[Strategy]
    Strat -->|on_bar| IC[BarContext]
    IC -->|OrderIntent[]| Exec[NextBarMatching]
    Exec -->|reserve| Acct[Account]
    Exec -->|match t+1| Fill[Fill]
    Fill -->|release+apply| Acct
    Acct -->|AccountView| IC
    Strat -->|metrics| Out[BacktestResult]
    Acct -->|equity_curve| Out
    Out -->|compute_metrics| M[BacktestMetrics]
    Out -->|compute_benchmark| B[Bench]
    Out -->|compute_brinson| A[Attribution]
    Out -->|Reporter| T[TearSheet HTML]
```

---

## 下一步

- 加载真实数据：[数据加载器](data-loaders.md)
- 写第一个策略：[策略开发](strategies.md)
- 多策略组合：[组合与权重](portfolio-allocation.md)
- 订单撮合细节：[执行与账户](execution-accounting.md)
