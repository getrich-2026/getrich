from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import (
    Account,
    AccountError,
    AssetClass,
    Fill,
    MarginCalculator,
    Side,
    daily_settle,
    get_settlement_prices,
    get_shanghai_tz,
)


def fill(
    *,
    side: Side = Side.BUY,
    symbol: str = "000001.SZ",
    qty: Decimal = Decimal("10"),
    price: Decimal = Decimal("10"),
    fee: Decimal = Decimal("0"),
) -> Fill:
    dt = datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())
    return Fill(
        fill_id=f"fill-{side.value}-{symbol}",
        order_id="order-1",
        strategy_name="TestStrategy",
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        notional=qty * price,
        fee=fee,
        fill_time=dt,
        bar_dt=dt,
    )


def test_account_rejects_non_decimal_cash() -> None:
    with pytest.raises(AccountError, match="decimal.Decimal"):
        Account(initial_cash=1000.0)  # type: ignore[arg-type]


def test_account_apply_buy_updates_cash_position_and_average_cost() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(qty=Decimal("10"), price=Decimal("20")))

    position = account.positions["000001.SZ"]
    assert account.cash == Decimal("700")
    assert position.qty == Decimal("20")
    assert position.avg_cost == Decimal("15")


def test_account_apply_sell_updates_cash_position_and_realized_pnl() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.BUY, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.SELL, qty=Decimal("4"), price=Decimal("12")))

    position = account.positions["000001.SZ"]
    assert account.cash == Decimal("948")
    assert position.qty == Decimal("6")
    assert position.realized_pnl == Decimal("8")


def test_account_apply_sell_resets_average_cost_when_flat() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.BUY, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.CLOSE_LONG, qty=Decimal("10"), price=Decimal("11")))

    position = account.positions["000001.SZ"]
    assert position.qty == Decimal("0")
    assert position.avg_cost == Decimal("0")
    assert position.realized_pnl == Decimal("10")


def test_account_apply_rejects_oversell() -> None:
    account = Account(initial_cash=Decimal("1000"))
    with pytest.raises(AccountError, match="insufficient position"):
        account.apply(fill(side=Side.SELL, qty=Decimal("1"), price=Decimal("10")))


def test_account_view_returns_strategy_facing_decimal_snapshot() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(qty=Decimal("10"), price=Decimal("10")))

    view = account.view()
    assert view.cash == Decimal("900")
    assert view.position("000001.SZ").qty == Decimal("10")
    assert view.position("600000.SH").qty == Decimal("0")


# ---------------------------------------------------------------------------
# Position enhancement (P9 Phase 1)
# ---------------------------------------------------------------------------


def test_position_defaults_to_equity_asset_class() -> None:
    """Position created without asset_class defaults to EQUITY_A."""
    from gr_backtest.account import Position

    pos = Position(symbol="X")
    assert pos.asset_class == AssetClass.EQUITY_A
    assert pos.multiplier == Decimal("1")
    assert pos.margin_held == Decimal("0")
    assert pos.today_qty is None


def test_position_notional_value() -> None:
    """notional_value = qty * last_price * multiplier."""
    from gr_backtest.account import Position

    pos = Position(
        symbol="IF",
        qty=Decimal("2"),
        last_price=Decimal("5000"),
        multiplier=Decimal("300"),
    )
    assert pos.notional_value == Decimal("3000000")


def test_position_unrealized_pnl() -> None:
    """unrealized_pnl = (last_price - avg_cost) * qty * multiplier."""
    from gr_backtest.account import Position

    pos = Position(
        symbol="IF",
        qty=Decimal("2"),
        avg_cost=Decimal("4800"),
        last_price=Decimal("5000"),
        multiplier=Decimal("300"),
    )
    assert pos.unrealized_pnl == Decimal("120000")


def test_position_no_last_price_returns_none() -> None:
    """notional_value and unrealized_pnl are None when last_price is None."""
    from gr_backtest.account import Position

    pos = Position(symbol="X")
    assert pos.notional_value is None
    assert pos.unrealized_pnl is None


# ---------------------------------------------------------------------------
# Frozen cash (P9 Phase 1)
# ---------------------------------------------------------------------------


def test_frozen_cash_defaults_to_zero() -> None:
    account = Account(initial_cash=Decimal("1000"))
    assert account.frozen_cash == Decimal("0")


def test_available_cash_equals_cash_minus_frozen() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.reserve(Decimal("200"))
    assert account.available_cash == Decimal("800")


def test_reserve_reduces_available_cash() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.reserve(Decimal("300"))
    assert account.available_cash == Decimal("700")
    assert account.frozen_cash == Decimal("300")


def test_reserve_raises_on_insufficient_available() -> None:
    account = Account(initial_cash=Decimal("100"))
    with pytest.raises(AccountError, match="insufficient available cash"):
        account.reserve(Decimal("150"))


