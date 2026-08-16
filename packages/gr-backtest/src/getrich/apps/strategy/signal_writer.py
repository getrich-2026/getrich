"""Async writer that persists Signal objects to PostgreSQL."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from getrich.apps.strategy.errors import SignalWriteError
from getrich.apps.web.metrics import LIVE_SIGNALS_PERSISTED_TOTAL
from gr_data.db.pool import PgConnectionPool, pg_pool
from getrich_backtest.live.signal import Signal


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_TABLE = "signals"

_INSERT_SQL = f"""
    INSERT INTO {_TABLE} (
        id, signal_code, strategy_id, type, action,
        direction, symbol, symbol_name, exchange,
        trigger_price, target_price, stop_loss_price,
        suggested_quantity, position_pct, confidence,
        urgency, reason, status, published_at
    ) VALUES (
        %(id)s, %(code)s, %(strategy_id)s, %(type)s, %(action)s,
        %(direction)s, %(symbol)s, %(symbol_name)s, %(exchange)s,
        %(trigger_price)s, %(target_price)s, %(stop_loss_price)s,
        %(suggested_qty)s, %(position_pct)s, %(confidence)s,
        %(urgency)s, %(reason)s, %(status)s, %(published_at)s
    )
    ON CONFLICT (strategy_id, symbol, published_at) DO NOTHING
    RETURNING signal_code
"""


def _make_signal_code() -> str:
    """Generate a human-readable signal code like ``SIG_20260531_A1B2C3``."""
    from datetime import datetime

    from getrich_backtest import get_shanghai_tz

    today = datetime.now(get_shanghai_tz()).strftime("%Y%m%d")
    suffix = uuid4().hex[:6].upper()
    return f"SIG_{today}_{suffix}"


def _to_params(signal: Signal, strategy_id: str, signal_id: str, signal_code: str) -> dict:
    """Convert a Signal dataclass to SQL INSERT params.

    Raises
    ------
    SignalWriteError
        If *signal.trigger_time* is ``None`` (required for idempotency).
    """
    if signal.trigger_time is None:
        raise SignalWriteError(
            f"signal.trigger_time must not be None (symbol={signal.symbol}, action={signal.action})"
        )
    return {
        "id": signal_id,
        "code": signal_code,
        "strategy_id": strategy_id,
        "type": signal.signal_type,
        "action": signal.action,
        "direction": signal.direction,
        "symbol": signal.symbol,
        "symbol_name": signal.symbol_name,
        "exchange": signal.exchange,
        "trigger_price": float(signal.trigger_price) if signal.trigger_price is not None else None,
        "target_price": float(signal.target_price) if signal.target_price is not None else None,
        "stop_loss_price": (
            float(signal.stop_loss_price) if signal.stop_loss_price is not None else None
        ),
        "suggested_qty": signal.suggested_quantity,
        "position_pct": float(signal.position_pct) if signal.position_pct is not None else None,
        "confidence": float(signal.confidence) if signal.confidence is not None else 0.50,
        "urgency": signal.urgency,
        "reason": signal.reason,
        "status": signal.status,
        "published_at": signal.trigger_time,
    }


class PgSignalWriter:
    """Async writer that persists ``Signal`` objects to PostgreSQL.

    Uses the global ``pg_pool`` singleton by default.  All write operations
    are transactional — the caller is responsible for calling ``commit()``
    when using ``write_one()`` with an explicit connection, or
    :meth:`write_batch` handles it automatically.

    Parameters
    ----------
    pool : PgConnectionPool | None
        Connection pool instance (default: ``pg_pool``).
    """

    def __init__(self, pool: PgConnectionPool | None = None) -> None:
        self._pool = pool or pg_pool

    async def write_one(
        self,
        signal: Signal,
        strategy_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> str | None:
        """Write a single signal to the ``signals`` table.

        Uses ``ON CONFLICT DO NOTHING`` — if a signal with the same
        ``(strategy_id, symbol, published_at)`` already exists, the
        insert is skipped and ``None`` is returned.

        Parameters
        ----------
        signal : Signal
            The signal to persist.  ``trigger_time`` must not be ``None``.
        strategy_id : str
            Internal UUID of the strategy (from ``strategies.id``).
        conn : AsyncConnection | None
            Optional existing connection for transaction grouping.
            When *None*, acquires a connection from the pool.

        Returns
        -------
        str | None
            The generated ``signal_code`` if the row was inserted,
            ``None`` if it was a duplicate (suppressed by conflict).

        Raises
        ------
        SignalWriteError
            If ``signal.trigger_time`` is ``None`` or the database
            operation fails.
        """
        signal_id = str(uuid4())
        signal_code = _make_signal_code()
        params = _to_params(signal, strategy_id, signal_id, signal_code)

        async def _do(c: AsyncConnection) -> str | None:
            try:
                async with c.cursor() as cur:
                    await cur.execute(_INSERT_SQL, params)
                    row = await cur.fetchone()
                # Only increment on a NEW row (not on the ON CONFLICT
                # DO NOTHING path). A duplicate means the signal was
                # already counted in a previous tick.
                if row is not None:
                    LIVE_SIGNALS_PERSISTED_TOTAL.inc()
                return row[0] if row is not None else None
            except Exception as exc:
                raise SignalWriteError(f"failed to write signal: {exc}") from exc

        if conn is not None:
            return await _do(conn)

        async with self._pool.connection() as c:
            result = await _do(c)
            await c.commit()
        return result

    async def write_batch(
        self,
        signals: list[Signal],
        strategy_id: str,
    ) -> list[str]:
        """Write multiple signals in a single transaction.

        Each signal is inserted with ``ON CONFLICT DO NOTHING`` —
        duplicates are silently skipped.  Only the ``signal_code``
        values for **newly inserted** rows are returned.

        Parameters
        ----------
        signals : list[Signal]
            Signals to persist.  Each signal's ``trigger_time`` must
            not be ``None``.
        strategy_id : str
            Internal UUID of the strategy.

        Returns
        -------
        list[str]
            ``signal_code`` values for rows that were actually inserted
            (duplicates are excluded).  May be shorter than *signals*.

        Raises
        ------
        SignalWriteError
            If any signal's ``trigger_time`` is ``None``, or the
            database operation fails (entire transaction rolls back).
        """
        if not signals:
            return []

        entries: list[tuple[str, dict]] = []
        for sig in signals:
            sid = str(uuid4())
            sc = _make_signal_code()
            entries.append((sc, _to_params(sig, strategy_id, sid, sc)))

        inserted: list[str] = []
        async with self._pool.connection() as conn:
            try:
                async with conn.cursor() as cur:
                    for _, params in entries:
                        await cur.execute(_INSERT_SQL, params)
                        row = await cur.fetchone()
                        if row is not None:
                            inserted.append(row[0])
            except Exception as exc:
                raise SignalWriteError(f"failed to write signal batch: {exc}") from exc
            await conn.commit()

        return inserted
