"""Tests for the backtest_run service.

`services.backtest_run` powers the read endpoints for the
`/v1/backtest/runs/*` family. The most security-critical helper is
``_resolve_local_path`` (artifact path-traversal defense). Tests
focus on:

- ``_resolve_local_path`` — rejects schemes, .., symlink escapes, relative paths
- ``_sanitize_filename`` — control-char scrubbing via regex sub
- ``_run_summary`` / ``_run_detail`` / ``_equity_point`` / ``_metrics`` /
  ``_position`` / ``_artifact`` row formatters (idempotent pure fns)
- ``_assert_run_owner`` — owner-scope NotFound

Tests use a ``_FakeConn`` / ``_FakeCursor`` that records ``execute``
and serves ``fetchone`` / ``fetchall`` from FIFO queues, matching
the convention in ``test_admin_import.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from getrich.apps.web.errors import BadRequest, NotFound
from getrich.apps.web.services.backtest_run import (
    _artifact,
    _assert_run_owner,
    _equity_point,
    _f,
    _f_nullable,
    _int_nullable,
    _metrics,
    _position,
    _resolve_local_path,
    _run_detail,
    _run_summary,
    _sanitize_filename,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []
        self._fetchone_q: list[dict[str, Any] | None] = []

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql.strip(), params))

    async def fetchone(self) -> dict[str, Any] | None:
        if self._fetchone_q:
            return self._fetchone_q.pop(0)
        return None

    def push_one(self, row: dict[str, Any] | None) -> None:
        self._fetchone_q.append(row)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits: int = 0

    def cursor(self) -> _FakeCursor:
        return self._cursor

    async def commit(self) -> None:
        self.commits += 1


# ---------------------------------------------------------------------------
# _resolve_local_path — path-traversal defense (SECURITY)
# ---------------------------------------------------------------------------


class TestResolveLocalPath:
    """The artifact download endpoint exposes any file under artifact_root
    if the URI is well-formed. These tests guard the path-traversal /
    SSRF defenses."""

    def _root(self, tmp_path: Path) -> Path:
        """Create a real artifact_root on disk (resolve() needs it)."""
        root = tmp_path / "artifacts"
        root.mkdir()
        (root / "run-1").mkdir()
        (root / "run-1" / "manifest.json").write_text("{}")
        return root

    def test_bare_absolute_path_inside_root(self, tmp_path: Path) -> None:
        """Bare absolute path that resolves inside the root is accepted."""
        root = self._root(tmp_path)
        target = root / "run-1" / "manifest.json"
        result = _resolve_local_path(str(target), artifact_root=root)
        assert result == target.resolve()

    def test_relative_path_rejected(self, tmp_path: Path) -> None:
        """Relative paths raise NotFound (never resolve against CWD)."""
        root = self._root(tmp_path)
        with pytest.raises(NotFound, match="not found"):
            _resolve_local_path("run-1/manifest.json", artifact_root=root)

    def test_path_traversal_dotdot_rejected(self, tmp_path: Path) -> None:
        """``..`` segments that escape the root raise NotFound."""
        root = self._root(tmp_path)
        # Create a sibling file outside the root
        secret = tmp_path / "secret.txt"
        secret.write_text("leaked")
        # Use a path that contains ``..`` to escape
        with pytest.raises(NotFound, match="not found"):
            _resolve_local_path(
                str(root / "run-1" / ".." / ".." / "secret.txt"),
                artifact_root=root,
            )

    def test_http_scheme_rejected_as_bad_request(self, tmp_path: Path) -> None:
        """Non-local schemes raise BadRequest (we WANT to signal
        'unsupported scheme' to the operator, not NotFound)."""
        root = self._root(tmp_path)
        with pytest.raises(BadRequest, match="not a local file"):
            _resolve_local_path("http://evil.example.com/x", artifact_root=root)
        with pytest.raises(BadRequest, match="not a local file"):
            _resolve_local_path("https://evil.example.com/x", artifact_root=root)
        with pytest.raises(BadRequest, match="not a local file"):
            _resolve_local_path("s3://bucket/key", artifact_root=root)

    def test_empty_uri_rejected(self, tmp_path: Path) -> None:
        """Empty string → NotFound (no info leak)."""
        root = self._root(tmp_path)
        with pytest.raises(NotFound, match="not found"):
            _resolve_local_path("", artifact_root=root)

    def test_file_url_accepted(self, tmp_path: Path) -> None:
        """``file://`` URL that resolves inside the root is accepted."""
        root = self._root(tmp_path)
        target = root / "run-1" / "manifest.json"
        result = _resolve_local_path(target.as_uri(), artifact_root=root)
        assert result == target.resolve()


