"""Tests for MultiStrategyRunner — parallel strategy scheduling."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from zoneinfo import ZoneInfo

from getrich.apps.strategy.live_runner import LiveSignalResult
from getrich.apps.strategy.scheduler import (
    MultiStrategyRunner,
    ScheduleResult,
    StrategyConfig,
)


_TZ = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------------------
# StrategyConfig
# ---------------------------------------------------------------------------


class TestStrategyConfig:
    def test_valid_config(self):
        cfg = StrategyConfig(name="macross", strategy_id="uuid-1", symbols=("AU2606",))
        assert cfg.name == "macross"
        assert cfg.strategy_id == "uuid-1"
        assert cfg.symbols == ("AU2606",)

    def test_rejects_empty_name(self):
        import pytest

        with pytest.raises(ValueError, match="strategy name must be non-empty"):
            StrategyConfig(name="", strategy_id="uuid-1", symbols=("AU2606",))

    def test_rejects_empty_strategy_id(self):
        import pytest

        with pytest.raises(ValueError, match="strategy_id must be non-empty"):
            StrategyConfig(name="macross", strategy_id="", symbols=("AU2606",))

    def test_rejects_empty_symbols(self):
        import pytest

        with pytest.raises(ValueError, match="symbols must be non-empty"):
            StrategyConfig(name="macross", strategy_id="uuid-1", symbols=())

    def test_frozen(self):
        cfg = StrategyConfig(name="macross", strategy_id="uuid-1", symbols=("AU2606",))
        import pytest

        with pytest.raises(FrozenInstanceError):
            cfg.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ScheduleResult
# ---------------------------------------------------------------------------


class TestScheduleResult:
    def _result(self, n=0, error=None):
        return LiveSignalResult(
            n_signals=n,
            signal_codes=[f"sig_{i}" for i in range(n)],
            triggered_at=datetime(2026, 5, 31, 10, 0, tzinfo=_TZ),
            duration_ms=100.0,
            error=error,
        )

    def _cfg(self, name="s1", sid="id-1"):
        return StrategyConfig(name=name, strategy_id=sid, symbols=("AU2606",))

    def test_total_signals(self):
        r = ScheduleResult(
            results=(self._result(3), self._result(2), self._result(0)),
            configs=(self._cfg("a"), self._cfg("b"), self._cfg("c")),
            triggered_at=datetime(2026, 5, 31, 10, 0, tzinfo=_TZ),
            duration_ms=300.0,
        )
        assert r.total_signals == 5

    def test_errors_list(self):
        r = ScheduleResult(
            results=(
                self._result(2),
                self._result(0, error="timeout"),
                self._result(1),
                self._result(0, error="risk blocked"),
            ),
            configs=(
                self._cfg("a"),
                self._cfg("b"),
                self._cfg("c"),
                self._cfg("d"),
            ),
            triggered_at=datetime(2026, 5, 31, 10, 0, tzinfo=_TZ),
            duration_ms=400.0,
        )
        assert r.errors == ["timeout", "risk blocked"]

    def test_all_signal_codes(self):
        r = ScheduleResult(
            results=(self._result(2), self._result(1)),
            configs=(self._cfg("a"), self._cfg("b")),
            triggered_at=datetime(2026, 5, 31, 10, 0, tzinfo=_TZ),
            duration_ms=200.0,
        )
        assert r.all_signal_codes == ["sig_0", "sig_1", "sig_0"]

    def test_to_dict_structure(self):
        r = ScheduleResult(
            results=(self._result(1), self._result(0, error="fail")),
            configs=(self._cfg("a"), self._cfg("b")),
            triggered_at=datetime(2026, 5, 31, 10, 0, tzinfo=_TZ),
            duration_ms=150.0,
        )
        d = r.to_dict()
        assert d["total_signals"] == 1
        assert d["errors"] == ["fail"]
        assert len(d["per_strategy"]) == 2
        assert d["per_strategy"][0]["name"] == "a"
        assert d["per_strategy"][1]["error"] == "fail"


# ---------------------------------------------------------------------------
# MultiStrategyRunner
# ---------------------------------------------------------------------------


class TestMultiStrategyRunner:
    def test_rejects_empty_configs(self):
        import pytest

        with pytest.raises(ValueError, match="at least one StrategyConfig"):
            MultiStrategyRunner([])
