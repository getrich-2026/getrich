"""Tests for BacktestTradeWriter — backtest fills → strategy_trades."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from gr_backtest.execution import Fill
from gr_backtest.types import Side
from gr_signal.trade_writer import (
    BacktestTradeWriter,
    _side_to_action,
)


_TZ = ZoneInfo("Asia/Shanghai")
_DT = datetime(2026, 5, 31, 10, 0, tzinfo=_TZ)


def _make_fill(
    fill_id: str = "f1",
    symbol: str = "000001.SZ",
    side: Side = Side.BUY,
    qty: str = "100",
    price: str = "50.00",
    notional: str | None = None,
    fee: str = "5.00",
    slippage: str = "0.01",
    fill_time: datetime | None = None,
    bar_dt: datetime | None = None,
    strategy_name: str = "test_strategy",
) -> Fill:
    ft = fill_time or _DT
    bd = bar_dt or _DT
    n = notional or str(Decimal(qty) * Decimal(price))
    return Fill(
        fill_id=fill_id,
        order_id=f"o_{fill_id}",
        strategy_name=strategy_name,
        symbol=symbol,
        side=side,
        qty=Decimal(qty),
        price=Decimal(price),
        notional=Decimal(n),
        fee=Decimal(fee),
        fill_time=ft,
        bar_dt=bd,
        slippage=Decimal(slippage),
    )


# ---------------------------------------------------------------------------
# Side → action mapping
# ---------------------------------------------------------------------------


class TestSideToAction:
    def test_buy_sides_map_to_buy(self):
        assert _side_to_action(Side.BUY) == "buy"
        assert _side_to_action(Side.OPEN_LONG) == "buy"
        assert _side_to_action(Side.CLOSE_SHORT) == "buy"

    def test_sell_sides_map_to_sell(self):
        assert _side_to_action(Side.SELL) == "sell"
        assert _side_to_action(Side.CLOSE_LONG) == "sell"
        assert _side_to_action(Side.OPEN_SHORT) == "sell"


# ---------------------------------------------------------------------------
# _build_params — AVCO computation
# ---------------------------------------------------------------------------


class TestBuildParams:
    def test_single_buy(self):
        f = _make_fill("f1", "000001.SZ", Side.BUY, "100", "50.00")
        params = BacktestTradeWriter._build_params((f,), "sid-1")

        assert len(params) == 1
        p = params[0]
        assert p["strategy_id"] == "sid-1"
        assert p["symbol"] == "000001.SZ"
        assert p["action"] == "buy"
        assert p["quantity"] == "100"
        assert p["price"] == "50.00"
        assert p["avg_cost"] is None  # no prior position
        assert p["realized_pnl"] == "0"
        assert p["cumulative_pnl"] == "0"
        assert p["signal_id"] is None
        assert p["executed_at"] == _DT
        assert p["bar_dt"] == _DT

    def test_buy_then_sell_profit(self):
        f1 = _make_fill("f1", "000001.SZ", Side.BUY, "100", "50.00")
        f2 = _make_fill("f2", "000001.SZ", Side.SELL, "100", "55.00")
        params = BacktestTradeWriter._build_params((f1, f2), "sid-1")

        assert len(params) == 2
        # Buy: avg_cost=None, realized_pnl=0
        assert params[0]["avg_cost"] is None
        assert params[0]["realized_pnl"] == "0"
        # Sell: avg_cost=50.00, realized_pnl=500
        assert params[1]["avg_cost"] == "50.00"
        assert params[1]["realized_pnl"] == "500.00"
        assert params[1]["cumulative_pnl"] == "500.00"

    def test_buy_then_sell_loss(self):
        f1 = _make_fill("f1", "000001.SZ", Side.BUY, "100", "50.00")
        f2 = _make_fill("f2", "000001.SZ", Side.SELL, "100", "45.00")
        params = BacktestTradeWriter._build_params((f1, f2), "sid-1")

        assert params[1]["avg_cost"] == "50.00"
        assert params[1]["realized_pnl"] == "-500.00"
        assert params[1]["cumulative_pnl"] == "-500.00"

    def test_partial_sell(self):
        f1 = _make_fill("f1", "000001.SZ", Side.BUY, "200", "50.00")
        f2 = _make_fill("f2", "000001.SZ", Side.SELL, "100", "55.00")
        params = BacktestTradeWriter._build_params((f1, f2), "sid-1")

        assert params[1]["realized_pnl"] == "500.00"
        assert params[1]["cumulative_pnl"] == "500.00"

    def test_multi_symbol_isolation(self):
        f_a1 = _make_fill("fa1", "A.SZ", Side.BUY, "100", "10.00")
        f_b1 = _make_fill("fb1", "B.SZ", Side.BUY, "100", "20.00")
        f_a2 = _make_fill("fa2", "A.SZ", Side.SELL, "100", "15.00")
        f_b2 = _make_fill("fb2", "B.SZ", Side.SELL, "100", "18.00")
        fills = (f_a1, f_b1, f_a2, f_b2)
        params = BacktestTradeWriter._build_params(fills, "sid-1")

        # A: profit 500, B: loss 200
        a_sell = [p for p in params if p["symbol"] == "A.SZ" and p["action"] == "sell"]
        b_sell = [p for p in params if p["symbol"] == "B.SZ" and p["action"] == "sell"]
        assert len(a_sell) == 1
        assert len(b_sell) == 1
        assert a_sell[0]["realized_pnl"] == "500.00"
        assert b_sell[0]["realized_pnl"] == "-200.00"

    def test_fills_sorted_by_symbol_then_time(self):
        dt1 = _DT
        dt2 = datetime(2026, 5, 31, 11, 0, tzinfo=_TZ)
        f1 = _make_fill("f1", "B.SZ", Side.BUY, "100", "10.00", fill_time=dt2)
        f2 = _make_fill("f2", "A.SZ", Side.BUY, "100", "10.00", fill_time=dt1)
        params = BacktestTradeWriter._build_params((f1, f2), "sid-1")

        # A.SZ should come first (sorted by symbol)
        assert params[0]["symbol"] == "A.SZ"
        assert params[1]["symbol"] == "B.SZ"

    def test_empty_fills_returns_empty(self):
        params = BacktestTradeWriter._build_params((), "sid-1")
        assert params == []

    def test_cumulative_pnl_accumulates(self):
        f1 = _make_fill("f1", "X.SZ", Side.BUY, "100", "10.00")
        f2 = _make_fill("f2", "X.SZ", Side.SELL, "50", "12.00")
        f3 = _make_fill("f3", "X.SZ", Side.SELL, "50", "8.00")
        fills = (f1, f2, f3)
        params = BacktestTradeWriter._build_params(fills, "sid-1")

        # First sell: profit 100
        assert params[1]["realized_pnl"] == "100.00"
        assert params[1]["cumulative_pnl"] == "100.00"
        # Second sell: loss 100
        assert params[2]["realized_pnl"] == "-100.00"
        assert params[2]["cumulative_pnl"] == "0.00"

    def test_tag_preserved(self):
        f = _make_fill("f1", "000001.SZ", Side.BUY, "100", "50.00")
        f = Fill(
            fill_id=f.fill_id,
            order_id=f.order_id,
            strategy_name=f.strategy_name,
            symbol=f.symbol,
            side=f.side,
            qty=f.qty,
            price=f.price,
            notional=f.notional,
            fee=f.fee,
            fill_time=f.fill_time,
            bar_dt=f.bar_dt,
            slippage=f.slippage,
            tag="my_note",
        )
        params = BacktestTradeWriter._build_params((f,), "sid-1")
        assert params[0]["tag"] == "my_note"

    def test_open_long_close_long(self):
        f1 = _make_fill("f1", "F.SZ", Side.OPEN_LONG, "10", "100.00")
        f2 = _make_fill("f2", "F.SZ", Side.CLOSE_LONG, "10", "110.00")
        params = BacktestTradeWriter._build_params((f1, f2), "sid-1")

        assert params[0]["action"] == "buy"
        assert params[1]["action"] == "sell"
        assert params[1]["realized_pnl"] == "100.00"

    def test_open_short_close_short(self):
        f1 = _make_fill("f1", "F.SZ", Side.OPEN_SHORT, "10", "100.00")
        f2 = _make_fill("f2", "F.SZ", Side.CLOSE_SHORT, "10", "90.00")
        params = BacktestTradeWriter._build_params((f1, f2), "sid-1")

        assert params[0]["action"] == "sell"
        assert params[1]["action"] == "buy"
        # Short: avg_cost=100, cover at 90, profit = (100-90)*10 = 100
        assert params[1]["realized_pnl"] == "100.00"