# ---------------------------------------------------------------------------
# _sanitize_filename — RFC 6266 Content-Disposition defense
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_simple_name_unchanged(self) -> None:
        """Plain ASCII printable is kept verbatim."""
        assert _sanitize_filename("manifest.json") == "manifest.json"

    def test_double_quotes_replaced_with_underscore(self) -> None:
        """``"`` is in the EXCLUDED set (0x22 is between 0x21 (!) and 0x23 (#)),
        so it gets replaced with ``_``, not stripped. The trailing
        ``.strip('"')`` is a defensive no-op for inputs that don't go
        through the regex (e.g. empty strings)."""
        result = _sanitize_filename('"manifest.json"')
        assert '"' not in result
        assert result == "_manifest.json_"

    def test_control_chars_replaced_with_underscore(self) -> None:
        """Non-printable / control characters become underscores."""
        # Tab + newline
        assert _sanitize_filename("a\nb\tc") == "a_b_c"

    def test_unicode_replaced(self) -> None:
        """Non-ASCII unicode is replaced with underscore (RFC 6266: only
        printable ASCII allowed in quoted-string filenames)."""
        result = _sanitize_filename("manifest_数据.json")
        assert "数据" not in result

    def test_empty_returns_default(self) -> None:
        """Filename that becomes empty after scrubbing → 'artifact'."""
        assert _sanitize_filename("") == "artifact"
        # All-stripped string
        result = _sanitize_filename('""')
        # After regex sub each " becomes _, so result is "__" — NOT empty
        # The default kicks in only if the WHOLE string is empty or whitespace
        assert result == "__"  # both " replaced with _
        # Whitespace only → after regex (space is in KEEP set, 0x20)
        # strip() removes them → empty → default
        assert _sanitize_filename("   ") == "artifact"


# ---------------------------------------------------------------------------
# Row formatters — match actual signatures
# ---------------------------------------------------------------------------


class TestRunSummary:
    """``_run_summary(row)`` extracts the canonical summary fields from
    a backtest_runs row."""

    def test_minimal_row(self) -> None:
        """All keys present, nulls → empty string, JSON fields parsed."""
        row = {
            "run_id": "run-1",
            "strategy_id": "s-1",
            "strategy_name": "Test",
            "strategy_names": '["a", "b"]',
            "symbols": '["600519"]',
            "freq": "1d",
            "status": "completed",
            "initial_cash": "100000.00",
            "final_cash": "120000.00",
            "final_equity": "125000.00",
            "benchmark_final_equity": "110000.00",
            "created_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-02T00:00:00Z",
            "updated_at": "2026-01-02T00:00:01Z",
        }
        result = _run_summary(row)
        assert result["run_id"] == "run-1"
        assert result["status"] == "completed"
        assert result["initial_cash"] == 100000.0  # parsed via _f
        assert result["final_cash"] == 120000.0  # _f_nullable
        assert result["strategy_names"] == ["a", "b"]  # JSON string → list
        assert result["symbols"] == ["600519"]

    def test_null_optional_fields(self) -> None:
        """Null optional fields → None (nullable semantics) for floats;
        empty string for dates."""
        row = {
            "run_id": "run-1",
            "strategy_id": "s-1",
            "strategy_name": "S",
            "strategy_names": "[]",
            "symbols": "[]",
            "freq": "1d",
            "status": "queued",
            "initial_cash": None,
            "final_cash": None,
            "final_equity": None,
            "benchmark_final_equity": None,
            "created_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
            "updated_at": "2026-01-01T00:00:00Z",
        }
        result = _run_summary(row)
        # None initial_cash → 0.0 (per _f default, not nullable)
        assert result["initial_cash"] == 0.0
        # None final_cash → None (per _f_nullable)
        assert result["final_cash"] is None
        # None completed_at → None (per _dt_nullable, stays None)
        assert result["completed_at"] is None


