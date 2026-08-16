"""Tests for trade journal and attribution computations."""

from datetime import datetime
from decimal import Decimal

import numpy as np
import polars as pl
import pytest
from gr_backtest import (
    DEFAULT_FUTURES_SESSIONS,
    AttributionError,
    FactorExposure,
    FactorRegResult,
    Fill,
    Session,
    SessionAttributionResult,
    SessionStats,
    Side,
    compute_brinson_attribution,
    compute_cost_attribution,
    compute_factor_regression,
    compute_pnl_attribution,
    compute_session_attribution,
    compute_trade_journal,
    get_shanghai_tz,
)
from gr_backtest.attribution import _classify_session


TZ = get_shanghai_tz()


def _fill(
    fill_id: str = "f1",
    symbol: str = "A",
    side: Side = Side.BUY,
    qty: Decimal = Decimal("100"),
    price: Decimal = Decimal("100"),
    fee: Decimal = Decimal("0"),
    slippage: Decimal = Decimal("0"),
    fill_time: datetime | None = None,
    strategy_name: str = "TestStrategy",
) -> Fill:
    if fill_time is None:
        fill_time = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
    return Fill(
        fill_id=fill_id,
        order_id=fill_id,
        strategy_name=strategy_name,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        notional=qty * price,
        fee=fee,
        slippage=slippage,
        fill_time=fill_time,
        bar_dt=fill_time,
        tag=None,
    )


