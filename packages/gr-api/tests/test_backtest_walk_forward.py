"""Tests for the backtest_walk_forward service.

`services.backtest_walk_forward` powers the read endpoints for the
`/v1/backtest/walk-forwards/*` family. Tests focus on:

- ``_is_terminal_payload`` — terminal-status detection (SSE stream logic)
- ``_payload_etag`` — coarse de-dup key for SSE updates
- ``_empty_wf_row`` — synthetic cancelled frame (when row vanishes mid-stream)
- Row formatters: ``_walk_forward_summary``, ``_walk_forward_detail``,
  ``_window``, ``_equity_point``
- Numeric / datetime coercion helpers: ``_f``, ``_f_nullable``, ``_dt``,
  ``_dt_nullable``, ``_json_value``

Mirrors the structure of ``test_backtest_sweep.py``. The SSE stream
generators and live listener are covered in
``test_walk_forward_run_sse.py`` and ``test_job_listener.py``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from gr_api.services.backtest_walk_forward import (
    _dt,
    _dt_nullable,
    _empty_wf_row,
    _equity_point,
    _f,
    _f_nullable,
    _is_terminal_payload,
    _json_value,
    _payload_etag,
    _walk_forward_detail,
    _walk_forward_summary,
    _window,
)


# ---------------------------------------------------------------------------
# _is_terminal_payload — terminal-status detection
# ---------------------------------------------------------------------------


class TestIsTerminalPayload:
    """``_is_terminal_payload(payload)`` decides whether the SSE generator
    should close the stream. Key on the parent job's status so cancellation
    is correctly surfaced — the walk-forward's own status enum has no
    ``cancelled`` value."""

    def test_job_status_completed_terminates(self) -> None:
        assert _is_terminal_payload({"status": "running", "job_status": "completed"}) is True

    def test_job_status_failed_terminates(self) -> None:
        assert _is_terminal_payload({"status": "running", "job_status": "failed"}) is True

    def test_job_status_cancelled_terminates(self) -> None:
        """Critical: the wf's own status enum has no 'cancelled' value,
        but the job's status does."""
        assert _is_terminal_payload({"status": "running", "job_status": "cancelled"}) is True

    def test_job_status_running_does_not_terminate(self) -> None:
        assert _is_terminal_payload({"status": "running", "job_status": "running"}) is False

    def test_job_status_pending_does_not_terminate(self) -> None:
        assert _is_terminal_payload({"status": "queued", "job_status": "pending"}) is False

    def test_fallback_to_wf_status_completed(self) -> None:
        """In the brief window after row create + before runner claim,
        ``job_status`` is None. The function falls back to the wf's
        own status."""
        assert _is_terminal_payload({"status": "completed", "job_status": None}) is True

    def test_fallback_wf_status_failed(self) -> None:
        assert _is_terminal_payload({"status": "failed", "job_status": None}) is True

    def test_fallback_wf_status_running_does_not_terminate(self) -> None:
        assert _is_terminal_payload({"status": "running", "job_status": None}) is False

    def test_both_none_does_not_terminate(self) -> None:
        assert _is_terminal_payload({"status": None, "job_status": None}) is False


# ---------------------------------------------------------------------------
# _payload_etag — SSE de-dup key
# ---------------------------------------------------------------------------