class TestRunDetail:
    """``_run_detail(row)`` = summary + config_fingerprint + config +
    start_at + end_at + error_message."""

    def test_includes_summary_and_detail_fields(self) -> None:
        row = {
            "run_id": "run-1",
            "strategy_id": "s-1",
            "strategy_name": "S",
            "strategy_names": "[]",
            "symbols": "[]",
            "freq": "1d",
            "status": "completed",
            "initial_cash": "1.0",
            "final_cash": "1.0",
            "final_equity": "1.0",
            "benchmark_final_equity": None,
            "created_at": "2026-01-01",
            "completed_at": "2026-01-02",
            "updated_at": "2026-01-02",
            # detail-only fields
            "config_fingerprint": "abc123",
            "config": '{"foo": 1}',
            "start_at": "2026-01-01T00:00:00Z",
            "end_at": "2026-01-02T00:00:00Z",
            "error_message": None,
        }
        result = _run_detail(row)
        # Summary fields still present
        assert result["run_id"] == "run-1"
        assert result["status"] == "completed"
        # Detail fields
        assert result["config_fingerprint"] == "abc123"
        assert result["config"] == {"foo": 1}  # JSON parsed
        assert result["error_message"] is None


class TestEquityPoint:
    def test_minimal(self) -> None:
        row = {
            "run_id": "run-1",
            "strategy_name": "S",
            "dt": "2026-01-02T00:00:00Z",
            "cash": "1.0",
            "equity": "1.05",
            "trading_pnl": "0.01",
            "mtm_pnl": "0.005",
            "total_fees": "0.0001",
            "gross_exposure": "0.5",
            "row_json": '{"extra": 1}',
            "created_at": "2026-01-02T00:00:01Z",
        }
        result = _equity_point(row)
        assert result["run_id"] == "run-1"
        assert result["dt"] == "2026-01-02T00:00:00Z"
        assert result["equity"] == 1.05
        assert result["trading_pnl"] == 0.01
        assert result["row_json"] == {"extra": 1}

    def test_null_pnl_fields_stay_null(self) -> None:
        """Nullable pnl fields (cash, trading_pnl, mtm_pnl, fees, exposure)
        stay None on null input."""
        row = {
            "run_id": "run-1",
            "strategy_name": "S",
            "dt": "2026-01-02",
            "cash": None,
            "equity": "1.0",  # required
            "trading_pnl": None,
            "mtm_pnl": None,
            "total_fees": None,
            "gross_exposure": None,
            "row_json": None,
            "created_at": "2026-01-02",
        }
        result = _equity_point(row)
        assert result["cash"] is None
        assert result["trading_pnl"] is None
        assert result["row_json"] == {}  # _json_value default is {} for non-list


class TestMetrics:
    def test_all_fields(self) -> None:
        row = {
            "run_id": "run-1",
            "total_return": "0.50",
            "log_return": "0.40",
            "annualized_return": "0.12",
            "annualized_volatility": "0.18",
            "sharpe_ratio": "1.5",
            "sortino_ratio": "2.0",
            "calmar_ratio": "1.2",
            "max_drawdown": "-0.20",
            "max_drawdown_duration": 30,
            "total_fees": "100.0",
            "total_turnover": "1000000.0",
            "turnover_rate": "2.5",
            "total_trades": 50,
            "n_bars": 252,
            "risk_free_rate": "0.03",
            "trading_days_per_year": 252,
            "metrics_json": '{"extra": {}}',
            "created_at": "2026-01-02T00:00:00Z",
        }
        result = _metrics(row)
        assert result["run_id"] == "run-1"
        assert result["total_return"] == 0.50
        assert result["max_drawdown_duration"] == 30
        assert result["total_trades"] == 50
        assert result["metrics_json"] == {"extra": {}}

    def test_null_sharpe_stays_null(self) -> None:
        """Sharpe can be None if std is 0 (no volatility → undefined)."""
        row = {
            "run_id": "run-1",
            "total_return": "0.0",
            "log_return": "0.0",
            "annualized_return": "0.0",
            "annualized_volatility": "0.0",
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "calmar_ratio": None,
            "max_drawdown": "0.0",
            "max_drawdown_duration": None,
            "total_fees": "0.0",
            "total_turnover": "0.0",
            "turnover_rate": "0.0",
            "total_trades": 0,
            "n_bars": 0,
            "risk_free_rate": "0.0",
            "trading_days_per_year": 252,
            "metrics_json": None,
            "created_at": "2026-01-02",
        }
        result = _metrics(row)
        assert result["sharpe_ratio"] is None
        assert result["sortino_ratio"] is None


