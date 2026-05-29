# 12. 交易日历与可交易性引擎

> 决定**每一根 bar 上哪些操作合法**：下单、撮合、估值、结算、换月。对应原需求第 2 节"交易日历与可交易性引擎"。本模块是 look-ahead 与跨品种回测正确性的最后一道防线。

## 1. 交易日历

### 1.1 交易所粒度

各交易所独立日历（节假日、临时休市差异）：`SSE`/`SZSE`/`BSE`/`CFFEX`/`SHFE`/`DCE`/`CZCE`/`INE`/`GFEX`。

```python
class Calendar:
    def is_trading_day(self, exchange: str, day: date) -> bool: ...
    def sessions(self, exchange: str, day: date) -> list[Session]: ...
    def prev_trading_day(self, exchange: str, day: date) -> date: ...
    def next_trading_day(self, exchange: str, day: date) -> date: ...
    def trading_days(self, exchange: str, start: date, end: date) -> list[date]: ...
```

### 1.2 临时休市

`md_holidays_temp`：

| 列 | 类型 |
| --- | --- |
| `exchange` | `Categorical` |
| `date` | `Date` |
| `kind` | `Enum{full_day, half_day, late_open, early_close}` |
| `note` | `Utf8` |
| `effective_sessions` | `Json`（覆盖默认 sessions） |

例：2024-09-23 SSE 全天，2025-XX 国务院调休次日半日。

## 2. 交易段（Session）

```python
@dataclass(frozen=True)
class Session:
    exchange: str
    name: str                  # e.g. "morning", "afternoon", "night"
    start: time                # tz-aware Asia/Shanghai
    end: time
    spans_midnight: bool       # 夜盘 21:00–次日 02:30
    phase: SessionPhase        # AUCTION / CONTINUOUS / CLOSE_AUCTION
```

### 2.1 默认交易段

| 交易所 | 段 | 时段 |
| --- | --- | --- |
| SSE/SZSE/BSE | 集合竞价 | 09:15–09:25 |
|  | 连续 | 09:30–11:30, 13:00–14:57 |
|  | 收盘集中竞价 | 14:57–15:00 |
| CFFEX (股指期货) | 连续 | 09:30–11:30, 13:00–15:00 |
| CFFEX (T、TS、TF、TL 国债) | 连续 | 09:30–11:30, 13:00–15:15 |
| SHFE/DCE/CZCE/INE/GFEX (商品期货) | 日盘 | 09:00–10:15, 10:30–11:30, 13:30–15:00 |
|  | 夜盘 | 21:00–次日（02:30/01:00/23:00，按品种） |

> 夜盘各品种结束时间差异由 `instruments_future.night_session_end` 维护。

### 2.2 阶段（Phase）

| Phase | 可下单 | 可成交 | 可估值 |
| --- | --- | --- | --- |
| `AUCTION` 集合竞价 | 是（特殊订单类型） | 在 phase 结束时一次性撮合 | 否 |
| `CONTINUOUS` 连续竞价 | 是 | 是（按撮合模型） | 是 |
| `CLOSE_AUCTION` 收盘集合 | 是（仅限价） | phase 结束时撮合 | 否 |
| `LUNCH_BREAK` 休市 | 否 | 否 | 上一段收盘价持续 |
| `CLOSED` 闭市 | 否 | 否 | 最近一次 close 持续 |

策略 `on_bar` 只在 `CONTINUOUS` 与 `CLOSE_AUCTION` 阶段被调用；其它阶段提供 `on_session_open` / `on_session_close` / `on_lunch_break` 等显式钩子。

## 3. 可交易性引擎（Tradability）

将每根 bar 上对每个 symbol 的"四类许可"统一表达：

```python
@dataclass(frozen=True)
class Tradability:
    can_submit: bool      # 可下单
    can_fill: bool        # 可成交（撮合）
    can_value: bool       # 可估值
    can_settle: bool      # 可参与当日结算
    reason: str | None    # 不满足时的原因码
```

`reason` 取值（用于风控日志与归因）：

```
TRADING_HALT_FULL_DAY
TRADING_HALT_INTRADAY
LIMIT_UP_NO_FILL
LIMIT_DOWN_NO_FILL
ZERO_VOLUME
MISSING_BAR
PRE_LIST
POST_DELIST
OPTION_LAST_DAY_HALT
AUCTION_PHASE
CLOSED
```

### 3.1 计算流程

```python
class TradabilityEngine:
    def evaluate(
        self,
        bar: BarRow,
        instrument: InstrumentMeta,
        calendar: Calendar,
    ) -> Tradability: ...
```

