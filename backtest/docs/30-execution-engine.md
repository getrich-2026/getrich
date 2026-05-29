# 30. 执行引擎

> 把 `OrderIntent` 转成成交 (`Fill`) 的全过程。对应原需求"策略模拟"的撮合/滑点/手续费/成交价/成交时间部分，以及第 4 节"容量与流动性约束"。

## 1. 订单生命周期

```text
OrderIntent              # 策略生成
    │ runner: 注入 timestamp/order_id
    ▼
Order(state=PENDING)     # 进入引擎
    │ Tradability 检查 (12-calendar-tradability §3)
    │ 风控事前检查 (32-risk-control §6)
    ├─→ Rejected → on_order_rejected
    ▼
Order(state=ACCEPTED)    # 进入撮合队列
    │ MatchingEngine
    ├─→ PartiallyFilled → on_fill (部分) → 余量回到队列
    ▼
Order(state=FILLED | EXPIRED | CANCELED)
    │
    ▼
Fill                     # 推送给 Account & Strategy
```

### 1.1 Order 状态

| 状态 | 含义 |
| --- | --- |
| `PENDING` | 已提交未撮合 |
| `ACCEPTED` | 通过 Tradability/风控/撮合队列 |
| `PARTIAL` | 部分成交 |
| `FILLED` | 完全成交 |
| `CANCELED` | 用户取消 |
| `REJECTED` | 引擎拒单（含 reason） |
| `EXPIRED` | TIF 超时 |

### 1.2 ID 体系

- `intent_id`：策略生成时的临时 ID
- `order_id`：引擎接受后分配，与策略对账
- `fill_id`：单笔成交，唯一
- `parent_id`：止盈止损/算法母单的父 ID

## 2. 订单类型

| 类型 | 含义 | 价格字段 |
| --- | --- | --- |
| `MARKET` | 市价单 | 无 |
| `LIMIT` | 限价单 | `limit_price` |
| `STOP` | 止损单（触发后变市价） | `stop_price` |
| `STOP_LIMIT` | 触发后变限价 | `stop_price` + `limit_price` |
| `IOC` | 立即成交剩余取消 | 限价 |
| `FOK` | 全部成交或全部取消 | 限价 |
| `AUCTION` | 集合竞价单 | 限价 / 市价 |
| `TWAP(child)` | 算法母单的子单 | 由算法生成 |
| `VWAP(child)` | 同上 | |

止盈止损按"子单"挂在母单上，母单 `Fill` 后子单激活。

## 3. 撮合模型

### 3.1 默认假设（`NextBarMatchingModel`）

- **决策延迟**：bar `t` 的 `on_bar` 产出意图，在 bar `t+1` 撮合（`execution_lag_bars=1`）。
- **成交价基准**：
  - 市价：`fill_price = bar_{t+1}.open`（加滑点）
  - 限价：若 `bar_{t+1}.low <= limit_price <= bar_{t+1}.high`，成交于 `clip(limit_price, low, high)`；否则该 bar 不成交，转下根 bar 或按 TIF 处理
  - STOP：触发条件 `bar_{t+1}.high >= stop_price`（买）或 `bar_{t+1}.low <= stop_price`（卖），触发后按市价/限价子流程
- **成交时间**：
  - 市价 → `bar_{t+1}.dt`（bar 起始时刻）
  - 限价/STOP → `bar_{t+1}.dt + Δt`，`Δt` 在 bar 内线性插值（用 high/low 与触发价的相对位置）

### 3.2 进阶撮合（`IntraBarMatchingModel`）

启用 tick 数据或 1m bar 内的 5 个采样点（O/H/L/C + VWAP），按时间顺序逐点判定触发与成交。计算成本高，仅推荐用于：

- 高频策略
- 严格回放止损止盈触发
- 滑点研究

### 3.3 保守撮合（`ConservativeMatchingModel`）

- 市价：`fill_price = (open + close) / 2`，再加滑点
- 限价：要求 `limit_price` 严格优于 bar 中位价 5 个 tick 才认为成交
- 适用：盘口数据缺失时的保守估计

### 3.4 涨跌停与可成交性

