"""Tests for persisted backtest run web services."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from getrich.apps.web.errors import BadRequest, NotFound
from getrich.apps.web.pagination import PageParams
from getrich.apps.web.routers.backtest_runs import router
from getrich.apps.web.services import backtest_run
from getrich.apps.web.services.backtest_run import ArtifactFileContent
from getrich.config.settings import BacktestStorageConfig


_TZ = ZoneInfo("Asia/Shanghai")
_PAGE = PageParams(page=2, page_size=10)
_DT = datetime(2026, 1, 2, 9, 30, tzinfo=_TZ)


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone: dict[str, Any] | None = None,
        fetchall: list[dict[str, Any]] | None = None,
        fetchone_seq: list[dict[str, Any] | None] | None = None,
    ) -> None:
        self.executed: list[tuple[str, dict[str, Any] | None]] = []
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self._fetchone_seq = fetchone_seq
        self._fetchone_idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self) -> dict[str, Any] | None:
        if self._fetchone_seq is not None:
            if self._fetchone_idx >= len(self._fetchone_seq):
                return None
            value = self._fetchone_seq[self._fetchone_idx]
            self._fetchone_idx += 1
            return value
        return self._fetchone

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._fetchall


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _run_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": "run-1",
        "strategy_id": "strategy-1",
        "strategy_name": "DemoStrategy",
        "strategy_names": '["DemoStrategy"]',
        "config_fingerprint": "fp-1",
        "config": '{"initial_cash":"1000"}',
        "symbols": '["000001.SZ"]',
        "freq": "1d",
        "start_at": _DT,
        "end_at": _DT,
        "initial_cash": Decimal("1000.0000"),
        "final_cash": Decimal("900.0000"),
        "final_equity": Decimal("1012.0000"),
        "benchmark_final_equity": None,
        "status": "completed",
        "error_message": None,
        "user_id": "user-1",
        "created_at": _DT,
        "completed_at": _DT,
        "updated_at": _DT,
        "_total": 3,
    }
    row.update(overrides)
    return row


def _metrics_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": "run-1",
        "total_return": Decimal("0.012"),
        "log_return": Decimal("0.0119285709"),
        "annualized_return": Decimal("0.10"),
        "annualized_volatility": Decimal("0.20"),
        "sharpe_ratio": Decimal("1.50"),
        "sortino_ratio": None,
        "calmar_ratio": None,
        "max_drawdown": Decimal("0.05"),
        "max_drawdown_duration": 3,
        "total_fees": Decimal("2.5000"),
        "total_turnover": Decimal("100.0000"),
        "turnover_rate": Decimal("0.10"),
        "total_trades": 4,
        "n_bars": 20,
        "risk_free_rate": Decimal("0.02"),
        "trading_days_per_year": 252,
        "metrics_json": '{"total_return":"0.012"}',
        "created_at": _DT,
    }
    row.update(overrides)
    return row


def test_list_runs_returns_empty_list_and_zero_total() -> None:
    cursor = _FakeCursor(fetchall=[])
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_run.list_runs(conn, strategy_id=None, status=None, page=_PAGE, user_id="user-1")
    )

    assert items == []
    assert total == 0


def test_list_runs_maps_summary_rows_and_total() -> None:
    cursor = _FakeCursor(fetchall=[_run_row()])
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_run.list_runs(conn, strategy_id=None, status=None, page=_PAGE, user_id="user-1")
    )

    assert total == 3
    assert items[0]["run_id"] == "run-1"
    assert items[0]["strategy_names"] == ["DemoStrategy"]
    assert items[0]["symbols"] == ["000001.SZ"]
    assert items[0]["initial_cash"] == 1000.0
    assert items[0]["final_equity"] == 1012.0
    assert items[0]["benchmark_final_equity"] is None
    assert items[0]["created_at"].endswith("+08:00")


def test_list_runs_applies_filters_and_pagination() -> None:
    cursor = _FakeCursor(fetchall=[_run_row()])
    conn = _FakeConn(cursor)

    _run(
        backtest_run.list_runs(
            conn,
            strategy_id="strategy-1",
            status="completed",
            page=_PAGE,
            user_id="user-1",
        )
    )

    sql, params = cursor.executed[0]
    assert "COUNT(*) OVER() AS _total" in sql
    assert "user_id = %(user_id)s" in sql
    assert "strategy_id = %(strategy_id)s" in sql
    assert "status = %(status)s" in sql
    assert params == {
        "limit": 10,
        "offset": 10,
        "user_id": "user-1",
        "strategy_id": "strategy-1",
        "status": "completed",
    }


def test_list_runs_filters_rows_by_user_id() -> None:
    """Owner scoping: list_runs should only return runs owned by user_id."""
    cursor = _FakeCursor(
        fetchall=[
            _run_row(_total=2),
            _run_row(run_id="run-2", user_id="user-1", _total=2),
        ],
    )
    conn = _FakeConn(cursor)

    items, total = _run(
        backtest_run.list_runs(conn, strategy_id=None, status=None, page=_PAGE, user_id="user-A")
    )

    assert total == 2
    assert {item["run_id"] for item in items} == {"run-1", "run-2"}
    sql, params = cursor.executed[0]
    assert "user_id = %(user_id)s" in sql
    assert params["user_id"] == "user-A"


def test_get_run_returns_full_detail() -> None:
    cursor = _FakeCursor(fetchone=_run_row())
    conn = _FakeConn(cursor)

    data = _run(backtest_run.get_run(conn, "run-1", user_id="user-1"))

    assert data["run_id"] == "run-1"
    assert data["config_fingerprint"] == "fp-1"
    assert data["config"] == {"initial_cash": "1000"}
    assert data["start_at"].endswith("+08:00")
    assert data["error_message"] is None


def test_get_run_raises_not_found_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_run(conn, "missing", user_id="user-1"))


def test_get_run_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user access must 404 (not leak existence)."""
    cursor = _FakeCursor(fetchone=_run_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_run(conn, "run-1", user_id="user-B"))


