"""Backtest / sweep / walk_forward execution request Pydantic models.

These models validate the body of the HTTP execution endpoints
``POST /v1/backtest-jobs/{backtest|sweep|walk-forward}``. They share the
common run-time configuration (symbols, window, initial cash, freq) and
additionally capture the engine-specific knobs.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


BarLoaderKind = Literal["pg", "duckdb"]


class _BaseRunRequest(BaseModel):
    """Common configuration for backtest / sweep / walk_forward runs."""

    strategy_name: str = Field(min_length=1, max_length=128)
    symbols: list[str] = Field(min_length=1)
    start: datetime
    end: datetime
    initial_cash: Decimal = Field(ge=0)
    freq: str = Field(default="1d", max_length=16)
    bar_loader: BarLoaderKind = "pg"
    # Retry policy: 1 = no retry (P0 default), up to 10 attempts total.
    # The idempotency_key lives in the ``Idempotency-Key`` HTTP header, not here.
    max_attempts: int = Field(default=1, ge=1, le=10)
    # Per-job retry override (P1 #6). All three are optional; any unset
    # field falls back to the BacktestJobRunner-level default. ``cap``
    # must be ``>= base`` when both are provided (cross-field check).
    retry_base_seconds: float | None = Field(default=None, gt=0)
    retry_cap_seconds: float | None = Field(default=None, gt=0)
    retry_jitter_pct: float | None = Field(default=None, ge=0.0, lt=1.0)

    @model_validator(mode="after")
    def _check_window(self) -> _BaseRunRequest:
        if self.start >= self.end:
            raise ValueError("start must be strictly before end")
        return self

    @model_validator(mode="after")
    def _check_retry_overrides(self) -> _BaseRunRequest:
        if (
            self.retry_base_seconds is not None
            and self.retry_cap_seconds is not None
            and self.retry_cap_seconds < self.retry_base_seconds
        ):
            raise ValueError("retry_cap_seconds must be >= retry_base_seconds")
        return self


class BacktestRunRequest(_BaseRunRequest):
    """POST /v1/backtest-jobs/backtest body."""

    extra_freqs: list[str] = Field(default_factory=list)
    execution_lag_bars: int = Field(default=1, ge=1)
    strategy_params: dict[str, object] = Field(default_factory=dict)
    save_artifacts: bool = False


class _SearchSpec(BaseModel):
    """Lightweight grid-search spec.

    Each entry in ``space`` is either a list of literal values (categorical)
    or a ``{kind: ..., ...}`` dict compatible with ``P.categorical`` /
    ``P.int_range`` / ``P.decimal_range``. Constraints are not supported
    in P0 and are silently ignored.
    """

    space: dict[str, object] = Field(min_length=1)
    constraints: list[object] = Field(default_factory=list)


class SweepRunRequest(_BaseRunRequest):
    """POST /v1/backtest-jobs/sweep body."""

    sweep_id: str | None = Field(default=None, min_length=1, max_length=128)
    search_type: Literal["grid"] = "grid"
    search_spec: _SearchSpec
    select_metric: str = Field(default="sharpe_ratio", max_length=64)
    maximize: bool = True
    fail_fast: bool = False
    strategy_params: dict[str, object] = Field(default_factory=dict)


class WalkForwardRunRequest(_BaseRunRequest):
    """POST /v1/backtest-jobs/walk-forward body."""

    walk_forward_id: str | None = Field(default=None, min_length=1, max_length=128)
    search_spec: _SearchSpec
    train_months: int = Field(ge=1)
    val_months: int = Field(ge=1)
    step_months: int | None = Field(default=None, ge=1)
    refit: Literal["rolling", "anchored"] = "rolling"
    select_metric: str = Field(default="sharpe_ratio", max_length=64)
    maximize: bool = True
    fail_fast: bool = False
    strategy_params: dict[str, object] = Field(default_factory=dict)
