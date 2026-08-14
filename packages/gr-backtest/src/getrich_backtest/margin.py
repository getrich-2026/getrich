"""Margin calculation and management for futures and leveraged products.

Provides ``MarginCalculator`` which reads ``margin_ratio_long``,
``margin_ratio_short``, and ``multiplier`` fields from the instruments
table to compute initial and maintenance margin requirements.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl

from getrich_backtest.types import AssetClass, Side


_DECIMAL_ZERO = Decimal("0")


class MarginCalculator:
    """Computes initial and maintenance margin from instruments metadata.

    For equities (no margin ratio in the instruments table) margin is
    always zero (full-cash settlement).  For futures the formula is::

        margin = abs(qty) * price * multiplier * margin_ratio

    Parameters
    ----------
    instruments_df : pl.DataFrame | None
        Instruments table with ``symbol``, ``margin_ratio_long``,
        ``margin_ratio_short``, ``multiplier`` columns.
    """

    def __init__(self, instruments_df: pl.DataFrame | None = None) -> None:
        self._margin_ratio_long: dict[str, Decimal] = {}
        self._margin_ratio_short: dict[str, Decimal] = {}
        self._multipliers: dict[str, Decimal] = {}
        self._asset_classes: dict[str, AssetClass] = {}
        if instruments_df is not None:
            self.update_instruments(instruments_df)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initial_margin(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        side: Side,
    ) -> Decimal:
        """Compute the initial margin required to open or hold a position.

        Parameters
        ----------
        symbol : str
            Instrument symbol.
        qty : Decimal
            Position quantity (sign ignored — absolute value used).
        price : Decimal
            Current price (or settlement price).
        side : Side
            ``Side.OPEN_LONG`` / ``Side.BUY`` uses ``margin_ratio_long``;
            ``Side.OPEN_SHORT`` uses ``margin_ratio_short``.

        Returns
        -------
        Decimal
            Margin amount.  Zero if no margin ratio is registered for the
            symbol (e.g. equities).
        """
        ratio = self._ratio_for(symbol, side)
        if ratio == _DECIMAL_ZERO:
            return _DECIMAL_ZERO
        mult = self._multipliers.get(symbol, Decimal("1"))
        return abs(qty) * price * mult * ratio

    def maintenance_margin(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        side: Side = Side.OPEN_LONG,
    ) -> Decimal:
        """Compute maintenance margin.

        Phase 1 simplification: same as initial margin.  The *side*
        parameter selects the long or short margin ratio (default
        ``OPEN_LONG`` for backward compatibility).
        """
        return self._margin_for(symbol, qty, price, side)

    def total_initial_margin(
        self,
        symbols: list[str],
        qtys: list[Decimal],
        prices: list[Decimal],
        sides: list[Side],
    ) -> Decimal:
        """Sum of initial margin across a collection of positions."""
        total = _DECIMAL_ZERO
        for sym, qty, price, side in zip(symbols, qtys, prices, sides, strict=True):
            if qty == _DECIMAL_ZERO:
                continue
            total += self.initial_margin(sym, qty, price, side)
        return total

    def update_instruments(self, instruments_df: pl.DataFrame) -> None:
        """Refresh the internal symbol cache from an instruments table."""
        self._margin_ratio_long.clear()
        self._margin_ratio_short.clear()
        self._multipliers.clear()
        self._asset_classes.clear()
        for row in instruments_df.iter_rows(named=True):
            sym: str = row["symbol"]
            if "margin_ratio_long" in row and row["margin_ratio_long"] is not None:
                self._margin_ratio_long[sym] = Decimal(str(row["margin_ratio_long"]))
            if "margin_ratio_short" in row and row["margin_ratio_short"] is not None:
                self._margin_ratio_short[sym] = Decimal(str(row["margin_ratio_short"]))
            if "multiplier" in row and row["multiplier"] is not None:
                self._multipliers[sym] = Decimal(str(row["multiplier"]))
            if "asset_class" in row and row["asset_class"] is not None:
                self._asset_classes[sym] = AssetClass(str(row["asset_class"]))

    def multiplier_for(self, symbol: str) -> Decimal:
        """Return the registered contract multiplier for *symbol*."""
        return self._multipliers.get(symbol, Decimal("1"))

    def asset_class_for(self, symbol: str) -> AssetClass:
        """Return the registered asset class for *symbol*."""
        return self._asset_classes.get(symbol, AssetClass.EQUITY_A)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ratio_for(self, symbol: str, side: Side) -> Decimal:
        if side in {Side.BUY, Side.OPEN_LONG}:
            return self._margin_ratio_long.get(symbol, _DECIMAL_ZERO)
        return self._margin_ratio_short.get(symbol, _DECIMAL_ZERO)

    def _margin_for(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        side: Side,
    ) -> Decimal:
        return self.initial_margin(symbol, qty, price, side)