class TestPayloadEtag:
    def test_keys_on_status(self) -> None:
        a = _payload_etag({"status": "running", "updated_at": "t1"})
        b = _payload_etag({"status": "completed", "updated_at": "t1"})
        assert a != b

    def test_keys_on_job_status(self) -> None:
        a = _payload_etag({"job_status": "running", "updated_at": "t1"})
        b = _payload_etag({"job_status": "cancelled", "updated_at": "t1"})
        assert a != b

    def test_keys_on_progress(self) -> None:
        a = _payload_etag({"progress": 0, "updated_at": "t1"})
        b = _payload_etag({"progress": 25, "updated_at": "t1"})
        assert a != b

    def test_keys_on_updated_at(self) -> None:
        a = _payload_etag({"status": "running", "updated_at": "t1"})
        b = _payload_etag({"status": "running", "updated_at": "t2"})
        assert a != b

    def test_ignores_summary_json_mutations(self) -> None:
        a = _payload_etag({"status": "running", "summary_json": {"a": 1}})
        b = _payload_etag({"status": "running", "summary_json": {"a": 2}})
        assert a == b

    def test_missing_keys_default_to_none(self) -> None:
        etag = _payload_etag({})
        assert etag == (None, None, None, None)

    def test_returns_tuple(self) -> None:
        etag = _payload_etag({"status": "running"})
        assert isinstance(etag, tuple)


# ---------------------------------------------------------------------------
# _empty_wf_row — synthetic cancelled frame
# ---------------------------------------------------------------------------


class TestEmptyWfRow:
    """``_empty_wf_row`` builds a synthetic ``cancelled``-status row when
    the walk-forward vanishes mid-stream (e.g. cleaned up by GC). The
    synthetic row is shaped like ``_walk_forward_summary`` input so the
    downstream ``_walk_forward_detail`` can render a coherent frame."""

    def test_basic_construction(self) -> None:
        last_payload = {
            "user_id": "u-1",
            "search_type": "grid",
            "search_spec": {"x": [1, 2]},
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "total_windows": 5,
            "completed_windows": 2,
            "failed_windows": 0,
            "mean_validation_metric": 1.5,
            "summary_json": {"winner": "w-1"},
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
        }
        result = _empty_wf_row("wf-99", last_payload)
        assert result["walk_forward_id"] == "wf-99"
        assert result["status"] == "cancelled"
        # All other fields mirror the last_payload
        assert result["user_id"] == "u-1"
        assert result["search_type"] == "grid"
        assert result["search_spec"] == {"x": [1, 2]}
        assert result["select_metric"] == "sharpe"
        assert result["maximize"] is True
        assert result["refit"] is False
        assert result["total_windows"] == 5
        assert result["completed_windows"] == 2
        assert result["failed_windows"] == 0
        assert result["mean_validation_metric"] == 1.5
        assert result["summary_json"] == {"winner": "w-1"}
        assert result["created_at"] == "2026-01-01"
        assert result["completed_at"] is None
        assert result["updated_at"] == "2026-01-01T00:00:05Z"

    def test_empty_payload_uses_none_for_optional_fields(self) -> None:
        """When last_payload is empty, all optional fields default to None."""
        result = _empty_wf_row("wf-1", {})
        assert result["walk_forward_id"] == "wf-1"
        assert result["status"] == "cancelled"
        assert result["user_id"] is None
        assert result["search_type"] is None
        assert result["total_windows"] is None
        assert result["completed_windows"] is None

    def test_status_is_always_cancelled(self) -> None:
        """Even if last_payload carried a different status, the synthetic
        row ALWAYS reports ``cancelled`` — that is the whole point of
        the synthetic row."""
        last_payload = {"status": "running", "completed_windows": 3}
        result = _empty_wf_row("wf-1", last_payload)
        assert result["status"] == "cancelled"
        # last_payload's other fields are still passed through
        assert result["completed_windows"] == 3

    def test_walk_forward_id_takes_precedence_over_payload(self) -> None:
        """If last_payload has a stale walk_forward_id, the function
        argument wins (the id is the lookup key)."""
        last_payload = {"walk_forward_id": "stale-id"}
        result = _empty_wf_row("wf-canonical", last_payload)
        assert result["walk_forward_id"] == "wf-canonical"


# ---------------------------------------------------------------------------
# Row formatters
# ---------------------------------------------------------------------------