def test_release_restores_available_cash() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.reserve(Decimal("200"))
    account.release(Decimal("100"))
    assert account.frozen_cash == Decimal("100")
    assert account.available_cash == Decimal("900")


def test_release_below_zero_clamps() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.reserve(Decimal("200"))
    account.release(Decimal("999"))  # more than frozen
    assert account.frozen_cash == Decimal("0")


def test_reserve_negative_raises() -> None:
    account = Account(initial_cash=Decimal("1000"))
    with pytest.raises(AccountError, match="non-negative"):
        account.reserve(Decimal("-100"))


def test_apply_buy_reduces_frozen_cash() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.reserve(Decimal("110"))
    account.apply(fill(side=Side.BUY, qty=Decimal("10"), price=Decimal("10")))
    assert account.frozen_cash == Decimal("10")  # 110 - 100 = 10


def test_available_cash_in_view() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.reserve(Decimal("200"))
    view = account.view()
    assert view.available_cash == Decimal("800")


# ---------------------------------------------------------------------------
# OPEN_LONG / CLOSE_LONG (P9 Phase 1)
# ---------------------------------------------------------------------------


def test_apply_open_long_works() -> None:
    """OPEN_LONG behaves like BUY."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_LONG, qty=Decimal("10"), price=Decimal("10")))
    assert account.cash == Decimal("900")
    assert account.positions["000001.SZ"].qty == Decimal("10")


def test_apply_close_long_works() -> None:
    """CLOSE_LONG behaves like SELL."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_LONG, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.CLOSE_LONG, qty=Decimal("10"), price=Decimal("12")))
    position = account.positions["000001.SZ"]
    assert position.qty == Decimal("0")
    assert position.realized_pnl == Decimal("20")


# ---------------------------------------------------------------------------
# Margin calculator integration (P9 Phase 1)
# ---------------------------------------------------------------------------


def _make_margin_calc() -> MarginCalculator:
    """Create a MarginCalculator with known IF (index futures) data."""
    instruments = pl.DataFrame(
        {
            "symbol": ["IF"],
            "asset_class": ["index_future"],
            "margin_ratio_long": [0.15],
            "margin_ratio_short": [0.15],
            "multiplier": [300.0],
        }
    )
    return MarginCalculator(instruments)


def test_account_accepts_margin_calculator() -> None:
    calc = _make_margin_calc()
    account = Account(initial_cash=Decimal("100000"), margin_calculator=calc)
    assert account._margin_calculator is calc


def test_open_long_deducts_margin() -> None:
    """OPEN_LONG with margin_calculator deducts initial margin."""
    calc = _make_margin_calc()
    account = Account(initial_cash=Decimal("100000"), margin_calculator=calc)
    account.apply(fill(symbol="IF", side=Side.OPEN_LONG, qty=Decimal("2"), price=Decimal("5000")))
    # margin = 2 * 5000 * 300 * 0.15 = 450000
    pos = account.positions["IF"]
    assert pos.margin_held == Decimal("450000")
    assert account.margin_state.initial_margin == Decimal("450000")


def test_close_long_releases_margin_proportionally() -> None:
    """CLOSE_LONG releases margin in proportion to the qty closed."""
    calc = _make_margin_calc()
    account = Account(initial_cash=Decimal("1000000"), margin_calculator=calc)
    account.apply(fill(symbol="IF", side=Side.OPEN_LONG, qty=Decimal("2"), price=Decimal("5000")))
    # margin = 450000
    account.apply(fill(symbol="IF", side=Side.CLOSE_LONG, qty=Decimal("1"), price=Decimal("5100")))
    pos = account.positions["IF"]
    # Released: 450000 * (1/2) = 225000, remaining: 225000
    assert pos.margin_held == Decimal("225000")
    assert account.margin_state.initial_margin == Decimal("225000")


def test_margin_state_initialized() -> None:
    account = Account(initial_cash=Decimal("1000"))
    assert account.margin_state.initial_margin == Decimal("0")
    assert account.margin_state.margin_call_triggered is False


# ---------------------------------------------------------------------------
# gross_exposure with multiplier (P9 Phase 1)
# ---------------------------------------------------------------------------


def test_gross_exposure_with_futures_multiplier() -> None:
    from gr_backtest.account import Position

    pos = Position(
        symbol="IF",
        qty=Decimal("2"),
        multiplier=Decimal("300"),
    )
    account = Account(
        initial_cash=Decimal("100000"),
        positions={"IF": pos},
    )
    exposure = account.gross_exposure({"IF": Decimal("5000")})
    assert exposure == Decimal("3000000")  # 2 * 5000 * 300


# ---------------------------------------------------------------------------
# daily_settle (P9 Phase 1)
# ---------------------------------------------------------------------------


