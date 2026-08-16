"""Walk-forward train/validation orchestration for backtest research."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import polars as pl
from dateutil.relativedelta import relativedelta

from gr_backtest.api import Backtest
from gr_backtest.metrics import BacktestMetrics, compute_metrics
from gr_backtest.result import BacktestResult
from gr_backtest.strategy import Strategy
from gr_backtest.sweep import (
    GridSearch,
    ProgressCallback,
    SweepResult,
    SweepRunner,
    SweepTrial,
    SweepTrialResult,
)
from gr_backtest.time import normalize_datetime_range


if TYPE_CHECKING:
    from gr_backtest.walk_forward_report import WalkForwardReport


logger = logging.getLogger(__name__)


RefitMode = Literal["rolling", "anchored"]
WalkForwardPhase = Literal["train", "validation"]
WalkForwardStatus = Literal["completed", "failed"]


@dataclass(frozen=True)
class WalkForwardWindow:
    """One half-open train/validation window pair."""

    index: int
    train_start: datetime
    train_end: datetime
    val_start: datetime
    val_end: datetime


@dataclass(frozen=True)
class WalkForwardRunSpec:
    """Factory context for one train or validation backtest run."""

    walk_forward_id: str
    window: WalkForwardWindow
    phase: WalkForwardPhase
    run_id: str
    params: dict[str, object]
    trial: SweepTrial | None = None


@dataclass(frozen=True)
class WalkForwardWindowResult:
    """Result for one walk-forward window."""

    window: WalkForwardWindow
    train_sweep: SweepResult | None
    best_trial: SweepTrialResult | None
    validation_result: BacktestResult | None
    validation_metrics: BacktestMetrics | None
    status: WalkForwardStatus
    error_message: str | None = None


@dataclass(frozen=True)
class WalkForwardResult:
    """Aggregated in-memory walk-forward result."""

    walk_forward_id: str
    windows: tuple[WalkForwardWindowResult, ...]
    select_metric: str
    maximize: bool
    refit: RefitMode
    cancelled: bool = False

    def completed(self) -> tuple[WalkForwardWindowResult, ...]:
        return tuple(window for window in self.windows if window.status == "completed")

    def failed(self) -> tuple[WalkForwardWindowResult, ...]:
        return tuple(window for window in self.windows if window.status == "failed")

    def summary(self) -> dict[str, object]:
        completed = self.completed()
        metric_values: list[Decimal] = []
        for window in completed:
            if window.validation_metrics is None:
                continue
            value = getattr(window.validation_metrics, self.select_metric, None)
            if isinstance(value, Decimal):
                metric_values.append(value)
            elif isinstance(value, int | float):
                metric_values.append(Decimal(str(value)))

        mean_metric = None
        if metric_values:
            mean_metric = sum(metric_values, Decimal("0")) / Decimal(len(metric_values))

        return {
            "walk_forward_id": self.walk_forward_id,
            "select_metric": self.select_metric,
            "maximize": self.maximize,
            "refit": self.refit,
            "total_windows": len(self.windows),
            "completed_windows": len(completed),
            "failed_windows": len(self.failed()),
            "mean_validation_metric": mean_metric,
        }

    def to_frame(self) -> pl.DataFrame:
        rows: list[dict[str, object]] = []
        for window_result in self.windows:
            best_trial = window_result.best_trial
            validation_result = window_result.validation_result
            best_params = dict(best_trial.trial.params) if best_trial is not None else None
            row: dict[str, object] = {
                "walk_forward_id": self.walk_forward_id,
                "window_index": window_result.window.index,
                "train_start": window_result.window.train_start,
                "train_end": window_result.window.train_end,
                "val_start": window_result.window.val_start,
                "val_end": window_result.window.val_end,
                "status": window_result.status,
                "error_message": window_result.error_message,
                "best_trial_id": best_trial.trial.trial_id if best_trial is not None else None,
                "best_run_id": best_trial.trial.run_id if best_trial is not None else None,
                "validation_run_id": (
                    validation_result.run_id if validation_result is not None else None
                ),
                "best_params": best_params,
            }
            if best_params is not None:
                for name, value in best_params.items():
                    row[f"param_{name}"] = value
            if window_result.validation_metrics is not None:
                row.update(
                    {
                        f"validation_{name}": value
                        for name, value in window_result.validation_metrics.to_dict().items()
                    }
                )
            rows.append(row)
        return pl.DataFrame(rows)

    def oos_equity_curve(self) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        for window_result in self.completed():
            if window_result.validation_result is None:
                continue
            frames.append(
                window_result.validation_result.equity_curve.with_columns(
                    pl.lit(window_result.window.index).alias("window_index"),
                    pl.lit(window_result.validation_result.run_id).alias("run_id"),
                )
            )
        if not frames:
            return pl.DataFrame()
        return pl.concat(frames, how="diagonal")

    def report(self) -> WalkForwardReport:
        """Build an analysis/report helper for this walk-forward result."""
        from gr_backtest.walk_forward_report import WalkForwardReport

        return WalkForwardReport(self)


class WalkForward:
    """Sequential walk-forward runner over repeated train sweeps and OOS validation."""

    def __init__(
        self,
        *,
        walk_forward_id: str,
        search: GridSearch,
        train_months: int,
        val_months: int,
        step_months: int | None = None,
        refit: RefitMode = "rolling",
        select_metric: str = "sharpe_ratio",
        maximize: bool = True,
        fail_fast: bool = False,
    ) -> None:
        if not walk_forward_id.strip():
            raise ValueError("walk_forward_id must be non-empty")
        if train_months <= 0:
            raise ValueError("train_months must be positive")
        if val_months <= 0:
            raise ValueError("val_months must be positive")
        if step_months is not None and step_months <= 0:
            raise ValueError("step_months must be positive")
        if refit not in ("rolling", "anchored"):
            raise ValueError("refit must be 'rolling' or 'anchored'")

        self.walk_forward_id = walk_forward_id
        self.search = search
        self.train_months = train_months
        self.val_months = val_months
        self.step_months = step_months or val_months
        self.refit: RefitMode = refit
        self.select_metric = select_metric
        self.maximize = maximize
        self.fail_fast = fail_fast

    def iter_windows(self, *, start: datetime, end: datetime) -> Iterator[WalkForwardWindow]:
        normalized_start, normalized_end = normalize_datetime_range(start, end)
        index = 0

        if self.refit == "rolling":
            cursor = normalized_start
            while True:
                train_start = cursor
                train_end = train_start + relativedelta(months=self.train_months)
                val_start = train_end
                val_end = val_start + relativedelta(months=self.val_months)
                if val_end > normalized_end:
                    break
                yield WalkForwardWindow(index, train_start, train_end, val_start, val_end)
                index += 1
                cursor = cursor + relativedelta(months=self.step_months)
            return

        train_start = normalized_start
        train_end = train_start + relativedelta(months=self.train_months)
        while True:
            val_start = train_end
            val_end = val_start + relativedelta(months=self.val_months)
            if val_end > normalized_end:
                break
            yield WalkForwardWindow(index, train_start, train_end, val_start, val_end)
            index += 1
            train_end = train_end + relativedelta(months=self.step_months)

    def run(
        self,
        *,
        start: datetime,
        end: datetime,
        strategy_factory: Callable[[dict[str, object]], Strategy],
        backtest_factory: Callable[[Strategy, WalkForwardRunSpec], Backtest],
        on_progress: ProgressCallback | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> WalkForwardResult:
        window_results: list[WalkForwardWindowResult] = []
        windows = list(self.iter_windows(start=start, end=end))
        total = len(windows)
        cancelled = False
        for i, window in enumerate(windows, start=1):
            if is_cancelled is not None:
                try:
                    if is_cancelled():
                        cancelled = True
                        break
                except Exception:  # noqa: BLE001
                    logger.exception("walk_forward is_cancelled check failed at %d/%d", i, total)
            try:
                window_results.append(
                    self._run_window(
                        window,
                        strategy_factory=strategy_factory,
                        backtest_factory=backtest_factory,
                    )
                )
            except Exception as exc:
                if self.fail_fast:
                    raise
                window_results.append(
                    WalkForwardWindowResult(
                        window=window,
                        train_sweep=None,
                        best_trial=None,
                        validation_result=None,
                        validation_metrics=None,
                        status="failed",
                        error_message=str(exc),
                    )
                )
            if on_progress is not None:
                try:
                    on_progress(i, total)
                except Exception:  # noqa: BLE001
                    # Progress callbacks must not interrupt the walk-forward loop.
                    logger.exception("walk_forward on_progress callback failed at %d/%d", i, total)

        return WalkForwardResult(
            walk_forward_id=self.walk_forward_id,
            windows=tuple(window_results),
            select_metric=self.select_metric,
            maximize=self.maximize,
            refit=self.refit,
            cancelled=cancelled,
        )

    def _run_window(
        self,
        window: WalkForwardWindow,
        *,
        strategy_factory: Callable[[dict[str, object]], Strategy],
        backtest_factory: Callable[[Strategy, WalkForwardRunSpec], Backtest],
    ) -> WalkForwardWindowResult:
        train_sweep_id = f"{self.walk_forward_id}-w{window.index:04d}-train"
        runner = SweepRunner(
            sweep_id=train_sweep_id,
            search=self.search,
            select_metric=self.select_metric,
            maximize=self.maximize,
            fail_fast=self.fail_fast,
        )

        def train_backtest_factory(strategy: Strategy, trial: SweepTrial) -> Backtest:
            spec = WalkForwardRunSpec(
                walk_forward_id=self.walk_forward_id,
                window=window,
                phase="train",
                run_id=trial.run_id,
                params=dict(trial.params),
                trial=trial,
            )
            return backtest_factory(strategy, spec)

        train_sweep = runner.run(
            strategy_factory=strategy_factory,
            backtest_factory=train_backtest_factory,
        )
        best_trial = train_sweep.best_trial(metric=self.select_metric, maximize=self.maximize)
        best_params = dict(best_trial.trial.params)
        validation_run_id = (
            f"{self.walk_forward_id}-w{window.index:04d}-validation-"
            f"{best_trial.trial.param_fingerprint[:12]}"
        )
        validation_strategy = strategy_factory(best_params)
        validation_spec = WalkForwardRunSpec(
            walk_forward_id=self.walk_forward_id,
            window=window,
            phase="validation",
            run_id=validation_run_id,
            params=best_params,
            trial=None,
        )
        validation_result = backtest_factory(validation_strategy, validation_spec).run()
        validation_metrics = compute_metrics(validation_result)

        return WalkForwardWindowResult(
            window=window,
            train_sweep=train_sweep,
            best_trial=best_trial,
            validation_result=validation_result,
            validation_metrics=validation_metrics,
            status="completed",
        )