class TestTradeJournal:
    def test_structure(self) -> None:
        """Trade journal has expected columns and types."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        fills = (
            _fill("f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fill_time=t1),
            _fill("f2", "A", Side.SELL, Decimal("100"), Decimal("110"), fill_time=t2),
        )
        journal = compute_trade_journal(fills)

        assert journal.height == 2
        expected_cols = [
            "fill_id",
            "symbol",
            "side",
            "qty",
            "price",
            "fee",
            "slippage",
            "fill_time",
            "strategy_name",
            "avg_cost_at_trade",
            "realized_pnl",
            "cumulative_realized_pnl",
        ]
        for col in expected_cols:
            assert col in journal.columns, f"Missing column: {col}"

    def test_pnl_simple_profit(self) -> None:
        """BUY 100@100, SELL 100@110 → realized PnL = 1000."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        fills = (
            _fill("f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fill_time=t1),
            _fill("f2", "A", Side.SELL, Decimal("100"), Decimal("110"), fill_time=t2),
        )
        journal = compute_trade_journal(fills)

        # BUY has 0 realized PnL
        buy_row = journal.filter(pl.col("side") == "BUY")
        assert buy_row["realized_pnl"][0] == 0.0

        # SELL has profit of (110 - 100) * 100 = 1000
        sell_row = journal.filter(pl.col("side") == "SELL")
        assert sell_row["realized_pnl"][0] == pytest.approx(1000.0, rel=1e-10)

        # Avg cost at trade for SELL should be 100
        assert sell_row["avg_cost_at_trade"][0] == pytest.approx(100.0, rel=1e-10)

    def test_pnl_loss(self) -> None:
        """BUY 100@100, SELL 100@90 → realized PnL = -1000."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        fills = (
            _fill("f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fill_time=t1),
            _fill("f2", "A", Side.SELL, Decimal("100"), Decimal("90"), fill_time=t2),
        )
        journal = compute_trade_journal(fills)
        sell_row = journal.filter(pl.col("side") == "SELL")
        assert sell_row["realized_pnl"][0] == pytest.approx(-1000.0, rel=1e-10)

    def test_multiple_buys_averaging(self) -> None:
        """BUY 100@100, BUY 100@120 → avg_cost = 110, SELL 200@115 → PnL = 1000."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        t3 = datetime(2026, 1, 6, 9, 30, tzinfo=TZ)
        fills = (
            _fill("f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fill_time=t1),
            _fill("f2", "A", Side.BUY, Decimal("100"), Decimal("120"), fill_time=t2),
            _fill("f3", "A", Side.SELL, Decimal("200"), Decimal("115"), fill_time=t3),
        )
        journal = compute_trade_journal(fills)

        # Avg cost after two BUYs: (10000 + 12000) / 200 = 110
        sell_row = journal.filter(pl.col("side") == "SELL")
        assert sell_row["avg_cost_at_trade"][0] == pytest.approx(110.0, rel=1e-10)

        # PnL: (115 - 110) * 200 = 1000
        assert sell_row["realized_pnl"][0] == pytest.approx(1000.0, rel=1e-10)

    def test_partial_sell(self) -> None:
        """BUY 200@100, SELL 100@110 → PnL = 1000, remaining qty = 100."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        fills = (
            _fill("f1", "A", Side.BUY, Decimal("200"), Decimal("100"), fill_time=t1),
            _fill("f2", "A", Side.SELL, Decimal("100"), Decimal("110"), fill_time=t2),
        )
        journal = compute_trade_journal(fills)

        sell_row = journal.filter(pl.col("side") == "SELL")
        # Avg cost is still 100
        assert sell_row["avg_cost_at_trade"][0] == pytest.approx(100.0, rel=1e-10)
        # PnL: (110 - 100) * 100 = 1000
        assert sell_row["realized_pnl"][0] == pytest.approx(1000.0, rel=1e-10)

    def test_cumulative_pnl(self) -> None:
        """Cumulative realized PnL tracks running total per symbol."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        t3 = datetime(2026, 1, 6, 9, 30, tzinfo=TZ)
        fills = (
            _fill("f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fill_time=t1),
            _fill("f2", "A", Side.SELL, Decimal("50"), Decimal("110"), fill_time=t2),
            _fill("f3", "A", Side.SELL, Decimal("50"), Decimal("90"), fill_time=t3),
        )
        journal = compute_trade_journal(fills)

        # After first SELL: (110-100)*50 = 500 → cumulative = 500
        # After second SELL: (90-100)*50 = -500 → cumulative = 0
        cum = journal["cumulative_realized_pnl"].to_list()
        assert cum[0] == 0.0  # BUY has 0 pnl
        assert cum[1] == pytest.approx(500.0, rel=1e-10)
        assert cum[2] == pytest.approx(0.0, rel=1e-10)

    def test_empty_fills_raises(self) -> None:
        """Empty fills raises AttributionError."""
        with pytest.raises(AttributionError, match="must not be empty"):
            compute_trade_journal(())

    def test_multiple_symbols(self) -> None:
        """Fills for multiple symbols are handled correctly."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        fills = (
            _fill("f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fill_time=t1),
            _fill("f2", "B", Side.BUY, Decimal("50"), Decimal("200"), fill_time=t1),
            _fill("f3", "A", Side.SELL, Decimal("100"), Decimal("110"), fill_time=t2),
            _fill("f4", "B", Side.SELL, Decimal("50"), Decimal("180"), fill_time=t2),
        )
        journal = compute_trade_journal(fills)

        assert journal.height == 4

        # A profit: (110-100)*100 = 1000
        # B loss: (180-200)*50 = -1000
        a_sells = journal.filter((pl.col("symbol") == "A") & (pl.col("side") == "SELL"))
        b_sells = journal.filter((pl.col("symbol") == "B") & (pl.col("side") == "SELL"))
        assert a_sells["realized_pnl"][0] == pytest.approx(1000.0, rel=1e-10)
        assert b_sells["realized_pnl"][0] == pytest.approx(-1000.0, rel=1e-10)


class TestCostAttribution:
    def test_by_symbol(self) -> None:
        """Cost attribution aggregates fee and slippage by symbol."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        fills = (
            _fill(
                "f1",
                "A",
                Side.BUY,
                Decimal("100"),
                Decimal("100"),
                fee=Decimal("10"),
                slippage=Decimal("5"),
                fill_time=t1,
            ),
            _fill(
                "f2",
                "A",
                Side.SELL,
                Decimal("100"),
                Decimal("110"),
                fee=Decimal("10"),
                slippage=Decimal("5"),
                fill_time=t2,
            ),
            _fill(
                "f3",
                "B",
                Side.BUY,
                Decimal("50"),
                Decimal("200"),
                fee=Decimal("5"),
                slippage=Decimal("2"),
                fill_time=t1,
            ),
            _fill(
                "f4",
                "B",
                Side.SELL,
                Decimal("50"),
                Decimal("180"),
                fee=Decimal("0"),
                slippage=Decimal("0"),
                fill_time=t2,
            ),
        )
        cost = compute_cost_attribution(fills)

        assert cost.height == 2
        a_row = cost.filter(pl.col("symbol") == "A")
        b_row = cost.filter(pl.col("symbol") == "B")

        # A: total_fee = 20, total_slippage = 10, total_cost = 30
        assert a_row["total_fee"][0] == pytest.approx(20.0, rel=1e-10)
        assert a_row["total_slippage"][0] == pytest.approx(10.0, rel=1e-10)
        assert a_row["total_cost"][0] == pytest.approx(30.0, rel=1e-10)
        assert a_row["n_fills"][0] == 2

        # B: total_fee = 5, total_slippage = 2, total_cost = 7
        assert b_row["total_fee"][0] == pytest.approx(5.0, rel=1e-10)
        assert b_row["total_slippage"][0] == pytest.approx(2.0, rel=1e-10)

    def test_empty_raises(self) -> None:
        """Empty fills raises AttributionError."""
        with pytest.raises(AttributionError):
            compute_cost_attribution(())

    def test_fee_rate_bps(self) -> None:
        """Fee rate in bps is computed correctly."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        fills = (
            _fill(
                "f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fee=Decimal("5"), fill_time=t1
            ),
        )
        cost = compute_cost_attribution(fills)
        # notional = 100 * 100 = 10000, fee = 5
        # fee_rate_bps = 5 / 10000 * 10000 = 5
        assert cost["fee_rate_bps"][0] == pytest.approx(5.0, rel=1e-10)


class TestPnlAttribution:
    def test_by_symbol(self) -> None:
        """PnL attribution aggregates realized PnL by symbol."""
        t1 = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        t2 = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        fills = (
            _fill(
                "f1", "A", Side.BUY, Decimal("100"), Decimal("100"), fee=Decimal("10"), fill_time=t1
            ),
            _fill(
                "f2",
                "A",
                Side.SELL,
                Decimal("100"),
                Decimal("110"),
                fee=Decimal("10"),
                fill_time=t2,
            ),
            _fill(
                "f3", "B", Side.BUY, Decimal("50"), Decimal("200"), fee=Decimal("5"), fill_time=t1
            ),
            _fill(
                "f4", "B", Side.SELL, Decimal("50"), Decimal("180"), fee=Decimal("0"), fill_time=t2
            ),
        )
        pnl = compute_pnl_attribution(fills)

        assert pnl.height == 2
        a_row = pnl.filter(pl.col("symbol") == "A")
        b_row = pnl.filter(pl.col("symbol") == "B")

        # A: realized_pnl = (110-100)*100 = 1000, fees = 20, net = 980
        assert a_row["total_realized_pnl"][0] == pytest.approx(1000.0, rel=1e-10)
        assert a_row["total_fee"][0] == pytest.approx(20.0, rel=1e-10)
        assert a_row["net_pnl"][0] == pytest.approx(980.0, rel=1e-10)
        assert a_row["n_trades"][0] == 1

        # B: realized_pnl = (180-200)*50 = -1000, fees = 5, net = -1005
        assert b_row["total_realized_pnl"][0] == pytest.approx(-1000.0, rel=1e-10)
        assert b_row["net_pnl"][0] == pytest.approx(-1005.0, rel=1e-10)

    def test_empty_raises(self) -> None:
        """Empty fills raises AttributionError."""
        with pytest.raises(AttributionError):
            compute_pnl_attribution(())


class TestBrinsonAttribution:
    """Tests for Brinson industry attribution."""

    def _make_data(
        self,
        symbols: list[str] = ("A", "B"),
        industries: list[str] = ("Tech", "Health"),
        prices_a: list[float] = (100.0, 102.0, 104.0),
        prices_b: list[float] = (200.0, 198.0, 202.0),
        trades: list[tuple] | None = None,
    ) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
        """Create test data for Brinson attribution.

        Returns (trade_journal, close_prices, classifications).
        Default: 3 periods, 2 symbols, 2 industries.
        """
        dts = [
            datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
            datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
            datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
        ]

        close_prices = pl.DataFrame(
            {
                "dt": [dts[0], dts[1], dts[2], dts[0], dts[1], dts[2]],
                "symbol": [symbols[0]] * 3 + [symbols[1]] * 3,
                "close": [
                    prices_a[0],
                    prices_a[1],
                    prices_a[2],
                    prices_b[0],
                    prices_b[1],
                    prices_b[2],
                ],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        classifications = pl.DataFrame(
            {
                "symbol": symbols,
                "industry_l1": industries,
            }
        )

        if trades is None:
            # Default: BUY 100 shares of each at first bar
            trades = [
                ("f1", symbols[0], Side.BUY, Decimal("100"), Decimal(str(prices_a[0])), dts[0]),
                ("f2", symbols[1], Side.BUY, Decimal("100"), Decimal(str(prices_b[0])), dts[0]),
            ]

        journal_rows = []
        for tid, sym, side, qty, price, dt in trades:
            journal_rows.append(
                {
                    "fill_id": tid,
                    "order_id": tid,
                    "symbol": sym,
                    "side": "BUY" if side == Side.BUY else "SELL",
                    "qty": float(qty),
                    "price": float(price),
                    "notional": float(qty * price),
                    "fee": 0.0,
                    "slippage": 0.0,
                    "fill_time": dt,
                    "bar_dt": dt,
                    "strategy_name": "Test",
                    "tag": None,
                    "avg_cost_at_trade": float(price),
                    "realized_pnl": 0.0,
                }
            )

        trade_journal = pl.DataFrame(journal_rows)

        return trade_journal, close_prices, classifications

    def test_allocation_only(self) -> None:
        """Same industry returns, different weights → allocation > 0."""
        tj, cp, cl = self._make_data(
            symbols=["A", "B"],
            industries=["Tech", "Health"],
            prices_a=[100.0, 102.0, 104.0],  # 2% return each period
            prices_b=[200.0, 204.0, 208.08],  # 2% return each period
            trades=[
                # Only invest in A (Tech), skip B (Health)
                (
                    "f1",
                    "A",
                    Side.BUY,
                    Decimal("100"),
                    Decimal("100"),
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                ),
            ],
        )

        bm_weights = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "B", "A", "B", "A", "B"],
                "weight": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            }
        )

        result = compute_brinson_attribution(tj, cp, cl, bm_weights)

        assert result.height > 0
        assert "allocation" in result.columns

        # Tech should have positive allocation (overweighted in 2% return industry)
        tech = result.filter(pl.col("industry_l1") == "Tech").select(pl.col("allocation").sum())
        health = result.filter(pl.col("industry_l1") == "Health").select(pl.col("allocation").sum())
        assert tech[0, 0] > 0  # Overweighted in performing industry
        assert health[0, 0] < 0  # Underweighted

    def test_selection_only(self) -> None:
        """Same weights, different returns → selection > 0."""
        tj, cp, cl = self._make_data(
            symbols=["A", "B"],
            industries=["Tech", "Tech"],  # Same industry!
            prices_a=[100.0, 105.0, 110.0],  # 5% returns
            prices_b=[200.0, 202.0, 204.0],  # 1% returns
        )

        # Equal weight benchmark
        bm_weights = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "B", "A", "B", "A", "B"],
                "weight": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            }
        )

        result = compute_brinson_attribution(tj, cp, cl, bm_weights)

        # Same industry, so allocation should be 0
        # Selection exists because A outperforms B
        tech = result.filter(pl.col("industry_l1") == "Tech")
        assert tech["selection"].abs().sum() > 0
        assert tech["allocation"].abs().sum() < 0.001

    def test_two_industries(self) -> None:
        """Full Brinson decomposition with 2 industries and custom weights."""
        tj, cp, cl = self._make_data(
            symbols=["A", "B"],
            industries=["Tech", "Health"],
            prices_a=[100.0, 103.0, 106.09],  # 3% each period
            prices_b=[200.0, 204.0, 208.08],  # 2% each period
        )

        bm_weights = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "B", "A", "B", "A", "B"],
                "weight": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            }
        )

        result = compute_brinson_attribution(tj, cp, cl, bm_weights)

        assert result.height > 0
        for col in ["allocation", "selection", "interaction", "active_return"]:
            assert col in result.columns

    def test_equal_weight_default(self) -> None:
        """No benchmark_weights → equal-weight fallback works."""
        tj, cp, cl = self._make_data(
            symbols=["A", "B"],
            industries=["Tech", "Health"],
            prices_a=[100.0, 102.0, 104.0],
            prices_b=[200.0, 204.0, 208.08],
        )

        result = compute_brinson_attribution(tj, cp, cl)

        assert result.height > 0
        assert result["benchmark_weight"].min() > 0  # all have weights
        assert result["benchmark_weight"].max() > 0

    def test_empty_journal_raises(self) -> None:
        """Empty trade journal columns raise error."""
        dts = [
            datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
            datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
        ]
        cp = pl.DataFrame(
            {"dt": dts, "symbol": ["A", "A"], "close": [100.0, 102.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        cl = pl.DataFrame({"symbol": ["A"], "industry_l1": ["Tech"]})
        tj = pl.DataFrame({"x": [1]})  # missing required columns

        with pytest.raises(AttributionError, match="missing columns"):
            compute_brinson_attribution(tj, cp, cl)

    def test_active_return_sum(self) -> None:
        """Allocation + Selection + Interaction = Active Return per row."""
        tj, cp, cl = self._make_data(
            symbols=["A", "B"],
            industries=["Tech", "Health"],
            prices_a=[100.0, 105.0, 110.0],
            prices_b=[200.0, 195.0, 190.0],
        )

        bm_weights = pl.DataFrame(
            {
                "dt": [
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 2, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 3, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                    datetime(2026, 1, 6, 9, 30, tzinfo=TZ),
                ],
                "symbol": ["A", "B", "A", "B", "A", "B"],
                "weight": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            }
        )

        result = compute_brinson_attribution(tj, cp, cl, bm_weights)

        # For each row: allocation + selection + interaction ≈ active_return
        for r in result.iter_rows(named=True):
            expected = r["allocation"] + r["selection"] + r["interaction"]
            assert abs(r["active_return"] - expected) < 1e-10


class TestFactorRegression:
    """Tests for factor regression attribution."""

    def _make_factor_data(
        self,
        n_periods: int = 10,
        n_stocks: int = 20,
        n_factors: int = 1,
        seed: int = 42,
    ) -> tuple[pl.DataFrame, dict[str, pl.DataFrame], pl.DataFrame]:
        """Create synthetic factor regression test data.

        Returns (equity_curve, factors_dict, close_prices).

        Factor values are random uniform. Close prices are random walks
        whose returns are driven by common factor return series scaled by
        each stock's factor value. The strategy returns likewise load on
        the common factor, guaranteeing a measurable R².
        """
        rng = np.random.default_rng(seed)
        tz = get_shanghai_tz()
        base = datetime(2026, 1, 2, 9, 30, tzinfo=tz)

        dts = [base]
        for i in range(1, n_periods):
            dts.append(datetime(2026, 1, 2 + i, 9, 30, tzinfo=tz))

        symbols = [f"STOCK_{i:03d}" for i in range(n_stocks)]

        # Generate factor values: constant per symbol across time (so quantile
        # membership is stable and the factor portfolio consistently loads on
        # the common factor return).
        symbol_fv: dict[str, float] = {}
        for _s_idx, sym in enumerate(symbols):
            symbol_fv[sym] = rng.uniform(-1.0, 1.0)

        factors: dict[str, pl.DataFrame] = {}
        for f_idx in range(n_factors):
            rows = []
            for dt in dts:
                for sym in symbols:
                    rows.append({"dt": dt, "symbol": sym, "value": symbol_fv[sym]})
            factors[f"factor_{f_idx}"] = pl.DataFrame(
                rows,
                schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
            )

        # Generate common factor return series (one per period t=1..n_periods-1)
        n_returns = n_periods - 1
        f_ret = rng.normal(0.002, 0.025, n_returns)

        # Build close prices so stock returns load on the common factor
        close_rows = []
        base_prices = 100.0 + rng.uniform(0, 50, n_stocks)
        for dt_idx, dt in enumerate(dts):
            for s_idx, sym in enumerate(symbols):
                fv = symbol_fv[sym]
                if dt_idx == 0:
                    price = base_prices[s_idx]
                else:
                    # stock return = 0.05 * factor_value * f_ret + noise
                    ret = 0.05 * fv * f_ret[dt_idx - 1] + 0.002 * rng.normal(0, 1)
                    # Use absolute index to find previous period's price for this stock
                    prev_idx = (dt_idx - 1) * n_stocks + s_idx
                    price = close_rows[prev_idx]["close"] * (1.0 + ret)
                close_rows.append({"dt": dt, "symbol": sym, "close": price})

        close_prices = pl.DataFrame(
            close_rows,
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        # Strategy equity curve: also loads on the same common factor
        # Strategy return = 0.03 * f_ret + 0.003 * noise
        eq_vals = [100000.0]
        for t in range(n_returns):
            strat_ret = 0.3 * f_ret[t] + 0.003 * rng.normal(0, 1)
            eq_vals.append(eq_vals[-1] * (1.0 + strat_ret))

        equity_curve = pl.DataFrame(
            {"dt": dts, "equity": eq_vals},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        return equity_curve, factors, close_prices

    def test_factor_exposure_dataclass(self) -> None:
        """FactorExposure is frozen and has to_dict."""
        fe = FactorExposure(
            name="momentum",
            beta=Decimal("0.5"),
            t_stat=Decimal("2.3"),
            p_value=Decimal("0.01"),
            contribution_pnl=Decimal("5000"),
        )
        with pytest.raises(AttributeError):
            fe.beta = Decimal("0.99")  # type: ignore[misc]

        d = fe.to_dict()
        assert d["name"] == "momentum"
        assert d["beta"] == "0.5"

    def test_factor_reg_result_dataclass(self) -> None:
        """FactorRegResult is frozen and has to_dict."""
        fe = FactorExposure(
            name="size",
            beta=Decimal("0.3"),
            t_stat=Decimal("1.8"),
            p_value=Decimal("0.05"),
            contribution_pnl=Decimal("3000"),
        )
        fr = FactorRegResult(
            alpha=Decimal("0.01"),
            alpha_tstat=Decimal("1.2"),
            r_squared=Decimal("0.8"),
            adj_r_squared=Decimal("0.75"),
            n_periods=100,
            factors=(fe,),
        )
        d = fr.to_dict()
        assert d["alpha"] == "0.01"
        assert d["r_squared"] == "0.8"
        assert len(d["factors"]) == 1

    def test_single_factor_high_r_squared(self) -> None:
        """Strategy driven by single factor → high R², beta near 1."""
        eq, factors, cp = self._make_factor_data(n_periods=20, n_stocks=30, seed=42)
        result = compute_factor_regression(
            eq,
            cp,
            factors,
            ["factor_0"],
            initial_cash=Decimal("100000"),
            n_quantiles=5,
        )

        assert result.r_squared > Decimal("0.3")
        assert result.n_periods >= 15
        assert len(result.factors) == 1
        assert result.factors[0].name == "factor_0"

    def test_two_factors(self) -> None:
        """Two factors produce stable results."""
        eq, factors, cp = self._make_factor_data(n_periods=30, n_stocks=30, n_factors=2, seed=123)
        result = compute_factor_regression(
            eq,
            cp,
            factors,
            ["factor_0", "factor_1"],
            initial_cash=Decimal("100000"),
        )

        assert len(result.factors) == 2
        assert result.r_squared > Decimal("0")

    def test_empty_factor_names_raises(self) -> None:
        """Empty factor_names raises AttributionError."""
        eq = pl.DataFrame(
            {"dt": [datetime(2026, 1, 2, 9, 30, tzinfo=TZ)], "equity": [100000.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        cp = pl.DataFrame(
            {"dt": [datetime(2026, 1, 2, 9, 30, tzinfo=TZ)], "symbol": ["A"], "close": [100.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        with pytest.raises(AttributionError, match="must not be empty"):
            compute_factor_regression(eq, cp, {}, [])

    def test_missing_factor_raises(self) -> None:
        """Requesting non-existent factor raises AttributionError."""
        eq = pl.DataFrame(
            {"dt": [datetime(2026, 1, 2, 9, 30, tzinfo=TZ)], "equity": [100000.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        cp = pl.DataFrame(
            {"dt": [datetime(2026, 1, 2, 9, 30, tzinfo=TZ)], "symbol": ["A"], "close": [100.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        with pytest.raises(AttributionError, match="not found"):
            compute_factor_regression(eq, cp, {}, ["momentum"])


class TestSessionAttribution:
    """Tests for session attribution."""

    def _make_eq_curve(
        self,
        n_per_session: int = 3,
        seed: int = 42,
    ) -> pl.DataFrame:
        """Create synthetic equity curve with known session timestamps.

        Produces bars at 10:00 (morning), 14:00 (afternoon), 22:00 (night),
        and 01:00 (night spanning midnight) for each of ``n_per_session``
        days.  Returns follow a small random walk so each session has
        some variation.
        """
        rng = np.random.default_rng(seed)
        tz = get_shanghai_tz()
        dts: list[datetime] = []
        for day in range(n_per_session):
            dts.append(datetime(2026, 1, 5 + day, 10, 0, tzinfo=tz))  # morning
            dts.append(datetime(2026, 1, 5 + day, 14, 0, tzinfo=tz))  # afternoon
            dts.append(datetime(2026, 1, 5 + day, 22, 0, tzinfo=tz))  # night (pre-midnight)
            dts.append(datetime(2026, 1, 6 + day, 1, 0, tzinfo=tz))  # night (post-midnight)
        dts.sort()
        n = len(dts)
        eq_vals = [100000.0]
        for _i in range(1, n):
            eq_vals.append(eq_vals[-1] * (1.0 + rng.normal(0.001, 0.01)))
        return pl.DataFrame(
            {"dt": dts, "equity": eq_vals},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

    def test_session_dataclass(self) -> None:
        """Session is frozen and to_dict works."""
        s = Session("night", 21, 0, 2, 30, spans_midnight=True)
        with pytest.raises(AttributeError):
            s.spans_midnight = False  # type: ignore[misc]
        d = s.to_dict()
        assert d["name"] == "night"
        assert d["start_hour"] == 21
        assert d["spans_midnight"] is True

    def test_session_stats_dataclass(self) -> None:
        """SessionStats is frozen and to_dict converts Decimal to str."""
        ss = SessionStats(
            name="morning",
            count=10,
            total_return=Decimal("0.05"),
            mean_return=Decimal("0.005"),
            std_return=Decimal("0.02"),
            sharpe=Decimal("0.25"),
            win_rate=Decimal("0.6"),
            contribution_pnl=Decimal("5000"),
        )
        d = ss.to_dict()
        assert d["name"] == "morning"
        assert d["count"] == 10
        assert d["total_return"] == "0.05"
        assert d["contribution_pnl"] == "5000"

    def test_session_attr_result_dataclass(self) -> None:
        """SessionAttributionResult is frozen and to_dict structure."""
        ss = SessionStats(
            name="night",
            count=5,
            total_return=Decimal("0.02"),
            mean_return=Decimal("0.004"),
            std_return=Decimal("0.01"),
            sharpe=Decimal("0.4"),
            win_rate=Decimal("0.6"),
            contribution_pnl=Decimal("2000"),
        )
        r = SessionAttributionResult(
            sessions=(ss,),
            total_periods=20,
            unclassified_count=2,
        )
        d = r.to_dict()
        assert len(d["sessions"]) == 1
        assert d["total_periods"] == 20
        assert d["unclassified_count"] == 2
        assert d["sessions"][0]["name"] == "night"

    def test_classify_morning(self) -> None:
        """dt at 10:00 classifies as morning."""
        tz = get_shanghai_tz()
        dt = datetime(2026, 1, 5, 10, 30, tzinfo=tz)
        result = _classify_session(dt, DEFAULT_FUTURES_SESSIONS)
        assert result == "morning"

    def test_classify_afternoon(self) -> None:
        """dt at 14:00 classifies as afternoon."""
        tz = get_shanghai_tz()
        dt = datetime(2026, 1, 5, 14, 0, tzinfo=tz)
        result = _classify_session(dt, DEFAULT_FUTURES_SESSIONS)
        assert result == "afternoon"

    def test_classify_night_midnight(self) -> None:
        """dt at 22:00 AND dt at 01:00 both classify as night."""
        tz = get_shanghai_tz()
        dt1 = datetime(2026, 1, 5, 22, 0, tzinfo=tz)
        dt2 = datetime(2026, 1, 6, 1, 30, tzinfo=tz)
        assert _classify_session(dt1, DEFAULT_FUTURES_SESSIONS) == "night"
        assert _classify_session(dt2, DEFAULT_FUTURES_SESSIONS) == "night"

    def test_classify_session_boundaries(self) -> None:
        """Session boundaries are half-open: start inclusive, end exclusive."""
        tz = get_shanghai_tz()
        sess = DEFAULT_FUTURES_SESSIONS
        # 09:30 is morning (start inclusive)
        assert _classify_session(datetime(2026, 1, 5, 9, 30, tzinfo=tz), sess) == "morning"
        # 11:30 is NOT morning (end exclusive)
        assert _classify_session(datetime(2026, 1, 5, 11, 30, tzinfo=tz), sess) != "morning"
        # 21:00 is night (start inclusive)
        assert _classify_session(datetime(2026, 1, 5, 21, 0, tzinfo=tz), sess) == "night"
        # 02:30 is NOT night (end exclusive)
        assert _classify_session(datetime(2026, 1, 6, 2, 30, tzinfo=tz), sess) != "night"

    def test_returns_by_session(self) -> None:
        """Returns are correctly distributed across sessions."""
        eq = self._make_eq_curve(n_per_session=3, seed=42)
        result = compute_session_attribution(eq)

        assert result.total_periods == eq.height - 1  # first row dropped
        assert len(result.sessions) == 3  # night, morning, afternoon
        session_names = {s.name for s in result.sessions}
        assert session_names == {"night", "morning", "afternoon"}

        # Each session should have 3 bars (one per day)
        total_count = sum(s.count for s in result.sessions)
        assert total_count == result.total_periods - result.unclassified_count

    def test_unclassified_periods(self) -> None:
        """dt outside all sessions -> unclassified_count > 0.

        Note: the FIRST row of equity_curve is always dropped by
        _compute_strategy_returns (shift produces null return), so we
        need 4+ rows to have an unclassified return survive.
        """
        tz = get_shanghai_tz()
        dts = [
            datetime(2026, 1, 5, 10, 0, tzinfo=tz),  # morning (dropped, first row)
            datetime(2026, 1, 5, 4, 0, tzinfo=tz),  # outside any session (unclassified)
            datetime(2026, 1, 5, 10, 30, tzinfo=tz),  # morning (classified)
            datetime(2026, 1, 5, 14, 0, tzinfo=tz),  # afternoon (classified)
        ]
        eq = pl.DataFrame(
            {"dt": dts, "equity": [100000.0, 100500.0, 101000.0, 101500.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        result = compute_session_attribution(eq)
        assert result.unclassified_count == 1

    def test_empty_equity_curve_raises(self) -> None:
        """Fewer than 2 rows raises AttributionError."""
        tz = get_shanghai_tz()
        eq = pl.DataFrame(
            {"dt": [datetime(2026, 1, 5, 10, 0, tzinfo=tz)], "equity": [100000.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        with pytest.raises(AttributionError, match="at least 2 rows"):
            compute_session_attribution(eq)

    def test_missing_columns_raises(self) -> None:
        """Missing required columns raises AttributionError."""
        eq = pl.DataFrame({"x": [1, 2]})
        with pytest.raises(AttributionError, match="missing columns"):
            compute_session_attribution(eq)

    def test_custom_sessions(self) -> None:
        """Custom session definitions work correctly."""
        tz = get_shanghai_tz()
        custom_sessions = (
            Session("morning", 9, 0, 12, 0, spans_midnight=False),
            Session("afternoon", 12, 0, 17, 0, spans_midnight=False),
        )
        dts = [
            datetime(2026, 1, 5, 10, 0, tzinfo=tz),  # morning (dropped as first row)
            datetime(2026, 1, 5, 11, 0, tzinfo=tz),  # morning
            datetime(2026, 1, 5, 15, 0, tzinfo=tz),  # afternoon
        ]
        eq = pl.DataFrame(
            {"dt": dts, "equity": [100000.0, 101000.0, 102000.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        result = compute_session_attribution(eq, sessions=custom_sessions)
        assert len(result.sessions) == 2
        assert result.unclassified_count == 0

    def test_sharpe_zero_when_no_vol(self) -> None:
        """Sharpe is 0 when std_return is 0 (flat returns)."""
        tz = get_shanghai_tz()
        dts = [
            datetime(2026, 1, 5, 10, 0, tzinfo=tz),
            datetime(2026, 1, 5, 14, 0, tzinfo=tz),
        ]
        eq = pl.DataFrame(
            {"dt": dts, "equity": [100000.0, 100000.0]},
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        result = compute_session_attribution(eq)
        for s in result.sessions:
            assert s.sharpe == Decimal("0")
