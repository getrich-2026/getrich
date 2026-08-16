"""Tests for the backtest_sweep service.

`services.backtest_sweep` powers the read endpoints for the
`/v1/backtest/sweeps/*` family. Tests focus on:

- ``_is_terminal_payload`` — terminal-status detection (SSE stream logic)
- ``_payload_etag`` — coarse de-dup key for SSE updates
- Row formatters: ``_sweep_summary``, ``_sweep_detail``, ``_trial``
- Numeric / datetime coercion helpers: ``_f``, ``_f_nullable``, ``_dt``,
  ``_dt_nullable``, ``_json_value``

The SSE stream generators (``stream_sweep_events``) and the live
``_LISTENER`` machinery are covered in ``test_backtest_run_sse.py``
and ``test_job_listener.py`` respectively. This file targets the
deterministic row-shaping helpers that the stream re-emits on
every poll tick.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from gr_api.services.backtest_sweep import (
    _dt,
    _dt_nullable,
    _f,
    _f_nullable,
    _is_terminal_payload,
    _json_value,
    _payload_etag,
    _sweep_detail,
    _sweep_summary,
    _trial,
)


# ---------------------------------------------------------------------------
# _is_terminal_payload — terminal-status detection
# ---------------------------------------------------------------------------


class TestIsTerminalPayload:
    """``_is_terminal_payload(payload)`` decides whether the SSE generator
    should close the stream. Key on the parent job's status (merged into
    ``payload`` via ``_sweep_detail``) so cancellation is correctly
    surfaced — the sweep's own status enum has no ``cancelled`` value."""

    def test_job_status_completed_terminates(self) -> None:
        payload = {"status": "running", "job_status": "completed"}
        assert _is_terminal_payload(payload) is True

    def test_job_status_failed_terminates(self) -> None:
        payload = {"status": "running", "job_status": "failed"}
        assert _is_terminal_payload(payload) is True

    def test_job_status_cancelled_terminates(self) -> None:
        """Critical: the sweep's own status enum has no 'cancelled' value,
        but the job's status does. The function MUST honour that."""
        payload = {"status": "running", "job_status": "cancelled"}
        assert _is_terminal_payload(payload) is True

    def test_job_status_running_does_not_terminate(self) -> None:
        payload = {"status": "running", "job_status": "running"}
        assert _is_terminal_payload(payload) is False

    def test_job_status_pending_does_not_terminate(self) -> None:
        payload = {"status": "queued", "job_status": "pending"}
        assert _is_terminal_payload(payload) is False

    def test_fallback_to_sweep_status_when_no_job(self) -> None:
        """In the brief window after row create + before runner claim,
        ``job_status`` is None. The function falls back to the sweep's
        own status."""
        payload = {"status": "completed", "job_status": None}
        assert _is_terminal_payload(payload) is True

    def test_fallback_sweep_status_failed(self) -> None:
        payload = {"status": "failed", "job_status": None}
        assert _is_terminal_payload(payload) is True

    def test_fallback_sweep_status_running_does_not_terminate(self) -> None:
        """``running`` is NOT in the fallback terminal set (only
        completed / failed are). This is correct: ``cancelled`` is
        only terminal via the job_status path."""
        payload = {"status": "running", "job_status": None}
        assert _is_terminal_payload(payload) is False

    def test_both_none_does_not_terminate(self) -> None:
        """Edge: both statuses missing → not terminal."""
        payload = {"status": None, "job_status": None}
        assert _is_terminal_payload(payload) is False


# ---------------------------------------------------------------------------
# _payload_etag — SSE de-dup key
# ---------------------------------------------------------------------------


class TestPayloadEtag:
    """``_payload_etag(payload)`` is a tuple de-dup key covering the
    live-status surface. Two payloads with the same etag do not need
    a re-emit."""

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
        b = _payload_etag({"progress": 50, "updated_at": "t1"})
        assert a != b

    def test_keys_on_updated_at(self) -> None:
        a = _payload_etag({"status": "running", "updated_at": "t1"})
        b = _payload_etag({"status": "running", "updated_at": "t2"})
        assert a != b

    def test_ignores_summary_json_mutations(self) -> None:
        """``summary_json`` mutates without changing the etag — the
        page can re-fetch the detail via REST instead of via SSE."""
        a = _payload_etag({"status": "running", "summary_json": {"a": 1}})
        b = _payload_etag({"status": "running", "summary_json": {"a": 2}})
        assert a == b

    def test_missing_keys_default_to_none(self) -> None:
        """All four keys default to None if absent (still produces a
        well-defined tuple)."""
        etag = _payload_etag({})
        assert etag == (None, None, None, None)

    def test_returns_tuple(self) -> None:
        etag = _payload_etag({"status": "running"})
        assert isinstance(etag, tuple)


