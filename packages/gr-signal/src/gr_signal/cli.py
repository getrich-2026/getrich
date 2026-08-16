"""CLI entry point for periodic live signal generation.

Intended to be invoked by an external scheduler every 5 minutes::

    uv run python -m gr_signal.cli

Environment variables
---------------------
GETRICH_STRATEGY : str
    Strategy name registered in ``StrategyRegistry`` (e.g. ``"macross"``).
GETRICH_STRATEGY_ID : str
    PostgreSQL UUID of the strategy row in the ``strategies`` table.
GETRICH_SYMBOLS : str
    Comma-separated list of symbols to monitor
    (e.g. ``"AU2606,SC2607"``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime

from gr_backtest import get_shanghai_tz
from gr_backtest.calendar import DEFAULT_FUTURES_SESSIONS
from gr_backtest.registry import get_registry
from gr_data.db.pool import pg_pool

from gr_signal.account_loader import AccountStateLoader
from gr_signal.live_runner import LiveSignalRunner
from gr_signal.signal_writer import PgSignalWriter


logger = logging.getLogger(__name__)

_ENV_STRATEGY = "GETRICH_STRATEGY"
_ENV_STRATEGY_ID = "GETRICH_STRATEGY_ID"
_ENV_SYMBOLS = "GETRICH_SYMBOLS"


# ---------------------------------------------------------------------------
# Market hours
# ---------------------------------------------------------------------------


def _is_trading_time() -> bool:
    """Return ``True`` if the current time falls within any default futures session."""
    tz = get_shanghai_tz()
    now = datetime.now(tz)
    hour = now.hour
    minute = now.minute
    current = hour * 60 + minute

    for session in DEFAULT_FUTURES_SESSIONS:
        start = session.start_hour * 60 + session.start_minute
        end = session.end_hour * 60 + session.end_minute

        if session.spans_midnight:
            if current >= start or current < end:
                return True
        else:
            if start <= current < end:
                return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    """Run one signal generation cycle.  Returns the process exit code."""
    strategy_name = os.environ.get(_ENV_STRATEGY, "").strip()
    strategy_id = os.environ.get(_ENV_STRATEGY_ID, "").strip()
    symbols_env = os.environ.get(_ENV_SYMBOLS, "").strip()

    # --- validate required env vars ----------------------------------------
    if not strategy_name:
        _emit({"status": "error", "message": f"{_ENV_STRATEGY} is required"})
        return 1

    if not strategy_id:
        _emit({"status": "error", "message": f"{_ENV_STRATEGY_ID} is required"})
        return 1

    # --- market hours guard ------------------------------------------------
    if not _is_trading_time():
        _emit({"status": "skipped", "message": "outside market hours"})
        return 0

    # --- symbols -----------------------------------------------------------
    symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]
    if not symbols:
        _emit({"status": "error", "message": f"{_ENV_SYMBOLS} is required and must not be empty"})
        return 1

    # --- pg pool init ------------------------------------------------------
    try:
        await pg_pool.init()
    except Exception as exc:
        _emit({"status": "error", "message": f"pg_pool init failed: {exc}"})
        return 1

    try:
        # --- build strategy ------------------------------------------------
        try:
            registry = get_registry()
            strategy = registry.build(strategy_name)
        except Exception as exc:
            _emit({"status": "error", "strategy": strategy_name, "message": str(exc)})
            return 1

        # --- run -----------------------------------------------------------
        runner = LiveSignalRunner(
            strategy,
            strategy_id=strategy_id,
            account_loader=AccountStateLoader(),
            signal_writer=PgSignalWriter(),
        )
        result = await runner.run_once(symbols)

        # --- emit result ---------------------------------------------------
        _emit(
            {
                "status": "ok" if result.error is None else "error",
                "strategy": strategy_name,
                "n_signals": result.n_signals,
                "signal_codes": result.signal_codes,
                "triggered_at": result.triggered_at.isoformat(),
                "duration_ms": round(result.duration_ms, 2),
                "error": result.error,
            }
        )
        return 0 if result.error is None else 1

    except Exception as exc:
        _emit({"status": "error", "strategy": strategy_name, "message": str(exc)})
        return 1

    finally:
        await pg_pool.close()


def _emit(payload: dict) -> None:
    """Write a single JSON line to stdout for journald / docker log collection."""
    print(json.dumps(payload, default=str), flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    sys.exit(asyncio.run(main()))