- 买单遇 `LIMIT_UP_NO_FILL` → 当 bar 不成交，进入"封板等待"
- 卖单遇 `LIMIT_DOWN_NO_FILL` → 当 bar 不成交
- 封板等待最多保持 N bar（默认 5），超时按 TIF 处理
- 部分撤板成交建模：`open_at_limit=true` 时按 `participation_rate × bar_volume` 与"封板时长"加权（默认 30% 成交概率，可配）

## 4. 滑点模型（SlippageModel）

```python
class SlippageModel(Protocol):
    def adjust(self, intended_price: Decimal, side: Side,
               bar: BarRow, order: Order) -> Decimal: ...
```

内置实现：

| 模型 | 公式 | 说明 |
| --- | --- | --- |
| `Zero` | 0 | 调试用 |
| `FixedBps(n)` | `intended × n/1e4` | 简单 |
| `FixedTick(n)` | `n × tick_size` | 按品种 tick |
| `VolatilityScaled(k)` | `k × σ × √(qty/avg_volume)` | 与波动率与单量相关 |
| `SquareRootImpact(c)` | `c × σ × sqrt(qty / ADV)` | 平方根冲击成本（Kyle/Almgren） |
| `Linear(a, b)` | `a + b × (qty / bar_volume)` | 线性参与率 |
| `Custom(fn)` | 用户函数 | |

滑点方向：买价上浮、卖价下压。

### 4.1 资产特化默认值

| 资产 | 默认模型 | 参数 |
| --- | --- | --- |
| A 股 | `FixedBps(5)` | 5 bps |
| A 股期权 | `FixedTick(2)` | 2 tick |
| 商品期货 | `FixedTick(1)` + `Linear(0, 0.5)` 叠加 | |
| 股指期货 | `FixedTick(1)` | |

可在 `RunConfig` 覆盖。

## 5. 容量与流动性约束

### 5.1 最大参与率

```python
capacity = CapacityModel.bar_pct(rate=0.05, mode="strict")
```

- `rate=0.05`：单 bar 单合约成交量 ≤ bar volume 的 5%
- `mode="strict"`：超出的 qty 拒单；`mode="defer"`：超出的 qty 拆到下根 bar 继续撮合
- 多策略共享同一标的时，参与率按聚合后的 qty 计算（组合层在分配 child order 前已聚合）

### 5.2 母单切片（VWAP/TWAP）

策略提交大单时可附 `algo="VWAP"` 标识：

```python
OrderIntent(symbol, side, qty,
            order_type=OrderType.MARKET,
            algo=AlgoStyle.VWAP(slice_minutes=60))
```

执行引擎拆为 60 根 1m 子单，按预测 VWAP 曲线分配子单 qty；每子单仍受 `CapacityModel` 约束。

### 5.3 大单冲击成本

`SquareRootImpact` 模型按订单 qty 与该 bar ADV（20 日均量）计算额外冲击；冲击叠加在滑点之上。

### 5.4 盘口不可用兜底

若数据缺 high/low（极端情况），执行引擎切换为 `ConservativeMatchingModel`，并记录 `quality_warning` 进入归因报告。

## 6. 手续费模型（FeeModel）

```python
class FeeModel(Protocol):
    def commission(self, fill: FillCandidate) -> Decimal: ...
    def stamp_tax(self, fill: FillCandidate) -> Decimal: ...   # A 股卖出印花税
    def transfer_fee(self, fill: FillCandidate) -> Decimal: ... # A 股过户费
    def exchange_fee(self, fill: FillCandidate) -> Decimal: ...
    def total(self, fill: FillCandidate) -> Decimal: ...
```

### 6.1 资产默认费率

| 资产 | 费率（一边） |
| --- | --- |
| A 股 | 佣金 `max(成交额 × 万 2.5, 5 元)`；卖出印花税 千 1；过户费 万 0.1（沪市） |
| A 股期权 | 每张 5 元（含交易所、券商；可分离） |
| 商品期货 | 按品种：固定金额 / 成交额比例；如 RB 万 1，平今 万 1.5；CU 每手 14 元 |
| 股指期货 | 成交额万 0.23（开仓）+ 万 3.45（平今） |
| 期货期权 | 每张 1-15 元，按品种 |

详细参数表在 `runtime/fees/default_fees.toml`。

### 6.2 阶梯费率

支持按月成交量阶梯（用于券商佣金谈判后的回测）：

