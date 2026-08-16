"""Tests for the backtest_job service.

`services.backtest_job` is the central job state machine. The
test suite focuses on the deterministic, pure-function helpers that
the idempotency machinery and the SSE stream rely on:

- ``_request_payload(body)`` — Pydantic / dict → JSON-safe dict
- ``_body_fingerprint(body)`` — sha256-hex of canonical body
  (idempotency key derivation, dedup of duplicate POSTs)
- ``_job_summary(row)`` / ``_job_detail(row)`` — row formatters
- ``_json_value(value, default)`` — defensive JSON parse helper
- ``_dt`` / ``_dt_nullable`` — datetime coercion helpers

The async DB-backed functions (``_create_job``, ``_resolve_idempotent``,
``_cancel_job``, ``stream_job_events``) are exercised by integration
tests in ``test_admin_import.py`` / ``test_sse.py`` and by the
``BacktestJobListener`` tests.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from gr_api.services.backtest_job import (
    _body_fingerprint,
    _dt,
    _dt_nullable,
    _job_detail,
    _job_summary,
    _json_value,
    _request_payload,
)
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pydantic fixtures
# ---------------------------------------------------------------------------


class _SampleRequest(BaseModel):
    """A realistic Pydantic v2 model for fingerprint / payload tests."""

    strategy_id: str
    symbols: list[str]
    initial_cash: Decimal
    start_at: datetime
    end_at: datetime | None = None
    freq: str = "1d"


# ---------------------------------------------------------------------------
# _request_payload
# ---------------------------------------------------------------------------


class TestRequestPayload:
    """``_request_payload(body)`` materializes a request body into a
    JSON-safe ``dict``."""

    def test_pydantic_model_dumps_to_json_safe_dict(self) -> None:
        body = _SampleRequest(
            strategy_id="s-1",
            symbols=["600519.SH", "000858.SZ"],
            initial_cash=Decimal("100000.50"),
            start_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        result = _request_payload(body)
        assert isinstance(result, dict)
        # Decimal → str (JSON-safe)
        assert result["initial_cash"] == "100000.50"
        # datetime → ISO string
        assert result["start_at"] == "2024-01-01T00:00:00"
        # All fields present
        assert result["strategy_id"] == "s-1"
        assert result["symbols"] == ["600519.SH", "000858.SZ"]
        assert result["freq"] == "1d"  # default

    def test_dict_input_returns_copy(self) -> None:
        """Plain dicts are returned as a shallow copy (not the original
        — callers must be able to mutate without touching the input)."""
        body = {"strategy_id": "s-1", "initial_cash": "100000"}
        result = _request_payload(body)
        assert result == body
        assert result is not body  # copy semantics

    def test_unsupported_type_raises(self) -> None:
        """Anything that is neither a Pydantic model nor a dict is rejected."""
        with __import__("pytest").raises(TypeError, match="unsupported request body"):
            _request_payload("a string")  # type: ignore[arg-type]
        with __import__("pytest").raises(TypeError, match="unsupported request body"):
            _request_payload(42)  # type: ignore[arg-type]
        with __import__("pytest").raises(TypeError, match="unsupported request body"):
            _request_payload([1, 2, 3])  # type: ignore[arg-type]

    def test_pydantic_with_optional_field_none(self) -> None:
        body = _SampleRequest(
            strategy_id="s-1",
            symbols=[],
            initial_cash=Decimal("0"),
            start_at=datetime(2024, 1, 1),
            end_at=None,
        )
        result = _request_payload(body)
        assert result["end_at"] is None


# ---------------------------------------------------------------------------
# _body_fingerprint — idempotency key derivation
# ---------------------------------------------------------------------------


class TestBodyFingerprint:
    """``_body_fingerprint(body)`` returns the sha256-hex digest of the
    canonical request body. Two POSTs with the same logical body MUST
    produce the same fingerprint (this is the core idempotency
    guarantee)."""

    def test_returns_64_char_hex(self) -> None:
        """SHA-256 hex digest is 64 hex characters."""
        body = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("100"),
            start_at=datetime(2024, 1, 1),
        )
        fp = _body_fingerprint(body)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_same_body_same_fingerprint(self) -> None:
        """Critical: identical bodies → identical fingerprints (the
        whole point of the function)."""
        body_a = _SampleRequest(
            strategy_id="s-1",
            symbols=["A", "B"],
            initial_cash=Decimal("100"),
            start_at=datetime(2024, 1, 1),
        )
        body_b = _SampleRequest(
            strategy_id="s-1",
            symbols=["A", "B"],
            initial_cash=Decimal("100"),
            start_at=datetime(2024, 1, 1),
        )
        assert _body_fingerprint(body_a) == _body_fingerprint(body_b)

    def test_dict_with_reordered_keys_same_fingerprint(self) -> None:
        """``sort_keys=True`` in canonical form means dict literal order
        does not matter — the fingerprint is order-invariant for dicts."""
        a = {"x": 1, "y": 2, "z": 3}
        b = {"z": 3, "y": 2, "x": 1}
        # The two dicts are different objects with the same content
        assert _body_fingerprint(a) == _body_fingerprint(b)

    def test_pydantic_with_field_reorder_same_fingerprint(self) -> None:
        """Pydantic ``model_dump`` preserves field declaration order, so
        two model instances built with the same kwargs in any order
        produce the same fingerprint."""
        a = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("1"),
            start_at=datetime(2024, 1, 1),
        )
        b = _SampleRequest(
            start_at=datetime(2024, 1, 1),
            initial_cash=Decimal("1"),
            symbols=["A"],
            strategy_id="s-1",
        )
        assert _body_fingerprint(a) == _body_fingerprint(b)

    def test_different_strategy_different_fingerprint(self) -> None:
        body_a = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("1"),
            start_at=datetime(2024, 1, 1),
        )
        body_b = _SampleRequest(
            strategy_id="s-2",
            symbols=["A"],
            initial_cash=Decimal("1"),
            start_at=datetime(2024, 1, 1),
        )
        assert _body_fingerprint(body_a) != _body_fingerprint(body_b)

    def test_different_initial_cash_different_fingerprint(self) -> None:
        body_a = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("100"),
            start_at=datetime(2024, 1, 1),
        )
        body_b = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("200"),
            start_at=datetime(2024, 1, 1),
        )
        assert _body_fingerprint(body_a) != _body_fingerprint(body_b)

    def test_decimal_value_preserved_canonically(self) -> None:
        """Decimal is dumped as string (``mode="json"``), so the
        fingerprint sees the canonical string form of the Decimal.
        Two Pydantic models with ``Decimal("100.5")`` and
        ``Decimal("100.5")`` (identical) hash equal, but
        ``Decimal("100.50")`` and ``Decimal("100.5")`` (different
        string representations) hash distinct — see the
        ``test_different_decimals_with_different_string_forms_distinct``
        test in the IdempotencyInvariants block."""
        body_a = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("100.5"),
            start_at=datetime(2024, 1, 1),
        )
        body_b = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("100.5"),
            start_at=datetime(2024, 1, 1),
        )
        # Same Decimal string form → same fp.
        assert _body_fingerprint(body_a) == _body_fingerprint(body_b)

    def test_server_stamped_keys_are_stripped(self) -> None:
        """``_idempotency_key`` and legacy ``_user_id`` are added by
        the server (not the client) and must NOT contribute to the
        fingerprint. Two bodies that differ only in these keys
        fingerprint equal."""
        body_a = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("1"),
            start_at=datetime(2024, 1, 1),
        )
        body_b = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("1"),
            start_at=datetime(2024, 1, 1),
        )
        # Inject server-stamped keys via dict (model_dump is read-only)
        a = _request_payload(body_a)
        b = _request_payload(body_b)
        a["_idempotency_key"] = "key-AAA"
        a["_user_id"] = "u-1"
        b["_idempotency_key"] = "key-BBB"
        b["_user_id"] = "u-2"
        # The fp function strips those keys before hashing
        assert _body_fingerprint(a) == _body_fingerprint(b)

    def test_dict_input_works(self) -> None:
        """Fingerprint accepts a plain dict (not just Pydantic models)."""
        body = {"strategy_id": "s-1", "x": [1, 2, 3]}
        fp = _body_fingerprint(body)
        assert isinstance(fp, str)
        assert len(fp) == 64


# ---------------------------------------------------------------------------
# Row formatters
# ---------------------------------------------------------------------------


class TestJobSummary:
    """``_job_summary(row)`` extracts the canonical 9 summary fields
    from a backtest_jobs row."""

    def test_minimal_row(self) -> None:
        row = {
            "job_id": "job-1",
            "job_type": "run",
            "ref_id": "ref-1",
            "status": "running",
            "progress": 50,
            "error_message": None,
            "created_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:01Z",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
        }
        result = _job_summary(row)
        assert result["job_id"] == "job-1"
        assert result["job_type"] == "run"
        assert result["ref_id"] == "ref-1"
        assert result["status"] == "running"
        assert result["progress"] == 50
        assert result["error_message"] is None
        assert result["created_at"] == "2026-01-01T00:00:00Z"
        assert result["started_at"] == "2026-01-01T00:00:01Z"
        assert result["completed_at"] is None
        assert result["updated_at"] == "2026-01-01T00:00:05Z"

    def test_completed_job_has_all_timestamps(self) -> None:
        row = {
            "job_id": "job-1",
            "job_type": "sweep",
            "ref_id": "ref-1",
            "status": "completed",
            "progress": 100,
            "error_message": None,
            "created_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:01Z",
            "completed_at": "2026-01-01T00:05:00Z",
            "updated_at": "2026-01-01T00:05:00Z",
        }
        result = _job_summary(row)
        assert result["status"] == "completed"
        assert result["progress"] == 100
        assert result["completed_at"] == "2026-01-01T00:05:00Z"

    def test_failed_job_keeps_error_message(self) -> None:
        row = {
            "job_id": "job-1",
            "job_type": "run",
            "ref_id": "ref-1",
            "status": "failed",
            "progress": 25,
            "error_message": "sweeper OOM",
            "created_at": "2026-01-01",
            "started_at": "2026-01-01",
            "completed_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }
        result = _job_summary(row)
        assert result["error_message"] == "sweeper OOM"
        assert result["status"] == "failed"


class TestJobDetail:
    def test_includes_summary_plus_request_json(self) -> None:
        row = {
            "job_id": "job-1",
            "job_type": "run",
            "ref_id": "ref-1",
            "status": "running",
            "progress": 50,
            "error_message": None,
            "created_at": "2026-01-01",
            "started_at": "2026-01-01",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:05Z",
            "request_json": '{"strategy_id": "s-1"}',
        }
        result = _job_detail(row)
        # Summary fields
        assert result["job_id"] == "job-1"
        assert result["status"] == "running"
        # request_json parsed
        assert result["request_json"] == {"strategy_id": "s-1"}

    def test_request_json_null_defaults_to_empty_dict(self) -> None:
        row = {
            "job_id": "job-1",
            "job_type": "run",
            "ref_id": "ref-1",
            "status": "pending",
            "progress": 0,
            "error_message": None,
            "created_at": "2026-01-01",
            "started_at": None,
            "completed_at": None,
            "updated_at": "2026-01-01",
            "request_json": None,
        }
        result = _job_detail(row)
        assert result["request_json"] == {}  # default

    def test_request_json_already_parsed(self) -> None:
        """If the store returns a dict (not a JSON string), pass through."""
        row = {
            "job_id": "job-1",
            "job_type": "run",
            "ref_id": "ref-1",
            "status": "pending",
            "progress": 0,
            "error_message": None,
            "created_at": "2026-01-01",
            "started_at": None,
            "completed_at": None,
            "updated_at": "2026-01-01",
            "request_json": {"strategy_id": "s-1"},
        }
        result = _job_detail(row)
        assert result["request_json"] == {"strategy_id": "s-1"}


# ---------------------------------------------------------------------------
# JSON / datetime coercion helpers
# ---------------------------------------------------------------------------


class TestJsonValue:
    def test_none_returns_default(self) -> None:
        assert _json_value(None, {}) == {}
        assert _json_value(None, []) == []
        assert _json_value(None, "fallback") == "fallback"

    def test_string_json_parses(self) -> None:
        assert _json_value('{"x": 1}', {}) == {"x": 1}
        assert _json_value("[1, 2]", []) == [1, 2]

    def test_invalid_json_returns_raw_string(self) -> None:
        assert _json_value("not-json", "default") == "not-json"

    def test_non_string_passes_through(self) -> None:
        assert _json_value({"x": 1}, {}) == {"x": 1}
        assert _json_value([1, 2], []) == [1, 2]
        assert _json_value(42, 0) == 42


class TestDtCoercion:
    def test_none_returns_empty_string(self) -> None:
        """``_dt(None)`` returns ``""`` (not None) — the summary
        fields are typed as ``str``, callers expect a string."""
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
# Cross-formatter consistency (defensive)
# ---------------------------------------------------------------------------


class TestCrossFormatterConsistency:
    def test_summary_contains_all_job_columns(self) -> None:
        row = {
            "job_id": "job-1",
            "job_type": "run",
            "ref_id": "ref-1",
            "status": "pending",
            "progress": 0,
            "error_message": None,
            "created_at": "2026-01-01",
            "started_at": None,
            "completed_at": None,
            "updated_at": "2026-01-01",
        }
        result = _job_summary(row)
        # 10 canonical summary keys
        expected_keys = {
            "job_id",
            "job_type",
            "ref_id",
            "status",
            "progress",
            "error_message",
            "created_at",
            "started_at",
            "completed_at",
            "updated_at",
        }
        assert expected_keys == set(result.keys())

    def test_detail_extends_summary_with_request_json(self) -> None:
        """``_job_detail`` adds only ``request_json`` to the summary."""
        row = {
            "job_id": "job-1",
            "job_type": "run",
            "ref_id": "ref-1",
            "status": "pending",
            "progress": 0,
            "error_message": None,
            "created_at": "2026-01-01",
            "started_at": None,
            "completed_at": None,
            "updated_at": "2026-01-01",
            "request_json": "{}",
        }
        summary_keys = set(_job_summary(row).keys())
        detail_keys = set(_job_detail(row).keys())
        assert summary_keys.issubset(detail_keys)
        # Exactly one extra key
        extra = detail_keys - summary_keys
        assert extra == {"request_json"}


# ---------------------------------------------------------------------------
# Idempotency invariants
# ---------------------------------------------------------------------------


class TestIdempotencyInvariants:
    """End-to-end invariant tests for the idempotency contract.

    The contract: if two POSTs carry the same ``Idempotency-Key`` AND
    bodies that fingerprint equal, they MUST resolve to the same job.
    Body fingerprint equality is what ``_body_fingerprint`` guarantees;
    the store-level dedup is the caller's responsibility but these
    invariants document the contract."""

    def test_two_pydantic_models_with_same_content_fingerprint_equal(self) -> None:
        """The most common case: client re-submits the same form after
        a network blip. Pydantic re-instantiation with the same kwargs
        must produce an equal fingerprint."""
        kwargs: dict[str, Any] = dict(
            strategy_id="s-1",
            symbols=["600519.SH"],
            initial_cash=Decimal("100000"),
            start_at=datetime(2024, 1, 1),
        )
        a = _SampleRequest(**kwargs)
        b = _SampleRequest(**kwargs)
        assert _body_fingerprint(a) == _body_fingerprint(b)

    def test_model_dump_matches_dict_input_fingerprint(self) -> None:
        """A Pydantic model and an equivalent dict produce the same
        fingerprint (so the same client payload in either form maps to
        the same job)."""
        model = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("1"),
            start_at=datetime(2024, 1, 1),
        )
        model_fp = _body_fingerprint(model)
        # Build the equivalent dict from the dumped form
        dict_form = _request_payload(model)
        dict_fp = _body_fingerprint(dict_form)
        assert model_fp == dict_fp

    def test_different_decimals_with_different_string_forms_distinct(self) -> None:
        """Two payloads with the same string field but different
        string-encoded Decimal representations fingerprint
        distinct. Pydantic's ``model_dump(mode="json")`` converts
        ``Decimal`` to its string form, so the fingerprint sees
        ``"100.50"`` and ``"100.5"`` as different (conservative
        behavior — we don't try to "normalize" Decimal representations
        because that can mask client bugs)."""
        a = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("100.5"),
            start_at=datetime(2024, 1, 1),
        )
        b = _SampleRequest(
            strategy_id="s-1",
            symbols=["A"],
            initial_cash=Decimal("100.50"),
            start_at=datetime(2024, 1, 1),
        )
        assert _body_fingerprint(a) != _body_fingerprint(b)