判定优先级：

1. 时段不在 Session 内 → `can_submit=can_fill=can_value=False`，reason=`CLOSED`。
2. `is_suspended=true` → 全 False，reason=`TRADING_HALT_FULL_DAY`。
3. `is_missing=true` → `can_submit=False, can_fill=False, can_value=True (用前值)`，reason=`MISSING_BAR`。
4. `volume == 0` → `can_fill=False`，reason=`ZERO_VOLUME`。
5. `close >= limit_up` → 买方 `can_fill=False`，reason=`LIMIT_UP_NO_FILL`；卖方仍可成交。
6. `close <= limit_down` → 卖方 `can_fill=False`，reason=`LIMIT_DOWN_NO_FILL`。
7. 上市前/退市后 → 全 False。
8. 期权最后交易日的最后 5 分钟 → `can_submit=False, can_fill=False`，reason=`OPTION_LAST_DAY_HALT`（防止深度实值期权操纵）。

涨跌停的判定是**方向性**的——同一根 bar，买方与卖方的 Tradability 可能不同，因此 `evaluate` 返回的实际是 `dict[Side, Tradability]`。

### 3.2 跨品种 Bar 对齐

多品种回测时，事件循环遍历**所有相关交易所的并集时间轴**。在 `t` 时刻：

- A 股 + 商品期货组合：商品期货上午 09:00–09:30 时，A 股仍在集合竞价，`Tradability(SSE).can_submit=True (auction)` 而 `can_fill=False`。
- 商品期货夜盘 21:00–02:30 时，A 股 `CLOSED`；A 股持仓继续按最近 `close` 估值，`can_value=True`。

事件循环按 `time` 单调推进，每个时间点只对**该时点处于 CONTINUOUS/AUCTION 阶段的合约**调用 `on_bar`。其他合约的状态由账户层持续 mark-to-market（用最近 close）。

## 4. 集合竞价的撮合假设

| 类型 | 处理 |
| --- | --- |
| 开盘集合竞价（09:15–09:25） | 接受限价单与"开盘价限价单"；引擎在 09:30 第一根 bar 的 open 处以 `open` 价成交（限价单需满足价位） |
| 收盘集合竞价（14:57–15:00） | 接受限价单；引擎在 15:00 以收盘价 `close` 成交 |

实现细节：策略在 `on_session_open` 内提交的订单可指定 `time_in_force="AUCTION"`，由引擎统一在集合竞价撮合时点处理。

## 5. 期货换月日的特殊处理

最后交易日（`last_trade_date`）：

- 09:00 开盘前推送 `on_contract_last_day(strategy, symbol)`。
- 该日**最后 30 分钟** `can_submit=False`（仅可平仓，禁止新开），reason=`FUTURE_LAST_DAY_NO_NEW`。
- 收盘后 `can_settle=True` 并触发交割结算（详见 `31-account-margin.md` §4）。

## 6. 估值频率

- **分钟级 mark-to-market**：账户在每根 1m bar 收盘时按 `t-1 close` 重估持仓市值。
- **日终 settle**：商品/股指期货按**结算价**重估并扣留保证金（详见 `31` §3）。结算价由 `settlement` 列提供；缺失则用当日加权均价兜底（写入 `quality_warning`）。

## 7. 最小示例

```python
from getrich_backtest.data import Calendar, TradabilityEngine
from datetime import date, datetime

cal = Calendar.from_pgsql(pool)
te = TradabilityEngine(cal)

print(cal.is_trading_day("SSE", date(2024, 10, 1)))   # False (国庆)
print(cal.sessions("SHFE", date(2024, 10, 8)))
# [Session(09:00-10:15), Session(10:30-11:30), ...]

bar = ...                # 一行 polars，含 limit_up / volume / is_suspended
inst = ...               # InstrumentMeta
tr = te.evaluate(bar, inst, cal)
# {Side.BUY: Tradability(can_fill=False, reason='LIMIT_UP_NO_FILL'),
#  Side.SELL: Tradability(can_fill=True)}
```

## 8. 与上层模块的契约

- **策略层**：在生成 `OrderIntent` 时调用 `ctx.tradability(symbol)` 自检，避免无效订单（事前风控也会拦截，但策略主动检查可减少日志噪声）。
- **执行层**：撮合前对每个订单查 `Tradability`，不满足直接拒单（reason 落到 `OrderRejection` 事件，进入归因）。
- **风控层**：以 `Tradability` 的 reason 分布作为流动性枯竭、停牌冲击的输入。
