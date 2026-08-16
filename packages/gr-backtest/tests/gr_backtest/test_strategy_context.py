from datetime import datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import (
    DEFAULT_ASHARE_SESSIONS,
    AccountView,
    BarContext,
    Context,
    HistoryView,
    PositionView,
    Strategy,
    StrategyError,
    TimezoneError,
    get_shanghai_tz,
)


def valid_bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
            ],
            "symbol": ["000001.SZ", "600000.SH", "000001.SZ", "600000.SH", "000001.SZ"],
            "open": [9.0, 20.0, 10.0, 21.0, 11.0],
            "high": [9.5, 20.5, 10.5, 21.5, 11.5],
            "low": [8.8, 19.8, 9.8, 20.8, 10.8],
            "close": [9.2, 20.2, 10.2, 21.2, 11.2],
            "volume": [900.0, 2000.0, 1000.0, 2100.0, 1100.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def test_strategy_default_hooks_are_noops() -> None:
    strategy = Strategy()
    ctx = Context(
        now=datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
        run_id="run-1",
        account=AccountView(),
    )
    strategy.setup(ctx)
    strategy.teardown(ctx)
    assert strategy.name == "Strategy"


def test_strategy_default_on_bar_returns_none() -> None:
    strategy = Strategy()
    history = HistoryView(valid_bars())
    ctx = BarContext(
        now=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
        run_id="run-1",
        account=AccountView(),
        bar=valid_bars().tail(1),
        history=history,
    )
    assert strategy.on_bar(ctx) is None


def test_context_rejects_naive_now() -> None:
    with pytest.raises(TimezoneError):
        Context(now=datetime(2026, 1, 1, 9, 30), run_id="run-1", account=AccountView())


def test_account_view_returns_existing_position() -> None:
    account = AccountView(
        cash=Decimal("1000"),
        positions={"000001.SZ": PositionView(symbol="000001.SZ", qty=Decimal("100"))},
    )
    assert account.position("000001.SZ").qty == Decimal("100")
    assert account.position("600000.SH").qty == Decimal("0")


def test_account_view_rejects_float_cash() -> None:
    with pytest.raises(StrategyError, match="decimal.Decimal"):
        AccountView(cash=1000.0)  # type: ignore[arg-type]


def test_history_view_lookback_returns_last_n_distinct_datetimes() -> None:
    history = HistoryView(valid_bars())
    result = history.lookback(n=2)
    assert result["dt"].n_unique() == 2
    assert result["dt"].min() == datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())


def test_history_view_lookback_filters_symbols_and_columns() -> None:
    history = HistoryView(valid_bars())
    result = history.lookback(symbols=["600000.SH"], columns=["dt", "symbol", "close"], n=2)
    assert result.columns == ["dt", "symbol", "close"]
    assert result["symbol"].to_list() == ["600000.SH", "600000.SH"]


def test_history_view_lookback_rejects_non_positive_n() -> None:
    history = HistoryView(valid_bars())
    with pytest.raises(StrategyError, match="positive"):
        history.lookback(n=0)


def test_bar_context_validates_current_bar_and_delegates_lookback() -> None:
    history = HistoryView(valid_bars())
    ctx = BarContext(
        now=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
        run_id="run-1",
        account=AccountView(),
        bar=valid_bars().tail(1),
        history=history,
    )
    assert ctx.bar.height == 1
    assert ctx.lookback(n=1)["dt"].n_unique() == 1


# ── HistoryView.resampled() (P10 Phase 2) ───────────────────────────────────


def test_history_view_resampled_type() -> None:
    """resampled() returns a HistoryView."""
    history = HistoryView(valid_bars())
    result = history.resampled("5m")
    assert isinstance(result, HistoryView)
    assert result.bars.height > 0


def test_history_view_resampled_caching() -> None:
    """Second call with same freq returns the same object instance."""
    history = HistoryView(valid_bars())
    view1 = history.resampled("5m")
    view2 = history.resampled("5m")
    assert view1 is view2  # identity check — same cached instance