def _make_futures_account() -> Account:
    """Create an account with an open index futures position."""
    from gr_backtest.account import Position

    pos = Position(
        symbol="IF",
        qty=Decimal("2"),
        avg_cost=Decimal("4800"),
        last_price=Decimal("4800"),
        multiplier=Decimal("300"),
        asset_class=AssetClass.INDEX_FUTURE,
    )
    return Account(
        initial_cash=Decimal("1000000"),
        cash=Decimal("400000"),
        positions={"IF": pos},
    )


def test_daily_settle_noop_for_equity() -> None:
    """Equity positions are unaffected by daily_settle."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.BUY, qty=Decimal("10"), price=Decimal("10")))
    events = daily_settle(account, {"000001.SZ": Decimal("11")}, datetime(2026, 1, 2, 9, 30))
    assert len(events) == 0
    # Cash unchanged by settlement
    assert account.cash == Decimal("900")


def test_daily_settle_variation_pnl_profit() -> None:
    """Futures profit: cash increases by variation PnL."""
    account = _make_futures_account()
    events = daily_settle(account, {"IF": Decimal("5000")}, datetime(2026, 1, 2, 9, 30))
    # variation_pnl = (5000 - 4800) * 2 * 300 = 120000
    assert len(events) == 1
    assert events[0]["variation_pnl"] == Decimal("120000")
    assert account.cash == Decimal("520000")  # 400000 + 120000
    assert account.margin_state.variation_pnl_cumulative == Decimal("120000")


def test_daily_settle_avg_cost_reset() -> None:
    """After settlement, avg_cost = settle price."""
    account = _make_futures_account()
    daily_settle(account, {"IF": Decimal("5000")}, datetime(2026, 1, 2, 9, 30))
    assert account.positions["IF"].avg_cost == Decimal("5000")


def test_daily_settle_loss() -> None:
    """Futures loss: cash decreases."""
    account = _make_futures_account()
    daily_settle(account, {"IF": Decimal("4700")}, datetime(2026, 1, 2, 9, 30))
    # variation_pnl = (4700 - 4800) * 2 * 300 = -60000
    assert account.cash == Decimal("340000")  # 400000 - 60000
    assert account.margin_state.variation_pnl_cumulative == Decimal("-60000")


def test_daily_settle_zero_qty_skipped() -> None:
    """Zero-qty positions are skipped during settlement."""
    account = Account(initial_cash=Decimal("1000"))
    events = daily_settle(account, {}, datetime(2026, 1, 2, 9, 30))
    assert len(events) == 0


def test_get_settlement_prices_prefers_settlement_column() -> None:
    """settlement column preferred over close/last_price."""
    dt = datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())
    bar = pl.DataFrame(
        {
            "dt": [dt],
            "symbol": ["IF"],
            "open": [5000.0],
            "high": [5100.0],
            "low": [4900.0],
            "close": [5050.0],
            "volume": [1000],
            "settlement": [5020.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    prices = get_settlement_prices(bar, {"IF": Decimal("5000")})
    assert prices["IF"] == Decimal("5020")


def test_get_settlement_prices_falls_back_to_close() -> None:
    """No settlement column -> uses last_prices."""
    dt = datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz())
    bar = pl.DataFrame(
        {
            "dt": [dt],
            "symbol": ["IF"],
            "open": [5000.0],
            "high": [5100.0],
            "low": [4900.0],
            "close": [5050.0],
            "volume": [1000],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    prices = get_settlement_prices(bar, {"IF": Decimal("5000")})
    assert prices["IF"] == Decimal("5000")  # from last_prices


# ---------------------------------------------------------------------------
# OPEN_SHORT / CLOSE_SHORT (P9 Phase 2)
# ---------------------------------------------------------------------------


def test_apply_open_short_increases_cash_and_creates_negative_qty() -> None:
    """OPEN_SHORT: cash increases, position qty goes negative."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("10")))
    assert account.cash == Decimal("1100")  # 1000 + 100
    position = account.positions["000001.SZ"]
    assert position.qty == Decimal("-10")
    assert position.avg_cost == Decimal("10")


def test_apply_open_short_avg_cost_weighted() -> None:
    """Short avg_cost is the weighted average of entry prices."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("20")))
    position = account.positions["000001.SZ"]
    assert position.qty == Decimal("-20")
    assert position.avg_cost == Decimal("15")  # (10*10 + 10*20) / 20


def test_apply_open_short_rejects_long() -> None:
    """OPEN_SHORT raises AccountError when long position exists."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.BUY, qty=Decimal("10"), price=Decimal("10")))
    with pytest.raises(AccountError, match="cannot open short when long"):
        account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("5"), price=Decimal("10")))


def test_apply_close_short_decreases_cash_and_reduces_short() -> None:
    """CLOSE_SHORT: cash decreases, short position reduces toward zero."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.CLOSE_SHORT, qty=Decimal("4"), price=Decimal("8")))
    position = account.positions["000001.SZ"]
    assert account.cash == Decimal("1068")  # 1100 - 32
    assert position.qty == Decimal("-6")


def test_apply_close_short_realized_pnl_profit() -> None:
    """Short profit when price drops: (avg_cost - price) * qty > 0."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.CLOSE_SHORT, qty=Decimal("4"), price=Decimal("8")))
    position = account.positions["000001.SZ"]
    # PnL = (10 - 8) * 4 = 8
    assert position.realized_pnl == Decimal("8")


