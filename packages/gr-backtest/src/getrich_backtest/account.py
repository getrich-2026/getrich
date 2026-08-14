"""Mutable account state for backtest execution with margin support."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from getrich_backtest.exceptions import AccountError, CorporateActionError
from getrich_backtest.strategy.context import AccountView, PositionView
from getrich_backtest.time import require_shanghai_aware
from getrich_backtest.types import AssetClass, Side


if TYPE_CHECKING:
    import polars as pl


if TYPE_CHECKING:
    from getrich_backtest.execution import Fill


_DECIMAL_ZERO = Decimal("0")
_LONG_BUY_SIDES = {Side.BUY, Side.OPEN_LONG}
_LONG_SELL_SIDES = {Side.SELL, Side.CLOSE_LONG}
_SHORT_SELL_SIDES = {Side.OPEN_SHORT}
_SHORT_BUY_SIDES = {Side.CLOSE_SHORT}
_FUTURES_ASSET_CLASSES = {AssetClass.COMMODITY_FUTURE, AssetClass.INDEX_FUTURE}


def _require_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise AccountError(f"{field_name} must be decimal.Decimal")
    return value


@dataclass
class Position:
    """Mutable position state owned by an account.

    New fields added in P9 (frozen_cash, margin_held, etc.) have safe
    defaults so that existing stock-only code continues to work without
    changes.
    """

    symbol: str
    qty: Decimal = _DECIMAL_ZERO
    avg_cost: Decimal = _DECIMAL_ZERO
    realized_pnl: Decimal = _DECIMAL_ZERO
    last_price: Decimal | None = None

    # P9 margin fields
    asset_class: AssetClass = AssetClass.EQUITY_A
    margin_held: Decimal = _DECIMAL_ZERO
    today_qty: Decimal | None = None
    multiplier: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise AccountError("position symbol must be non-empty")
        _require_decimal(self.qty, "position qty")
        _require_decimal(self.avg_cost, "position avg_cost")
        _require_decimal(self.realized_pnl, "position realized_pnl")
        if self.last_price is not None:
            _require_decimal(self.last_price, "position last_price")
        _require_decimal(self.margin_held, "position margin_held")
        _require_decimal(self.multiplier, "position multiplier")
        if self.today_qty is not None:
            _require_decimal(self.today_qty, "position today_qty")
        if not isinstance(self.asset_class, AssetClass):
            raise AccountError("position asset_class must be an AssetClass enum")

    @property
    def notional_value(self) -> Decimal | None:
        """Position market value = ``qty * last_price * multiplier``."""
        if self.last_price is None:
            return None
        return abs(self.qty) * self.last_price * self.multiplier

    @property
    def market_value(self) -> Decimal | None:
        """Alias for :attr:`notional_value`."""
        return self.notional_value

    @property
    def unrealized_pnl(self) -> Decimal | None:
        """Unrealised PnL = ``(last_price - avg_cost) * qty * multiplier``."""
        if self.last_price is None:
            return None
        return (self.last_price - self.avg_cost) * self.qty * self.multiplier


@dataclass
class MarginState:
    """Tracks aggregate margin and margin-call state for an ``Account``."""

    initial_margin: Decimal = _DECIMAL_ZERO
    maintenance_margin: Decimal = _DECIMAL_ZERO
    variation_pnl_cumulative: Decimal = _DECIMAL_ZERO
    margin_call_triggered: bool = False
    last_margin_call_dt: datetime | None = None
    forced_liquidation_triggered: bool = False


@dataclass
class SubAccountSnapshot:
    """Immutable snapshot of a sub-account."""

    name: str
    cash: Decimal
    positions: dict[str, Position]
    margin_state: MarginState
    available_cash: Decimal
    equity: Decimal
    nav: Decimal


@dataclass
class SubAccount:
    """Minimal sub-account data model for future routing support."""

    name: str
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    margin_state: MarginState = field(default_factory=MarginState)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise AccountError("sub-account name must be non-empty")
        _require_decimal(self.cash, "sub-account cash")

    @property
    def available_cash(self) -> Decimal:
        """Cash currently available in this sub-account."""
        return self.cash

    def snapshot(self, last_prices: Mapping[str, Decimal] | None = None) -> SubAccountSnapshot:
        """Return an immutable view of this sub-account."""
        prices = last_prices or {}
        equity = self.cash + self.margin_state.variation_pnl_cumulative
        for symbol, position in self.positions.items():
            price = prices.get(symbol, position.last_price)
            if price is not None:
                equity += position.qty * price * position.multiplier
        return SubAccountSnapshot(
            name=self.name,
            cash=self.cash,
            positions=dict(self.positions),
            margin_state=self.margin_state,
            available_cash=self.available_cash,
            equity=equity,
            nav=equity,
        )


@dataclass(init=False)
class Account:
    """Mutable cash and position state used by the execution loop."""

    initial_cash: Decimal
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    frozen_cash: Decimal = _DECIMAL_ZERO
    margin_state: MarginState = field(default_factory=MarginState)
    sub_accounts: dict[str, SubAccount] = field(default_factory=dict)
    _active_sub_account: str | None = None
    _margin_calculator: object | None = None

    def __init__(
        self,
        initial_cash: Decimal,
        cash: Decimal | None = None,
        positions: Mapping[str, Position] | None = None,
        margin_calculator: object | None = None,
    ) -> None:
        self.initial_cash = _require_decimal(initial_cash, "initial_cash")
        self.cash = _require_decimal(cash if cash is not None else initial_cash, "cash")
        self.frozen_cash = _DECIMAL_ZERO
        self.positions = dict(positions or {})
        self.margin_state = MarginState()
        self.sub_accounts = {}
        self._margin_calculator = margin_calculator

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def available_cash(self) -> Decimal:
        """Cash available for new reservations and orders (cash - frozen_cash)."""
        return self.cash - self.frozen_cash

    # ------------------------------------------------------------------
    # Cash reservation lifecycle
    # ------------------------------------------------------------------

    def reserve(self, amount: Decimal) -> None:
        """Freeze *amount* cash for a pending order.

        Raises
        ------
        AccountError
            If ``available_cash`` is insufficient.
        """
        if amount < _DECIMAL_ZERO:
            raise AccountError(f"reserve amount must be non-negative: {amount}")
        if self.available_cash < amount:
            raise AccountError(f"insufficient available cash: {self.available_cash} < {amount}")
        self.frozen_cash += amount

    def release(self, amount: Decimal) -> None:
        """Unfreeze *amount* cash after an order is rejected.

        Clamps to zero to prevent negative frozen_cash.
        """
        self.frozen_cash = max(_DECIMAL_ZERO, self.frozen_cash - amount)

    # ------------------------------------------------------------------
    # Strategy-facing snapshot
    # ------------------------------------------------------------------

    def view(self) -> AccountView:
        """Return the strategy-facing immutable account view."""
        return AccountView(
            cash=self.cash,
            positions={
                symbol: PositionView(symbol=symbol, qty=position.qty)
                for symbol, position in self.positions.items()
            },
            available_cash=self.available_cash,
        )

    # ------------------------------------------------------------------
    # Fill application
    # ------------------------------------------------------------------

    def apply(self, fill: Fill) -> None:
        """Apply one fill to cash and positions.

        Supports long (``BUY`` / ``SELL`` / ``OPEN_LONG`` / ``CLOSE_LONG``)
        and short (``OPEN_SHORT`` / ``CLOSE_SHORT``) orders.

        When ``active_sub_account`` is set, this fill is mirrored to the
        sub-account's cash and positions in addition to the main account.
        """
        cash_before = self.cash
        self._dispatch_fill(fill)

        # Mirror to active sub-account if set.
        if self._active_sub_account is not None:
            sub = self.sub_accounts[self._active_sub_account]
            delta = self.cash - cash_before
            sub.cash += delta
            # Sync position snapshot from main account
            main_pos = self.positions.get(fill.symbol)
            if main_pos is not None and main_pos.qty != _DECIMAL_ZERO:
                sub.positions[fill.symbol] = Position(
                    symbol=main_pos.symbol,
                    qty=main_pos.qty,
                    avg_cost=main_pos.avg_cost,
                    last_price=main_pos.last_price,
                    realized_pnl=main_pos.realized_pnl,
                    margin_held=main_pos.margin_held,
                    asset_class=main_pos.asset_class,
                    multiplier=main_pos.multiplier,
                )
            elif fill.symbol in sub.positions:
                del sub.positions[fill.symbol]

    def _dispatch_fill(self, fill: Fill) -> None:
        """Internal dispatch: route *fill* to the correct handler."""
        if fill.side in _LONG_BUY_SIDES:
            self._apply_buy(fill)
        elif fill.side in _LONG_SELL_SIDES:
            self._apply_sell(fill)
        elif fill.side in _SHORT_SELL_SIDES:
            self._apply_open_short(fill)
        elif fill.side in _SHORT_BUY_SIDES:
            self._apply_close_short(fill)
        else:
            raise AccountError(f"unsupported side for account apply: {fill.side.value}")

    def equity(self, last_prices: Mapping[str, Decimal]) -> Decimal:
        """Return cash plus marked positions using the supplied last prices."""
        equity = self.cash + self.margin_state.variation_pnl_cumulative
        for symbol, position in self.positions.items():
            price = last_prices.get(symbol, position.last_price)
            if price is None:
                continue
            _require_decimal(price, f"last price for {symbol}")
            equity += position.qty * price * position.multiplier
        return equity

    @property
    def total_realized_pnl(self) -> Decimal:
        """Return the sum of realized PnL across all positions."""
        total = _DECIMAL_ZERO
        for position in self.positions.values():
            total += position.realized_pnl
        return total

    def sub_account_equity_map(self, last_prices: Mapping[str, Decimal]) -> dict[str, Decimal]:
        """Return per-sub-account equity keyed by sub-account name.

        Each sub-account's equity is computed from its own cash plus the
        market value of positions mirrored from the main account.
        When no sub-accounts exist, returns an empty dict.
        """
        result: dict[str, Decimal] = {}
        for name, sub in self.sub_accounts.items():
            equity = sub.cash + sub.margin_state.variation_pnl_cumulative
            for symbol, pos in sub.positions.items():
                price = last_prices.get(symbol, pos.last_price)
                if price is not None and pos.qty != _DECIMAL_ZERO:
                    equity += pos.qty * price * pos.multiplier
            result[name] = equity
        return result

    def gross_exposure(self, last_prices: Mapping[str, Decimal]) -> Decimal:
        """Return the absolute sum of position market values (with multiplier)."""
        total = _DECIMAL_ZERO
        for symbol, position in self.positions.items():
            price = last_prices.get(symbol, position.last_price)
            if price is None or position.qty == _DECIMAL_ZERO:
                continue
            total += abs(position.qty) * price * position.multiplier
        return total

    def add_sub_account(self, name: str, cash: Decimal) -> SubAccount:
        """Create and register a minimal sub-account."""
        if name in self.sub_accounts:
            raise AccountError(f"sub-account already exists: {name}")
        sub_account = SubAccount(name=name, cash=_require_decimal(cash, "sub-account cash"))
        self.sub_accounts[name] = sub_account
        return sub_account

    def get_sub_account(self, name: str) -> SubAccount:
        """Return the sub-account with *name*.

        Raises ``AccountError`` if the sub-account does not exist.
        """
        try:
            return self.sub_accounts[name]
        except KeyError:
            raise AccountError(f"sub-account not found: {name}") from None

    @property
    def active_sub_account(self) -> str | None:
        """Name of the sub-account that receives routed fills (or ``None``)."""
        return self._active_sub_account

    @active_sub_account.setter
    def active_sub_account(self, name: str | None) -> None:
        if name is not None and name not in self.sub_accounts:
            raise AccountError(f"cannot activate unknown sub-account: {name}")
        self._active_sub_account = name

    def force_close_position(
        self,
        symbol: str,
        price: Decimal,
        dt: datetime,
        qty: Decimal | None = None,
    ) -> Fill:
        """Force-close a long or short position with a synthetic fill."""
        _require_decimal(price, "force close price")
        require_shanghai_aware(dt)
        position = self.positions.get(symbol)
        if position is None or position.qty == _DECIMAL_ZERO:
            raise AccountError("no position to force close")

        close_qty = abs(position.qty) if qty is None else _require_decimal(qty, "force close qty")
        if close_qty <= _DECIMAL_ZERO:
            raise AccountError("force close qty must be positive")
        if close_qty > abs(position.qty):
            raise AccountError("force close qty exceeds position quantity")

        side = Side.CLOSE_LONG if position.qty > _DECIMAL_ZERO else Side.CLOSE_SHORT
        from getrich_backtest.execution import Fill  # noqa: PLC0415

        fill = Fill(
            fill_id=f"force-close-{symbol}-{dt.isoformat()}",
            order_id=f"force-close-{symbol}-{dt.isoformat()}",
            strategy_name="RiskManager",
            symbol=symbol,
            side=side,
            qty=close_qty,
            price=price,
            notional=close_qty * price,
            fee=_DECIMAL_ZERO,
            fill_time=dt,
            bar_dt=dt,
            tag="forced_liquidation",
        )
        self.apply(fill)
        return fill

    def _position(self, symbol: str) -> Position:
        position = self.positions.get(symbol)
        if position is None:
            position = Position(symbol=symbol)
            self.positions[symbol] = position
        return position

    def _apply_buy(self, fill: Fill) -> None:
        total_cost = fill.notional + fill.fee
        if self.cash < total_cost:
            raise AccountError("insufficient cash")

        position = self._position(fill.symbol)
        old_qty = position.qty
        new_qty = old_qty + fill.qty
        if new_qty <= _DECIMAL_ZERO:
            raise AccountError("buy fill produced non-positive position quantity")

        position.avg_cost = ((old_qty * position.avg_cost) + fill.notional) / new_qty
        position.qty = new_qty
        position.last_price = fill.price
        self.cash -= total_cost
        # Release frozen cash (the reserve that was placed before matching)
        self.frozen_cash = max(_DECIMAL_ZERO, self.frozen_cash - total_cost)

        # Deduct margin if MarginCalculator is available and this is OPEN_LONG
        if self._margin_calculator is not None and fill.side == Side.OPEN_LONG:
            self._apply_buy_margin(fill, position)

    def _apply_buy_margin(self, fill: Fill, position: Position) -> None:
        """Compute and deduct margin for an OPEN_LONG fill."""
        from getrich_backtest.margin import MarginCalculator  # noqa: F811

        calc: MarginCalculator = self._margin_calculator  # type: ignore[assignment]
        margin = calc.initial_margin(fill.symbol, fill.qty, fill.price, Side.OPEN_LONG)
        if margin > _DECIMAL_ZERO:
            position.asset_class = calc.asset_class_for(fill.symbol)
            position.multiplier = calc.multiplier_for(fill.symbol)
            position.margin_held += margin
            self.margin_state.initial_margin += margin
            self.margin_state.maintenance_margin += margin

    def _apply_sell(self, fill: Fill) -> None:
        position = self._position(fill.symbol)
        if position.qty < fill.qty:
            raise AccountError("insufficient position quantity")

        # Release margin proportionally for CLOSE_LONG
        if self._margin_calculator is not None and fill.side == Side.CLOSE_LONG:
            close_ratio = fill.qty / position.qty
            released = position.margin_held * close_ratio
            position.margin_held -= released
            self.margin_state.initial_margin -= released
            self.margin_state.maintenance_margin -= released

        position.qty -= fill.qty
        position.realized_pnl += (fill.price - position.avg_cost) * fill.qty - fill.fee
        position.last_price = fill.price
        self.cash += fill.notional - fill.fee

        if position.qty == _DECIMAL_ZERO:
            position.avg_cost = _DECIMAL_ZERO
            position.margin_held = _DECIMAL_ZERO

    # ------------------------------------------------------------------
    # Short selling (P9 Phase 2)
    # ------------------------------------------------------------------

    def _apply_open_short(self, fill: Fill) -> None:
        """Sell to open a short position.

        Cash INCREASES from the short sale. Margin is deducted using
        the short margin ratio.
        """
        position = self._position(fill.symbol)
        if position.qty > _DECIMAL_ZERO:
            raise AccountError("cannot open short when long position exists")

        old_abs = abs(position.qty)
        new_abs = old_abs + fill.qty
        if old_abs > _DECIMAL_ZERO:
            position.avg_cost = ((old_abs * position.avg_cost) + (fill.qty * fill.price)) / new_abs
        else:
            position.avg_cost = fill.price

        position.qty -= fill.qty  # more negative
        position.last_price = fill.price
        self.cash += fill.notional - fill.fee

        # Deduct margin using OPEN_SHORT side
        if self._margin_calculator is not None:
            from getrich_backtest.margin import MarginCalculator  # noqa: F811

            calc: MarginCalculator = self._margin_calculator  # type: ignore[assignment]
            margin = calc.initial_margin(fill.symbol, fill.qty, fill.price, Side.OPEN_SHORT)
            if margin > _DECIMAL_ZERO:
                position.asset_class = calc.asset_class_for(fill.symbol)
                position.multiplier = calc.multiplier_for(fill.symbol)
                position.margin_held += margin
                self.margin_state.initial_margin += margin
                self.margin_state.maintenance_margin += margin

    def _apply_close_short(self, fill: Fill) -> None:
        """Buy to cover a short position.

        Cash DECREASES. Margin is released proportionally.
        PnL = ``(avg_cost - fill_price) * fill.qty - fill.fee``.
        """
        total_cost = fill.notional + fill.fee
        if self.cash < total_cost:
            raise AccountError("insufficient cash")

        position = self._position(fill.symbol)
        if position.qty >= _DECIMAL_ZERO:
            raise AccountError("no short position to close")
        if position.qty + fill.qty > _DECIMAL_ZERO:
            raise AccountError("close short would exceed short position")

        # Release margin proportionally
        if self._margin_calculator is not None:
            close_ratio = fill.qty / abs(position.qty)
            released = position.margin_held * close_ratio
            position.margin_held -= released
            self.margin_state.initial_margin -= released
            self.margin_state.maintenance_margin -= released

        # Realized PnL for short: (avg_cost - price) * qty - fee
        position.realized_pnl += (position.avg_cost - fill.price) * fill.qty - fill.fee

        position.qty += fill.qty  # toward zero
        position.last_price = fill.price
        self.cash -= total_cost
        # Release frozen cash (the reserve placed before matching)
        self.frozen_cash = max(_DECIMAL_ZERO, self.frozen_cash - total_cost)

        if position.qty == _DECIMAL_ZERO:
            position.avg_cost = _DECIMAL_ZERO
            position.margin_held = _DECIMAL_ZERO

    def apply_corporate_action(
        self,
        symbol: str,
        action_type: str,
        amount: float | None = None,
        split_ratio: float | None = None,
        bonus_ratio: float | None = None,
        dividend_tax_rate: Decimal | None = None,
    ) -> None:
        """Apply a corporate action to the account.

        Mirrors cash and position changes to all sub-accounts that hold
        the affected symbol (consistent with :meth:`apply`).

        Parameters
        ----------
        symbol : str
            The instrument symbol.
        action_type : str
            One of ``"dividend"``, ``"split"``, ``"bonus"``, ``"rights"``.
        amount : float | None
            Cash dividend per share (required for ``"dividend"``).
        split_ratio : float | None
            Split ratio (required for ``"split"``).
        bonus_ratio : float | None
            Bonus share ratio (required for ``"bonus"``).
        dividend_tax_rate : Decimal | None
            Tax rate on dividends (default 10% for A-shares).
        """
        pos = self._position(symbol)
        if dividend_tax_rate is None:
            dividend_tax_rate = Decimal("0.10")

        cash_before = self.cash

        if action_type == "dividend":
            if amount is None:
                raise CorporateActionError("dividend requires 'amount'")
            per_share = Decimal(str(amount))
            net_dividend = pos.qty * per_share * (Decimal("1") - dividend_tax_rate)
            self.cash += net_dividend

        elif action_type == "split":
            if split_ratio is None:
                raise CorporateActionError("split requires 'split_ratio'")
            ratio = Decimal(str(split_ratio))
            pos.qty = Decimal(str(int(pos.qty * ratio)))
            pos.avg_cost /= ratio

        elif action_type == "bonus":
            if bonus_ratio is None:
                raise CorporateActionError("bonus requires 'bonus_ratio'")
            ratio = Decimal(str(bonus_ratio))
            pos.qty = Decimal(str(int(pos.qty * (Decimal("1") + ratio))))
            pos.avg_cost /= Decimal("1") + ratio

        elif action_type == "rights":
            # Default: waive rights issue
            pass

        else:
            raise CorporateActionError(f"unknown action_type: '{action_type}'")

        # Mirror to sub-accounts holding this symbol.
        cash_delta = self.cash - cash_before
        for sub in self.sub_accounts.values():
            sub_pos = sub.positions.get(symbol)
            if sub_pos is None or sub_pos.qty == _DECIMAL_ZERO:
                continue
            # Mirror cash delta (dividend)
            if cash_delta != _DECIMAL_ZERO:
                sub.cash += cash_delta
            # Sync position state from main (splits, bonuses)
            sub_pos.qty = pos.qty
            sub_pos.avg_cost = pos.avg_cost


# ---------------------------------------------------------------------------
# Daily settlement
# ---------------------------------------------------------------------------


def _check_margin_call(account: Account, dt: datetime) -> None:
    """Set ``margin_call_triggered`` if maintenance margin is breached."""
    if account.margin_state.maintenance_margin <= _DECIMAL_ZERO:
        return
    if account.available_cash < account.margin_state.maintenance_margin:
        account.margin_state.margin_call_triggered = True
        account.margin_state.last_margin_call_dt = dt


def get_settlement_prices(
    bar: pl.DataFrame,
    last_prices: Mapping[str, Decimal],
) -> dict[str, Decimal]:
    """Extract settlement prices from *bar* data, falling back to last_price.

    Prefers the optional ``settlement`` column if present, otherwise uses
    ``close`` from *last_prices*.
    """
    pass  # runtime import not needed — TYPE_CHECKING above covers annotation

    settle_prices: dict[str, Decimal] = {}
    if "settlement" in bar.columns:
        for row in bar.select(["symbol", "settlement"]).iter_rows(named=True):
            sym: str = row["symbol"]
            val = row.get("settlement")
            if val is not None:
                settle_prices[sym] = Decimal(str(val))
    # Fall back to last_prices for symbols not in the settlement column
    for sym in last_prices:
        if sym not in settle_prices and last_prices[sym] is not None:
            settle_prices[sym] = last_prices[sym]
    return settle_prices


def daily_settle(
    account: Account,
    settlement_prices: Mapping[str, Decimal],
    dt: datetime,
) -> list[dict[str, object]]:
    """Apply daily mark-to-market settlement for margined positions.

    For each futures position with non-zero qty:
    1. Compute variation PnL = ``(settle - avg_cost) × qty × multiplier``
       and add to cash.
    2. Reset ``avg_cost`` to the settlement price.
    3. Recalculate ``margin_held`` at the settlement price.
    4. Update ``last_price``.

    After all positions are settled, aggregate margin totals are
    recomputed and a margin-call check is performed.

    Parameters
    ----------
    account : Account
        The account to settle.
    settlement_prices : Mapping[str, Decimal]
        Settlement prices keyed by symbol.
    dt : datetime
        Current date (for margin-call timestamp).

    Returns
    -------
    list[dict[str, object]]
        Settlement event records (for future ledger integration).
    """
    futures_classes = {AssetClass.COMMODITY_FUTURE, AssetClass.INDEX_FUTURE}
    events: list[dict[str, object]] = []

    for symbol, position in list(account.positions.items()):
        if position.qty == _DECIMAL_ZERO:
            continue
        if position.asset_class not in futures_classes:
            continue

        settle_price = settlement_prices.get(symbol, position.last_price)
        if settle_price is None:
            continue

        # Step 1-2: Variation PnL
        variation_pnl = (settle_price - position.avg_cost) * position.qty * position.multiplier
        if variation_pnl != _DECIMAL_ZERO:
            account.cash += variation_pnl
            account.margin_state.variation_pnl_cumulative += variation_pnl

        # Step 3: Reset avg_cost to settlement price
        position.avg_cost = settle_price

        # Step 4: Recalculate margin_held at settlement price
        if account._margin_calculator is not None:
            from getrich_backtest.margin import MarginCalculator  # noqa: F811

            calc: MarginCalculator = account._margin_calculator  # type: ignore[assignment]
            side = Side.OPEN_LONG if position.qty > _DECIMAL_ZERO else Side.OPEN_SHORT
            position.margin_held = calc.initial_margin(symbol, position.qty, settle_price, side)

        position.last_price = settle_price

        # Mirror settlement to sub-accounts holding this symbol.
        for sub in account.sub_accounts.values():
            sub_pos = sub.positions.get(symbol)
            if sub_pos is None or sub_pos.qty == _DECIMAL_ZERO:
                continue
            # Apply the same variation PnL to sub-account cash.
            if variation_pnl != _DECIMAL_ZERO:
                sub.cash += variation_pnl
                sub.margin_state.variation_pnl_cumulative += variation_pnl
            # Sync position state from main (avg_cost already reset).
            sub_pos.avg_cost = settle_price
            sub_pos.last_price = settle_price
            sub_pos.margin_held = position.margin_held

        events.append(
            {
                "dt": dt,
                "symbol": symbol,
                "type": "variation_margin",
                "variation_pnl": variation_pnl,
                "settle_price": settle_price,
                "margin_held": position.margin_held,
            }
        )

    # Recalculate aggregate margin totals (main account)
    total_initial = _DECIMAL_ZERO
    total_maint = _DECIMAL_ZERO
    for pos in account.positions.values():
        total_initial += pos.margin_held
        total_maint += pos.margin_held
    account.margin_state.initial_margin = total_initial
    account.margin_state.maintenance_margin = total_maint

    # Recalculate sub-account margin totals
    for sub in account.sub_accounts.values():
        sub_initial = _DECIMAL_ZERO
        sub_maint = _DECIMAL_ZERO
        for pos in sub.positions.values():
            sub_initial += pos.margin_held
            sub_maint += pos.margin_held
        sub.margin_state.initial_margin = sub_initial
        sub.margin_state.maintenance_margin = sub_maint

    # Margin-call check
    _check_margin_call(account, dt)

    return events