# ---------------------------------------------------------------------------
# Row formatters
# ---------------------------------------------------------------------------


class TestSweepSummary:
    def test_minimal_row(self) -> None:
        row = {
            "sweep_id": "sw-1",
            "search_type": "grid",
            "search_spec": '{"x": [1, 2, 3]}',
            "select_metric": "sharpe_ratio",
            "maximize": True,
            "status": "running",
            "total_trials": 6,
            "completed_trials": 2,
            "failed_trials": 0,
            "best_trial_id": "tr-2",
            "best_run_id": "run-2",
            "best_metric_value": Decimal("1.85"),
            "created_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
        }
        result = _sweep_summary(row)
        assert result["sweep_id"] == "sw-1"
        assert result["search_type"] == "grid"
        assert result["search_spec"] == {"x": [1, 2, 3]}  # JSON parsed
        assert result["maximize"] is True
        assert result["total_trials"] == 6
        assert result["best_metric_value"] == 1.85
        assert result["completed_at"] is None

    def test_null_search_spec_defaults_to_empty_dict(self) -> None:
        row = {
            "sweep_id": "sw-1",
            "search_type": "grid",
            "search_spec": None,
            "select_metric": "sharpe",
            "maximize": False,
            "status": "completed",
            "total_trials": 0,
            "completed_trials": 0,
            "failed_trials": 0,
            "best_trial_id": None,
            "best_run_id": None,
            "best_metric_value": None,
            "created_at": "2026-01-01",
            "completed_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }
        result = _sweep_summary(row)
        assert result["search_spec"] == {}  # default
        assert result["best_metric_value"] is None


class TestSweepDetail:
    def test_includes_summary_plus_job_linkage(self) -> None:
        row = {
            "sweep_id": "sw-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "status": "running",
            "total_trials": 6,
            "completed_trials": 0,
            "failed_trials": 0,
            "best_trial_id": None,
            "best_run_id": None,
            "best_metric_value": None,
            "summary_json": '{"winner": "trial-3"}',
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
        }
        job_row = {
            "job_id": "job-99",
            "progress": 50,
            "status": "running",
        }
        result = _sweep_detail(row, job_row)
        # Summary fields
        assert result["sweep_id"] == "sw-1"
        assert result["search_type"] == "grid"
        # Job linkage surfaced
        assert result["job_id"] == "job-99"
        assert result["progress"] == 50
        assert result["job_status"] == "running"
        # summary_json parsed
        assert result["summary_json"] == {"winner": "trial-3"}

    def test_no_job_row_yields_none_linkage(self) -> None:
        """``job_row=None`` → job_id / progress / job_status are all None.
        This is the brief window between job create and runner claim."""
        row = {
            "sweep_id": "sw-1",
            "search_type": "random",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "status": "running",
            "total_trials": 10,
            "completed_trials": 0,
            "failed_trials": 0,
            "best_trial_id": None,
            "best_run_id": None,
            "best_metric_value": None,
            "summary_json": "{}",
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        result = _sweep_detail(row, job_row=None)
        assert result["job_id"] is None
        assert result["progress"] is None
        assert result["job_status"] is None

    def test_job_row_progress_none_or_missing_int_default_zero(self) -> None:
        """``int(job_row.get('progress') or 0)`` — falsy values (None, 0,
        missing key) all become 0."""
        row = {
            "sweep_id": "sw-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "status": "running",
            "total_trials": 6,
            "completed_trials": 0,
            "failed_trials": 0,
            "best_trial_id": None,
            "best_run_id": None,
            "best_metric_value": None,
            "summary_json": "{}",
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        # None progress
        result = _sweep_detail(row, {"job_id": "j-1", "progress": None, "status": "running"})
        assert result["progress"] == 0
        # Missing progress key
        result = _sweep_detail(row, {"job_id": "j-1", "status": "running"})
        assert result["progress"] == 0


class TestTrial:
    def test_minimal_row(self) -> None:
        row = {
            "trial_id": "tr-1",
            "sweep_id": "sw-1",
            "run_id": "run-1",
            "trial_index": 0,
            "params": '{"x": 1}',
            "param_fingerprint": "abc123",
            "status": "completed",
            "error_message": None,
            "select_metric_value": Decimal("1.2"),
            "metrics_json": '{"sharpe": 1.2}',
            "created_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:10Z",
            "updated_at": "2026-01-01T00:00:10Z",
        }
        result = _trial(row)
        assert result["trial_id"] == "tr-1"
        assert result["sweep_id"] == "sw-1"
        assert result["run_id"] == "run-1"
        assert result["trial_index"] == 0
        assert result["params"] == {"x": 1}
        assert result["param_fingerprint"] == "abc123"
        assert result["status"] == "completed"
        assert result["error_message"] is None
        assert result["select_metric_value"] == 1.2
        assert result["metrics_json"] == {"sharpe": 1.2}

    def test_failed_trial_keeps_error_message(self) -> None:
        row = {
            "trial_id": "tr-1",
            "sweep_id": "sw-1",
            "run_id": None,
            "trial_index": 3,
            "params": "{}",
            "param_fingerprint": "fp",
            "status": "failed",
            "error_message": "OOM",
            "select_metric_value": None,
            "metrics_json": None,
            "created_at": "2026-01-01",
            "completed_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }
        result = _trial(row)
        assert result["status"] == "failed"
        assert result["error_message"] == "OOM"
        assert result["select_metric_value"] is None
        assert result["run_id"] is None
        assert result["metrics_json"] == {}  # null → empty dict default


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
        """Invalid JSON string is returned as-is (defensive — not an
        exception)."""
        assert _json_value("not-json", "default") == "not-json"

    def test_non_string_passes_through(self) -> None:
        """dict / list / int passes through unchanged."""
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
        """Edge: 0 is not None — must stay 0.0, not None."""
        assert _f_nullable(0) == 0.0
        assert _f_nullable(Decimal("0")) == 0.0


class TestDtCoercion:
    def test_none_returns_empty_string(self) -> None:
        """``_dt(None)`` returns empty string (NOT None) — the summary
        fields are typed as `str`, so callers expect a string."""
        assert _dt(None) == ""

    def test_none_nullable_stays_none(self) -> None:
        """``_dt_nullable(None)`` returns None — the nullable twin."""
        assert _dt_nullable(None) is None

    def test_datetime_to_isoformat(self) -> None:
        ts = datetime(2026, 1, 2, 12, 30, 45)
        assert _dt(ts) == "2026-01-02T12:30:45"
        assert _dt_nullable(ts) == "2026-01-02T12:30:45"

    def test_string_passes_through(self) -> None:
        assert _dt("2026-01-01") == "2026-01-01"
        assert _dt_nullable("2026-01-01") == "2026-01-01"

    def test_datetime_aware_string_passes_through(self) -> None:
        """ISO string with TZ is preserved verbatim."""
        assert _dt("2026-01-01T00:00:00+08:00") == "2026-01-01T00:00:00+08:00"


# ---------------------------------------------------------------------------
# Cross-formatter consistency (defensive)
# ---------------------------------------------------------------------------


class TestCrossFormatterConsistency:
    """Sanity checks that the 3 formatters agree on the empty-row shape."""

    def test_summary_contains_all_sweep_columns(self) -> None:
        row = {
            "sweep_id": "sw-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "status": "running",
            "total_trials": 6,
            "completed_trials": 0,
            "failed_trials": 0,
            "best_trial_id": None,
            "best_run_id": None,
            "best_metric_value": None,
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        result = _sweep_summary(row)
        # 15 canonical summary keys
        expected_keys = {
            "sweep_id",
            "search_type",
            "search_spec",
            "select_metric",
            "maximize",
            "status",
            "total_trials",
            "completed_trials",
            "failed_trials",
            "best_trial_id",
            "best_run_id",
            "best_metric_value",
            "created_at",
            "completed_at",
            "updated_at",
        }
        assert expected_keys.issubset(result.keys())

    def test_detail_extends_summary_with_job_linkage(self) -> None:
        """``_sweep_detail`` must include everything in ``_sweep_summary``
        PLUS the job-linkage triple (job_id, progress, job_status)
        PLUS summary_json."""
        row = {
            "sweep_id": "sw-1",
            "search_type": "grid",
            "search_spec": "{}",
            "select_metric": "sharpe",
            "maximize": True,
            "status": "running",
            "total_trials": 6,
            "completed_trials": 0,
            "failed_trials": 0,
            "best_trial_id": None,
            "best_run_id": None,
            "best_metric_value": None,
            "summary_json": "{}",
            "created_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        summary_keys = set(_sweep_summary(row).keys())
        detail_keys = set(_sweep_detail(row, None).keys())
        # Detail is a strict superset of summary
        assert summary_keys.issubset(detail_keys)
        # Detail adds summary_json + the 3 linkage fields
        extra = detail_keys - summary_keys
        assert "summary_json" in extra
        assert "job_id" in extra
        assert "progress" in extra
        assert "job_status" in extra
