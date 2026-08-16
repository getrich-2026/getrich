"""Schema validation tests for per-job retry override fields on
_BaseRunRequest and its subclasses.

P1 #6: ``retry_base_seconds`` / ``retry_cap_seconds`` / ``retry_jitter_pct``
become optional fields on every backtest / sweep / walk_forward run
request. They default to ``None``, which means "use the runner's
default". When non-None, the cross-field invariant
``cap >= base`` must hold.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from gr_api.schemas.backtest import (
    BacktestRunRequest,
    SweepRunRequest,
    WalkForwardRunRequest,
)
from pydantic import ValidationError


_TZ = ZoneInfo("Asia/Shanghai")


def _base_payload() -> dict:
    return {
        "strategy_name": "macross",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "1000",
        "freq": "1d",
        "extra_freqs": [],
        "execution_lag_bars": 1,
        "strategy_params": {},
        "bar_loader": "pg",
        "save_artifacts": False,
    }


# ---------------------------------------------------------------- baseline


def test_retry_fields_default_to_none() -> None:
    """No retry_* fields in the body → all default to None."""
    body = BacktestRunRequest.model_validate(_base_payload())

    assert body.retry_base_seconds is None
    assert body.retry_cap_seconds is None
    assert body.retry_jitter_pct is None


def test_retry_fields_are_propagated() -> None:
    """All three fields are stored verbatim when provided."""
    payload = _base_payload()
    payload.update(
        {
            "retry_base_seconds": 2.5,
            "retry_cap_seconds": 30.0,
            "retry_jitter_pct": 0.15,
        }
    )
    body = BacktestRunRequest.model_validate(payload)

    assert body.retry_base_seconds == 2.5
    assert body.retry_cap_seconds == 30.0
    assert body.retry_jitter_pct == 0.15


# ---------------------------------------------------------------- per-field bounds


def test_retry_base_must_be_positive() -> None:
    """retry_base_seconds must be > 0."""
    payload = _base_payload()
    payload["retry_base_seconds"] = 0.0
    with pytest.raises(ValidationError):
        BacktestRunRequest.model_validate(payload)


def test_retry_base_negative_rejected() -> None:
    payload = _base_payload()
    payload["retry_base_seconds"] = -1.0
    with pytest.raises(ValidationError):
        BacktestRunRequest.model_validate(payload)


def test_retry_cap_must_be_positive() -> None:
    payload = _base_payload()
    payload["retry_cap_seconds"] = 0.0
    with pytest.raises(ValidationError):
        BacktestRunRequest.model_validate(payload)


def test_retry_jitter_must_be_in_unit_interval() -> None:
    """retry_jitter_pct must be in [0.0, 1.0) — 1.0 is rejected to keep
    the runner's "cap semantics" intact."""
    payload = _base_payload()
    payload["retry_jitter_pct"] = 1.0  # boundary — rejected
    with pytest.raises(ValidationError):
        BacktestRunRequest.model_validate(payload)

    payload["retry_jitter_pct"] = 0.5  # midpoint — accepted
    body = BacktestRunRequest.model_validate(payload)
    assert body.retry_jitter_pct == 0.5

    payload["retry_jitter_pct"] = 0.0  # lower boundary — accepted
    body = BacktestRunRequest.model_validate(payload)
    assert body.retry_jitter_pct == 0.0


def test_retry_jitter_negative_rejected() -> None:
    payload = _base_payload()
    payload["retry_jitter_pct"] = -0.01
    with pytest.raises(ValidationError):
        BacktestRunRequest.model_validate(payload)


# ---------------------------------------------------------------- cross-field


def test_retry_cap_must_be_gte_base() -> None:
    """cap < base is rejected (would make the backoff curve inverted)."""
    payload = _base_payload()
    payload.update({"retry_base_seconds": 5.0, "retry_cap_seconds": 3.0})
    with pytest.raises(ValidationError, match="retry_cap_seconds must be >= retry_base_seconds"):
        BacktestRunRequest.model_validate(payload)


def test_retry_cap_equals_base_accepted() -> None:
    """cap == base is the boundary case and is allowed."""
    payload = _base_payload()
    payload.update({"retry_base_seconds": 5.0, "retry_cap_seconds": 5.0})
    body = BacktestRunRequest.model_validate(payload)
    assert body.retry_base_seconds == body.retry_cap_seconds == 5.0


def test_retry_only_base_provided_does_not_trigger_cross_check() -> None:
    """When cap is None (omitted), the cross-field check is skipped."""
    payload = _base_payload()
    payload["retry_base_seconds"] = 1.0
    body = BacktestRunRequest.model_validate(payload)
    assert body.retry_base_seconds == 1.0
    assert body.retry_cap_seconds is None


def test_retry_only_cap_provided_does_not_trigger_cross_check() -> None:
    """When base is None (omitted), the cross-field check is skipped."""
    payload = _base_payload()
    payload["retry_cap_seconds"] = 60.0
    body = BacktestRunRequest.model_validate(payload)
    assert body.retry_cap_seconds == 60.0
    assert body.retry_base_seconds is None


# ---------------------------------------------------------------- sweep / walk_forward inherit


def test_sweep_request_inherits_retry_fields() -> None:
    """SweepRunRequest must accept the same retry_* fields."""
    payload = {
        "strategy_name": "macross",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "1000",
        "freq": "1d",
        "strategy_params": {},
        "bar_loader": "pg",
        "sweep_id": "s-1",
        "search_spec": {"space": {"fast": [5, 10]}, "constraints": []},
        "select_metric": "sharpe_ratio",
        "maximize": True,
        "fail_fast": False,
        "retry_base_seconds": 1.0,
        "retry_cap_seconds": 10.0,
        "retry_jitter_pct": 0.2,
    }
    body = SweepRunRequest.model_validate(payload)
    assert body.retry_base_seconds == 1.0
    assert body.retry_cap_seconds == 10.0
    assert body.retry_jitter_pct == 0.2


def test_walk_forward_request_inherits_retry_fields() -> None:
    payload = {
        "strategy_name": "macross",
        "symbols": ["000001.SZ"],
        "start": datetime(2026, 6, 1, 9, 30, tzinfo=_TZ).isoformat(),
        "end": datetime(2026, 6, 2, 9, 30, tzinfo=_TZ).isoformat(),
        "initial_cash": "1000",
        "freq": "1d",
        "strategy_params": {"fast": 5, "slow": 10},
        "bar_loader": "pg",
        "walk_forward_id": "wf-1",
        "search_spec": {"space": {"fast": [5, 10]}, "constraints": []},
        "train_months": 1,
        "val_months": 1,
        "step_months": None,
        "refit": "rolling",
        "select_metric": "sharpe_ratio",
        "maximize": True,
        "fail_fast": False,
        "retry_base_seconds": 2.0,
    }
    body = WalkForwardRunRequest.model_validate(payload)
    assert body.retry_base_seconds == 2.0
    assert body.retry_cap_seconds is None
    assert body.retry_jitter_pct is None