def test_apply_close_short_realized_pnl_loss() -> None:
    """Short loss when price rises: (avg_cost - price) * qty < 0."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.CLOSE_SHORT, qty=Decimal("4"), price=Decimal("12")))
    position = account.positions["000001.SZ"]
    # PnL = (10 - 12) * 4 = -8
    assert position.realized_pnl == Decimal("-8")


def test_apply_close_short_resets_when_flat() -> None:
    """CLOSE_SHORT fully covering resets avg_cost and margin_held."""
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("10")))
    account.apply(fill(side=Side.CLOSE_SHORT, qty=Decimal("10"), price=Decimal("9")))
    position = account.positions["000001.SZ"]
    assert position.qty == Decimal("0")
    assert position.avg_cost == Decimal("0")
    assert position.realized_pnl == Decimal("10")  # (10 - 9) * 10


def test_apply_close_short_rejects_no_short() -> None:
    account = Account(initial_cash=Decimal("1000"))
    with pytest.raises(AccountError, match="no short position to close"):
        account.apply(fill(side=Side.CLOSE_SHORT, qty=Decimal("5"), price=Decimal("10")))


def test_apply_close_short_rejects_overtrade() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("5"), price=Decimal("10")))
    with pytest.raises(AccountError, match="exceed short position"):
        account.apply(fill(side=Side.CLOSE_SHORT, qty=Decimal("10"), price=Decimal("10")))


def test_short_position_unrealized_pnl() -> None:
    """unrealized_pnl for short: (last_price - avg_cost) * qty * multiplier.
    Profit when last_price < avg_cost on negative qty."""
    from gr_backtest.account import Position

    pos = Position(
        symbol="IF",
        qty=Decimal("-2"),
        avg_cost=Decimal("5000"),
        last_price=Decimal("4800"),
        multiplier=Decimal("300"),
    )
    # (4800 - 5000) * (-2) * 300 = +120000 (profit)
    assert pos.unrealized_pnl == Decimal("120000")


def test_open_short_deducts_margin() -> None:
    """OPEN_SHORT with MarginCalculator deducts margin using short ratio."""
    calc = _make_margin_calc()  # margin_ratio_short = 0.15
    account = Account(initial_cash=Decimal("100000"), margin_calculator=calc)
    account.apply(fill(symbol="IF", side=Side.OPEN_SHORT, qty=Decimal("2"), price=Decimal("5000")))
    pos = account.positions["IF"]
    # margin = 2 * 5000 * 300 * 0.15 = 450000
    assert pos.margin_held == Decimal("450000")
    assert account.margin_state.initial_margin == Decimal("450000")


def test_close_short_releases_margin() -> None:
    """CLOSE_SHORT releases margin proportionally."""
    calc = _make_margin_calc()
    account = Account(initial_cash=Decimal("1000000"), margin_calculator=calc)
    account.apply(fill(symbol="IF", side=Side.OPEN_SHORT, qty=Decimal("2"), price=Decimal("5000")))
    account.apply(fill(symbol="IF", side=Side.CLOSE_SHORT, qty=Decimal("1"), price=Decimal("4900")))
    pos = account.positions["IF"]
    # Released: 450000 * (1/2) = 225000, remaining: 225000
    assert pos.margin_held == Decimal("225000")
    assert account.margin_state.initial_margin == Decimal("225000")


def test_open_short_daily_settle_profit() -> None:
    """Short futures profit on price decrease after daily_settle."""
    from gr_backtest.account import Position

    pos = Position(
        symbol="IF",
        qty=Decimal("-2"),
        avg_cost=Decimal("5000"),
        last_price=Decimal("5000"),
        multiplier=Decimal("300"),
        asset_class=AssetClass.INDEX_FUTURE,
        margin_held=Decimal("450000"),
    )
    account = Account(
        initial_cash=Decimal("1000000"),
        cash=Decimal("1100000"),
        positions={"IF": pos},
        margin_calculator=_make_margin_calc(),
    )
    events = daily_settle(account, {"IF": Decimal("4800")}, datetime(2026, 1, 2, 9, 30))
    # variation_pnl = (4800 - 5000) * (-2) * 300 = +120000 (profit)
    assert len(events) == 1
    assert events[0]["variation_pnl"] == Decimal("120000")
    assert account.cash == Decimal("1220000")  # 1100000 + 120000


# ---------------------------------------------------------------------------
# Risk control foundation (P9 Phase 3)
# ---------------------------------------------------------------------------


def test_force_close_long_position() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.BUY, qty=Decimal("10"), price=Decimal("10")))
    forced = account.force_close_position(
        symbol="000001.SZ",
        price=Decimal("12"),
        dt=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
    )
    position = account.positions["000001.SZ"]
    assert forced.side == Side.CLOSE_LONG
    assert forced.qty == Decimal("10")
    assert position.qty == Decimal("0")
    assert position.realized_pnl == Decimal("20")


def test_force_close_short_position() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.apply(fill(side=Side.OPEN_SHORT, qty=Decimal("10"), price=Decimal("10")))
    forced = account.force_close_position(
        symbol="000001.SZ",
        price=Decimal("8"),
        dt=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
    )
    position = account.positions["000001.SZ"]
    assert forced.side == Side.CLOSE_SHORT
    assert forced.qty == Decimal("10")
    assert position.qty == Decimal("0")
    assert position.realized_pnl == Decimal("20")


def test_force_close_rejects_missing_position() -> None:
    account = Account(initial_cash=Decimal("1000"))
    with pytest.raises(AccountError, match="no position to force close"):
        account.force_close_position(
            symbol="MISSING",
            price=Decimal("10"),
            dt=datetime(2026, 1, 3, 9, 30, tzinfo=get_shanghai_tz()),
        )


def test_add_sub_account() -> None:
    account = Account(initial_cash=Decimal("1000"))
    sub_account = account.add_sub_account("alpha", Decimal("300"))
    assert sub_account.name == "alpha"
    assert sub_account.cash == Decimal("300")
    assert account.sub_accounts["alpha"] is sub_account


def test_sub_account_snapshot() -> None:
    account = Account(initial_cash=Decimal("1000"))
    sub_account = account.add_sub_account("alpha", Decimal("300"))
    snapshot = sub_account.snapshot()
    assert snapshot.name == "alpha"
    assert snapshot.cash == Decimal("300")
    assert snapshot.available_cash == Decimal("300")
    assert snapshot.equity == Decimal("300")
    assert snapshot.nav == Decimal("300")


# ---------------------------------------------------------------------------
# Sub-account routing tests
# ---------------------------------------------------------------------------


def test_active_sub_account_getter_returns_none_by_default() -> None:
    account = Account(initial_cash=Decimal("1000"))
    assert account.active_sub_account is None


def test_active_sub_account_setter_activates_existing_sub_account() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.add_sub_account("alpha", Decimal("300"))
    account.active_sub_account = "alpha"
    assert account.active_sub_account == "alpha"


def test_active_sub_account_setter_rejects_unknown_sub_account() -> None:
    account = Account(initial_cash=Decimal("1000"))
    with pytest.raises(AccountError, match="cannot activate unknown sub-account"):
        account.active_sub_account = "nonexistent"


def test_active_sub_account_setter_deactivates_with_none() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.add_sub_account("alpha", Decimal("300"))
    account.active_sub_account = "alpha"
    account.active_sub_account = None
    assert account.active_sub_account is None


def test_get_sub_account_returns_correct_sub_account() -> None:
    account = Account(initial_cash=Decimal("1000"))
    sa = account.add_sub_account("alpha", Decimal("300"))
    found = account.get_sub_account("alpha")
    assert found is sa
    assert found.name == "alpha"
    assert found.cash == Decimal("300")


def test_get_sub_account_raises_for_unknown_name() -> None:
    account = Account(initial_cash=Decimal("1000"))
    with pytest.raises(AccountError, match="sub-account not found: beta"):
        account.get_sub_account("beta")


def test_apply_mirrors_fill_to_active_sub_account() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.add_sub_account("alpha", Decimal("500"))
    account.active_sub_account = "alpha"

    f = fill(symbol="000001.SZ", qty=Decimal("10"), price=Decimal("10"))
    account.apply(f)

    sa = account.get_sub_account("alpha")
    # Sub-account cash tracks the delta: main cash went from 1000 → 900
    # (spent 100 notional), so sub cash: 500 - 100 = 400
    assert sa.cash == Decimal("400")
    # Position mirrored
    assert "000001.SZ" in sa.positions
    assert sa.positions["000001.SZ"].qty == Decimal("10")


def test_sub_account_equity_map_empty_when_no_sub_accounts() -> None:
    account = Account(initial_cash=Decimal("1000"))
    result = account.sub_account_equity_map({"000001.SZ": Decimal("10")})
    assert result == {}


def test_sub_account_equity_map_returns_per_account_equity() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.add_sub_account("alpha", Decimal("500"))
    account.add_sub_account("beta", Decimal("300"))

    result = account.sub_account_equity_map({})
    assert result == {"alpha": Decimal("500"), "beta": Decimal("300")}


def test_sub_account_equity_map_includes_position_market_value() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.add_sub_account("alpha", Decimal("500"))
    account.active_sub_account = "alpha"

    f = fill(symbol="000001.SZ", qty=Decimal("10"), price=Decimal("10"))
    account.apply(f)

    # At mark price 12, position is worth 120
    result = account.sub_account_equity_map({"000001.SZ": Decimal("12")})
    # Sub cash: 500 - 100 = 400, equity = 400 + 10*12*1 = 520
    assert result["alpha"] == Decimal("520")


def test_apply_without_active_sub_account_does_not_mirror() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.add_sub_account("alpha", Decimal("500"))
    # active_sub_account is None (default)

    f = fill(symbol="000001.SZ", qty=Decimal("10"), price=Decimal("10"))
    account.apply(f)

    sa = account.get_sub_account("alpha")
    # Sub-account untouched
    assert sa.cash == Decimal("500")
    assert sa.positions == {}


def test_apply_mirrors_sell_fill_to_sub_account() -> None:
    account = Account(initial_cash=Decimal("1000"))
    account.add_sub_account("alpha", Decimal("500"))
    account.active_sub_account = "alpha"

    buy = fill(symbol="000001.SZ", side=Side.BUY, qty=Decimal("10"), price=Decimal("10"))
    account.apply(buy)

    sell = fill(symbol="000001.SZ", side=Side.SELL, qty=Decimal("5"), price=Decimal("12"))
    account.apply(sell)

    sa = account.get_sub_account("alpha")
    # After buy: cash 500-100=400
    # After sell: cash 400+60=460 (delta: +60 from sell)
    assert sa.cash == Decimal("460")
    # Position reduced
    assert sa.positions["000001.SZ"].qty == Decimal("5")


# ---------------------------------------------------------------------------
# Sub-account settlement tests — daily_settle mirroring
# ---------------------------------------------------------------------------


def _make_futures_account_with_sub() -> Account:
    """Create an account with IF futures position and one sub-account."""
    calc = _make_margin_calc()
    account = Account(initial_cash=Decimal("500000"), margin_calculator=calc)
    account.add_sub_account("alpha", Decimal("500000"))
    account.active_sub_account = "alpha"

    # Open a long IF position via fill
    f = Fill(
        fill_id="fill-IF-1",
        order_id="order-1",
        strategy_name="Test",
        symbol="IF",
        side=Side.OPEN_LONG,
        qty=Decimal("2"),
        price=Decimal("4000"),
        notional=Decimal("8000"),
        fee=Decimal("0"),
        fill_time=datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
        bar_dt=datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
    )
    account.apply(f)
    return account


def test_daily_settle_mirrors_variation_pnl_to_sub_account() -> None:
    """Sub-account cash receives same variation PnL as main account."""
    account = _make_futures_account_with_sub()
    sa = account.get_sub_account("alpha")

    # Main: 500000 - 360000 (margin: 2*4000*300*0.15 = 360000) = 140000 cash after margin
    # Sub: same (mirrored from apply())
    settle_prices = {"IF": Decimal("4100")}  # +100 points

    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    # Variation PnL per contract: (4100-4000)*2*300 = 60000
    # Main cash increases by 60000
    # Sub cash should increase by 60000 too
    assert sa.cash == account.cash


def test_daily_settle_syncs_avg_cost_to_sub_account() -> None:
    """Sub-account position avg_cost is reset to settle price."""
    account = _make_futures_account_with_sub()
    sa = account.get_sub_account("alpha")
    settle_prices = {"IF": Decimal("4100")}

    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    main_pos = account.positions["IF"]
    sub_pos = sa.positions["IF"]
    assert sub_pos.avg_cost == Decimal("4100")
    assert sub_pos.avg_cost == main_pos.avg_cost


def test_daily_settle_syncs_margin_held_to_sub_account() -> None:
    """Sub-account position margin_held is synced from main."""
    account = _make_futures_account_with_sub()
    sa = account.get_sub_account("alpha")
    settle_prices = {"IF": Decimal("4100")}

    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    main_pos = account.positions["IF"]
    sub_pos = sa.positions["IF"]
    assert sub_pos.margin_held == main_pos.margin_held
    # At 4100: 2*4100*300*0.15 = 369000
    assert sub_pos.margin_held == Decimal("369000")


def test_daily_settle_updates_sub_variation_pnl_cumulative() -> None:
    """Sub-account margin_state tracks cumulative variation PnL."""
    account = _make_futures_account_with_sub()
    sa = account.get_sub_account("alpha")
    settle_prices = {"IF": Decimal("4100")}

    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    # Variation PnL: (4100-4000)*2*300 = 60000
    assert sa.margin_state.variation_pnl_cumulative == Decimal("60000")
    assert sa.margin_state.variation_pnl_cumulative == account.margin_state.variation_pnl_cumulative


def test_daily_settle_recalculates_sub_margin_totals() -> None:
    """Sub-account margin_state totals are recalculated from positions."""
    account = _make_futures_account_with_sub()
    sa = account.get_sub_account("alpha")
    settle_prices = {"IF": Decimal("4100")}

    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    # Sub margin totals should match its own position margin_held
    expected = Decimal("369000")  # 2*4100*300*0.15
    assert sa.margin_state.initial_margin == expected
    assert sa.margin_state.maintenance_margin == expected


def test_daily_settle_does_not_affect_sub_without_position() -> None:
    """Sub-account without the settled position is untouched."""
    account = _make_futures_account_with_sub()
    # Add a second sub-account that has NOT traded
    account.add_sub_account("beta", Decimal("100000"))
    beta = account.get_sub_account("beta")
    beta_cash_before = beta.cash
    settle_prices = {"IF": Decimal("4100")}

    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    # Beta has no IF position → untouched
    assert beta.cash == beta_cash_before
    assert beta.margin_state.variation_pnl_cumulative == Decimal("0")


def test_daily_settle_sub_account_equity_map_reflects_settlement() -> None:
    """sub_account_equity_map includes variation PnL after settlement."""
    account = _make_futures_account_with_sub()
    settle_prices = {"IF": Decimal("4100")}

    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    # Equity = sub.cash + variation_pnl + position_market_value
    # cash = 500000 - 360000 (margin) + 60000 (var pnl) = 200000
    # pos value = 2*4100*300 = 2460000
    # But wait, cash was reduced by margin during fill. Let me use sub_account_equity_map directly.
    eq_map = account.sub_account_equity_map({"IF": Decimal("4100")})
    # Should match main equity
    main_equity = account.equity({"IF": Decimal("4100")})
    assert eq_map["alpha"] == main_equity


def test_daily_settle_no_sub_accounts_still_works() -> None:
    """daily_settle works when no sub-accounts exist (backward compat)."""
    calc = _make_margin_calc()
    account = Account(initial_cash=Decimal("500000"), margin_calculator=calc)
    f = Fill(
        fill_id="fill-IF-1",
        order_id="order-1",
        strategy_name="Test",
        symbol="IF",
        side=Side.OPEN_LONG,
        qty=Decimal("2"),
        price=Decimal("4000"),
        notional=Decimal("8000"),
        fee=Decimal("0"),
        fill_time=datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
        bar_dt=datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
    )
    account.apply(f)
    settle_prices = {"IF": Decimal("4100")}

    events = daily_settle(
        account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz())
    )
    # Should complete without error, events are produced
    assert len(events) == 1
    assert events[0]["symbol"] == "IF"


# ---------------------------------------------------------------------------
# Sub-account settlement tests — apply_corporate_action mirroring
# ---------------------------------------------------------------------------


def _make_equity_account_with_sub() -> Account:
    """Create an account with equity position and one sub-account."""
    account = Account(initial_cash=Decimal("100000"))
    account.add_sub_account("alpha", Decimal("50000"))
    account.active_sub_account = "alpha"

    f = fill(symbol="000001.SZ", qty=Decimal("1000"), price=Decimal("10"))
    account.apply(f)
    return account


def test_corp_action_dividend_mirrors_cash_to_sub() -> None:
    """Dividend cash is mirrored to sub-account holding the position."""
    account = _make_equity_account_with_sub()
    sa = account.get_sub_account("alpha")
    # Main: 100000 - 10000 (buy) = 90000; Sub: 50000 - 10000 = 40000
    cash_before_sa = sa.cash
    cash_before_main = account.cash

    account.apply_corporate_action("000001.SZ", "dividend", amount=0.5)

    # Net dividend: 1000 * 0.5 * (1-0.10) = 450 each
    assert sa.cash == cash_before_sa + Decimal("450")
    assert account.cash == cash_before_main + Decimal("450")


def test_corp_action_split_mirrors_position_to_sub() -> None:
    """Split qty and avg_cost changes are mirrored to sub-account."""
    account = _make_equity_account_with_sub()
    sa = account.get_sub_account("alpha")

    account.apply_corporate_action("000001.SZ", "split", split_ratio=2.0)

    main_pos = account.positions["000001.SZ"]
    sub_pos = sa.positions["000001.SZ"]
    assert sub_pos.qty == main_pos.qty
    assert sub_pos.avg_cost == main_pos.avg_cost
    assert sub_pos.qty == Decimal("2000")
    assert sub_pos.avg_cost == Decimal("5")  # 10/2


def test_corp_action_bonus_mirrors_position_to_sub() -> None:
    """Bonus shares qty and avg_cost changes are mirrored to sub-account."""
    account = _make_equity_account_with_sub()
    sa = account.get_sub_account("alpha")

    account.apply_corporate_action("000001.SZ", "bonus", bonus_ratio=0.5)

    main_pos = account.positions["000001.SZ"]
    sub_pos = sa.positions["000001.SZ"]
    assert sub_pos.qty == main_pos.qty
    assert sub_pos.avg_cost == main_pos.avg_cost
    # 1000 * 1.5 = 1500
    assert sub_pos.qty == Decimal("1500")


def test_corp_action_rights_does_not_affect_sub() -> None:
    """Rights issue (no-op) doesn't change sub-account state."""
    account = _make_equity_account_with_sub()
    sa = account.get_sub_account("alpha")
    cash_before = sa.cash
    pos_qty_before = sa.positions["000001.SZ"].qty

    account.apply_corporate_action("000001.SZ", "rights")

    assert sa.cash == cash_before
    assert sa.positions["000001.SZ"].qty == pos_qty_before


