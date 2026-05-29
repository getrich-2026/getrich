# 20. 策略 API

> 策略层是**用户编写**最多的代码。本模块定义 `Strategy` 基类、上下文对象、生命周期钩子、状态持久化与热启动。对应原需求第 9 节"策略开发接口"。

## 1. 策略类型

支持三种策略范式，统一抽象为 `Strategy` 基类的不同子类。

| 范式 | 适用 | 输出 |
| --- | --- | --- |
| **信号型** `SignalStrategy` | 因子/技术策略：产生 `score`，由组合层转换为目标头寸 | `pl.DataFrame[symbol, score]` |
| **目标仓位型** `TargetPositionStrategy` | 多空、配比类策略：直接给目标仓位 | `pl.DataFrame[symbol, target_qty]` 或 `target_weight` |
| **事件驱动型** `EventStrategy` | 高频、做市、套利：基于 `OrderIntent` 直接驱动 | `list[OrderIntent]` |

子类自由组合：CTA 策略可同时是 `TargetPositionStrategy + EventStrategy`，按 bar 决定走哪条路径。

## 2. 基类签名

```python
from abc import ABC
from typing import Iterable

class Strategy(ABC):
    name: str                          # 唯一标识；用于状态文件、归因 key
    version: str = "0.1.0"
    universe_provider: UniverseProvider | None = None

    # ---- 生命周期 ----
    def setup(self, ctx: Context) -> None: ...
    def teardown(self, ctx: Context) -> None: ...

    # ---- 数据回调（按 bar / session 触发）----
    def on_session_open(self, ctx: Context, session: Session) -> Iterable[OrderIntent] | None: ...
    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None: ...
    def on_session_close(self, ctx: Context, session: Session) -> Iterable[OrderIntent] | None: ...

    # ---- 交易回调 ----
    def on_order_accepted(self, ctx: Context, order: Order) -> None: ...
    def on_order_rejected(self, ctx: Context, order: Order, reason: str) -> None: ...
    def on_fill(self, ctx: Context, fill: Fill) -> None: ...
    def on_order_expired(self, ctx: Context, order: Order) -> None: ...

    # ---- 账户/风控回调 ----
    def on_daily_settlement(self, ctx: Context, settlement: Settlement) -> None: ...
    def on_margin_call(self, ctx: Context, alert: MarginCallAlert) -> None: ...
    def on_corp_action(self, ctx: Context, event: CorpActionEvent) -> None: ...
    def on_option_expire(self, ctx: Context, symbol: str, payoff: Decimal) -> None: ...
    def on_contract_last_day(self, ctx: Context, symbol: str) -> None: ...

    # ---- 状态持久化（默认 pickle，可重写）----
    def save_state(self) -> bytes: ...
    def load_state(self, blob: bytes) -> None: ...
```

子类按需重写。回调若返回 `Iterable[OrderIntent]`，引擎收集后交给执行层。

### 2.1 `SignalStrategy` 简化形态

```python
class SignalStrategy(Strategy):
    def compute_signal(self, ctx: BarContext) -> pl.DataFrame:
        """返回 [symbol, score]，由 Portfolio 转换为目标头寸。"""
        ...

    # 不要重写 on_bar；基类已实现：调用 compute_signal 后交组合层
```

### 2.2 `TargetPositionStrategy` 简化形态

```python
class TargetPositionStrategy(Strategy):
    def compute_target(self, ctx: BarContext) -> pl.DataFrame:
        """返回 [symbol, target_qty] 或 [symbol, target_weight]。"""
        ...
```

引擎自动计算 `delta = target - current` 并生成订单，按 `21-portfolio-construction.md` 的 turnover/约束规则裁剪。

## 3. Context 对象

`Context` 是策略与平台之间唯一的双向接口。两个粒度：`Context`（会话级） 与 `BarContext`（bar 级）。

### 3.1 `Context`

```python
@dataclass(frozen=True)
class Context:
    now: datetime                     # 当前虚拟时间
    run_id: str
    config: RunConfig                 # 只读
    calendar: Calendar
    universe: Universe                # 当前 universe 快照
    account: AccountView              # 只读视图，含 cash / margin / positions
    risk: RiskView                    # 只读视图，含 Greeks / 杠杆 / 风险度
    logger: StrategyLogger            # 写入策略日志
    state: StrategyStateStore         # 持久化 key-value
    rng: random.Random                # seeded 随机源

    def submit(self, intent: OrderIntent) -> None: ...
    def cancel(self, order_id: str) -> None: ...
    def cancel_all(self, symbol: str | None = None) -> None: ...
    def roll_position(self, from_sym: str, to_sym: str, qty: Decimal | None = None) -> None: ...
```

### 3.2 `BarContext`

```python
@dataclass(frozen=True)
class BarContext(Context):
    bar: pl.DataFrame                 # 当前 bar 的横截面（所有 universe symbol 的一行）
    history: HistoryView              # 滚动历史窗口访问
    tradability: dict[str, dict[Side, Tradability]]

    def lookback(self, symbols, columns, n: int) -> pl.DataFrame: ...
    def factor(self, name: str) -> pl.DataFrame: ...
    def session(self) -> Session: ...
```

- `bar`：长表，列与 `10-data-layer.md` §1.1 一致；行数 ≤ universe 大小。
- `history.lookback(n=20)`：返回过去 n 根 bar 的长表（已包含当前 bar）。
- `factor(name)`：从因子库取已预计算的因子值，避免在 on_bar 里重复算指标。

### 3.3 关键不变量