```python
fee = FeeModel.equity_a(
    commission=ScaleSchedule([
        (Decimal("0"),       Decimal("0.00025")),
        (Decimal("1e8"),     Decimal("0.00020")),
        (Decimal("5e8"),     Decimal("0.00015")),
    ]),
)
```

### 6.3 平今 vs 平昨

商品期货费率区分平今、平昨；执行引擎按 FIFO（先开先平）确定 `is_close_today` 标志，写入 `Fill.fee_breakdown`。

## 7. 部分成交

- 容量约束 → 部分成交
- IOC → 立即成交可成交部分，剩余取消
- 涨停封板 → 0% 成交，整单延后/取消
- 流动性不足 → 按 `participation_rate × bar_volume` 部分成交

每次部分成交产生一个 `Fill` 事件；引擎确保 `sum(fills.qty) == order.qty_filled`。

## 8. Fill 数据结构

```python
@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    intent_id: str
    strategy_name: str
    symbol: str
    asset_class: AssetClass
    side: Side
    qty: Decimal                 # 始终 > 0
    price: Decimal               # 含滑点后的实际成交价
    notional: Decimal            # = qty × price × multiplier
    fee: Decimal
    fee_breakdown: dict[str, Decimal]   # commission/stamp/transfer/exchange
    fill_time: datetime          # Asia/Shanghai aware
    is_close_today: bool         # 期货平今标志
    bar_dt: datetime             # 撮合所在 bar 的起始时刻
    slippage: Decimal            # 相对意图价的偏移
    tag: str | None              # 策略 tag
```

Fill 同时推送给：
- `Strategy.on_fill`
- `Account.apply(fill)`（更新现金、持仓、保证金）
- `AttributionEngine.record(fill)`（归因日志）

## 9. 决策与执行延迟（execution_lag）

- 默认 `execution_lag_bars=1`：意图在下根 bar 撮合
- `=0` 适用：日频策略以 close 价回测、Tick 级策略（实时模拟）
- `=N`：用于消息延迟模拟

事件循环在 `t` 处理 `t-N` 提交的意图。`lag=0` 时引擎会做 **look-ahead 检查**：若 `fill_price` 涉及 `t` 的 high/low，必须显式声明 `allow_close_fill=True`，否则报错。

## 10. 与策略层、账户层的契约

| 接口方向 | 内容 |
| --- | --- |
| 策略 → 执行 | `ctx.submit(OrderIntent)` / `ctx.cancel(order_id)` |
| 执行 → 策略 | `on_order_accepted`, `on_order_rejected`, `on_fill`, `on_order_expired` |
| 执行 → 账户 | `account.apply(fill)`；账户处理现金、持仓、保证金（详见 `31-account-margin.md`） |
| 风控 → 执行 | 事前 `RiskManager.precheck(order)`；返回 `Reject(reason)` 时直接拒单 |
| 执行 → 归因 | 每个 `Fill` 写入 `runs/{run_id}/fills.parquet` |

## 11. 最小示例

```python
from getrich_backtest.execution import (
    ExecutionEngine, NextBarMatchingModel,
    SlippageModel, FeeModel, CapacityModel,
)

engine = ExecutionEngine(
    matching=NextBarMatchingModel(),
    slippage={
        AssetClass.EQUITY_A: SlippageModel.fixed_bps(5),
        AssetClass.COMMODITY_FUTURE: SlippageModel.fixed_tick(1) + SlippageModel.linear(0, 0.5),
    },
    fees={
        AssetClass.EQUITY_A: FeeModel.equity_a_default(),
        AssetClass.COMMODITY_FUTURE: FeeModel.commodity_future_default(),
    },
    capacity=CapacityModel.bar_pct(0.05, mode="defer"),
    execution_lag_bars=1,
)
```

## 12. 设计禁区

- **禁止**策略代码直接构造 `Fill`——只能由引擎产生。
- **禁止**用同一根 bar 的 close 估值意图、close 又撮合（默认 `lag=1` 强制隔离）。
- **禁止**滑点为负（即让策略"占便宜")，除非显式 `allow_negative_slippage=True`（仅 debug）。
- **禁止**手续费写入 `bar.amount` 之外的字段——必须落到 `Fill.fee_breakdown`，由归因层分门别类。
