# 31. 账户、保证金与结算

> 资金、持仓、保证金、市值、每日结算、强平、T+x 规则、期权行权与指派、公司行为对账户的影响。对应原需求"账户系统"全部条目 + 第 1/2/9 节相关项。

## 1. 账户构成

```text
Account
├── cash:        Decimal                 # 可用现金（含未结算分红、未交收资金占用）
├── frozen_cash: Decimal                 # 委托冻结（含 A 股 T+1 在途）
├── positions:   dict[symbol, Position]
├── margin:      MarginState
└── subaccounts: dict[strategy_name, SubAccount]  # 多策略时
```

`Account` 是整体的"总账"，`SubAccount` 是策略级分簿。所有资金更新经过 `Account.apply(...)` 单一入口，保证一致性。

### 1.1 Position

```python
@dataclass
class Position:
    symbol: str
    asset_class: AssetClass
    qty: Decimal                         # 多头正，空头负（期货/期权）；A 股仅正
    avg_cost: Decimal                    # 加权平均开仓价
    cost_basis: Decimal                  # = avg_cost × qty × multiplier
    mark_price: Decimal                  # 最近一次 mark
    market_value: Decimal                # = mark × qty × multiplier
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    margin_held: Decimal                 # 占用保证金
    open_time: datetime                  # 首次开仓时刻（用于税阶梯）
    # 期货专属
    today_qty: Decimal | None            # 当日开仓未平的部分（平今费率用）
    # 期权专属
    is_short_option: bool                # 卖方需保证金
    delta: Decimal | None                # 当前 Greek 快照（由风险层填）
    gamma: Decimal | None
    vega: Decimal | None
    theta: Decimal | None
```

### 1.2 现金账与可用资金

```
available_cash = cash - frozen_cash
```

下单时引擎调用 `account.reserve(intent)` 冻结所需保证金/资金；成交后 `account.apply(fill)` 转为正式占用；拒单时 `account.release(intent)`。

## 2. T+x 规则

| 资产 | 买入 | 卖出 |
| --- | --- | --- |
| A 股 | T+0 持仓可见，T+1 才可卖出 | T+0 卖出，T+1 资金可用 |
| A 股期权 | T+0 全程 | T+0 全程 |
| 商品期货 | T+0 | T+0 |
| 股指期货 | T+0 | T+0 |
| 期货期权 | T+0 | T+0 |

实现：`Position` 额外维护 `available_qty` 与 `pending_qty`，A 股每日 settle 把 `pending_qty` 转入 `available_qty`。卖出意图引擎只能扣 `available_qty`。

## 3. 保证金（Margin）

仅期货 / 卖方期权 / 备兑 / 融券 涉及。

### 3.1 保证金类型

| 类型 | 说明 |
| --- | --- |
| `Initial` 初始保证金 | 开仓时占用 = `qty × price × multiplier × margin_ratio` |
| `Maintenance` 维持保证金 | 每日结算后需保持的最低水平 |
| `Variation` 变动保证金 | 每日盯市的 PnL 累加 |
| `Add-on` 附加保证金 | 临近交割、政策调整时的额外占用 |
| `Span/Portfolio` 组合保证金 | CFFEX/INE 等支持的组合优惠（多空对冲减保证金） |

### 3.2 保证金率来源

- 静态：`instruments_future.margin_ratio_long/short`
- 动态：交易所临时上调（如节假日、单边市），由 `MarginPolicy.adjust(dt, product)` 注入
- 策略侧：策略可重写 `margin_buffer=1.2`，留 20% 缓冲防止意外强平

### 3.3 每日盯市（Mark-to-Market）

每个交易日收盘后 (`SessionPhase.CLOSED`)：

1. 用**当日结算价** `bar_1d.settlement` 重估所有期货持仓
2. `variation_pnl = (settle - avg_cost) × qty × multiplier`（含正负方向）
3. `cash += variation_pnl`（盈利落袋，亏损扣现金）
4. `avg_cost = settle`（结算后头寸成本归零，重新基于结算价计算次日 PnL）
5. 重新计算 `margin_held = qty × settle × multiplier × current_margin_ratio`
6. 检查 `available_cash >= maintenance_margin_total`；不足触发追保 / 强平