def test_corp_action_does_not_affect_sub_without_position() -> None:
    """Sub-account without the affected symbol is untouched."""
    account = _make_equity_account_with_sub()
    account.add_sub_account("beta", Decimal("30000"))
    beta = account.get_sub_account("beta")
    cash_before = beta.cash

    account.apply_corporate_action("000001.SZ", "dividend", amount=1.0)

    assert beta.cash == cash_before
    assert "000001.SZ" not in beta.positions


def test_corp_action_apply_without_sub_accounts_still_works() -> None:
    """apply_corporate_action works when no sub-accounts exist."""
    account = Account(initial_cash=Decimal("100000"))
    f = fill(symbol="000001.SZ", qty=Decimal("100"), price=Decimal("10"))
    account.apply(f)

    account.apply_corporate_action("000001.SZ", "dividend", amount=1.0)

    # Main cash increased by 100*1.0*0.9=90
    assert account.sub_accounts == {}


# ---------------------------------------------------------------------------
# Sub-account margin-call checks
# ---------------------------------------------------------------------------


def test_sub_account_margin_call_triggered_by_low_cash() -> None:
    """Main account margin_call_triggered is set when sub-account cash is low."""
    from gr_backtest.risk import RiskConfig, RiskManager

    account = _make_futures_account_with_sub()
    sa = account.get_sub_account("alpha")

    # Run daily_settle first to populate sub-account margin_state
    settle_prices = {"IF": Decimal("4000")}
    daily_settle(account, settle_prices, datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()))

    # Then drain sub-account cash below the margin-call threshold
    maint = sa.margin_state.maintenance_margin
    assert maint > Decimal("0")
    sa.cash = Decimal("100")

    rm = RiskManager(RiskConfig(margin_call_threshold=Decimal("2.0")))
    # Sub-account cash (100) < maintenance * 2.0 → margin call
    assert rm.check_margin_call(sa)  # type: ignore[arg-type]