class TestPosition:
    def test_minimal(self) -> None:
        row = {
            "run_id": "run-1",
            "symbol": "600519.SH",
            "qty": "100",
            "position_json": '{"side": "long"}',
            "created_at": "2026-01-02",
        }
        result = _position(row)
        assert result["run_id"] == "run-1"
        assert result["symbol"] == "600519.SH"
        assert result["qty"] == 100.0  # _f default
        assert result["position_json"] == {"side": "long"}


class TestArtifact:
    def test_minimal(self) -> None:
        row = {
            "id": "art-1",
            "run_id": "run-1",
            "artifact_type": "tear_sheet",
            "uri": "/var/lib/getrich/artifacts/run-1/tear_sheet.html",
            "checksum": "sha256:abc",
            "meta": '{"size": 12345}',
            "created_at": "2026-01-02T00:00:00Z",
        }
        result = _artifact(row)
        assert result["id"] == "art-1"
        assert result["run_id"] == "run-1"
        assert result["artifact_type"] == "tear_sheet"
        assert result["uri"].endswith("tear_sheet.html")
        assert result["checksum"] == "sha256:abc"
        assert result["meta"] == {"size": 12345}


# ---------------------------------------------------------------------------
# Numeric coercion helpers
# ---------------------------------------------------------------------------


class TestNumericCoercion:
    def test_f_coerces_to_float(self) -> None:
        assert _f("1.5") == 1.5
        assert _f(2) == 2.0
        assert _f(None) == 0.0  # default

    def test_f_nullable(self) -> None:
        assert _f_nullable("3.14") == 3.14
        assert _f_nullable(0) == 0.0
        assert _f_nullable(None) is None  # stays None

    def test_int_nullable(self) -> None:
        assert _int_nullable("100") == 100
        assert _int_nullable(0) == 0
        assert _int_nullable(None) is None


# ---------------------------------------------------------------------------
# _assert_run_owner
# ---------------------------------------------------------------------------


class TestAssertRunOwner:
    async def test_owner_match_passes(self) -> None:
        """Owner-scope check passes when user_id matches the row."""
        cur = _FakeCursor()
        cur.push_one({"user_id": "u-1"})
        conn = _FakeConn(cur)
        # Should not raise
        await _assert_run_owner(conn, "run-1", user_id="u-1")
        # SQL used the run_id param
        assert "run-1" in str(cur.executed[0][1]["run_id"])

    async def test_owner_mismatch_raises_not_found(self) -> None:
        """Mismatched user_id → NotFound (no info leak about existence)."""
        cur = _FakeCursor()
        cur.push_one({"user_id": "u-OTHER"})
        conn = _FakeConn(cur)
        with pytest.raises(NotFound, match="run-1"):
            await _assert_run_owner(conn, "run-1", user_id="u-1")

    async def test_missing_run_raises_not_found(self) -> None:
        """Run not in DB → NotFound (same error as owner mismatch)."""
        cur = _FakeCursor()  # fetchone returns None
        conn = _FakeConn(cur)
        with pytest.raises(NotFound, match="run-1"):
            await _assert_run_owner(conn, "run-1", user_id="u-1")
