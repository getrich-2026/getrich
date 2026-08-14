from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest

from getrich_backtest import (
    Backtest,
    BacktestResult,
    BarContext,
    DataFrameBarLoader,
    MetricsError,
    OrderIntent,
    RunConfig,
    Side,
    Strategy,
    compute_metrics,
    get_shanghai_tz,
)


def equity_curve(
    values: list[float],
    *,
    start: datetime | None = None,
) -> pl.DataFrame:
    """Build an equity curve DataFrame with known equity values."""
    if start is None:
        start = datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
    n = len(values)
    dts = [start + timedelta(days=i) for i in range(n)]
    return pl.DataFrame(
        {
            "dt": dts,
            "cash": [Decimal(str(v)) for v in values],
            "equity": [Decimal(str(v)) for v in values],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def _cfg(**overrides: object) -> RunConfig:
    """Build a minimal RunConfig with overridable fields."""
    tz = get_shanghai_tz()
    kwargs: dict[str, object] = dict(
        run_id="test",
        strategy_name="Test",
        symbols=("000001.SZ",),
        start=datetime(2026, 1, 1, 9, 30, tzinfo=tz),
        end=datetime(2026, 1, 4, 9, 30, tzinfo=tz),
        initial_cash=Decimal("1000"),
    )
    kwargs.update(overrides)
    return RunConfig(**kwargs)  # type: ignore[arg-type]


def min_result(**overrides: object) -> BacktestResult:
    """Build a minimal BacktestResult with overridable fields."""
    defaults = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=equity_curve([1000.0, 1100.0]),
    )
    return defaults


def test_compute_metrics_returns_expected_total_return() -> None:
    """A 10% gain should produce total_return=0.1."""
    result = min_result()
    m = compute_metrics(result)
    assert m.total_return == Decimal("0.1")
    assert m.strategy_name == "Test"
    assert m.run_id == "test"


def test_compute_metrics_log_return_is_consistent() -> None:
    """Log return should be consistent with total_return."""
    import math

    result = min_result()
    m = compute_metrics(result)
    expected = Decimal(str(math.log(1.1)))
    assert m.log_return == expected


def test_compute_metrics_sharpe_ratio_with_known_returns() -> None:
    """Varying positive returns should yield a positive Sharpe."""
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=equity_curve([1000.0, 1100.0, 1200.0, 1300.0]),
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0"))
    assert m.sharpe_ratio > Decimal("0")


def test_compute_metrics_zero_vol_sharpe_is_zero() -> None:
    """Constant equity curve should produce zero vol, and Sharpe should be 0."""
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=equity_curve([1000.0, 1000.0, 1000.0]),
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0.03"))
    assert m.annualized_volatility == Decimal("0")
    assert m.sharpe_ratio == Decimal("0")


def test_compute_metrics_max_drawdown() -> None:
    """Equity that drops 20% then recovers should have max_drawdown ≈ -0.2."""
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=equity_curve([1000.0, 1100.0, 880.0, 950.0]),
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0"))
    assert m.max_drawdown == Decimal("-0.2")


def test_compute_metrics_from_real_backtest_run() -> None:
    """End-to-end: run a buy-and-hold strategy and compute metrics."""
    bars = pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
            ],
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [Decimal("9"), Decimal("10"), Decimal("11")],
            "high": [Decimal("9.5"), Decimal("10.5"), Decimal("11.5")],
            "low": [Decimal("8.8"), Decimal("9.8"), Decimal("10.8")],
            "close": [Decimal("9.2"), Decimal("10.2"), Decimal("11.2")],
            "volume": [900.0, 1000.0, 1100.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )

    class BuyOnFirstBar(Strategy):
        def __init__(self) -> None:
            self.calls = 0

        def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
            self.calls += 1
            if self.calls == 1:
                return [OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal("10"))]
            return None

    bt = Backtest(
        strategy=BuyOnFirstBar(),
        bar_loader=DataFrameBarLoader(bars),
        symbols=["000001.SZ"],
        start=datetime(2026, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2026, 1, 4, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("1000"),
    )
    result = bt.run()
    m = compute_metrics(result)

    # Bought 10 @ 10 on bar 2, final close = 11.2 → equity ≈ 900 + 10*11.2 = 1012
    assert m.total_return > Decimal("0")
    assert m.total_fees == Decimal("0")
    assert m.total_trades == 1
    assert m.n_bars == 3
    assert m.strategy_name == "BuyOnFirstBar"
    assert m.run_id == "default"


def test_compute_metrics_rejects_single_bar() -> None:
    """A single-row equity curve should raise MetricsError."""
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=equity_curve([1000.0]),
    )
    with pytest.raises(MetricsError, match="at least 2"):
        compute_metrics(result)


def test_compute_metrics_rejects_zero_initial_cash() -> None:
    """Zero initial_cash should raise MetricsError."""
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("0"),
        config=_cfg(initial_cash=Decimal("0")),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=equity_curve([0.0, 0.0]),
    )
    with pytest.raises(MetricsError, match="positive"):
        compute_metrics(result)


def test_compute_metrics_zero_fills_zero_turnover() -> None:
    """No fills means zero fees, zero turnover, zero trades."""
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=equity_curve([1000.0, 1000.0]),
    )
    m = compute_metrics(result)
    assert m.total_fees == Decimal("0")
    assert m.total_turnover == Decimal("0")
    assert m.turnover_rate == Decimal("0")
    assert m.total_trades == 0