def test_history_view_resampled_cache_key_includes_sessions() -> None:
    """Session-aligned resampling does not reuse wall-clock cached bars."""
    tz = get_shanghai_tz()
    rows = []
    for i in range(60):
        dt = datetime(2026, 1, 1, 9, 30, tzinfo=tz) + timedelta(minutes=i)
        rows.append(
            {
                "dt": dt,
                "symbol": "000001.SZ",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 1000.0,
            }
        )
    history = HistoryView(
        pl.DataFrame(rows, schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")})
    )

    wall_clock = history.resampled("1h")
    session_aligned = history.resampled("1h", sessions=DEFAULT_ASHARE_SESSIONS)

    assert wall_clock is not session_aligned
    assert wall_clock.bars["dt"][0] == datetime(2026, 1, 1, 9, 0, tzinfo=tz)
    assert session_aligned.bars["dt"][0] == datetime(2026, 1, 1, 9, 30, tzinfo=tz)


def test_history_view_resampled_lookback() -> None:
    """Chaining resampled() with .lookback() works."""
    # Build multi-day 1m bars
    tz = get_shanghai_tz()
    rows = []
    for day in range(1, 4):
        for m in range(5):
            dt = datetime(2026, 1, day, 9, 30 + m, 0, tzinfo=tz)
            rows.append(
                {
                    "dt": dt,
                    "symbol": "A",
                    "open": 10.0 + day,
                    "high": 10.5 + day,
                    "low": 9.5 + day,
                    "close": 10.2 + day,
                    "volume": 1000.0,
                }
            )
    bars = pl.DataFrame(
        rows,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    history = HistoryView(bars)
    daily = history.resampled("1d")
    # Look back 2 days
    last2 = daily.lookback(n=2)
    assert last2["dt"].n_unique() == 2


def test_history_view_resampled_invalid_freq() -> None:
    """ValueError on unknown freq."""
    history = HistoryView(valid_bars())
    with pytest.raises(ValueError, match="unknown target_freq"):
        history.resampled("weekly")


# ── BarContext.extra_history (P10 Phase 3) ─────────────────────────────────


def test_bar_context_extra_history_default_none() -> None:
    """extra_history is None when not provided."""
    history = HistoryView(valid_bars())
    ctx = BarContext(
        now=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
        run_id="run-1",
        account=AccountView(),
        bar=valid_bars().tail(1),
        history=history,
    )
    assert ctx.extra_history is None


def test_bar_context_extra_history_has_keys() -> None:
    """extra_history contains HistoryView instances keyed by freq."""
    history = HistoryView(valid_bars())
    daily_view = HistoryView(valid_bars())
    ctx = BarContext(
        now=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
        run_id="run-1",
        account=AccountView(),
        bar=valid_bars().tail(1),
        history=history,
        extra_history={"1d": daily_view},
    )
    assert ctx.extra_history is not None
    assert set(ctx.extra_history.keys()) == {"1d"}
    assert isinstance(ctx.extra_history["1d"], HistoryView)


def test_bar_context_extra_history_lookback_works() -> None:
    """extra_history['1d'].lookback() returns correct data."""
    history = HistoryView(valid_bars())
    # Build a daily bar for the extra history
    daily_bars = pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
                datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
            ],
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [9.0, 10.0, 11.0],
            "high": [9.5, 10.5, 11.5],
            "low": [8.8, 9.8, 10.8],
            "close": [9.2, 10.2, 11.2],
            "volume": [900.0, 1000.0, 1100.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    daily_view = HistoryView(daily_bars)
    ctx = BarContext(
        now=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
        run_id="run-1",
        account=AccountView(),
        bar=valid_bars().tail(1),
        history=history,
        extra_history={"1d": daily_view},
    )
    # Look back the last 2 daily bars
    assert ctx.extra_history is not None
    last2 = ctx.extra_history["1d"].lookback(n=2)
    assert last2["dt"].n_unique() == 2
