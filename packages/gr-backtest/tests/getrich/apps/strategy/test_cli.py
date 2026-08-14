"""Tests for the live signal CLI entry point."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from getrich.apps.strategy.cli import (
    _ENV_STRATEGY,
    _ENV_STRATEGY_ID,
    _ENV_SYMBOLS,
    main,
)


TZ = __import__("getrich_backtest", fromlist=["get_shanghai_tz"]).get_shanghai_tz()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strategy():
    """Return a minimal Strategy-like mock."""
    s = MagicMock()
    return s


def _result(
    *,
    n_signals: int = 1,
    signal_codes: list[str] | None = None,
    error: str | None = None,
) -> MagicMock:
    result = MagicMock()
    result.n_signals = n_signals
    result.signal_codes = signal_codes or ["SIG_20260601_ABCDEF"]
    result.triggered_at = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
    result.duration_ms = 42.0
    result.error = error
    return result


def _make_runner_mock(result=None, exc=None):
    """Create a mock LiveSignalRunner."""
    runner = MagicMock()
    if exc is not None:
        runner.run_once = AsyncMock(side_effect=exc)
    else:
        runner.run_once = AsyncMock(return_value=result or _result())
    return runner


def _set_env(**kwargs: str) -> None:
    """Set env vars for the test."""
    for k, v in kwargs.items():
        if v is None:
            continue
        import os

        os.environ[k] = v


def _del_env(*keys: str) -> None:
    import os

    for k in keys:
        os.environ.pop(k, None)


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Market hours
# ---------------------------------------------------------------------------


class TestIsTradingTime:
    def test_detect_night_session(self):
        """Night session (21:00-02:30) should be detected as trading time."""
        from getrich_backtest.calendar import DEFAULT_FUTURES_SESSIONS

        sessions = DEFAULT_FUTURES_SESSIONS
        assert len(sessions) == 3
        night = sessions[0]
        assert night.spans_midnight is True
        assert night.start_hour == 21
        assert night.end_hour == 2

    def test_detect_day_sessions(self):
        """Morning and afternoon sessions should be detected."""
        from getrich_backtest.calendar import DEFAULT_FUTURES_SESSIONS

        sessions = DEFAULT_FUTURES_SESSIONS
        morning = sessions[1]
        afternoon = sessions[2]
        assert morning.start_hour == 9
        assert afternoon.start_hour == 13


# ---------------------------------------------------------------------------
# CLI main
# ---------------------------------------------------------------------------


class TestCliMain:
    def test_missing_strategy_env_var_returns_1(self):
        """Missing GETRICH_STRATEGY exits with code 1."""
        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        _set_env(**{_ENV_STRATEGY_ID: "uuid-1", _ENV_SYMBOLS: "A,B"})

        with patch("getrich.apps.strategy.cli._is_trading_time", return_value=True):
            ret = _run(main())

        assert ret == 1

    def test_missing_strategy_id_env_var_returns_1(self):
        """Missing GETRICH_STRATEGY_ID exits with code 1."""
        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        _set_env(**{_ENV_STRATEGY: "macross", _ENV_SYMBOLS: "A,B"})

        with patch("getrich.apps.strategy.cli._is_trading_time", return_value=True):
            ret = _run(main())

        assert ret == 1

    def test_outside_market_hours_returns_0(self):
        """Outside market hours returns 0 (skipped, not an error)."""
        _set_env(**{_ENV_STRATEGY: "macross", _ENV_STRATEGY_ID: "uuid-1", _ENV_SYMBOLS: "A,B"})

        with patch("getrich.apps.strategy.cli._is_trading_time", return_value=False):
            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        assert ret == 0

    def test_empty_symbols_returns_1(self):
        """Empty GETRICH_SYMBOLS exits with code 1."""
        _set_env(**{_ENV_STRATEGY: "macross", _ENV_STRATEGY_ID: "uuid-1", _ENV_SYMBOLS: ""})

        with patch("getrich.apps.strategy.cli._is_trading_time", return_value=True):
            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        assert ret == 1

    def test_happy_path_returns_0_and_emits_ok(self):
        """Full happy path produces signals and returns 0."""
        _set_env(
            **{
                _ENV_STRATEGY: "macross",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "A,B",
            }
        )

        mock_result = _result(n_signals=2, signal_codes=["SIG_A", "SIG_B"])
        mock_runner = _make_runner_mock(result=mock_result)

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
            patch("getrich.apps.strategy.cli.get_registry") as mock_get_reg,
            patch("getrich.apps.strategy.cli.LiveSignalRunner", return_value=mock_runner),
        ):
            mock_registry = MagicMock()
            mock_registry.build.return_value = _strategy()
            mock_get_reg.return_value = mock_registry

            mock_pool.init = AsyncMock()
            mock_pool.close = AsyncMock()

            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)

        assert ret == 0
        mock_pool.init.assert_awaited_once()
        mock_registry.build.assert_called_once_with("macross")
        mock_runner.run_once.assert_awaited_once_with(["A", "B"])
        mock_pool.close.assert_awaited_once()

    def test_unknown_strategy_returns_1(self):
        """Unknown strategy name exits with code 1."""
        _set_env(
            **{
                _ENV_STRATEGY: "nonexistent",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "A",
            }
        )

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
            patch("getrich.apps.strategy.cli.get_registry") as mock_get_reg,
        ):
            mock_pool.init = AsyncMock()
            mock_pool.close = AsyncMock()

            mock_registry = MagicMock()
            mock_registry.build.side_effect = ValueError("Unknown strategy 'nonexistent'")
            mock_get_reg.return_value = mock_registry

            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        assert ret == 1

    def test_pg_pool_init_failure_returns_1(self):
        """pg_pool.init() failure exits with code 1."""
        _set_env(
            **{
                _ENV_STRATEGY: "macross",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "A,B",
            }
        )

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
        ):
            mock_pool.init = AsyncMock(side_effect=RuntimeError("connection refused"))

            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        assert ret == 1

    def test_runner_error_returns_1(self):
        """Runner failure exits with code 1."""
        _set_env(
            **{
                _ENV_STRATEGY: "macross",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "A,B",
            }
        )

        mock_runner = _make_runner_mock(exc=RuntimeError("clickhouse unreachable"))

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
            patch("getrich.apps.strategy.cli.get_registry") as mock_get_reg,
            patch("getrich.apps.strategy.cli.LiveSignalRunner", return_value=mock_runner),
        ):
            mock_registry = MagicMock()
            mock_registry.build.return_value = _strategy()
            mock_get_reg.return_value = mock_registry

            mock_pool.init = AsyncMock()
            mock_pool.close = AsyncMock()

            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        assert ret == 1

    def test_zero_signals_returns_0(self):
        """Zero signals produced is still a successful run (exit 0)."""
        _set_env(
            **{
                _ENV_STRATEGY: "macross",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "A,B",
            }
        )

        mock_result = _result(n_signals=0, signal_codes=[])
        mock_runner = _make_runner_mock(result=mock_result)

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
            patch("getrich.apps.strategy.cli.get_registry") as mock_get_reg,
            patch("getrich.apps.strategy.cli.LiveSignalRunner", return_value=mock_runner),
        ):
            mock_registry = MagicMock()
            mock_registry.build.return_value = _strategy()
            mock_get_reg.return_value = mock_registry

            mock_pool.init = AsyncMock()
            mock_pool.close = AsyncMock()

            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        assert ret == 0

    def test_runner_result_error_returns_1(self):
        """Runner result with error string returns 1."""
        _set_env(
            **{
                _ENV_STRATEGY: "macross",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "A,B",
            }
        )

        mock_result = _result(error="LiveDataError: failed to load live bars")
        mock_runner = _make_runner_mock(result=mock_result)

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
            patch("getrich.apps.strategy.cli.get_registry") as mock_get_reg,
            patch("getrich.apps.strategy.cli.LiveSignalRunner", return_value=mock_runner),
        ):
            mock_registry = MagicMock()
            mock_registry.build.return_value = _strategy()
            mock_get_reg.return_value = mock_registry

            mock_pool.init = AsyncMock()
            mock_pool.close = AsyncMock()

            ret = _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        assert ret == 1

    def test_pg_pool_close_called_on_error(self):
        """pg_pool.close() is called even when runner fails."""
        _set_env(
            **{
                _ENV_STRATEGY: "macross",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "A,B",
            }
        )

        mock_runner = _make_runner_mock(exc=RuntimeError("boom"))

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
            patch("getrich.apps.strategy.cli.get_registry") as mock_get_reg,
            patch("getrich.apps.strategy.cli.LiveSignalRunner", return_value=mock_runner),
        ):
            mock_registry = MagicMock()
            mock_registry.build.return_value = _strategy()
            mock_get_reg.return_value = mock_registry
            mock_pool.init = AsyncMock()
            mock_pool.close = AsyncMock()

            _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        mock_pool.close.assert_awaited_once()

    def test_symbols_with_whitespace_are_trimmed(self):
        """Symbols with whitespace around commas are properly trimmed."""
        _set_env(
            **{
                _ENV_STRATEGY: "macross",
                _ENV_STRATEGY_ID: "uuid-1",
                _ENV_SYMBOLS: "  A , B , C  ",
            }
        )

        mock_runner = _make_runner_mock()

        with (
            patch("getrich.apps.strategy.cli._is_trading_time", return_value=True),
            patch("getrich.apps.strategy.cli.pg_pool") as mock_pool,
            patch("getrich.apps.strategy.cli.get_registry") as mock_get_reg,
            patch("getrich.apps.strategy.cli.LiveSignalRunner", return_value=mock_runner),
        ):
            mock_registry = MagicMock()
            mock_registry.build.return_value = _strategy()
            mock_get_reg.return_value = mock_registry
            mock_pool.init = AsyncMock()
            mock_pool.close = AsyncMock()

            _run(main())

        _del_env(_ENV_STRATEGY, _ENV_STRATEGY_ID, _ENV_SYMBOLS)
        mock_runner.run_once.assert_awaited_once_with(["A", "B", "C"])