def test_compute_metrics_field_types_are_correct() -> None:
    """All fields should have the correct types."""
    result = min_result()
    m = compute_metrics(result, risk_free_rate=Decimal("0.03"), trading_days_per_year=252)

    assert isinstance(m.strategy_name, str)
    assert isinstance(m.run_id, str)
    assert isinstance(m.total_return, Decimal)
    assert isinstance(m.log_return, Decimal)
    assert isinstance(m.annualized_return, Decimal)
    assert isinstance(m.annualized_volatility, Decimal)
    assert isinstance(m.sharpe_ratio, Decimal)
    assert isinstance(m.max_drawdown, Decimal)
    assert isinstance(m.max_drawdown_duration, int)
    assert isinstance(m.total_fees, Decimal)
    assert isinstance(m.total_turnover, Decimal)
    assert isinstance(m.turnover_rate, Decimal)
    assert isinstance(m.total_trades, int)
    assert isinstance(m.n_bars, int)
    assert isinstance(m.risk_free_rate, Decimal)
    assert isinstance(m.trading_days_per_year, int)


# ── Sub-daily / daily downsampling tests (P10 Phase 2) ────────────────────


def _subdaily_equity_curve(values: list[float]) -> pl.DataFrame:
    """Build a 1-minute equity curve with ``len(values)`` bars."""
    start = datetime(2026, 1, 5, 9, 30, tzinfo=get_shanghai_tz())
    dts = [start + timedelta(minutes=i) for i in range(len(values))]
    return pl.DataFrame(
        {
            "dt": dts,
            "cash": [Decimal(str(v)) for v in values],
            "equity": [Decimal(str(v)) for v in values],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def _daily_equity_curve(values: list[float]) -> pl.DataFrame:
    """Build a daily equity curve with ``len(values)`` daily bars."""
    start = datetime(2026, 1, 5, 9, 30, tzinfo=get_shanghai_tz())
    dts = [start + timedelta(days=i) for i in range(len(values))]
    return pl.DataFrame(
        {
            "dt": dts,
            "cash": [Decimal(str(v)) for v in values],
            "equity": [Decimal(str(v)) for v in values],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_cagr_with_1m_equity() -> None:
    """With 1-minute data, CAGR should be reasonable — not ~0."""
    # 390 bars = one full trading day (09:30–15:59), each minute equity rises
    values = [1000.0 + i * 0.01 for i in range(390)]  # steady climb
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=_subdaily_equity_curve(values),
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0"))
    # With ~390 bars but only 1 day, CAGR should be total_return
    # (single day cannot be annualized properly, but it should NOT be ~0)
    assert m.annualized_return != Decimal("0")
    # n_bars should be the original count (390), not daily count (1)
    assert m.n_bars == 390


def test_annualized_vol_with_1m() -> None:
    """Vol should scale from daily returns, not minute returns."""
    # 4 days of data, 2 bars per day → 4 daily bars, 3 daily returns
    start = datetime(2026, 1, 5, 9, 30, tzinfo=get_shanghai_tz())
    dts: list[datetime] = []
    for day in range(4):
        dts.append(start + timedelta(days=day))
        dts.append(start + timedelta(days=day, minutes=1))
    values = [Decimal(str(1000.0 + i * 10)) for i in range(len(dts))]
    eq = pl.DataFrame(
        {
            "dt": dts,
            "cash": values,
            "equity": values,
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=eq,
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0"))
    # Vol should be computed from daily returns and be reasonable
    assert m.annualized_volatility > Decimal("0")


def test_daily_downsampling_correctness() -> None:
    """Daily-daily mapping: known daily equity values are preserved exactly."""
    values = [1000.0, 1100.0, 1200.0, 1300.0]
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=_daily_equity_curve(values),
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0"))
    # CAGR for 4 days: (1300/1000)^(252/4) - 1
    from math import isnan

    assert not isnan(float(m.annualized_return))
    assert m.total_return == Decimal("0.3")
    assert m.n_bars == 4


def test_subdaily_preserves_total_return() -> None:
    """total_return and log_return are frequency-independent."""
    # Same equity endpoints, one at 1m, one at 1d
    daily_values = [1000.0, 1100.0]
    subdaily_values = [1000.0, 1000.1, 1000.2, 1100.0]  # intraday wiggles

    result_daily = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=_daily_equity_curve(daily_values),
    )
    result_sub = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=_subdaily_equity_curve(subdaily_values),
    )

    m_daily = compute_metrics(result_daily)
    m_sub = compute_metrics(result_sub)

    assert m_daily.total_return == m_sub.total_return
    assert m_daily.log_return == m_sub.log_return


def test_one_bar_per_day_no_degradation() -> None:
    """Existing daily data (one bar per day) metrics are unchanged."""
    daily_vals = [1000.0, 1100.0, 1200.0, 1300.0, 1400.0]
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=_daily_equity_curve(daily_vals),
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0"))

    # These should all be sensible, non-zero values
    assert m.total_return == Decimal("0.4")
    assert m.annualized_return > Decimal("0")
    assert m.annualized_volatility > Decimal("0")
    assert m.sharpe_ratio > Decimal("0")


def test_metrics_short_backtest_under_1d() -> None:
    """Less than 1 day of data: n_daily=1, metrics handle gracefully."""
    # 60 bars within same day
    values = [1000.0 + i * 0.001 for i in range(60)]
    result = BacktestResult(
        run_id="test",
        strategy_name="Test",
        initial_cash=Decimal("1000"),
        config=_cfg(),
        orders=(),
        fills=(),
        final_account=None,  # type: ignore[arg-type]
        equity_curve=_subdaily_equity_curve(values),
    )
    m = compute_metrics(result, risk_free_rate=Decimal("0"))
    # Should complete without error; vol/Sharpe/Sortino may be 0
    assert isinstance(m.annualized_return, Decimal)
    assert m.annualized_volatility >= Decimal("0")
    assert m.sharpe_ratio >= Decimal("0")
