"""Parameter sweep utilities for systematic backtest research."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal

import polars as pl

from gr_backtest.api import Backtest
from gr_backtest.metrics import BacktestMetrics, compute_metrics
from gr_backtest.result import BacktestResult
from gr_backtest.strategy import Strategy


logger = logging.getLogger(__name__)


ParamConfig = Mapping[str, object]


# Sync callback signature: (completed, total) -> None. The sweep engine does
# not impose a percent-vs-trial-count contract; the caller maps as needed.
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class ParamDimension:
    """One named parameter dimension in a grid search."""

    values: tuple[object, ...]
    kind: str

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("parameter dimension values must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "values": list(self.values)}


class P:
    """Factory helpers for parameter dimensions."""

    @staticmethod
    def categorical(values: Sequence[object]) -> ParamDimension:
        return ParamDimension(tuple(values), "categorical")

    @staticmethod
    def int_range(
        start: int,
        stop: int,
        *,
        step: int = 1,
        inclusive: bool = True,
    ) -> ParamDimension:
        if step <= 0:
            raise ValueError("step must be positive")
        if start > stop:
            raise ValueError("start must be less than or equal to stop")
        end = stop + 1 if inclusive else stop
        return ParamDimension(tuple(range(start, end, step)), "int_range")

    @staticmethod
    def decimal_range(
        start: Decimal | str,
        stop: Decimal | str,
        *,
        step: Decimal | str,
        inclusive: bool = True,
    ) -> ParamDimension:
        start_d = Decimal(str(start))
        stop_d = Decimal(str(stop))
        step_d = Decimal(str(step))
        if step_d <= Decimal("0"):
            raise ValueError("step must be positive")
        if start_d > stop_d:
            raise ValueError("start must be less than or equal to stop")

        values: list[Decimal] = []
        current = start_d
        while current < stop_d or (inclusive and current == stop_d):
            values.append(current)
            current += step_d
        return ParamDimension(tuple(values), "decimal_range")


class ParamSpace:
    """Deterministic Cartesian parameter space with optional constraints."""

    def __init__(self, dimensions: Mapping[str, ParamDimension | Sequence[object]]) -> None:
        if not dimensions:
            raise ValueError("dimensions must be non-empty")
        self._dimensions: dict[str, ParamDimension] = {}
        for name, dimension in dimensions.items():
            if not name.strip():
                raise ValueError("parameter names must be non-empty")
            if isinstance(dimension, ParamDimension):
                self._dimensions[name] = dimension
            else:
                self._dimensions[name] = P.categorical(dimension)
        self._constraints: list[Callable[[dict[str, object]], bool]] = []

    def add_constraint(self, fn: Callable[[dict[str, object]], bool]) -> ParamSpace:
        self._constraints.append(fn)
        return self

    def iter_configs(self) -> Iterator[dict[str, object]]:
        names = tuple(self._dimensions)
        yield from self._iter_configs(names, 0, {})

    def to_dict(self) -> dict[str, object]:
        return {
            "dimensions": {
                name: dimension.to_dict() for name, dimension in self._dimensions.items()
            }
        }

    def _iter_configs(
        self,
        names: tuple[str, ...],
        index: int,
        current: dict[str, object],
    ) -> Iterator[dict[str, object]]:
        if index == len(names):
            candidate = dict(current)
            if all(fn(candidate) for fn in self._constraints):
                yield candidate
            return

        name = names[index]
        for value in self._dimensions[name].values:
            current[name] = value
            yield from self._iter_configs(names, index + 1, current)
        current.pop(name, None)


@dataclass(frozen=True)
class GridSearch:
    """Deterministic grid search over a ``ParamSpace``."""

    space: ParamSpace

    def to_dict(self) -> dict[str, object]:
        return {"type": "grid", "space": self.space.to_dict()}

    def iter_trials(
        self,
        *,
        sweep_id: str,
        run_id_prefix: str | None = None,
    ) -> Iterator[SweepTrial]:
        if not sweep_id.strip():
            raise ValueError("sweep_id must be non-empty")
        prefix = run_id_prefix or sweep_id
        for index, params in enumerate(self.space.iter_configs()):
            fingerprint = _param_fingerprint(params)
            short = fingerprint[:12]
            yield SweepTrial(
                sweep_id=sweep_id,
                trial_id=f"{sweep_id}-trial-{index:04d}-{short}",
                run_id=f"{prefix}-run-{index:04d}-{short}",
                index=index,
                params=params,
                param_fingerprint=fingerprint,
            )


@dataclass(frozen=True)
class SweepTrial:
    """One concrete parameter configuration scheduled in a sweep."""

    sweep_id: str
    trial_id: str
    run_id: str
    index: int
    params: dict[str, object]
    param_fingerprint: str


@dataclass(frozen=True)
class SweepTrialResult:
    """Outcome of one sweep trial."""

    trial: SweepTrial
    status: Literal["completed", "failed"]
    result: BacktestResult | None
    metrics: BacktestMetrics | None
    error_message: str | None = None

    @property
    def run_id(self) -> str:
        return self.trial.run_id


@dataclass(frozen=True)
class SweepResult:
    """Aggregated result of a completed parameter sweep."""

    sweep_id: str
    trials: tuple[SweepTrialResult, ...]
    select_metric: str
    maximize: bool
    cancelled: bool = False

    def completed(self) -> tuple[SweepTrialResult, ...]:
        return tuple(trial for trial in self.trials if trial.status == "completed")

    def failed(self) -> tuple[SweepTrialResult, ...]:
        return tuple(trial for trial in self.trials if trial.status == "failed")

    def summary(self) -> dict[str, object]:
        try:
            best = self.best_trial()
            best_metric = (
                getattr(best.metrics, self.select_metric) if best.metrics is not None else None
            )
        except ValueError:
            best = None
            best_metric = None
        return {
            "sweep_id": self.sweep_id,
            "select_metric": self.select_metric,
            "maximize": self.maximize,
            "total_trials": len(self.trials),
            "completed_trials": len(self.completed()),
            "failed_trials": len(self.failed()),
            "best_trial_id": best.trial.trial_id if best is not None else None,
            "best_run_id": best.trial.run_id if best is not None else None,
            "best_params": dict(best.trial.params) if best is not None else None,
            "best_metric_value": best_metric,
        }

    def best_trial(
        self,
        metric: str | None = None,
        *,
        maximize: bool | None = None,
    ) -> SweepTrialResult:
        metric_name = metric or self.select_metric
        should_maximize = self.maximize if maximize is None else maximize
        scored: list[tuple[Decimal, SweepTrialResult]] = []
        for trial in self.completed():
            if trial.metrics is None or not hasattr(trial.metrics, metric_name):
                continue
            value = getattr(trial.metrics, metric_name)
            if isinstance(value, Decimal):
                scored.append((value, trial))
            elif isinstance(value, int | float):
                scored.append((Decimal(str(value)), trial))
        if not scored:
            raise ValueError(f"no completed trials with metric {metric_name!r}")
        return sorted(scored, key=lambda item: item[0], reverse=should_maximize)[0][1]

    def to_frame(self) -> pl.DataFrame:
        rows: list[dict[str, object]] = []
        for trial_result in self.trials:
            row: dict[str, object] = {
                "sweep_id": self.sweep_id,
                "trial_id": trial_result.trial.trial_id,
                "run_id": trial_result.trial.run_id,
                "index": trial_result.trial.index,
                "status": trial_result.status,
                "error_message": trial_result.error_message,
                "param_fingerprint": trial_result.trial.param_fingerprint,
                "params": dict(trial_result.trial.params),
            }
            for name, value in trial_result.trial.params.items():
                row[f"param_{name}"] = value
            if trial_result.metrics is not None:
                row.update(trial_result.metrics.to_dict())
            rows.append(row)
        return pl.DataFrame(rows)


class SweepRunner:
    """Sequential runner for deterministic parameter sweeps."""

    def __init__(
        self,
        *,
        sweep_id: str,
        search: GridSearch,
        select_metric: str = "sharpe_ratio",
        maximize: bool = True,
        fail_fast: bool = False,
    ) -> None:
        if not sweep_id.strip():
            raise ValueError("sweep_id must be non-empty")
        self.sweep_id = sweep_id
        self.search = search
        self.select_metric = select_metric
        self.maximize = maximize
        self.fail_fast = fail_fast

    def run(
        self,
        *,
        strategy_factory: Callable[[dict[str, object]], Strategy],
        backtest_factory: Callable[[Strategy, SweepTrial], Backtest],
        on_progress: ProgressCallback | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> SweepResult:
        trial_results: list[SweepTrialResult] = []
        trials = list(self.search.iter_trials(sweep_id=self.sweep_id))
        total = len(trials)
        cancelled = False
        for i, trial in enumerate(trials, start=1):
            if is_cancelled is not None:
                try:
                    if is_cancelled():
                        cancelled = True
                        break
                except Exception:  # noqa: BLE001
                    # Cancellation checks must never crash the engine.
                    logger.exception("sweep is_cancelled check failed at %d/%d", i, total)
            try:
                params = dict(trial.params)
                strategy = strategy_factory(params)
                backtest = backtest_factory(strategy, trial)
                result = backtest.run()
                metrics = compute_metrics(result)
                trial_results.append(
                    SweepTrialResult(
                        trial=trial,
                        status="completed",
                        result=result,
                        metrics=metrics,
                    )
                )
            except Exception as exc:
                if self.fail_fast:
                    raise
                trial_results.append(
                    SweepTrialResult(
                        trial=trial,
                        status="failed",
                        result=None,
                        metrics=None,
                        error_message=str(exc),
                    )
                )
            if on_progress is not None:
                try:
                    on_progress(i, total)
                except Exception:  # noqa: BLE001
                    # Progress callbacks must not interrupt the sweep loop.
                    logger.exception("sweep on_progress callback failed at %d/%d", i, total)
        return SweepResult(
            sweep_id=self.sweep_id,
            trials=tuple(trial_results),
            select_metric=self.select_metric,
            maximize=self.maximize,
            cancelled=cancelled,
        )


def _param_fingerprint(params: Mapping[str, object]) -> str:
    payload = json.dumps(
        params,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