def test_sub_account_margin_call_not_triggered_with_adequate_cash() -> None:
    """Healthy sub-account with ample cash relative to maintenance does not
    trigger margin call."""
    from gr_backtest.risk import RiskConfig, RiskManager

    calc = _make_margin_calc()
    account = Account(initial_cash=Decimal("500000"), margin_calculator=calc)
    account.add_sub_account("alpha", Decimal("500000"))
    account.active_sub_account = "alpha"

    # Open only 1 IF contract — margin held = 1 × 4000 × 300 × 0.15 = 180k,
    # cash after fill = 500k − 180k = 320k.
    fill = Fill(
        fill_id="fill-IF-1",
        order_id="order-1",
        strategy_name="Test",
        symbol="IF",
        side=Side.OPEN_LONG,
        qty=Decimal("1"),
        price=Decimal("4000"),
        notional=Decimal("4000"),
        fee=Decimal("0"),
        fill_time=datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
        bar_dt=datetime(2026, 1, 2, 9, 30, tzinfo=get_shanghai_tz()),
    )
    account.apply(fill)

    sa = account.get_sub_account("alpha")
    settle_prices = {"IF": Decimal("4000")}
    daily_settle(
        account,
        settle_prices,
        datetime(2026, 1, 2, 15, 0, tzinfo=get_shanghai_tz()),
    )

    # maint = 180k, threshold = 180k × 1.5 = 270k, available_cash ≈ 320k → ok
    assert sa.available_cash > Decimal("0")
    assert sa.margin_state.maintenance_margin > Decimal("0")
    assert sa.available_cash > sa.margin_state.maintenance_margin * Decimal("1.5"), (
        f"Expected available_cash ({sa.available_cash}) > "
        f"maintenance × 1.5 ({sa.margin_state.maintenance_margin * Decimal('1.5')})"
    )

    rm = RiskManager(RiskConfig(margin_call_threshold=Decimal("1.5")))
    assert not rm.check_margin_call(sa)  # type: ignore[arg-type]


def test_sub_account_no_margin_check_when_zero_maintenance() -> None:
    """Sub-account with zero maintenance margin returns False (no check)."""
    from gr_backtest.risk import RiskConfig, RiskManager

    account = _make_futures_account_with_sub()
    sa = account.get_sub_account("alpha")
    sa.margin_state.maintenance_margin = Decimal("0")

    rm = RiskManager(RiskConfig(margin_call_threshold=Decimal("2.0")))
    assert not rm.check_margin_call(sa)  # type: ignore[arg-type]