def test_get_equity_curve_returns_points_and_filters_strategy_name() -> None:
    cursor = _FakeCursor(
        fetchone=_run_row(user_id="user-1"),
        fetchall=[
            {
                "run_id": "run-1",
                "strategy_name": "Fast",
                "dt": _DT,
                "cash": Decimal("900"),
                "equity": Decimal("1012"),
                "trading_pnl": Decimal("1"),
                "mtm_pnl": Decimal("12"),
                "total_fees": Decimal("0.5"),
                "gross_exposure": Decimal("112"),
                "row_json": '{"net_exposure":"112"}',
                "created_at": _DT,
            }
        ],
    )
    conn = _FakeConn(cursor)

    points = _run(
        backtest_run.get_equity_curve(conn, "run-1", user_id="user-1", strategy_name="Fast")
    )

    # Second executed statement is the equity-points SELECT.
    sql, params = cursor.executed[1]
    assert "strategy_name = %(strategy_name)s" in sql
    assert params == {"run_id": "run-1", "strategy_name": "Fast"}
    assert points[0]["strategy_name"] == "Fast"
    assert points[0]["equity"] == 1012.0
    assert points[0]["row_json"] == {"net_exposure": "112"}


def test_get_equity_curve_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user equity-curve lookup must 404."""
    cursor = _FakeCursor(fetchone=_run_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_equity_curve(conn, "run-1", user_id="user-B"))


def test_get_metrics_returns_metrics_row() -> None:
    cursor = _FakeCursor(
        fetchone_seq=[_run_row(user_id="user-1"), _metrics_row()],
    )
    conn = _FakeConn(cursor)

    data = _run(backtest_run.get_metrics(conn, "run-1", user_id="user-1"))

    assert data["run_id"] == "run-1"
    assert data["total_return"] == 0.012
    assert data["sortino_ratio"] is None
    assert data["total_trades"] == 4
    assert data["metrics_json"] == {"total_return": "0.012"}


def test_get_metrics_raises_not_found_when_missing() -> None:
    cursor = _FakeCursor(fetchone=None)
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_metrics(conn, "missing", user_id="user-1"))


def test_get_metrics_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user metrics lookup must 404."""
    cursor = _FakeCursor(fetchone=_run_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_metrics(conn, "run-1", user_id="user-B"))


