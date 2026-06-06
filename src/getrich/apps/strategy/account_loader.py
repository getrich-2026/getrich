"""Async PostgreSQL reader for live account state and positions.

Gracefully degrades to zero-state ``AccountView`` when live account tables
don't exist or the database is unreachable.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from getrich.libs.postgres.pool import PgConnectionPool, pg_pool
from getrich_backtest.strategy.context import AccountView, PositionView


logger = logging.getLogger(__name__)

_DECIMAL_ZERO = Decimal("0")


class AccountStateLoader:
    """Load live account state (cash + positions) from PostgreSQL.

    Queries the ``live_account_state`` and ``live_positions`` tables.
    When those tables don't exist or the database is unreachable the
    loader returns a zero-state ``AccountView`` and emits a warning.

    Parameters
    ----------
    pool : PgConnectionPool | None
        Connection pool instance (default: global ``pg_pool`` singleton).
    """

    def __init__(self, pool: PgConnectionPool | None = None) -> None:
        self._pool = pool or pg_pool

    async def load_account_view(self, *, strategy_id: str | None = None) -> AccountView:
        """Load the current account state from PostgreSQL.

        When *strategy_id* is provided the loader resolves it to a
        sub-account ID via ``strategy_sub_account_mapping`` before
        querying cash and positions.  When *strategy_id* is ``None``
        (default) the global account (``id=1``) is used — this is
        fully backward compatible.

        Parameters
        ----------
        strategy_id : str | None
            Strategy UUID.  Omitting it loads the global account.

        Returns
        -------
        AccountView
            Live account state, or a zero-state fallback when the
            live tables are unavailable.
        """
        try:
            account_id = await self._resolve_account_id(strategy_id) if strategy_id else 1
            cash, available_cash, maintenance_margin = await self._load_cash(account_id)
            positions = await self._load_positions(account_id)
            return AccountView(
                cash=cash,
                positions=positions,
                available_cash=available_cash,
                maintenance_margin=maintenance_margin,
            )
        except Exception as exc:
            logger.warning("Failed to load live account state, using zero fallback: %s", exc)
            return AccountView()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _resolve_account_id(self, strategy_id: str) -> int:
        """Resolve *strategy_id* to a sub-account ID.

        Queries ``strategy_sub_account_mapping``.  When the mapping
        table does not exist or *strategy_id* has no entry the method
        falls back to ``1`` (global account).
        """
        try:
            async with self._pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "SELECT sub_account_id FROM strategy_sub_account_mapping "
                    "WHERE strategy_id = %(strategy_id)s",
                    {"strategy_id": strategy_id},
                )
                row = await cur.fetchone()
            if row is not None:
                return row["sub_account_id"]
        except Exception:
            logger.debug(
                "strategy_sub_account_mapping table not available, "
                "falling back to global account id=1"
            )
        return 1

    async def _load_cash(self, account_id: int = 1) -> tuple[Decimal, Decimal, Decimal]:
        """Load cash / available_cash / maintenance_margin from ``live_account_state``.

        Returns ``(cash, available_cash, maintenance_margin)`` — each
        field defaults to zero when the table or column is unavailable.
        """
        try:
            async with self._pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "SELECT cash, available_cash, maintenance_margin "
                    "FROM live_account_state WHERE id = %(id)s",
                    {"id": account_id},
                )
                row = await cur.fetchone()
            if row is not None:
                cash = row["cash"]
                available_cash = row["available_cash"]
                # maintenance_margin column may not exist in older schemas
                maintenance_margin = row.get("maintenance_margin", _DECIMAL_ZERO)
                return (cash, available_cash, maintenance_margin)
            return (_DECIMAL_ZERO, _DECIMAL_ZERO, _DECIMAL_ZERO)
        except Exception:
            logger.debug("live_account_state table not available, defaulting cash to zero")
            return (_DECIMAL_ZERO, _DECIMAL_ZERO, _DECIMAL_ZERO)

    async def _load_positions(self, account_id: int = 1) -> dict[str, PositionView]:
        """Load non-zero positions from ``live_positions`` for a given account."""
        try:
            async with self._pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    "SELECT symbol, qty FROM live_positions "
                    "WHERE account_id = %(account_id)s AND qty != 0",
                    {"account_id": account_id},
                )
                rows = await cur.fetchall()
            result: dict[str, PositionView] = {}
            if rows:
                for row in rows:
                    symbol = row["symbol"]
                    qty = row["qty"]
                    if qty != _DECIMAL_ZERO:
                        result[symbol] = PositionView(symbol=symbol, qty=qty)
            return result
        except Exception:
            logger.debug("live_positions table not available, defaulting to empty")
            return {}
