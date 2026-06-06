"""Tests for ClickHouse-backed live data provider."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import polars as pl
import pytest

from getrich.apps.strategy import LiveDataError, LiveDataProvider
from getrich_backtest import DEFAULT_ASHARE_SESSIONS, Session, get_shanghai_tz
from getrich_backtest.strategy.context import HistoryView


TZ = get_shanghai_tz()


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.new_event_loop().run_until_complete(coro)


class _SyncCtxMgr(AbstractContextManager):
    def __init__(self, client: _MockClickHouseClient) -> None:
        self._client = client

    def __enter__(self) -> _MockClickHouseClient:
        return self._client

    def __exit__(self, *args: object) -> None:
        pass


class _MockClickHouseClient:
    def __init__(self, df: pd.DataFrame | None = None, exc: Exception | None = None) -> None:
        self.df = df if df is not None else pd.DataFrame()
        self.exc = exc
        self.queries: list[tuple[str, dict[str, Any] | None]] = []

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        self.queries.append((sql, params))
        if self.exc is not None:
            raise self.exc
        return self.df


class _MockClickHousePool:
    def __init__(self, client: _MockClickHouseClient) -> None:
        self.client = client

    def connection(self) -> _SyncCtxMgr:
        return _SyncCtxMgr(self.client)


def _sample_factor_df() -> pd.DataFrame:
    """Return a sample factors_long result with two factors, two symbols."""
    return pd.DataFrame(
        {
            "dt": [
                datetime(2026, 6, 1, 9, 29, tzinfo=TZ),
                datetime(2026, 6, 1, 9, 29, tzinfo=TZ),
                datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
            ],
            "symbol": ["A", "B", "A", "B"],
            "factor": ["mom20", "mom20", "rs_14", "rs_14"],
            "value": [0.05, 0.03, 62.0, 48.0],
        }
    )


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dt": [
                datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                datetime(2026, 6, 1, 9, 31, tzinfo=TZ),
                datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
                datetime(2026, 6, 1, 9, 31, tzinfo=TZ),
            ],
            "symbol": ["A", "A", "B", "B"],
            "open": [10.0, 10.1, 20.0, 20.1],
            "high": [10.2, 10.3, 20.2, 20.3],
            "low": [9.9, 10.0, 19.9, 20.0],
            "close": [10.1, 10.2, 20.1, 20.2],
            "volume": [1000.0, 1100.0, 2000.0, 2100.0],
        }
    )


class TestLiveDataProvider:
    def test_load_latest_bars_returns_valid_schema(self) -> None:
        client = _MockClickHouseClient(_sample_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        bars = provider.load_latest_bars(["A", "B"], n_bars=2)

        assert bars.height == 4
        assert bars.schema["dt"] == pl.Datetime("ms", "Asia/Shanghai")
        assert bars["symbol"].to_list() == ["A", "B", "A", "B"]
        sql, params = client.queries[0]
        assert "row_number() OVER" in sql
        assert params == {"symbols": ["A", "B"], "n_bars": 2}

    def test_empty_query_returns_empty_bars(self) -> None:
        client = _MockClickHouseClient(pd.DataFrame())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        bars = provider.load_latest_bars(["A"])

        assert bars.is_empty()
        assert bars.schema["dt"] == pl.Datetime("ms", "Asia/Shanghai")
        assert set(bars.columns) == {"dt", "symbol", "open", "high", "low", "close", "volume"}

    def test_build_context_uses_latest_bar_and_full_history(self) -> None:
        client = _MockClickHouseClient(_sample_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A", "B"], n_bars=2, run_id="live-test"))

        assert ctx is not None
        assert ctx.run_id == "live-test"
        assert ctx.now == datetime(2026, 6, 1, 9, 31, tzinfo=TZ)
        assert ctx.bar.height == 2
        assert ctx.history.bars.height == 4
        assert ctx.account.cash == 0
        assert ctx.account.available_cash == 0

    def test_build_context_no_data_returns_none(self) -> None:
        client = _MockClickHouseClient(pd.DataFrame())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        assert _run(provider.build_context(["A"])) is None

    def test_invalid_symbols_raise_live_data_error(self) -> None:
        provider = LiveDataProvider(pool=_MockClickHousePool(_MockClickHouseClient()))
        with pytest.raises(LiveDataError, match="symbols"):
            provider.load_latest_bars([])

    def test_invalid_n_bars_raise_live_data_error(self) -> None:
        provider = LiveDataProvider(pool=_MockClickHousePool(_MockClickHouseClient()))
        with pytest.raises(LiveDataError, match="n_bars"):
            provider.load_latest_bars(["A"], n_bars=0)

    def test_query_error_is_wrapped(self) -> None:
        client = _MockClickHouseClient(exc=RuntimeError("network down"))
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        with pytest.raises(LiveDataError, match="failed to load live bars"):
            provider.load_latest_bars(["A"])

    def test_custom_table_name_is_used(self) -> None:
        client = _MockClickHouseClient(pd.DataFrame())
        provider = LiveDataProvider(
            pool=_MockClickHousePool(client),
            table_name="market.md_bars_5m",
        )

        provider.load_latest_bars(["A"])

        sql, _params = client.queries[0]
        assert "FROM market.md_bars_5m" in sql

    def test_invalid_table_name_is_rejected(self) -> None:
        with pytest.raises(LiveDataError, match="table name"):
            LiveDataProvider(
                pool=_MockClickHousePool(_MockClickHouseClient()),
                table_name="bad;drop",
            )

    def test_utc_datetime_is_converted_to_shanghai(self) -> None:
        df = pd.DataFrame(
            {
                "dt": [datetime(2026, 6, 1, 1, 30, tzinfo=timezone.utc)],
                "symbol": ["A"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000.0],
            }
        )
        provider = LiveDataProvider(pool=_MockClickHousePool(_MockClickHouseClient(df)))

        bars = provider.load_latest_bars(["A"])

        assert bars.schema["dt"] == pl.Datetime("ms", "Asia/Shanghai")
        assert bars["dt"].item() == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)


# ---------------------------------------------------------------------------
# Factor loading tests
# ---------------------------------------------------------------------------


class TestLoadLatestFactors:
    def test_returns_correct_dict(self) -> None:
        """load_latest_factors returns {factor_name: DataFrame[dt, symbol, value]}."""
        client = _MockClickHouseClient(_sample_factor_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A", "B"], ["mom20", "rs_14"], n_bars=2)

        assert set(result.keys()) == {"mom20", "rs_14"}
        mom20 = result["mom20"]
        assert mom20.columns == ["dt", "symbol", "value"]
        assert mom20.schema["dt"] == pl.Datetime("ms", "Asia/Shanghai")
        assert mom20.height == 2
        # SQL was issued with correct params
        assert len(client.queries) == 1
        _sql, params = client.queries[0]
        assert params["symbols"] == ["A", "B"]
        assert params["factors"] == ["mom20", "rs_14"]
        assert params["n_bars"] == 2

    def test_empty_factor_names_returns_empty_dict(self) -> None:
        """Empty factor_names list returns {} without querying ClickHouse."""
        client = _MockClickHouseClient()
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A"], [])

        assert result == {}
        assert client.queries == []

    def test_empty_whitespace_factor_names_returns_empty_dict(self) -> None:
        """Factor names containing only whitespace are filtered out."""
        client = _MockClickHouseClient()
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A"], ["  ", "\t"])

        assert result == {}
        assert client.queries == []

    def test_empty_result_returns_empty_dict(self) -> None:
        """Empty ClickHouse result returns {}."""
        client = _MockClickHouseClient(pd.DataFrame())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A"], ["mom20"])

        assert result == {}

    def test_query_error_returns_empty_dict_with_warning(self, caplog) -> None:
        """ClickHouse query failure returns {} and logs a warning."""
        client = _MockClickHouseClient(exc=RuntimeError("clickhouse down"))
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        with caplog.at_level(logging.WARNING, logger="getrich.apps.strategy.live_data_provider"):
            result = provider.load_latest_factors(["A"], ["mom20"])

        assert result == {}
        assert any("Failed to load live factors" in m for m in caplog.messages)

    def test_single_factor_returns_single_key(self) -> None:
        """A single factor name returns a dict with one key."""
        df = pd.DataFrame(
            {
                "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
                "symbol": ["A"],
                "factor": ["mom20"],
                "value": [0.05],
            }
        )
        client = _MockClickHouseClient(df)
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A"], ["mom20"])

        assert list(result.keys()) == ["mom20"]
        assert result["mom20"].height == 1

    def test_multiple_factors_return_multiple_keys(self) -> None:
        """Each factor name becomes a key in the result dict."""
        client = _MockClickHouseClient(_sample_factor_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A", "B"], ["mom20", "rs_14"])

        assert len(result) == 2
        assert "mom20" in result and "rs_14" in result
        assert result["mom20"].height == 2

    def test_invalid_table_name_raises(self) -> None:
        """Invalid factor table name raises LiveDataError."""
        provider = LiveDataProvider(pool=_MockClickHousePool(_MockClickHouseClient()))

        with pytest.raises(LiveDataError, match="factor table name"):
            provider.load_latest_factors(["A"], ["mom20"], table_name="bad;drop")

    def test_factor_values_preserve_data_types(self) -> None:
        """Factor value column remains Float64."""
        df = pd.DataFrame(
            {
                "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
                "symbol": ["A"],
                "factor": ["mom20"],
                "value": [0.05],
            }
        )
        client = _MockClickHouseClient(df)
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A"], ["mom20"])

        assert result["mom20"].schema["value"] == pl.Float64
        assert result["mom20"]["value"].item() == 0.05

    def test_factor_names_are_deduplicated(self) -> None:
        """Duplicate factor names in input are normalized to unique values."""
        df = pd.DataFrame(
            {
                "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
                "symbol": ["A"],
                "factor": ["mom20"],
                "value": [0.05],
            }
        )
        client = _MockClickHouseClient(df)
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A"], ["mom20", "mom20"])

        assert list(result.keys()) == ["mom20"]
        _sql, params = client.queries[0]
        assert params["factors"] == ["mom20"]

    def test_extra_columns_in_result_are_ignored(self) -> None:
        """Extra columns like asset_class in the result are silently dropped."""
        df = pd.DataFrame(
            {
                "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)],
                "symbol": ["A"],
                "factor": ["mom20"],
                "value": [0.05],
                "asset_class": ["equity"],
            }
        )
        client = _MockClickHouseClient(df)
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        result = provider.load_latest_factors(["A"], ["mom20"])

        assert result["mom20"].columns == ["dt", "symbol", "value"]

    def test_polars_conversion_error_returns_empty_dict(self, caplog) -> None:
        """If polars conversion fails, return {} with a warning."""
        # A DataFrame with non-serializable data that breaks polars
        client = _MockClickHouseClient(_sample_factor_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        import polars as pl

        original = pl.from_pandas
        try:

            def _fail(*args, **kwargs):
                raise RuntimeError("polars error")

            pl.from_pandas = _fail  # type: ignore[assignment]

            with caplog.at_level(
                logging.WARNING, logger="getrich.apps.strategy.live_data_provider"
            ):
                result = provider.load_latest_factors(["A"], ["mom20"])

            assert result == {}
            assert any("Failed to convert factor result" in m for m in caplog.messages)
        finally:
            pl.from_pandas = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# build_context factor integration
# ---------------------------------------------------------------------------


class TestBuildContextFactors:
    def test_with_factors_ctx_factor_accessible(self) -> None:
        """build_context with factor_names injects factors accessible via ctx.factor()."""
        bar_client = _MockClickHouseClient(_sample_df())
        factor_client = _MockClickHouseClient(_sample_factor_df())

        class _MultiClientPool:
            def __init__(self, clients: list[_MockClickHouseClient]) -> None:
                self.clients = clients
                self._idx = -1

            def connection(self) -> _SyncCtxMgr:
                self._idx += 1
                return _SyncCtxMgr(self.clients[self._idx])

        pool = _MultiClientPool([bar_client, factor_client])
        provider = LiveDataProvider(pool=pool)

        ctx = _run(
            provider.build_context(
                ["A", "B"], n_bars=2, run_id="live-test", factor_names=["mom20", "rs_14"]
            )
        )

        assert ctx is not None
        mom20 = ctx.factor("mom20")
        assert mom20 is not None
        assert mom20.columns == ["dt", "symbol", "value"]
        assert mom20.height == 2

    def test_without_factor_names_no_factors(self) -> None:
        """factor_names=None means no factors are set on the context."""
        client = _MockClickHouseClient(_sample_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A", "B"], n_bars=2))

        assert ctx is not None
        assert ctx.factor("mom20") is None

    def test_empty_factor_names_no_factors(self) -> None:
        """factor_names=[] means no factors are set on the context."""
        client = _MockClickHouseClient(_sample_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A", "B"], n_bars=2, factor_names=[]))

        assert ctx is not None
        assert ctx.factor("mom20") is None

    def test_factor_load_failure_still_returns_context(self) -> None:
        """When factor query fails the context is still returned (no factors)."""
        bar_client = _MockClickHouseClient(_sample_df())
        factor_client = _MockClickHouseClient(exc=RuntimeError("factors_long table does not exist"))

        class _MultiClientPool:
            def __init__(self, clients: list[_MockClickHouseClient]) -> None:
                self.clients = clients
                self._idx = -1

            def connection(self) -> _SyncCtxMgr:
                self._idx += 1
                return _SyncCtxMgr(self.clients[self._idx])

        pool = _MultiClientPool([bar_client, factor_client])
        provider = LiveDataProvider(pool=pool)

        ctx = _run(
            provider.build_context(["A", "B"], n_bars=2, run_id="live-test", factor_names=["mom20"])
        )

        assert ctx is not None
        assert ctx.run_id == "live-test"
        assert ctx.factor("mom20") is None  # factors failed, but context is fine


# ---------------------------------------------------------------------------
# Extra freq (multi-frequency) tests for build_context
# ---------------------------------------------------------------------------


def _many_bars(num_bars: int = 120) -> pd.DataFrame:
    """Generate *num_bars* consecutive 1m bars for symbol A."""
    import pandas as pd

    base = datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
    records = []
    for i in range(num_bars):
        dt = base + pd.Timedelta(minutes=i)
        records.append(
            {
                "dt": dt,
                "symbol": "A",
                "open": 10.0 + i * 0.01,
                "high": 10.2 + i * 0.01,
                "low": 9.9 + i * 0.01,
                "close": 10.1 + i * 0.01,
                "volume": 1000.0 + i * 10,
            }
        )
    return pd.DataFrame(records)


class TestBuildContextExtraFreqs:
    def test_single_extra_freq_populates_extra_history(self) -> None:
        """extra_freqs=["5m"] → ctx.extra_history["5m"] is a HistoryView."""
        client = _MockClickHouseClient(_many_bars(60))
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A"], n_bars=60, run_id="live-test", extra_freqs=["5m"]))

        assert ctx is not None
        assert ctx.extra_history is not None
        assert "5m" in ctx.extra_history
        view_5m = ctx.extra_history["5m"]
        assert isinstance(view_5m, HistoryView)
        # 60 one-minute bars → ~12 five-minute bars (9:30-10:29 → 12 buckets)
        assert view_5m.bars.height >= 10

    def test_multiple_extra_freqs(self) -> None:
        """extra_freqs=["5m", "1h"] → both keys present in extra_history."""
        client = _MockClickHouseClient(_many_bars(120))
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(
            provider.build_context(["A"], n_bars=120, run_id="live-test", extra_freqs=["5m", "1h"])
        )

        assert ctx is not None
        assert ctx.extra_history is not None
        assert "5m" in ctx.extra_history
        assert "1h" in ctx.extra_history
        assert isinstance(ctx.extra_history["5m"], HistoryView)
        assert isinstance(ctx.extra_history["1h"], HistoryView)
        # Hourly bars should be fewer than 5m bars for the same range
        assert ctx.extra_history["1h"].bars.height < ctx.extra_history["5m"].bars.height

    def test_no_extra_freqs_extra_history_is_none(self) -> None:
        """build_context without extra_freqs → extra_history is None."""
        client = _MockClickHouseClient(_sample_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A"], n_bars=2))

        assert ctx is not None
        assert ctx.extra_history is None

    def test_empty_extra_freqs_extra_history_is_none(self) -> None:
        """build_context with extra_freqs=[] → extra_history is None."""
        client = _MockClickHouseClient(_sample_df())
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A"], n_bars=2, extra_freqs=[]))

        assert ctx is not None
        assert ctx.extra_history is None

    def test_extra_freq_n_bars_auto_adjust(self) -> None:
        """n_bars=1 + extra_freqs=["1h"] → effective n_bars ≥ 60."""
        client = _MockClickHouseClient(_many_bars(120))
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A"], n_bars=1, run_id="live-test", extra_freqs=["1h"]))

        assert ctx is not None
        # The query should have been called with n_bars ≥ 60 (auto-adjusted)
        sql, params = client.queries[0]
        assert params["n_bars"] >= 60
        # Verify extra_history is populated
        assert ctx.extra_history is not None
        assert "1h" in ctx.extra_history

    def test_extra_freq_can_be_session_aligned(self) -> None:
        """Provider sessions align 1h extra history to 09:30 session open."""
        client = _MockClickHouseClient(_many_bars(60))
        provider = LiveDataProvider(
            pool=_MockClickHousePool(client),
            sessions=DEFAULT_ASHARE_SESSIONS,
        )

        ctx = _run(provider.build_context(["A"], n_bars=60, run_id="live-test", extra_freqs=["1h"]))

        assert ctx is not None
        assert ctx.extra_history is not None
        first_dt = ctx.extra_history["1h"].bars["dt"][0]
        assert first_dt == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)

    def test_extra_freq_default_remains_wall_clock_aligned(self) -> None:
        """Without sessions, 1h extra history keeps existing 09:00 wall-clock bucket."""
        client = _MockClickHouseClient(_many_bars(60))
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(provider.build_context(["A"], n_bars=60, run_id="live-test", extra_freqs=["1h"]))

        assert ctx is not None
        assert ctx.extra_history is not None
        first_dt = ctx.extra_history["1h"].bars["dt"][0]
        assert first_dt == datetime(2026, 6, 1, 9, 0, tzinfo=TZ)

    def test_extra_freq_build_context_sessions_override_provider_sessions(self) -> None:
        """Explicit build_context sessions override constructor sessions."""
        client = _MockClickHouseClient(_many_bars(60))
        provider = LiveDataProvider(
            pool=_MockClickHousePool(client),
            sessions=DEFAULT_ASHARE_SESSIONS,
        )

        ctx = _run(
            provider.build_context(
                ["A"],
                n_bars=60,
                run_id="live-test",
                extra_freqs=["1h"],
                sessions=(Session("wall", 9, 0, 11, 30, spans_midnight=False),),
            )
        )

        assert ctx is not None
        assert ctx.extra_history is not None
        first_dt = ctx.extra_history["1h"].bars["dt"][0]
        assert first_dt == datetime(2026, 6, 1, 9, 0, tzinfo=TZ)

    def test_extra_freq_lookback_works(self) -> None:
        """ctx.extra_history["5m"].lookback(n=2) returns 2 completed bars."""
        client = _MockClickHouseClient(_many_bars(120))
        provider = LiveDataProvider(pool=_MockClickHousePool(client))

        ctx = _run(
            provider.build_context(["A"], n_bars=120, run_id="live-test", extra_freqs=["5m"])
        )

        assert ctx is not None
        assert ctx.extra_history is not None
        looked = ctx.extra_history["5m"].lookback(n=2)
        assert looked.height == 2
        assert set(looked.columns) == {"dt", "symbol", "open", "high", "low", "close", "volume"}
