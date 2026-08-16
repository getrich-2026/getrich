"""Tests for the Backtest / Sweep / WalkForward job operations."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest
from gr_api.jobs.ops import (
    BacktestRunOp,
    SweepRunOp,
    WalkForwardRunOp,
    get_op_for_job_type,
)
from gr_backtest import (
    DataFrameBarLoader,
    Side,
    Strategy,
    get_shanghai_tz,
)
from gr_backtest.strategy import OrderIntent
from gr_signal.errors import BacktestJobError


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------- fixtures


_TZ = get_shanghai_tz()


def _bars() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "dt": [
                datetime(2026, 1, 1, 9, 30, tzinfo=_TZ),
                datetime(2026, 1, 2, 9, 30, tzinfo=_TZ),
                datetime(2026, 1, 3, 9, 30, tzinfo=_TZ),
            ],
            "symbol": ["000001.SZ"] * 3,
            "open": [Decimal("10"), Decimal("11"), Decimal("12")],
            "high": [Decimal("10.5"), Decimal("11.5"), Decimal("12.5")],
            "low": [Decimal("9.5"), Decimal("10.5"), Decimal("11.5")],
            "close": [Decimal("10"), Decimal("11"), Decimal("12")],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def _loader() -> DataFrameBarLoader:
    return DataFrameBarLoader(_bars())


class _BuyOnce(Strategy):
    """Buy 1 share on first bar; no further action."""

    name = "BuyOnce"

    def __init__(self, qty: int = 1) -> None:
        self.qty = qty
        self.calls = 0

    def on_bar(self, ctx):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            return [OrderIntent(symbol="000001.SZ", side=Side.BUY, qty=Decimal(self.qty))]
        return None


def _register_buy_once() -> None:
    """Register a fresh ``BuyOnce`` strategy under a known name."""
    from gr_backtest.registry import get_registry

    registry = get_registry()
    if "buy_once" not in [entry.name for entry in registry._entries.values()]:  # type: ignore[attr-defined]
        registry.register("buy_once", "Buy Once", _BuyOnce)


def _base_request_dict() -> dict[str, Any]:
    return {
        "strategy_name": "buy_once",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 1, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 1, 3, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "1000",
        "freq": "1d",
        "bar_loader": "pg",
    }


def _backtest_request() -> dict[str, Any]:
    return {
        **_base_request_dict(),
        "extra_freqs": [],
        "execution_lag_bars": 1,
        "strategy_params": {"qty": 1},
        "save_artifacts": False,
    }


def _sweep_request() -> dict[str, Any]:
    return {
        **_base_request_dict(),
        "sweep_id": None,
        "search_type": "grid",
        "search_spec": {"space": {"qty": [1, 2]}, "constraints": []},
        "select_metric": "sharpe_ratio",
        "maximize": True,
        "fail_fast": False,
        "strategy_params": {},
    }


def _walk_forward_request() -> dict[str, Any]:
    return {
        **_base_request_dict(),
        "walk_forward_id": None,
        "search_spec": {"space": {"qty": [1]}, "constraints": []},
        "train_months": 1,
        "val_months": 1,
        "step_months": None,
        "refit": "rolling",
        "select_metric": "sharpe_ratio",
        "maximize": True,
        "fail_fast": False,
        "strategy_params": {"qty": 1},
    }


# ---------------------------------------------------------------- op registry


def test_get_op_for_job_type_returns_matching_classes() -> None:
    assert isinstance(get_op_for_job_type("backtest"), BacktestRunOp)
    assert isinstance(get_op_for_job_type("sweep"), SweepRunOp)
    assert isinstance(get_op_for_job_type("walk_forward"), WalkForwardRunOp)


def test_get_op_for_job_type_raises_for_unknown() -> None:
    with pytest.raises(BacktestJobError, match="unknown job_type"):
        get_op_for_job_type("not-a-real-job")


# ---------------------------------------------------------------- BacktestRunOp


def test_backtest_run_op_persists_result_and_returns_progress() -> None:
    _register_buy_once()
    op = BacktestRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "request_json": _backtest_request(),
    }

    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgBacktestResultStore.save_result",
            new=AsyncMockSave(),
        ) as save_mock,
    ):
        result = _run(op(job))

    assert result == {"progress": 100}
    assert len(save_mock.calls) == 1


def test_backtest_run_op_propagates_exceptions() -> None:
    _register_buy_once()
    op = BacktestRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "request_json": _backtest_request(),
    }

    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        pytest.raises(BacktestJobError, match="Unknown strategy"),
    ):
        _run(
            op(
                {
                    **job,
                    "request_json": {
                        **_backtest_request(),
                        "strategy_name": "no_such_strategy",
                    },
                }
            )
        )


def test_backtest_run_op_rejects_invalid_window() -> None:
    _register_buy_once()
    op = BacktestRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "request_json": {
            **_backtest_request(),
            "start": datetime(2026, 1, 5, 9, 30, tzinfo=_TZ).isoformat(),
            "end": datetime(2026, 1, 1, 9, 30, tzinfo=_TZ).isoformat(),
        },
    }
    from pydantic import ValidationError

    with pytest.raises((BacktestJobError, ValidationError)):
        _run(op(job))


# ---------------------------------------------------------------- SweepRunOp


def test_sweep_run_op_persists_sweep_and_returns_progress() -> None:
    _register_buy_once()
    op = SweepRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "sweep",
        "ref_id": "sweep-1",
        "request_json": _sweep_request(),
    }

    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgSweepResultStore.save_sweep_result",
            new=AsyncMockSave(),
        ) as save_mock,
    ):
        result = _run(op(job))

    assert result == {"progress": 100}
    assert len(save_mock.calls) == 1


def test_sweep_run_op_rejects_empty_search_spec() -> None:
    _register_buy_once()
    op = SweepRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "sweep",
        "ref_id": "sweep-1",
        "request_json": {**_sweep_request(), "search_spec": {"space": {}, "constraints": []}},
    }
    with pytest.raises(BacktestJobError, match="invalid SweepRunRequest"):
        _run(op(job))


# ---------------------------------------------------------------- WalkForwardRunOp


def test_walk_forward_run_op_persists_wf_and_returns_progress() -> None:
    _register_buy_once()
    op = WalkForwardRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "walk_forward",
        "ref_id": "wf-1",
        "request_json": _walk_forward_request(),
    }

    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgWalkForwardResultStore.save_walk_forward_result",
            new=AsyncMockSave(),
        ) as save_mock,
    ):
        result = _run(op(job))

    assert result == {"progress": 100}
    assert len(save_mock.calls) == 1


# ---------------------------------------------------------------- progress wiring


def test_backtest_run_op_invokes_progress_callback_when_provided() -> None:
    """BacktestRunOp should call progress_cb(0) and let the runner write 100."""
    _register_buy_once()
    op = BacktestRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "request_json": _backtest_request(),
    }
    progress_pcts: list[int] = []

    async def progress_cb(pct: int) -> None:
        progress_pcts.append(pct)

    augmented = {**job, "_progress_cb": progress_cb, "_event_loop": _asyncio_loop()}

    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgBacktestResultStore.save_result",
            new=AsyncMockSave(),
        ),
    ):
        result = _run(op(augmented))

    assert result == {"progress": 100}
    assert progress_pcts == [0]


def test_sweep_run_op_calls_on_progress_per_trial() -> None:
    """SweepRunOp should emit one sync callback per trial through the adapter."""
    _register_buy_once()
    op = SweepRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "sweep",
        "ref_id": "sweep-1",
        "request_json": _sweep_request(),
    }
    progress_pcts: list[int] = []

    async def progress_cb(pct: int) -> None:
        progress_pcts.append(pct)

    loop = _asyncio_loop()
    augmented = {**job, "_progress_cb": progress_cb, "_event_loop": loop}

    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgSweepResultStore.save_sweep_result",
            new=AsyncMockSave(),
        ),
    ):
        result = _run(op(augmented))

    assert result == {"progress": 100}
    # Two trials in the search spec → two sync adapter calls.
    # Drain the loop so the run_coroutine_threadsafe futures complete.
    loop.run_until_complete(_drain())
    assert sorted(progress_pcts) == [50, 100]


def test_walk_forward_run_op_calls_on_progress_per_window() -> None:
    """WalkForwardRunOp should emit one sync callback per window."""
    _register_buy_once()
    op = WalkForwardRunOp()
    # 1m train + 1m val needs a 2+ month window to yield at least one trial.
    payload = _walk_forward_request()
    payload["start"] = datetime(2026, 1, 1, 9, 30, tzinfo=_TZ).isoformat()
    payload["end"] = datetime(2026, 4, 15, 9, 30, tzinfo=_TZ).isoformat()
    job = {
        "job_id": "job-1",
        "job_type": "walk_forward",
        "ref_id": "wf-1",
        "request_json": payload,
    }
    progress_pcts: list[int] = []

    async def progress_cb(pct: int) -> None:
        progress_pcts.append(pct)

    loop = _asyncio_loop()
    augmented = {**job, "_progress_cb": progress_cb, "_event_loop": loop}

    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgWalkForwardResultStore.save_walk_forward_result",
            new=AsyncMockSave(),
        ),
    ):
        result = _run(op(augmented))

    assert result == {"progress": 100}
    loop.run_until_complete(_drain())
    # 3-month window with step_months=1 → 2 windows.
    assert sorted(progress_pcts) == [50, 100]


# ---------------------------------------------------------------- cancellation wiring


def test_backtest_run_op_returns_cancelled_when_is_set() -> None:
    """BacktestRunOp short-circuits before running when is_cancelled is True."""
    _register_buy_once()
    op = BacktestRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "backtest",
        "ref_id": "run-1",
        "request_json": _backtest_request(),
    }

    def _is_cancelled() -> bool:
        return True

    save_mock = AsyncMockSave()
    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgBacktestResultStore.save_result",
            new=save_mock,
        ),
    ):
        result = _run(op({**job, "_is_cancelled": _is_cancelled}))

    assert result == {"cancelled": True}
    assert len(save_mock.calls) == 0


def test_sweep_run_op_returns_cancelled_without_persisting() -> None:
    """SweepRunOp must not call save_sweep_result when the sweep was cancelled."""
    _register_buy_once()
    op = SweepRunOp()
    job = {
        "job_id": "job-1",
        "job_type": "sweep",
        "ref_id": "sweep-1",
        "request_json": _sweep_request(),
    }

    # The runner injects a sync ``() -> bool``; mimic by checking event.set() state.
    counter = {"n": 0}

    def _is_cancelled() -> bool:
        return counter["n"] > 0

    save_mock = AsyncMockSave()
    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        # Patch strategy_factory via the underlying _build_strategy so the
        # counter advances exactly once before the next is_cancelled() call.
        patch(
            "gr_api.jobs.ops._build_strategy",
            side_effect=lambda name, **kw: (
                counter.__setitem__("n", counter["n"] + 1) or _BuyOnceCounter()
            ),
        ),
        patch(
            "gr_api.jobs.ops.PgSweepResultStore.save_sweep_result",
            new=save_mock,
        ),
    ):
        result = _run(op({**job, "_is_cancelled": _is_cancelled}))

    assert result == {"cancelled": True}
    assert len(save_mock.calls) == 0


class _BuyOnceCounter(_BuyOnce):
    """Subclass marker; matches registry call when patching _build_strategy."""

    name = "BuyOnceCounter"


def test_walk_forward_run_op_returns_cancelled_without_persisting() -> None:
    """WalkForwardRunOp short-circuits save_walk_forward_result on cancellation."""
    _register_buy_once()
    op = WalkForwardRunOp()
    payload = _walk_forward_request()
    payload["start"] = datetime(2026, 1, 1, 9, 30, tzinfo=_TZ).isoformat()
    payload["end"] = datetime(2026, 4, 15, 9, 30, tzinfo=_TZ).isoformat()
    job = {
        "job_id": "job-1",
        "job_type": "walk_forward",
        "ref_id": "wf-1",
        "request_json": payload,
    }

    def _is_cancelled() -> bool:
        return True

    save_mock = AsyncMockSave()
    with (
        patch("gr_api.jobs.ops._build_bar_loader", return_value=_loader()),
        patch(
            "gr_api.jobs.ops.PgWalkForwardResultStore.save_walk_forward_result",
            new=save_mock,
        ),
    ):
        result = _run(op({**job, "_is_cancelled": _is_cancelled}))

    assert result == {"cancelled": True}
    assert len(save_mock.calls) == 0


# ---------------------------------------------------------------- helpers


class AsyncMockSave:
    """Record coroutine calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


def _asyncio_loop() -> asyncio.AbstractEventLoop:
    """Return a fresh asyncio loop for the test thread.

    ``_sync_progress_adapter`` calls ``asyncio.run_coroutine_threadsafe``,
    which posts to a loop. We hand the test its own loop so we can drain
    it deterministically.
    """
    return asyncio.new_event_loop()


async def _drain() -> None:
    """Sleep zero — gives run_coroutine_threadsafe futures a chance to complete."""
    await asyncio.sleep(0)