### 3.4 期权保证金

中国 ETF 期权 / 个股期权采用专用公式（最大值法）：

```
认购卖方:
  initial = max(
    pre_settle + max(0.12 × underlying - max(0, strike - underlying), 0.07 × underlying),
    pre_settle + 0.07 × underlying
  ) × multiplier × qty

认沽卖方:
  initial = min(
    pre_settle + max(0.12 × underlying - max(0, underlying - strike), 0.07 × strike),
    strike
  ) × multiplier × qty
```

期货期权按交易所公式（Black-76 衍生）。所有公式封装在 `MarginRule.option_xxx(...)` 内。

## 4. 每日结算流程

```python
def daily_settle(account, bars_1d, calendar, dt):
    # 1. 期货 / 卖方期权 mark-to-market
    for pos in account.futures_and_short_options():
        apply_variation_margin(pos, bars_1d[pos.symbol].settlement)

    # 2. A 股 T+1 资金 / 持仓释放
    account.release_t1_positions(dt)
    account.release_t1_cash(dt)

    # 3. 公司行为
    for event in corp_actions_on(dt):
        apply_corp_action(account, event)

    # 4. 期权到期处理
    for sym in expiring_options_on(dt):
        apply_option_expiry(account, sym)

    # 5. 期货到期/换月
    for sym in last_trade_day_futures(dt):
        apply_future_delivery_or_roll(account, sym)

    # 6. 风险扫描
    risk_alerts = RiskManager.eod_scan(account)

    # 7. 写 daily snapshot
    snapshot.write(account, dt)
```

## 5. 期权到期 / 行权

### 5.1 European 期权（A 股 ETF 期权、个股期权、股指期货期权）

到期日 15:00 自动行权：

| 情况 | 处理 |
| --- | --- |
| 实值 + 多头 | 行权得到标的（或现金交割）；A 股期权 multiplier=10000，得 10000 股 |
| 虚值 + 多头 | 期权作废，权利金已沉没 |
| 实值 + 空头 | 被指派；现金/标的方向扣减 |
| 虚值 + 空头 | 保证金全部释放 |

策略可在到期日**之前**主动平仓避免行权。引擎在到期日推送 `on_option_expire(strategy, symbol, payoff)`。

### 5.2 American 期权（部分商品期货期权）

可在到期前任意交易日主动行权。策略调用 `ctx.exercise_option(symbol, qty)`，引擎在下一日盘前完成行权（涉及实物交割时按交割流程）。

### 5.3 现金交割 vs 实物交割

| 品种 | 交割方式 |
| --- | --- |
| 股指期货 (IF/IH/IC/IM) | 现金交割，按交割结算价 |
| 商品期货 | 实物交割（回测中默认强平避免） |
| A 股 ETF 期权 | 实物交割 ETF 份额 |
| 期货期权 | 行权后转为期货持仓 |

回测默认对实物交割的商品期货**临近交割日强制平仓**（产品 `last_trade_date - 5d`），避免回测涉及实物流程。可配 `allow_physical_delivery=True` 启用实物模拟。

## 6. 强平（Forced Liquidation）

### 6.1 触发条件

```
risk_ratio = (margin_held + funded_position_value) / total_equity
```

- `risk_ratio >= margin_call_threshold` (默认 0.95) → `MarginCallAlert` 推送，策略可主动减仓
- `risk_ratio >= liquidation_threshold` (默认 1.00) → 强平流程启动

### 6.2 强平流程

1. 触发后下一根 bar 开始强平
2. 按品种风险贡献排序，优先平损失最大、保证金最高的合约
3. 强平用市价单（带 2× 滑点惩罚，模拟流动性枯竭）
4. 每根 bar 平至 `risk_ratio < safety_threshold` (默认 0.80) 为止
5. 全平仓后 `cash < 0` → 标记 `account.is_blown_out = True`，回测继续仅做记录，不再下单

### 6.3 与策略的交互

- `on_margin_call(alert)`：策略可在此回调内主动 `ctx.cancel_all()` + 平仓
- 若策略未处理，下一根 bar 由引擎强平
- 强平 `Fill.tag = "forced_liquidation"`，进入归因

