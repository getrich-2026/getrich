from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from gr_api.diagnosis_calc.replay import ReplayDay, buy_and_hold


def test_buy_and_hold_dividend_and_delisting() -> None:
    days = [date(2026, 11, 16) + timedelta(days=i) for i in range(5)]
    ten, nine = Decimal(10), Decimal(9)
    bars = [
        ReplayDay(ten, ten, False, False),
        ReplayDay(nine, nine, False, False, dividends=((days[2], Decimal(1)),)),
        ReplayDay(nine, nine, False, False),
        ReplayDay(nine, ten, False, False),
        ReplayDay(None, None, False, False, delisted=True),
    ]
    result = buy_and_hold(
        {1: Decimal(1)}, days, {(1, d): b for d, b in zip(days, bars, strict=True)}
    )
    first, ex_day, pay_day, reinvest = result.points
    assert first.nav == ex_day.nav == pay_day.nav == 1
    assert ex_day.receivable == pay_day.cash == Decimal("0.1")
    assert reinvest.cash == 0 and reinvest.nav == (Decimal("0.1") + Decimal("0.1") / nine) * ten
    assert (result.stopped_on, result.reason) == (days[-1], "delisted_no_terminal_value")


def test_suspended_cash_is_reserved_and_open_limit_is_respected() -> None:
    days = [date(2026, 11, 16) + timedelta(days=i) for i in range(3)]
    price = Decimal(10)
    series = [
        ReplayDay(None, None, True, False, fully_suspended=True),
        ReplayDay(price, price, False, True),
        ReplayDay(price, 2 * price, False, False),
    ]
    result = buy_and_hold(
        {1: Decimal("0.4"), 2: Decimal("0.6")},
        days,
        {
            **{(1, d): b for d, b in zip(days, series, strict=True)},
            **{(2, d): ReplayDay(price, price, False, False) for d in days},
        },
    )
    assert [p.cash for p in result.points] == [Decimal("0.4"), Decimal("0.4"), 0]
    assert result.points[-1].nav == Decimal("1.4")


def test_missing_observation_truncates_without_publishing_partial_day() -> None:
    days = [date(2026, 11, 16), date(2026, 11, 17)]
    bar = ReplayDay(Decimal(10), Decimal(10), False, False)
    result = buy_and_hold({1: Decimal(1)}, days, {(1, days[0]): bar})
    assert [p.day for p in result.points] == days[:1]
    assert (result.stopped_on, result.reason) == (days[1], "execution_undetermined")


def test_unknown_open_preserves_real_close_until_dividend_cash_needs_execution() -> None:
    days = [date(2026, 11, 16) + timedelta(days=i) for i in range(3)]
    bars = [
        ReplayDay(Decimal(10), Decimal(10), False, False),
        ReplayDay(None, Decimal(12), None, None, dividends=((days[1], Decimal(1)),)),
        ReplayDay(Decimal(11), Decimal(11), None, False),
    ]
    result = buy_and_hold(
        {1: Decimal(1)}, days, dict(zip(((1, d) for d in days), bars, strict=True))
    )
    assert result.points[-1].nav == Decimal("1.3")
    assert result.points[-1].cash == Decimal("0.1")
    assert (result.stopped_on, result.reason) == (days[-1], "execution_undetermined")