- **决策时点的可见性**：`BarContext` 暴露的所有数据满足 `dt <= ctx.now`，绝不会含未来 bar。
- **AccountView 是 t-1 估值**：用前一根 bar close 估值，与 mark-to-market 一致。
- **不允许直接修改 universe/account**：所有变更走 `ctx.submit`。

## 4. OrderIntent 与订单类型

策略输出的最小单位是 `OrderIntent`（非 `Order`，后者由执行引擎生成）：

```python
@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: Side                         # BUY / SELL / OPEN_LONG / OPEN_SHORT / CLOSE_LONG / CLOSE_SHORT
    qty: Decimal | None                # 与 weight 二选一
    weight: Decimal | None             # 目标权重（相对组合 NAV）
    order_type: OrderType              # MARKET / LIMIT / STOP / STOP_LIMIT / IOC / FOK / AUCTION
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TIF = TIF.DAY       # DAY / GTC / IOC / FOK / AUCTION
    take_profit: TPSLDef | None = None # 子单：止盈
    stop_loss: TPSLDef | None = None   # 子单：止损
    tag: str | None = None             # 策略自定义标签，用于归因
    parent_order_id: str | None = None # 配对单/子单

@dataclass(frozen=True)
class TPSLDef:
    trigger: Decimal                   # 触发价
    order_type: OrderType              # 默认 MARKET
    limit_price: Decimal | None = None # 若用 STOP_LIMIT
    trailing: Decimal | None = None    # 跟踪幅度（绝对值或 bps）
```

> **A 股仅支持 BUY/SELL**（无双向持仓）；**期货支持 OPEN_LONG/OPEN_SHORT/CLOSE_LONG/CLOSE_SHORT**（区分开平、多空）。执行引擎对资产类做校验。

## 5. 状态持久化与热启动

### 5.1 `StrategyStateStore`

策略私有的 KV 存储，回测每个 bar 末/会话末由 runner 自动 flush 到 `runs/{run_id}/state/{strategy_name}.parquet`。

```python
ctx.state["last_signal"] = signal_df
ctx.state["consecutive_losses"] = ctx.state.get("consecutive_losses", 0) + 1
```

支持 Polars DataFrame、Decimal、嵌套 dict、自定义可序列化对象（`__reduce__` 协议）。

### 5.2 热启动

`Backtest(resume_from="runs/abc123/checkpoint/2024-09-30/")` 从指定时点重启：

- 加载账户快照（cash, positions, margin）
- 加载策略 state
- 加载因子缓存
- 时间轴从 checkpoint 时点之后开始

适用于：
- 长回测中断后恢复
- Walk-forward 训练 → 测试段衔接（详见 `50-param-search.md` §3）

### 5.3 检查点频率

默认每个交易日收盘后 checkpoint。可配 `checkpoint=Checkpoint.daily()` / `Checkpoint.weekly()` / `Checkpoint.bars(1000)`。

## 6. 多策略

平台原生支持**同一回测中跑多个策略**，共享行情但拥有独立账户子簿与 state。

```python
bt = Backtest(...)
bt.add_strategy(StrategyA(), capital_weight=0.6)
bt.add_strategy(StrategyB(), capital_weight=0.4)
result = bt.run()

result.strategy("StrategyA").tear_sheet()       # 各自归因
result.combined.tear_sheet()                     # 合并
```

资金分配规则见 `21-portfolio-construction.md` §5。

## 7. 最小示例

### 7.1 双均线（事件型）

```python
import polars as pl
from decimal import Decimal
from getrich_backtest import Strategy, OrderIntent, Side, OrderType
from getrich_backtest.api import BarContext

class MACross(Strategy):
    name = "ma_cross_v1"

    def __init__(self, fast: int = 5, slow: int = 20):
        self.fast = fast
        self.slow = slow

    def on_bar(self, ctx: BarContext):
        hist = ctx.lookback(ctx.universe.symbols, ["close"], n=self.slow + 1)
        sig = (
            hist.group_by("symbol", maintain_order=True)
            .agg([
                pl.col("close").tail(self.fast).mean().alias("fast"),
                pl.col("close").tail(self.slow).mean().alias("slow"),
            ])
            .with_columns(direction=pl.when(pl.col("fast") > pl.col("slow")).then(1).otherwise(-1))
        )
        for row in sig.iter_rows(named=True):
            current = ctx.account.position(row["symbol"]).qty
            target = Decimal("100") * row["direction"]
            if current != target:
                yield OrderIntent(
                    symbol=row["symbol"],
                    side=Side.BUY if target > current else Side.SELL,
                    qty=abs(target - current),
                    order_type=OrderType.MARKET,
                )
```

### 7.2 信号型（IC 研究）

```python
class MomentumSignal(SignalStrategy):
    name = "mom20"

    def compute_signal(self, ctx: BarContext) -> pl.DataFrame:
        hist = ctx.lookback(ctx.universe.symbols, ["close"], n=21)
        return (
            hist.group_by("symbol", maintain_order=True)
            .agg(score=(pl.col("close").last() / pl.col("close").first() - 1))
        )
```

由组合层把 `score` 转为多空头寸（详见 `21-portfolio-construction.md`）。

## 8. 设计禁区

- **禁止**在策略代码内直接访问 `ctx.bar` 之外的未来数据。
- **禁止**自定义全局变量保存跨 bar 状态——一律用 `ctx.state`，否则热启动后状态丢失。
- **禁止**在 `on_bar` 内做长耗时 IO（数据库查询、HTTP）；耗时操作放 `setup` 或 factor 预计算。
- **禁止**直接修改 `ctx.account` / `ctx.universe`；它们是只读视图。
- **禁止**使用 `time.sleep()` 或 wall-clock；回测时间由 runner 推进。