## 7. 公司行为对账户的调整

详见 `11-data-quality.md` §2.4，此处补充账户层落地：

```python
def apply_corp_action(account, event):
    pos = account.positions.get(event.symbol)
    if pos is None: return

    if event.type == "cash_dividend":
        tax_rate = dividend_tax_rate(event.dt, pos.open_time)
        cash_in = pos.qty * event.cash_dividend * (1 - tax_rate)
        account.cash += cash_in
        account.ledger.write(LedgerEntry(
            type="dividend", symbol=event.symbol, amount=cash_in,
        ))

    elif event.type == "split":   # 送转
        new_qty = pos.qty * (1 + event.split_ratio)
        new_cost = pos.avg_cost / (1 + event.split_ratio)
        pos.qty = new_qty
        pos.avg_cost = new_cost

    elif event.type == "rights":  # 配股
        if strategy.consent_rights_offer(event):
            sub_qty = pos.qty * event.rights_ratio
            sub_cost = sub_qty * event.rights_price
            account.cash -= sub_cost
            pos.qty += sub_qty
            pos.avg_cost = weighted_avg([pos.avg_cost, event.rights_price],
                                        [pos.qty - sub_qty, sub_qty])
```

## 8. 多策略子账户

`SubAccount` 由 `Account` 派生，遵循"账面隔离 + 实际共享"：

- 账面隔离：每个 SubAccount 维护独立 cash、positions、margin、PnL
- 实际共享（可选）：`shared_pool=True` 时，cash 池物理共享；某策略 cash 暂时为负，由其他策略借出（按权重计利息，详见 `21-portfolio-construction.md` §5.1）

### 8.1 子账户视图

策略通过 `ctx.account` 访问的是 **SubAccountView**：

- 现金 = `SubAccount.cash`
- 持仓 = `SubAccount.positions`
- 风险 = `RiskManager.subaccount_view(strategy_name)`

策略**看不到**其他策略的 state。

### 8.2 PnL 与归因

每个 fill 标记 `strategy_name`；账户内部维护 `pnl_by_strategy`，每日 settle 时累计：

- `realized_pnl_by_strategy[name]`
- `unrealized_pnl_by_strategy[name]`
- `fee_by_strategy[name]`

为归因报告提供基础数据。

## 9. 账本（Ledger）

所有资金变动落到 `LedgerEntry` 流水，供事后对账：

```python
@dataclass(frozen=True)
class LedgerEntry:
    dt: datetime
    type: LedgerType    # FILL / FEE / VARIATION_MARGIN / DIVIDEND / TAX / INTEREST / RIGHTS / LIQUIDATION
    symbol: str | None
    amount: Decimal     # 正=流入，负=流出
    strategy_name: str | None
    fill_id: str | None
    note: str | None
```

落 Parquet：`runs/{run_id}/ledger.parquet`。日终断言：

```
total_equity_eod = cash_eod + sum(position.market_value) + ...
                ==
total_equity_bod + sum(ledger.amount within day)
```

不一致直接抛错并终止回测。

## 10. 最小示例

```python
from getrich_backtest.account import Account, MarginPolicy
from decimal import Decimal

acct = Account(
    initial_cash=Decimal("10_000_000"),
    margin_policy=MarginPolicy.from_default_table(),
    base_currency="CNY",
)

# 引擎内部使用，外部只读
print(acct.cash)                 # Decimal('10000000')
print(acct.position("IF2412.CFE"))
print(acct.equity_at(some_dt))   # 历史回看
```

## 11. 设计禁区

- **禁止**用 float 表达 cash / margin / fee / pnl，无例外。
- **禁止**绕开 `Account.apply` 直接改持仓——破坏 ledger 与日终对账。
- **禁止**在策略层计算保证金/可用资金；只通过 `ctx.account` 只读视图。
- **禁止**省略期权到期处理，会导致"持仓凭空消失"。
- **禁止**在 mark-to-market 用当日 close（除非 `bar.dt == day.end`）；强制用结算价 / 上一根 bar close。
