"""Target-position-based strategy abstraction.

``TargetPositionStrategy`` lets users directly specify desired positions
by overriding ``compute_target()``.  The framework computes the delta
between target and current positions and generates ``OrderIntent`` objects.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import polars as pl

from getrich_backtest.exceptions import StrategyError
from getrich_backtest.strategy.base import Strategy
from getrich_backtest.strategy.context import BarContext
from getrich_backtest.strategy.order import OrderIntent
from getrich_backtest.strategy.portfolio import _round_to_lot
from getrich_backtest.types import OrderType, Side


_DECIMAL_ZERO = Decimal("0")


class TargetPositionStrategy(Strategy):
    """Strategy that directly expresses target positions.

    Override ``compute_target()`` to return a DataFrame with columns
    ``[symbol, target_qty]`` or ``[symbol, target_weight]``.

    With **target_qty**: the framework computes
    ``delta = target_qty - current_qty`` and generates BUY/SELL orders.

    With **target_weight**: the framework computes
    ``target_qty = floor(target_weight * NAV / price)`` then the same
    delta logic.

    Parameters
    ----------
    lot_size : int
        Minimum trading unit for quantity rounding (default 100 for A-shares).

    Examples
    --------
    >>> class FixedTarget(TargetPositionStrategy):
    ...     def compute_target(self, ctx):
    ...         return pl.DataFrame({
    ...             "symbol": ["000001.SZ"],
    ...             "target_qty": [Decimal("100")],
    ...         })
    """

    def __init__(self, lot_size: int = 100) -> None:
        super().__init__()
        if lot_size <= 0:
            raise ValueError("lot_size must be positive")
        self.lot_size = lot_size

    def compute_target(self, ctx: BarContext) -> pl.DataFrame:
        """Return a DataFrame with ``[symbol, target_qty]`` or
        ``[symbol, target_weight]`` columns.

        Override this method in your subclass.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement compute_target()")

    def on_bar(self, ctx: BarContext) -> Iterable[OrderIntent] | None:
        targets = self.compute_target(ctx)
        if targets is None or targets.is_empty():
            return None

        if "target_qty" in targets.columns:
            return self._target_qty_to_intents(targets, ctx)
        if "target_weight" in targets.columns:
            return self._target_weight_to_intents(targets, ctx)

        raise StrategyError(
            "compute_target() must return a DataFrame with 'target_qty' or 'target_weight' column"
        )

    # ------------------------------------------------------------------
    # Internal: target_qty mode
    # ------------------------------------------------------------------

    def _target_qty_to_intents(
        self,
        targets: pl.DataFrame,
        ctx: BarContext,
    ) -> list[OrderIntent]:
        _require_columns(targets, ["symbol", "target_qty"])
        intents: list[OrderIntent] = []
        for row in targets.iter_rows(named=True):
            symbol = str(row["symbol"])
            target_qty = _to_decimal(row["target_qty"])
            current_qty = ctx.account.position(symbol).qty
            delta = target_qty - current_qty
            if delta > 0:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=Side.BUY,
                        qty=delta,
                        order_type=OrderType.MARKET,
                    )
                )
            elif delta < 0:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=Side.SELL,
                        qty=-delta,
                        order_type=OrderType.MARKET,
                    )
                )
        return intents

    # ------------------------------------------------------------------
    # Internal: target_weight mode
    # ------------------------------------------------------------------

    def _target_weight_to_intents(
        self,
        targets: pl.DataFrame,
        ctx: BarContext,
    ) -> list[OrderIntent]:
        _require_columns(targets, ["symbol", "target_weight"])

        # Extract prices from current bar
        prices: dict[str, Decimal] = {}
        for row in ctx.bar.select(["symbol", "close"]).iter_rows(named=True):
            close = row["close"]
            price = close if isinstance(close, Decimal) else Decimal(str(close))
            if price > _DECIMAL_ZERO:
                prices[str(row["symbol"])] = price

        # Compute NAV
        nav = ctx.account.cash
        for sym, pos in (ctx.account.positions or {}).items():
            if sym in prices:
                nav += pos.qty * prices[sym]

        if nav <= _DECIMAL_ZERO:
            return []

        intents: list[OrderIntent] = []
        for row in targets.iter_rows(named=True):
            symbol = str(row["symbol"])
            raw_wt = _to_decimal(row["target_weight"])
            price = prices.get(symbol)
            if price is None or price <= _DECIMAL_ZERO:
                continue

            target_qty = int((raw_wt * nav) // price)
            current_qty = ctx.account.position(symbol).qty
            raw_delta = Decimal(str(target_qty)) - current_qty
            delta = _round_to_lot(raw_delta, self.lot_size)

            if delta > 0:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=Side.BUY,
                        qty=delta,
                        order_type=OrderType.MARKET,
                    )
                )
            elif delta < 0:
                intents.append(
                    OrderIntent(
                        symbol=symbol,
                        side=Side.SELL,
                        qty=-delta,
                        order_type=OrderType.MARKET,
                    )
                )
        return intents


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise StrategyError(f"Cannot convert {type(value)} to Decimal")


def _require_columns(df: pl.DataFrame, expected: list[str]) -> None:
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise StrategyError(f"DataFrame missing required columns: {', '.join(missing)}")
