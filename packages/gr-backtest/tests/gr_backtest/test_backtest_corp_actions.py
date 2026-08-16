"""Tests for Backtest corporate action integration."""

from datetime import date, datetime
from decimal import Decimal

import polars as pl
from gr_backtest import (
    Backtest,
    BarContext,
    DataFrameBarLoader,
    OrderIntent,
    Strategy,
    get_shanghai_tz,
)
from gr_backtest.types import Side


TZ = get_shanghai_tz()


class TestBacktestCorporateActions:
    def test_dividend_applied_during_backtest(self) -> None:
        """Dividend on ex-date with no position: cash unchanged."""
        bars = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 3, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "A", "A"],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000.0, 1000.0, 1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        corp_actions = pl.DataFrame(
            {
                "symbol": ["A"],
                "ex_date": [date(2026, 6, 2)],
                "action_type": ["dividend"],
                "amount": [0.5],
            },
            schema={
                "symbol": pl.Utf8,
                "ex_date": pl.Date,
                "action_type": pl.Utf8,
                "amount": pl.Float64,
            },
        )

        class NoOp(Strategy):
            @property
            def name(self) -> str:
                return "NoOp"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                return None

        bt = Backtest(
            strategy=NoOp(),
            bar_loader=DataFrameBarLoader(bars, corp_actions_df=corp_actions),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        result = bt.run()
        assert result.final_account.cash == Decimal("100000")

    def test_dividend_with_position(self) -> None:
        """Dividend on held position increases cash."""
        bars = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 6, 3, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "A", "A"],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000.0, 1000.0, 1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        corp_actions = pl.DataFrame(
            {
                "symbol": ["A"],
                "ex_date": [date(2026, 6, 2)],
                "action_type": ["dividend"],
                "amount": [1.0],
            },
            schema={
                "symbol": pl.Utf8,
                "ex_date": pl.Date,
                "action_type": pl.Utf8,
                "amount": pl.Float64,
            },
        )

        class BuyAndHold(Strategy):
            def __init__(self) -> None:
                super().__init__()
                self.bought = False

            @property
            def name(self) -> str:
                return "BuyAndHold"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                if not self.bought:
                    self.bought = True
                    return [OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))]
                return None

        bt = Backtest(
            strategy=BuyAndHold(),
            bar_loader=DataFrameBarLoader(bars, corp_actions_df=corp_actions),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 4, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        result = bt.run()
        # Order placed on bar 0, fills on bar 1 at open=101.0 (next bar matching)
        # Cash after fill: 100000 - (100 * 101.0) = 100000 - 10100 = 89900
        # Dividend on bar 1 ex-date: 100 shares * 1.0 * (1 - 0.10) = 90
        # Cash after dividend: 89900 + 90 = 89990
        assert result.final_account.cash == Decimal("89990")

    def test_corp_actions_accessible_in_strategy(self) -> None:
        """Corporate actions accessible via ctx.corp_actions in on_bar."""
        bars = pl.DataFrame(
            {
                "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
                "symbol": ["A"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        corp_actions = pl.DataFrame(
            {
                "symbol": ["A"],
                "ex_date": [date(2026, 6, 1)],
                "action_type": ["dividend"],
                "amount": [0.5],
            },
            schema={
                "symbol": pl.Utf8,
                "ex_date": pl.Date,
                "action_type": pl.Utf8,
                "amount": pl.Float64,
            },
        )

        captured = None

        class CheckCorpActions(Strategy):
            @property
            def name(self) -> str:
                return "CheckCorpActions"

            def on_bar(self, ctx: BarContext) -> list[OrderIntent] | None:
                nonlocal captured
                captured = ctx.corp_actions
                return None

        bt = Backtest(
            strategy=CheckCorpActions(),
            bar_loader=DataFrameBarLoader(bars, corp_actions_df=corp_actions),
            symbols=["A"],
            start=datetime(2026, 6, 1, tzinfo=TZ),
            end=datetime(2026, 6, 2, tzinfo=TZ),
            initial_cash=Decimal("100000"),
        )
        bt.run()
        assert captured is not None
        assert not captured.is_empty()
