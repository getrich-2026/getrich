"""Backtest job operations — real executors for ``BacktestJobOp``.

Each ``Op`` receives a claimed job row and:

1. Reconstructs the typed request from ``job["request_json"]``.
2. Resolves a strategy via ``StrategyRegistry``.
3. Builds a ``Backtest`` (and per-trial factories for sweeps / walk_forward).
4. Runs the engine, persists the result via the appropriate store.
5. Returns ``{"progress": 100}`` on success or lets exceptions propagate so
   ``BacktestJobRunner.run_once`` can mark the job as failed.

P0 keeps the executors deliberately simple:

* ``bar_loader`` is one of ``"pg"`` or ``"duckdb"`` and the loader is built
  with default settings. Future revisions can take per-request config.
* Search specs are reduced to a ``{space: {name: values_or_dim}}`` dict.
* No artifact generation.

P1 progress wiring: when ``BacktestJobRunner`` invokes an op it injects two
keys into the row dict — ``_progress_cb`` (async ``(int) -> None`` writing to
``backtest_jobs.progress``) and ``_event_loop`` (the runner's running loop).
The sweep and walk-forward ops wrap those into a sync ``(done, total) -> None``
adapter and pass it to ``SweepRunner.run(on_progress=...)`` /
``WalkForward.run(on_progress=...)``. The ``BacktestRunOp`` is a single-shot
task and only emits 0% and 100%.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from getrich.apps.strategy.errors import (
    BacktestJobError,
    StrategyRegistryError,
)
from getrich.apps.strategy.registry import get_registry
from getrich_backtest import (
    Backtest,
    BacktestMetrics,
    BacktestResult,
    GridSearch,
    ParamSpace,
    ProgressCallback,
    SweepRunner,
    WalkForward,
    compute_metrics,
)
from getrich_backtest.persistence import PgBacktestResultStore
from getrich_backtest.sweep import SweepTrial
from getrich_backtest.sweep_persistence import PgSweepResultStore
from getrich_backtest.walk_forward import WalkForwardRunSpec
from getrich_backtest.walk_forward_persistence import PgWalkForwardResultStore


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- progress adapters


def _resolve_progress(
    job: dict[str, Any],
) -> tuple[ProgressCallback | None, asyncio.AbstractEventLoop | None]:
    """Extract the runner-injected progress callback and event loop.

    Both are optional — tests and direct invocations may omit them. Returns
    ``(None, None)`` when the job dict was not augmented by the runner.
    """
    cb = job.get("_progress_cb")
    loop = job.get("_event_loop")
    if cb is None or loop is None:
        return None, None
    return cb, loop  # type: ignore[return-value]


def _resolve_cancel(job: dict[str, Any]):
    """Return the sync ``() -> bool`` cancellation probe injected by the runner.

    ``None`` when the job dict was not augmented (e.g. direct op invocation
    in tests).
    """
    return job.get("_is_cancelled")


def _sync_progress_adapter(
    progress_cb: ProgressCallback,
    loop: asyncio.AbstractEventLoop,
) -> ProgressCallback:
    """Build a sync ``(done, total) -> None`` adapter for ``SweepRunner`` / ``WalkForward``.

    The engine runs synchronously in the worker thread. We translate the
    integer percent into a coroutine and schedule it on the runner's loop
    via ``asyncio.run_coroutine_threadsafe``. The future itself is
    discarded; any DB failure is logged by the runner-supplied callback
    and never propagates back into the engine.
    """
    if not progress_cb or loop is None:
        return lambda done, total: None

    def _adapter(done: int, total: int) -> None:
        pct = 100 if total <= 0 else int(done * 100 / total)
        try:
            asyncio.run_coroutine_threadsafe(progress_cb(pct), loop)
        except Exception:  # noqa: BLE001
            # Loop closed or other scheduling failure: log once and move on.
            logger.exception("failed to schedule progress update (%d/%d)", done, total)

    return _adapter


# ---------------------------------------------------------------- helpers


def _build_bar_loader(kind: str) -> Any:
    """Return a default-configured ``PgBarLoader`` or ``DuckDBBarLoader``."""
    from getrich_backtest.data import DuckDBBarLoader, PgBarLoader

    if kind == "duckdb":
        return DuckDBBarLoader()
    return PgBarLoader()


def _build_param_space(spec: dict[str, object]) -> ParamSpace:
    """Translate a request ``search_spec.space`` dict into a ``ParamSpace``.

    Each entry must already be one of:
    * a list of literal values (categorical), or
    * a ``ParamDimension.to_dict()`` payload ``{"kind": "...", "values": [...]}``.

    Constraint functions are not supported over the wire in P0 and are
    silently ignored.
    """
    if not isinstance(spec, dict):
        raise BacktestJobError("search_spec.space must be a dict")
    raw = spec.get("space", spec)
    if not isinstance(raw, dict) or not raw:
        raise BacktestJobError("search_spec.space must be a non-empty dict")
    dimensions: dict[str, object] = {}
    for name, value in raw.items():
        if isinstance(value, dict) and "values" in value:
            kind = str(value.get("kind", "categorical"))
            values = tuple(value["values"])
            dimensions[name] = _dimension_from_kind(kind, values)
        elif isinstance(value, (list, tuple)):
            dimensions[name] = list(value)
        else:
            raise BacktestJobError(
                f"search_spec.space[{name!r}] must be a list or a {{kind, values}} dict"
            )
    return ParamSpace(dimensions)


def _dimension_from_kind(kind: str, values: tuple[Any, ...]) -> Any:
    from getrich_backtest.sweep import P

    if kind == "int_range":
        # values are already a flat int range tuple from P.int_range; rebuild
        # from the original start/stop/step when possible — otherwise fall
        # back to a categorical encoding to preserve user intent.
        if not values:
            raise BacktestJobError("int_range dimension must be non-empty")
        start = values[0]
        stop = values[-1]
        step = values[1] - values[0] if len(values) > 1 else 1
        return P.int_range(int(start), int(stop), step=int(step), inclusive=True)
    if kind == "decimal_range":
        from decimal import Decimal

        if not values:
            raise BacktestJobError("decimal_range dimension must be non-empty")
        start = Decimal(str(values[0]))
        stop = Decimal(str(values[-1]))
        step = Decimal(str(values[1])) - start if len(values) > 1 else Decimal("1")
        return P.decimal_range(start, stop, step=step, inclusive=True)
    return P.categorical(list(values))


def _request_from_job(job: dict[str, Any], model: type) -> Any:
    """Materialize a typed request from ``job['request_json']``.

    The ``model`` argument must be a Pydantic ``BaseModel`` subclass. We avoid
    ``pydantic.TypeAdapter`` here because forward references in nested
    sub-models are not eagerly resolved under TypeAdapter validation.
    """
    payload = job.get("request_json") or {}
    if not isinstance(payload, dict):
        raise BacktestJobError("job.request_json must be a dict")
    try:
        return model.model_validate(payload)
    except Exception as exc:
        raise BacktestJobError(f"invalid {model.__name__}: {exc}") from exc


def _build_strategy(
    name: str,
    *,
    overrides: dict[str, Any] | None = None,
) -> Any:
    """Instantiate a strategy via the registry, surfacing failures as ``BacktestJobError``."""
    try:
        return get_registry().build(name, **(overrides or {}))
    except StrategyRegistryError as exc:
        raise BacktestJobError(str(exc)) from exc


# ---------------------------------------------------------------- backtest op


class BacktestRunOp:
    """Execute one ``Backtest.run()`` and persist the result."""

    async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
        from getrich.apps.web.schemas.backtest import BacktestRunRequest

        request = _request_from_job(job, BacktestRunRequest)
        # ``request`` is a pydantic model instance; mypy doesn't see it here
        # because we validated dynamically. Cast via attribute access.
        strategy = _build_strategy(
            request.strategy_name,  # type: ignore[attr-defined]
            overrides=request.strategy_params,  # type: ignore[attr-defined]
        )
        loader = _build_bar_loader(request.bar_loader)  # type: ignore[attr-defined]

        progress_cb, _ = _resolve_progress(job)
        if progress_cb is not None:
            await progress_cb(0)

        is_cancelled = _resolve_cancel(job)
        if is_cancelled is not None and is_cancelled():
            return {"cancelled": True}

        bt = Backtest(
            bar_loader=loader,
            strategy=strategy,
            run_id=job["ref_id"],
            symbols=tuple(request.symbols),  # type: ignore[attr-defined]
            start=request.start,  # type: ignore[attr-defined]
            end=request.end,  # type: ignore[attr-defined]
            initial_cash=request.initial_cash,  # type: ignore[attr-defined]
            freq=request.freq,  # type: ignore[attr-defined]
            extra_freqs=tuple(request.extra_freqs),  # type: ignore[attr-defined]
            execution_lag_bars=request.execution_lag_bars,  # type: ignore[attr-defined]
            strategy_params=request.strategy_params,  # type: ignore[attr-defined]
        )
        result = bt.run()
        if not isinstance(result, BacktestResult):
            raise BacktestJobError(
                f"Backtest.run() returned {type(result).__name__}; "
                "single-strategy runs must yield a BacktestResult"
            )
        metrics: BacktestMetrics = compute_metrics(result)
        await PgBacktestResultStore().save_result(
            result,
            metrics=metrics,
            strategy_id=job["ref_id"],
        )
        return {"progress": 100}


# ---------------------------------------------------------------- sweep op


class SweepRunOp:
    """Execute a parameter sweep and persist the parent + trial rows."""

    async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
        from getrich.apps.web.schemas.backtest import SweepRunRequest

        request = _request_from_job(job, SweepRunRequest)
        sweep_id: str = job["ref_id"]
        space = _build_param_space(request.search_spec.model_dump())  # type: ignore[attr-defined]
        runner = SweepRunner(
            sweep_id=sweep_id,
            search=GridSearch(space=space),
            select_metric=request.select_metric,  # type: ignore[attr-defined]
            maximize=request.maximize,  # type: ignore[attr-defined]
            fail_fast=request.fail_fast,  # type: ignore[attr-defined]
        )
        loader = _build_bar_loader(request.bar_loader)  # type: ignore[attr-defined]
        start = request.start  # type: ignore[attr-defined]
        end = request.end  # type: ignore[attr-defined]
        initial_cash = request.initial_cash  # type: ignore[attr-defined]
        freq = request.freq  # type: ignore[attr-defined]
        strategy_params = request.strategy_params  # type: ignore[attr-defined]
        symbols = tuple(request.symbols)  # type: ignore[attr-defined]
        strategy_name = request.strategy_name  # type: ignore[attr-defined]

        progress_cb, loop = _resolve_progress(job)
        sync_progress = (
            _sync_progress_adapter(progress_cb, loop)  # type: ignore[arg-type]
            if progress_cb is not None and loop is not None
            else None
        )
        is_cancelled = _resolve_cancel(job)

        def strategy_factory(params: dict[str, Any]) -> Any:
            merged = {**strategy_params, **params}
            return _build_strategy(strategy_name, overrides=merged)

        def backtest_factory(strategy: Any, trial: SweepTrial) -> Backtest:
            return Backtest(
                bar_loader=loader,
                strategy=strategy,
                run_id=trial.run_id,
                symbols=symbols,
                start=start,
                end=end,
                initial_cash=initial_cash,
                freq=freq,
                strategy_params=strategy_params,
            )

        result = runner.run(
            strategy_factory=strategy_factory,
            backtest_factory=backtest_factory,
            on_progress=sync_progress,
            is_cancelled=is_cancelled,
        )
        if result.cancelled:
            return {"cancelled": True}
        await PgSweepResultStore().save_sweep_result(
            result,
            search_spec=request.search_spec.model_dump(),  # type: ignore[attr-defined]
            search_type=request.search_type,  # type: ignore[attr-defined]
            user_id=job.get("user_id"),
        )
        return {"progress": 100}


# ---------------------------------------------------------------- walk-forward op


class WalkForwardRunOp:
    """Execute a walk-forward study and persist parent + window rows."""

    async def __call__(self, job: dict[str, Any]) -> dict[str, Any] | None:
        from getrich.apps.web.schemas.backtest import WalkForwardRunRequest

        request = _request_from_job(job, WalkForwardRunRequest)
        wf_id: str = job["ref_id"]
        space = _build_param_space(request.search_spec.model_dump())  # type: ignore[attr-defined]
        wf = WalkForward(
            walk_forward_id=wf_id,
            search=GridSearch(space=space),
            train_months=request.train_months,  # type: ignore[attr-defined]
            val_months=request.val_months,  # type: ignore[attr-defined]
            step_months=request.step_months,  # type: ignore[attr-defined]
            refit=request.refit,  # type: ignore[attr-defined]
            select_metric=request.select_metric,  # type: ignore[attr-defined]
            maximize=request.maximize,  # type: ignore[attr-defined]
            fail_fast=request.fail_fast,  # type: ignore[attr-defined]
        )
        loader = _build_bar_loader(request.bar_loader)  # type: ignore[attr-defined]
        start = request.start  # type: ignore[attr-defined]
        end = request.end  # type: ignore[attr-defined]
        initial_cash = request.initial_cash  # type: ignore[attr-defined]
        freq = request.freq  # type: ignore[attr-defined]
        strategy_params = request.strategy_params  # type: ignore[attr-defined]
        symbols = tuple(request.symbols)  # type: ignore[attr-defined]
        strategy_name = request.strategy_name  # type: ignore[attr-defined]

        progress_cb, loop = _resolve_progress(job)
        sync_progress = (
            _sync_progress_adapter(progress_cb, loop)  # type: ignore[arg-type]
            if progress_cb is not None and loop is not None
            else None
        )
        is_cancelled = _resolve_cancel(job)

        def strategy_factory(params: dict[str, Any]) -> Any:
            merged = {**strategy_params, **params}
            return _build_strategy(strategy_name, overrides=merged)

        def backtest_factory(strategy: Any, spec: WalkForwardRunSpec) -> Backtest:
            window = spec.window
            if spec.phase == "train":
                phase_start = window.train_start
                phase_end = window.train_end
            else:
                phase_start = window.val_start
                phase_end = window.val_end
            return Backtest(
                bar_loader=loader,
                strategy=strategy,
                run_id=spec.run_id,
                symbols=symbols,
                start=phase_start,
                end=phase_end,
                initial_cash=initial_cash,
                freq=freq,
                strategy_params=strategy_params,
            )

        result = wf.run(
            start=start,
            end=end,
            strategy_factory=strategy_factory,
            backtest_factory=backtest_factory,
            on_progress=sync_progress,
            is_cancelled=is_cancelled,
        )
        if result.cancelled:
            return {"cancelled": True}
        await PgWalkForwardResultStore().save_walk_forward_result(
            result,
            search_spec=request.search_spec.model_dump(),  # type: ignore[attr-defined]
            search_type="grid",
        )
        return {"progress": 100}


# ---------------------------------------------------------------- registry


_OPS: dict[str, Any] = {
    "backtest": BacktestRunOp,
    "sweep": SweepRunOp,
    "walk_forward": WalkForwardRunOp,
}


def get_op_for_job_type(job_type: str) -> Any:
    """Return the ``BacktestJobOp`` implementation for a given job_type.

    Raises ``BacktestJobError`` for unknown categories.
    """
    op = _OPS.get(job_type)
    if op is None:
        raise BacktestJobError(f"unknown job_type: {job_type!r}")
    return op()


__all__ = [
    "BacktestRunOp",
    "SweepRunOp",
    "WalkForwardRunOp",
    "get_op_for_job_type",
]