def test_get_positions_returns_final_position_rows() -> None:
    cursor = _FakeCursor(
        fetchone=_run_row(user_id="user-1"),
        fetchall=[
            {
                "run_id": "run-1",
                "symbol": "000001.SZ",
                "qty": Decimal("10.5"),
                "position_json": '{"symbol":"000001.SZ","qty":"10.5"}',
                "created_at": _DT,
            }
        ],
    )
    conn = _FakeConn(cursor)

    positions = _run(backtest_run.get_positions(conn, "run-1", user_id="user-1"))

    sql, params = cursor.executed[1]
    assert "ORDER BY symbol ASC" in sql
    assert params == {"run_id": "run-1"}
    assert positions == [
        {
            "run_id": "run-1",
            "symbol": "000001.SZ",
            "qty": 10.5,
            "position_json": {"symbol": "000001.SZ", "qty": "10.5"},
            "created_at": _DT.isoformat(),
        }
    ]


def test_get_positions_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user positions lookup must 404."""
    cursor = _FakeCursor(fetchone=_run_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_positions(conn, "run-1", user_id="user-B"))


def test_get_artifacts_returns_artifact_rows() -> None:
    cursor = _FakeCursor(
        fetchone=_run_row(user_id="user-1"),
        fetchall=[
            {
                "id": "artifact-1",
                "run_id": "run-1",
                "artifact_type": "manifest",
                "uri": "/tmp/manifest.json",
                "checksum": None,
                "meta": '{"format":"json"}',
                "created_at": _DT,
            }
        ],
    )
    conn = _FakeConn(cursor)

    artifacts = _run(backtest_run.get_artifacts(conn, "run-1", user_id="user-1"))

    sql, params = cursor.executed[1]
    assert "ORDER BY artifact_type ASC, id ASC" in sql
    assert params == {"run_id": "run-1"}
    assert artifacts[0]["id"] == "artifact-1"
    assert artifacts[0]["meta"] == {"format": "json"}


def test_get_artifacts_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user artifacts lookup must 404."""
    cursor = _FakeCursor(fetchone=_run_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_artifacts(conn, "run-1", user_id="user-B"))


def test_router_registers_backtest_run_paths() -> None:
    paths = {route.path for route in router.routes}

    assert "/backtest-runs" in paths
    assert "/backtest-runs/{run_id}" in paths
    assert "/backtest-runs/{run_id}/equity-curve" in paths
    assert "/backtest-runs/{run_id}/metrics" in paths
    assert "/backtest-runs/{run_id}/positions" in paths
    assert "/backtest-runs/{run_id}/artifacts" in paths
    assert "/backtest-runs/{run_id}/artifacts/{artifact_id}/content" in paths


# ------------------------------------------------------------------
# artifact content download helpers / tests
# ------------------------------------------------------------------


def _artifact_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "artifact-1",
        "run_id": "run-1",
        "artifact_type": "manifest",
        "uri": "/var/lib/getrich/artifacts/run-1/manifest.json",
        "checksum": None,
        "meta": '{"format":"json"}',
        "created_at": _DT,
    }
    row.update(overrides)
    return row


def _storage(root: Path) -> BacktestStorageConfig:
    return BacktestStorageConfig(artifact_dir=root)


def test_get_artifact_returns_row_for_owner() -> None:
    cursor = _FakeCursor(
        fetchone_seq=[_run_row(user_id="user-1"), _artifact_row()],
    )
    conn = _FakeConn(cursor)

    data = _run(backtest_run.get_artifact(conn, "run-1", "artifact-1", user_id="user-1"))

    assert data["id"] == "artifact-1"
    assert data["uri"] == "/var/lib/getrich/artifacts/run-1/manifest.json"
    assert data["meta"] == {"format": "json"}
    # The second executed statement is the artifact lookup.
    sql, params = cursor.executed[1]
    assert "run_id = %(run_id)s" in sql
    assert "id = %(artifact_id)s" in sql
    assert params == {"run_id": "run-1", "artifact_id": "artifact-1"}


def test_get_artifact_raises_not_found_for_other_user() -> None:
    """Owner check: cross-user artifact lookup must 404 (no existence leak)."""
    cursor = _FakeCursor(fetchone=_run_row(user_id="user-A"))
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_artifact(conn, "run-1", "artifact-1", user_id="user-B"))


def test_get_artifact_raises_not_found_when_missing() -> None:
    """Owner passes but no matching artifact row -> 404."""
    cursor = _FakeCursor(
        fetchone_seq=[_run_row(user_id="user-1"), None],
    )
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(backtest_run.get_artifact(conn, "run-1", "missing", user_id="user-1"))


