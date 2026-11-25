from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True)
class ReplayDay:
    """已核验的单股日输入。价格未复权，现金及终止价值以每股元表示。

    分红列表为除息日权益（派息日、每股税前金额）。股份倍数包含原股份。
    全天停牌可用已验证的前值估值。日内停牌须另行验证开盘是否可买。
    公司行动覆盖缺失用缺失观测；开盘状态未知用 None，仍可保留可靠的收盘价。
    """

    open_price: Decimal | None
    close_price: Decimal | None
    suspended_at_open: bool | None
    limit_up_at_open: bool | None
    fully_suspended: bool = False
    share_multiplier: Decimal = ONE
    dividends: tuple[tuple[date, Decimal], ...] = ()
    delisted: bool = False
    terminal_value: Decimal | None = None


@dataclass(frozen=True)
class ReplayPoint:
    """交易日收盘持仓估值、现金及应收分红，初始总资产为 1。"""

    day: date
    equity: Decimal
    cash: Decimal
    receivable: Decimal

    @property
    def nav(self) -> Decimal:
        return self.equity + self.cash + self.receivable


@dataclass(frozen=True)
class Unfilled:
    instrument_id: int
    amount_share: Decimal
    reason: str
    waiting_days: int


@dataclass(frozen=True)
class ReplayResult:
    points: tuple[ReplayPoint, ...]
    stopped_on: date | None
    reason: str | None
    instrument_id: int | None
    unexecuted: tuple[Unfilled, ...] = ()


def buy_and_hold(
    weights: Mapping[int, Decimal],
    calendar: Sequence[date],
    observations: Mapping[tuple[int, date], ReplayDay],
) -> ReplayResult:
    """逐日按 PA-12 买入持有。小数股、税前、未扣交易成本，现金不计息。

    calendar 须为按序完整的交易日，缺观测时返回截至前一日的有效净值。
    开盘前已持有股份才享有当日除权息权益，派息日之后首个可买日再投资。
    """
    if not weights or any(not w.is_finite() or w <= 0 for w in weights.values()):
        raise ValueError("Expected positive finite weights")
    if sum(weights.values()) != ONE or not calendar or list(calendar) != sorted(set(calendar)):
        raise ValueError("Expected normalized weights and ordered unique trading days")
    cash = dict(weights)
    shares = dict.fromkeys(weights, ZERO)
    previous: dict[int, Decimal] = {}
    pending: dict[int, dict[date, Decimal]] = {i: defaultdict(Decimal) for i in weights}
    retired: set[int] = set()
    points: list[ReplayPoint] = []
    waiting: dict[int, tuple[str, int]] = {}
    unexecuted: tuple[Unfilled, ...] = ()
    for day in calendar:
        equity = ZERO
        for i in weights:
            if i not in retired:
                bar = observations.get((i, day))
                if bar is None:
                    return ReplayResult(tuple(points), day, "execution_undetermined", i, unexecuted)
                mult = bar.share_multiplier
                if not mult.is_finite() or mult <= 0:
                    raise ValueError("Invalid share multiplier")
                for pay, amount in bar.dividends:
                    if pay < day or not amount.is_finite() or amount < 0:
                        raise ValueError("Invalid dividend entitlement")
                    pending[i][pay] += shares[i] * amount
                shares[i] *= mult
                if bar.delisted:
                    price = bar.terminal_value
                    if price is None or not price.is_finite() or price < 0:
                        return ReplayResult(
                            tuple(points), day, "delisted_no_terminal_value", i, unexecuted
                        )
                    cash[i] += shares[i] * price
                    shares[i] = ZERO
                    retired.add(i)
                    waiting.pop(i, None)
                else:
                    if cash[i] and (bar.suspended_at_open or bar.limit_up_at_open):
                        reason = (
                            "suspended_at_open" if bar.suspended_at_open else "limit_up_at_open"
                        )
                        waiting[i] = (reason, waiting.get(i, (reason, 0))[1] + 1)
                    elif cash[i]:
                        if bar.suspended_at_open is None or bar.limit_up_at_open is None:
                            return ReplayResult(
                                tuple(points), day, "execution_undetermined", i, unexecuted
                            )
                        price = bar.open_price
                        if price is None or not price.is_finite() or price <= 0:
                            return ReplayResult(
                                tuple(points), day, "execution_undetermined", i, unexecuted
                            )
                        shares[i] += cash[i] / price
                        cash[i] = ZERO
                        waiting.pop(i, None)
                    close = bar.close_price
                    if close is None and bar.fully_suspended and i in previous:
                        # 除权除息时，延续估值也要扣除本日已单列的分红并调整股数。
                        close = (previous[i] - sum(a for _, a in bar.dividends)) / mult
                    if close is not None and close.is_finite() and close > 0:
                        previous[i] = close
                        equity += shares[i] * close
                    elif shares[i]:
                        return ReplayResult(
                            tuple(points), day, "valuation_unreliable", i, unexecuted
                        )
            # 非交易日派息在下一交易日开盘前已到账，由下方的日间结转处理。
            cash[i] += pending[i].pop(day, ZERO)
        points.append(
            ReplayPoint(
                day,
                equity,
                sum(cash.values(), ZERO),
                sum((sum(items.values(), ZERO) for items in pending.values()), ZERO),
            )
        )
        unexecuted = tuple(
            Unfilled(i, cash[i] / points[-1].nav, reason, count)
            for i, (reason, count) in waiting.items()
        )
        for i, items in pending.items():
            if len(points) < len(calendar):
                for pay in [p for p in items if p < calendar[len(points)]]:
                    cash[i] += items.pop(pay)
    return ReplayResult(tuple(points), None, None, None, unexecuted)