class TestWalkForwardSummary:
    def test_minimal_row(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "search_type": "grid",
            "search_spec": '{"splits": 3}',
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "status": "running",
            "total_windows": 5,
            "completed_windows": 2,
            "failed_windows": 0,
            "mean_validation_metric": Decimal("1.2"),
            "created_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
        }
        result = _walk_forward_summary(row)
        assert result["walk_forward_id"] == "wf-1"
        assert result["search_type"] == "grid"
        assert result["search_spec"] == {"splits": 3}
        assert result["refit"] is False
        assert result["total_windows"] == 5
        assert result["completed_windows"] == 2
        assert result["mean_validation_metric"] == 1.2
        assert result["completed_at"] is None

    def test_null_optional_fields(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "search_type": "grid",
            "search_spec": None,
            "select_metric": "sharpe",
            "maximize": True,
            "refit": True,
            "status": "completed",
            "total_windows": 0,
            "completed_windows": 0,
            "failed_windows": 0,
            "mean_validation_metric": None,
            "created_at": "2026-01-01",
            "completed_at": "2026-01-02",
            "updated_at": "2026-01-02",
        }
        result = _walk_forward_summary(row)
        assert result["search_spec"] == {}  # default
        assert result["mean_validation_metric"] is None


class TestWalkForwardDetail:
    def test_includes_summary_plus_job_linkage(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "status": "running",
            "total_windows": 5,
            "completed_windows": 0,
            "failed_windows": 0,
            "mean_validation_metric": None,
            "summary_json": '{"windows": []}',
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
        }
        job_row = {"job_id": "job-1", "progress": 40, "status": "running"}
        result = _walk_forward_detail(row, job_row)
        # Summary fields
        assert result["walk_forward_id"] == "wf-1"
        assert result["search_type"] == "grid"
        # Job linkage
        assert result["job_id"] == "job-1"
        assert result["progress"] == 40
        assert result["job_status"] == "running"
        # summary_json parsed
        assert result["summary_json"] == {"windows": []}

    def test_no_job_row_yields_none_linkage(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "status": "running",
            "total_windows": 5,
            "completed_windows": 0,
            "failed_windows": 0,
            "mean_validation_metric": None,
            "summary_json": "{}",
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        result = _walk_forward_detail(row, None)
        assert result["job_id"] is None
        assert result["progress"] is None
        assert result["job_status"] is None

    def test_job_row_progress_falsy_int_zero(self) -> None:
        """``int(job_row.get('progress') or 0)`` — falsy values (None, 0,
        missing key) all become 0."""
        row = {
            "walk_forward_id": "wf-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "status": "running",
            "total_windows": 5,
            "completed_windows": 0,
            "failed_windows": 0,
            "mean_validation_metric": None,
            "summary_json": "{}",
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        result = _walk_forward_detail(row, {"job_id": "j-1", "progress": None, "status": "running"})
        assert result["progress"] == 0
        result = _walk_forward_detail(row, {"job_id": "j-1", "status": "running"})
        assert result["progress"] == 0


class TestWindow:
    def test_minimal_row(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "window_index": 0,
            "train_start": "2024-01-01",
            "train_end": "2024-06-30",
            "val_start": "2024-07-01",
            "val_end": "2024-09-30",
            "status": "completed",
            "error_message": None,
            "train_sweep_id": "sw-1",
            "best_trial_id": "tr-3",
            "best_run_id": "run-3",
            "validation_run_id": "run-v-3",
            "best_params": '{"x": 3}',
            "train_metric_value": Decimal("1.2"),
            "validation_metric_value": Decimal("0.95"),
            "validation_metrics_json": '{"sharpe": 0.95}',
            "created_at": "2024-01-01T00:00:00Z",
            "completed_at": "2024-09-30T00:00:00Z",
            "updated_at": "2024-09-30T00:00:01Z",
        }
        result = _window(row)
        assert result["walk_forward_id"] == "wf-1"
        assert result["window_index"] == 0
        assert result["train_start"] == "2024-01-01"
        assert result["train_end"] == "2024-06-30"
        assert result["val_start"] == "2024-07-01"
        assert result["val_end"] == "2024-09-30"
        assert result["status"] == "completed"
        assert result["error_message"] is None
        assert result["train_sweep_id"] == "sw-1"
        assert result["best_trial_id"] == "tr-3"
        assert result["best_run_id"] == "run-3"
        assert result["validation_run_id"] == "run-v-3"
        assert result["best_params"] == {"x": 3}
        assert result["train_metric_value"] == 1.2
        assert result["validation_metric_value"] == 0.95
        assert result["validation_metrics_json"] == {"sharpe": 0.95}

    def test_failed_window_keeps_error_message(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "window_index": 2,
            "train_start": "2024-01-01",
            "train_end": "2024-06-30",
            "val_start": "2024-07-01",
            "val_end": "2024-09-30",
            "status": "failed",
            "error_message": "sweep timeout",
            "train_sweep_id": "sw-3",
            "best_trial_id": None,
            "best_run_id": None,
            "validation_run_id": None,
            "best_params": None,
            "train_metric_value": None,
            "validation_metric_value": None,
            "validation_metrics_json": None,
            "created_at": "2024-01-01",
            "completed_at": "2024-01-01",
            "updated_at": "2024-01-01",
        }
        result = _window(row)
        assert result["status"] == "failed"
        assert result["error_message"] == "sweep timeout"
        assert result["best_params"] == {}  # null → empty dict
        assert result["validation_metrics_json"] == {}
        assert result["validation_metric_value"] is None
        assert result["completed_at"] == "2024-01-01"


class TestEquityPoint:
    def test_minimal_row(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "window_index": 0,
            "run_id": "run-1",
            "strategy_name": "MACross",
            "dt": "2024-09-30T00:00:00Z",
            "cash": "0.5",
            "equity": "1.05",
            "trading_pnl": "0.01",
            "mtm_pnl": "0.005",
            "total_fees": "0.0001",
            "gross_exposure": "0.5",
            "row_json": '{"extra": 1}',
            "created_at": "2024-09-30T00:00:01Z",
        }
        result = _equity_point(row)
        assert result["walk_forward_id"] == "wf-1"
        assert result["window_index"] == 0
        assert result["run_id"] == "run-1"
        assert result["strategy_name"] == "MACross"
        assert result["dt"] == "2024-09-30T00:00:00Z"
        assert result["cash"] == 0.5
        assert result["equity"] == 1.05
        assert result["trading_pnl"] == 0.01
        assert result["row_json"] == {"extra": 1}

    def test_null_pnl_fields_stay_null(self) -> None:
        """Nullable pnl fields (cash, trading_pnl, mtm_pnl, fees, exposure)
        stay None on null input; ``equity`` defaults to 0.0."""
        row = {
            "walk_forward_id": "wf-1",
            "window_index": 0,
            "run_id": "run-1",
            "strategy_name": "S",
            "dt": "2024-09-30",
            "cash": None,
            "equity": None,
            "trading_pnl": None,
            "mtm_pnl": None,
            "total_fees": None,
            "gross_exposure": None,
            "row_json": None,
            "created_at": "2024-09-30",
        }
        result = _equity_point(row)
        assert result["cash"] is None
        assert result["trading_pnl"] is None
        assert result["equity"] == 0.0  # _f default
        assert result["row_json"] == {}


# ---------------------------------------------------------------------------
# Numeric / datetime coercion helpers
# ---------------------------------------------------------------------------


class TestJsonValue:
    def test_none_returns_default(self) -> None:
        assert _json_value(None, {}) == {}
        assert _json_value(None, []) == []
        assert _json_value(None, "fallback") == "fallback"

    def test_string_json_parses(self) -> None:
        assert _json_value('{"x": 1}', {}) == {"x": 1}
        assert _json_value("[1, 2, 3]", []) == [1, 2, 3]

    def test_invalid_json_returns_raw_string(self) -> None:
        assert _json_value("not-json", "default") == "not-json"

    def test_non_string_passes_through(self) -> None:
        assert _json_value({"x": 1}, {}) == {"x": 1}
        assert _json_value([1, 2], []) == [1, 2]
        assert _json_value(42, 0) == 42


class TestFCoercion:
    def test_decimal_to_float(self) -> None:
        assert _f(Decimal("3.14")) == 3.14

    def test_string_to_float(self) -> None:
        assert _f("2.5") == 2.5

    def test_int_to_float(self) -> None:
        assert _f(2) == 2.0

    def test_none_returns_zero(self) -> None:
        assert _f(None) == 0.0

    def test_f_nullable_none_stays_none(self) -> None:
        assert _f_nullable(None) is None

    def test_f_nullable_decimal(self) -> None:
        assert _f_nullable(Decimal("1.5")) == 1.5

    def test_f_nullable_zero_stays_zero(self) -> None:
        assert _f_nullable(0) == 0.0
        assert _f_nullable(Decimal("0")) == 0.0


class TestDtCoercion:
    def test_none_returns_empty_string(self) -> None:
        assert _dt(None) == ""

    def test_none_nullable_stays_none(self) -> None:
        assert _dt_nullable(None) is None

    def test_datetime_to_isoformat(self) -> None:
        ts = datetime(2026, 1, 2, 12, 30, 45)
        assert _dt(ts) == "2026-01-02T12:30:45"
        assert _dt_nullable(ts) == "2026-01-02T12:30:45"

    def test_string_passes_through(self) -> None:
        assert _dt("2026-01-01") == "2026-01-01"
        assert _dt_nullable("2026-01-01") == "2026-01-01"


# ---------------------------------------------------------------------------
# Cross-formatter consistency
# ---------------------------------------------------------------------------


class TestCrossFormatterConsistency:
    def test_summary_contains_all_wf_columns(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "status": "running",
            "total_windows": 5,
            "completed_windows": 0,
            "failed_windows": 0,
            "mean_validation_metric": None,
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        result = _walk_forward_summary(row)
        expected_keys = {
            "walk_forward_id",
            "search_type",
            "search_spec",
            "select_metric",
            "maximize",
            "refit",
            "status",
            "total_windows",
            "completed_windows",
            "failed_windows",
            "mean_validation_metric",
            "created_at",
            "completed_at",
            "updated_at",
        }
        assert expected_keys.issubset(result.keys())

    def test_detail_extends_summary_with_job_linkage(self) -> None:
        row = {
            "walk_forward_id": "wf-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "status": "running",
            "total_windows": 5,
            "completed_windows": 0,
            "failed_windows": 0,
            "mean_validation_metric": None,
            "summary_json": "{}",
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        summary_keys = set(_walk_forward_summary(row).keys())
        detail_keys = set(_walk_forward_detail(row, None).keys())
        # Detail is a strict superset of summary
        assert summary_keys.issubset(detail_keys)
        # Detail adds summary_json + 3 linkage fields
        extra = detail_keys - summary_keys
        assert "summary_json" in extra
        assert "job_id" in extra
        assert "progress" in extra
        assert "job_status" in extra

    def test_empty_wf_row_has_cancelled_status(self) -> None:
        """Cross-check: the synthetic row from ``_empty_wf_row`` can be
        fed into ``_walk_forward_summary`` to render a coherent
        cancelled frame (the intended use case)."""
        last_payload = {
            "user_id": "u-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "refit": False,
            "status": "running",
            "total_windows": 5,
            "completed_windows": 2,
            "failed_windows": 0,
            "mean_validation_metric": 1.5,
            "summary_json": "{}",
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
        }
        synthetic = _empty_wf_row("wf-1", last_payload)
        # Now feed into summary
        result = _walk_forward_summary(synthetic)
        assert result["status"] == "cancelled"
        assert result["total_windows"] == 5
        assert result["completed_windows"] == 2
        assert result["mean_validation_metric"] == 1.5