def test_stream_artifact_file_rejects_http_uri(tmp_path: Path) -> None:
    """Non-local URI schemes must raise BadRequest (no SSRF / proxy)."""
    cursor = _FakeCursor(
        fetchone_seq=[
            _run_row(user_id="user-1"),
            _artifact_row(uri="https://example.com/leak.json"),
        ],
    )
    conn = _FakeConn(cursor)

    with pytest.raises(BadRequest):
        _run(
            backtest_run.stream_artifact_file(
                conn, "run-1", "artifact-1", user_id="user-1", storage=_storage(tmp_path)
            )
        )


def test_stream_artifact_file_rejects_s3_uri(tmp_path: Path) -> None:
    cursor = _FakeCursor(
        fetchone_seq=[
            _run_row(user_id="user-1"),
            _artifact_row(uri="s3://bucket/secret"),
        ],
    )
    conn = _FakeConn(cursor)

    with pytest.raises(BadRequest):
        _run(
            backtest_run.stream_artifact_file(
                conn, "run-1", "artifact-1", user_id="user-1", storage=_storage(tmp_path)
            )
        )


def test_stream_artifact_file_rejects_path_traversal(tmp_path: Path) -> None:
    """A resolved path that escapes artifact_dir must raise NotFound."""
    outside = tmp_path.parent / "outside.json"
    outside.write_text("leak", encoding="utf-8")

    cursor = _FakeCursor(
        fetchone_seq=[
            _run_row(user_id="user-1"),
            _artifact_row(uri=str(outside)),
        ],
    )
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(
            backtest_run.stream_artifact_file(
                conn, "run-1", "artifact-1", user_id="user-1", storage=_storage(tmp_path)
            )
        )


def test_stream_artifact_file_rejects_dotdot_escape(tmp_path: Path) -> None:
    """``../`` segments that resolve outside the root must be blocked."""
    cursor = _FakeCursor(
        fetchone_seq=[
            _run_row(user_id="user-1"),
            _artifact_row(uri=str(tmp_path / ".." / "escape.json")),
        ],
    )
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(
            backtest_run.stream_artifact_file(
                conn, "run-1", "artifact-1", user_id="user-1", storage=_storage(tmp_path)
            )
        )


def test_stream_artifact_file_rejects_missing_file(tmp_path: Path) -> None:
    """Path resolves under root, but the file is gone -> NotFound."""
    cursor = _FakeCursor(
        fetchone_seq=[
            _run_row(user_id="user-1"),
            _artifact_row(uri=str(tmp_path / "does-not-exist.json")),
        ],
    )
    conn = _FakeConn(cursor)

    with pytest.raises(NotFound):
        _run(
            backtest_run.stream_artifact_file(
                conn, "run-1", "artifact-1", user_id="user-1", storage=_storage(tmp_path)
            )
        )


def test_stream_artifact_file_accepts_file_uri_scheme(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text('{"ok": true}', encoding="utf-8")

    cursor = _FakeCursor(
        fetchone_seq=[
            _run_row(user_id="user-1"),
            _artifact_row(uri=target.as_uri()),
        ],
    )
    conn = _FakeConn(cursor)

    result = _run(
        backtest_run.stream_artifact_file(
            conn, "run-1", "artifact-1", user_id="user-1", storage=_storage(tmp_path)
        )
    )

    assert isinstance(result, ArtifactFileContent)
    assert result.path == target.resolve()
    assert result.filename == "manifest.json"
    assert result.content_type == "application/json"
    assert result.size == target.stat().st_size


def test_stream_artifact_file_returns_correct_content_metadata(tmp_path: Path) -> None:
    """Bare absolute path resolves and exposes filename / mime / size."""
    target = tmp_path / "equity.parquet"
    payload = b"PAR1\x00\x00fake-parquet-bytes"
    target.write_bytes(payload)

    cursor = _FakeCursor(
        fetchone_seq=[
            _run_row(user_id="user-1"),
            _artifact_row(uri=str(target)),
        ],
    )
    conn = _FakeConn(cursor)

    result = _run(
        backtest_run.stream_artifact_file(
            conn, "run-1", "artifact-1", user_id="user-1", storage=_storage(tmp_path)
        )
    )

    assert result.path == target.resolve()
    assert result.filename == "equity.parquet"
    assert result.content_type == "application/octet-stream"  # parquet has no built-in mime
    assert result.size == len(payload)
