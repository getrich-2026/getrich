"""Tests for the admin/imports service.

`services.admin_import` powers the backoffice ``/v1/admin/imports/*``
endpoints. It exposes 6 public functions:

- ``upsert_strategy`` — strategy metadata create-or-update
- ``preview_import`` — CSV parse + validation, persists a preview job
- ``commit_import`` — materialise a validated job into DB tables
- ``list_import_history`` — last 20 import jobs
- ``get_import_job`` — single job by code
- ``list_import_errors`` — per-row error breakdown

These tests cover the validation paths, the SQL execution order, and
the small helpers (CSV parser, validators, error formatter, code
generator) in isolation. They use a ``_FakeConn`` that records
``execute`` calls and serves ``fetchone``/``fetchall`` from a queue
the test pre-populates.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from getrich.apps.web.errors import BadRequest, NotFound
from getrich.apps.web.schemas.admin_import import ImportPreviewIn, StrategyUpsertIn
from getrich.apps.web.services.admin_import import (
    _derive_daily_return_payload,
    _make_job_code,
    _parse_csv_rows,
    _parse_datetime,
    _stable_signal_code,
    commit_import,
    get_import_job,
    list_import_errors,
    list_import_history,
    preview_import,
    upsert_strategy,
)


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mock async cursor.

    Records every ``execute(sql, params)`` call. ``fetchone`` /
    ``fetchall`` return the next pre-queued row(s) (FIFO). The test
    pushes the exact number of responses it expects the production
    code to consume.

    A common pattern: push N ``push_one`` responses, then call the
    function, then assert ``executed`` and ``commits`` against
    expectations.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, Any]] = []
        self._fetchone_q: list[dict[str, Any] | None] = []
        self._fetchall_q: list[list[dict[str, Any]]] = []

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

    async def fetchall(self) -> list[dict[str, Any]]:
        if self._fetchall_q:
            return self._fetchall_q.pop(0)
        return []

    def push_one(self, row: dict[str, Any] | None) -> None:
        self._fetchone_q.append(row)

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self._fetchall_q.append(rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits: int = 0

    def cursor(self) -> _FakeCursor:
        return self._cursor

    async def commit(self) -> None:
        self.commits += 1


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _strategy_upsert_body(**overrides: Any) -> StrategyUpsertIn:
    body: dict[str, Any] = {
        "strategy_code": "STRAT_TEST_001",
        "name": "Test Strategy",
        "asset_class": "equity",
        "market": "cn",
        "risk_level": "medium",
        "author_id": "user-uuid-1",
        "subscription_monthly": "99.00",
        "subscription_yearly": "999.00",
    }
    body.update(overrides)
    return StrategyUpsertIn(**body)


def _preview_body(
    *,
    csv_text: str,
    import_type: str = "strategy_daily_returns",
    strategy_code: str | None = "STRAT_TEST_001",
) -> ImportPreviewIn:
    return ImportPreviewIn(
        import_type=import_type,  # type: ignore[arg-type]
        csv_text=csv_text,
        file_name="import.csv",
        strategy_code=strategy_code,
        mode="upsert",
        return_calc_method="compound",
        initial_nav=1.0,
        trading_days_per_year=252,
        risk_free_rate=0.0,
    )


# ---------------------------------------------------------------------------
# upsert_strategy
# ---------------------------------------------------------------------------


class TestUpsertStrategy:
    async def test_insert_happy_path(self) -> None:
        """INSERT path: no prior strategy, returns RETURNING row."""
        cur = _FakeCursor()
        cur.push_one(
            {
                "id": "strat-uuid-1",
                "strategy_code": "STRAT_TEST_001",
                "name": "Test Strategy",
                "pub_status": "draft",
                "run_status": "paper",
            }
        )
        conn = _FakeConn(cur)

        result = await upsert_strategy(
            conn, body=_strategy_upsert_body(), admin_user_id="admin-uuid-1",
        )

        assert result == {
            "strategy_id": "strat-uuid-1",
            "strategy_code": "STRAT_TEST_001",
            "name": "Test Strategy",
            "pub_status": "draft",
            "run_status": "paper",
        }
        assert conn.commits == 1
        # INSERT ... ON CONFLICT ... DO UPDATE used
        sql = cur.executed[0][0]
        assert "INSERT INTO strategies" in sql
        assert "ON CONFLICT (strategy_code) DO UPDATE" in sql
        assert "RETURNING" in sql
        # Params passed
        params = cur.executed[0][1]
        assert params["strategy_code"] == "STRAT_TEST_001"
        # Decimal is parsed eagerly via _parse_decimal_required before SQL,
        # so the param dict holds Decimal objects, not strings.
        assert params["subscription_monthly"] == Decimal("99.00")
        assert params["subscription_yearly"] == Decimal("999.00")

    async def test_update_via_on_conflict(self) -> None:
        """UPDATE path: existing strategy_code → ON CONFLICT triggers UPDATE SET."""
        cur = _FakeCursor()
        cur.push_one(
            {
                "id": "strat-uuid-2",
                "strategy_code": "STRAT_TEST_001",
                "name": "Test Strategy (renamed)",
                "pub_status": "published",
                "run_status": "live",
            }
        )
        conn = _FakeConn(cur)

        body = _strategy_upsert_body(name="Test Strategy (renamed)", pub_status="published")
        result = await upsert_strategy(conn, body=body, admin_user_id="admin-uuid-1")

        assert result["name"] == "Test Strategy (renamed)"
        assert result["pub_status"] == "published"
        # The SQL is the same INSERT/ON CONFLICT — the difference is the
        # RETURNING row. The cursor's `id` distinguishes insert vs update.
        assert "DO UPDATE SET" in cur.executed[0][0]
        assert cur.executed[0][1]["name"] == "Test Strategy (renamed)"

    async def test_negative_price_raises_bad_request(self) -> None:
        """subscription_monthly < 0 must be rejected BEFORE SQL execution."""
        conn = _FakeConn(_FakeCursor())

        with pytest.raises(BadRequest, match="subscription price must be >= 0"):
            await upsert_strategy(
                conn,
                body=_strategy_upsert_body(subscription_monthly="-1"),
                admin_user_id="admin-uuid-1",
            )
        # No SQL should have been executed
        assert conn._cursor.executed == []
        assert conn.commits == 0

    async def test_invalid_decimal_raises_bad_request(self) -> None:
        """Non-numeric subscription string is rejected."""
        conn = _FakeConn(_FakeCursor())

        with pytest.raises(BadRequest, match="invalid decimal: subscription_monthly"):
            await upsert_strategy(
                conn,
                body=_strategy_upsert_body(subscription_monthly="not_a_number"),
                admin_user_id="admin-uuid-1",
            )
        assert conn._cursor.executed == []


# ---------------------------------------------------------------------------
# preview_import
# ---------------------------------------------------------------------------


class TestPreviewImport:
    async def test_daily_returns_happy_path(self) -> None:
        """Valid CSV → status=validated, no errors, job_code returned."""
        csv = "trade_date,daily_return\n2026-01-02,0.01\n2026-01-03,-0.005\n"
        cur = _FakeCursor()
        # _load_strategy_map
        cur.set_rows(
            [
                {"id": "strat-uuid-1", "strategy_code": "STRAT_TEST_001", "market": "cn"},
            ]
        )
        # _count_existing_keys: equity curve SELECT returns 0
        cur.push_one({"cnt": 0})
        conn = _FakeConn(cur)

        result = await preview_import(
            conn,
            body=_preview_body(csv_text=csv),
            admin_user_id="admin-uuid-1",
        )

        assert result["status"] == "validated"
        assert result["summary"]["total_rows"] == 2
        assert result["summary"]["valid_rows"] == 2
        assert result["summary"]["error_rows"] == 0
        assert result["summary"]["will_insert"] == 2
        assert result["summary"]["will_update"] == 0
        # Job code follows the IMPORT_YYYYMMDDHHMMSS_XXXXXXXX pattern
        assert result["job_id"].startswith("IMPORT_")
        assert conn.commits == 1

    async def test_daily_returns_with_validation_errors(self) -> None:
        """Mixed valid/invalid rows → status=blocked, errors collected."""
        csv = (
            "trade_date,daily_return\n"
            "2026-01-02,0.01\n"           # valid
            "2026-01-03,not_a_number\n"   # invalid: float
            "2026-01-04,-2.0\n"            # invalid: <= -1
            "2026-01-05,0.02\n"            # valid
        )
        cur = _FakeCursor()
        cur.set_rows(
            [{"id": "strat-uuid-1", "strategy_code": "STRAT_TEST_001", "market": "cn"}]
        )
        cur.push_one({"cnt": 0})
        conn = _FakeConn(cur)

        result = await preview_import(
            conn,
            body=_preview_body(csv_text=csv),
            admin_user_id="admin-uuid-1",
        )

        assert result["status"] == "blocked"
        assert result["summary"]["error_rows"] == 2
        assert result["summary"]["valid_rows"] == 2
        # 2 errors captured in the response
        assert len(result["errors"]) == 2
        codes = {e["error_code"] for e in result["errors"]}
        assert "invalid_number" in codes
        assert "out_of_range" in codes

    async def test_signals_happy_path(self) -> None:
        """Signal CSV → validated; parent_signal_code absent → parent_id None."""
        csv = (
            "type,action,symbol,published_at\n"
            "entry,buy,600519.SH,2026-01-02T09:30:00+08:00\n"
        )
        cur = _FakeCursor()
        cur.set_rows(
            [{"id": "strat-uuid-1", "strategy_code": "STRAT_TEST_001", "market": "cn"}]
        )
        cur.push_one({"cnt": 0})
        conn = _FakeConn(cur)

        result = await preview_import(
            conn,
            body=_preview_body(
                csv_text=csv, import_type="strategy_signals", strategy_code="STRAT_TEST_001",
            ),
            admin_user_id="admin-uuid-1",
        )

        assert result["status"] == "validated"
        assert result["summary"]["total_rows"] == 1
        assert result["summary"]["valid_rows"] == 1

    async def test_empty_csv_raises_bad_request(self) -> None:
        """CSV with no data rows → BadRequest."""
        conn = _FakeConn(_FakeCursor())
        with pytest.raises(BadRequest, match="csv data row is required"):
            await preview_import(
                conn,
                body=_preview_body(csv_text="trade_date,daily_return\n"),
                admin_user_id="admin-uuid-1",
            )

    async def test_csv_too_many_rows_raises(self) -> None:
        """CSV with > 100k rows → BadRequest (truncated check)."""
        rows = ["trade_date,daily_return"]
        rows.extend(f"2026-01-{(i % 28) + 1:02d},0.01" for i in range(100_001))
        conn = _FakeConn(_FakeCursor())
        with pytest.raises(BadRequest, match="csv row count exceeds 100000"):
            await preview_import(
                conn,
                body=_preview_body(csv_text="\n".join(rows)),
                admin_user_id="admin-uuid-1",
            )

    async def test_duplicate_trade_date_in_csv(self) -> None:
        """Same (strategy_code, trade_date) twice → duplicate error."""
        csv = (
            "trade_date,daily_return\n"
            "2026-01-02,0.01\n"
            "2026-01-02,-0.005\n"
        )
        cur = _FakeCursor()
        # _load_strategy_map: fetchall
        cur.set_rows(
            [{"id": "strat-uuid-1", "strategy_code": "STRAT_TEST_001", "market": "cn"}]
        )
        # _count_existing_keys (daily returns): fetchone per strategy group
        cur.push_one({"cnt": 0})
        conn = _FakeConn(cur)

        result = await preview_import(
            conn, body=_preview_body(csv_text=csv), admin_user_id="admin-uuid-1",
        )

        assert result["status"] == "blocked"
        assert any(e["error_code"] == "duplicate" for e in result["errors"])

    async def test_position_ratio_out_of_range(self) -> None:
        """position_ratio > 1 → out_of_range error."""
        csv = "trade_date,daily_return,position_ratio\n2026-01-02,0.01,1.5\n"
        cur = _FakeCursor()
        cur.set_rows(
            [{"id": "strat-uuid-1", "strategy_code": "STRAT_TEST_001", "market": "cn"}]
        )
        conn = _FakeConn(cur)

        result = await preview_import(
            conn, body=_preview_body(csv_text=csv), admin_user_id="admin-uuid-1",
        )

        assert result["status"] == "blocked"
        assert any(
            e["error_code"] == "out_of_range" and e["column"] == "position_ratio"
            for e in result["errors"]
        )


# ---------------------------------------------------------------------------
# commit_import
# ---------------------------------------------------------------------------


class TestCommitImport:
    async def test_daily_returns_commit_upsert(self) -> None:
        """validated daily-returns job → INSERT 3 tables (equity/monthly/snapshot), 1 commit."""
        cur = _FakeCursor()
        # _fetch_job: returns the validated job
        cur.push_one(
            {
                "id": 1,
                "job_code": "IMPORT_TEST",
                "import_type": "strategy_daily_returns",
                "strategy_id": "strat-uuid-1",
                "file_name": "import.csv",
                "file_sha256": "abc",
                "mode": "upsert",
                "status": "validated",
                "summary": {
                    "return_calc_method": "compound",
                    "initial_nav": 1.0,
                    "trading_days_per_year": 252,
                    "risk_free_rate": 0.0,
                },
                "preview_rows": [],
                "validated_rows": [
                    {
                        "strategy_code": "STRAT_TEST_001",
                        "strategy_id": "strat-uuid-1",
                        "trade_date": "2026-01-02",
                        "daily_return": 0.01,
                        "benchmark_daily_return": None,
                        "position_ratio": None,
                    },
                    {
                        "strategy_code": "STRAT_TEST_001",
                        "strategy_id": "strat-uuid-1",
                        "trade_date": "2026-01-03",
                        "daily_return": -0.005,
                        "benchmark_daily_return": None,
                        "position_ratio": None,
                    },
                ],
                "created_by": "admin-uuid-1",
                "committed_by": None,
                "created_at": datetime(2026, 1, 1),
                "committed_at": None,
            }
        )
        # No fetchone results needed after — the loop INSERTs in cursor
        conn = _FakeConn(cur)

        result = await commit_import(
            conn, job_code="IMPORT_TEST", admin_user_id="admin-uuid-1",
        )

        assert result["status"] == "committed"
        assert result["job_id"] == "IMPORT_TEST"
        # 2 equity rows + 1 monthly + 1 snapshot = 4 affected
        assert result["affected_rows"] == 4
        assert conn.commits == 1
        # UPDATE status to committed was last
        last_sql, last_params = cur.executed[-1]
        assert "UPDATE import_jobs" in last_sql
        assert "SET status = 'committed'" in last_sql
        assert last_params[0] == "admin-uuid-1"
        assert last_params[2] == "IMPORT_TEST"

    async def test_not_validated_raises_bad_request(self) -> None:
        """Job in 'committed' or 'blocked' state cannot be re-committed."""
        cur = _FakeCursor()
        cur.push_one(
            {
                "id": 1,
                "job_code": "IMPORT_DONE",
                "import_type": "strategy_daily_returns",
                "strategy_id": None,
                "file_name": "import.csv",
                "file_sha256": "abc",
                "mode": "upsert",
                "status": "committed",  # already done
                "summary": {},
                "preview_rows": [],
                "validated_rows": [],
                "created_by": "admin-uuid-1",
                "committed_by": "admin-uuid-1",
                "created_at": datetime(2026, 1, 1),
                "committed_at": datetime(2026, 1, 2),
            }
        )
        conn = _FakeConn(cur)

        with pytest.raises(BadRequest, match="import job is not ready to commit"):
            await commit_import(
                conn, job_code="IMPORT_DONE", admin_user_id="admin-uuid-1",
            )
        assert conn.commits == 0

    async def test_signals_commit_insert_only(self) -> None:
        """Signals import with mode=insert_only → ON CONFLICT DO NOTHING."""
        cur = _FakeCursor()
        cur.push_one(
            {
                "id": 1,
                "job_code": "IMPORT_SIG",
                "import_type": "strategy_signals",
                "strategy_id": "strat-uuid-1",
                "file_name": "signals.csv",
                "file_sha256": "abc",
                "mode": "insert_only",  # not upsert → DO NOTHING
                "status": "validated",
                "summary": {},
                "preview_rows": [],
                "validated_rows": [
                    {
                        "strategy_code": "STRAT_TEST_001",
                        "strategy_id": "strat-uuid-1",
                        "market": "cn",
                        "signal_code": "SIG_AAA",
                        "type": "entry",
                        "action": "buy",
                        "direction": "long",
                        "symbol": "600519.SH",
                        "symbol_name": None,
                        "exchange": None,
                        "trigger_price": "100.00",
                        "target_price": None,
                        "stop_loss_price": None,
                        "suggested_quantity": 100,
                        "position_pct": 0.1,
                        "confidence": 0.8,
                        "urgency": "normal",
                        "reason": None,
                        "reason_detail": {},
                        "status": "active",
                        "published_at": "2026-01-02T09:30:00+08:00",
                        "expire_at": None,
                        "parent_signal_code": None,
                    },
                ],
                "created_by": "admin-uuid-1",
                "committed_by": None,
                "created_at": datetime(2026, 1, 1),
                "committed_at": None,
            }
        )
        # No parent_signal_id lookup → next fetchone returns None (no parent)
        cur.push_one(None)
        conn = _FakeConn(cur)

        result = await commit_import(
            conn, job_code="IMPORT_SIG", admin_user_id="admin-uuid-1",
        )

        assert result["status"] == "committed"
        assert result["affected_rows"] == 1
        # Verify the INSERT used DO NOTHING (not DO UPDATE)
        insert_sqls = [s for s, _ in cur.executed if "INSERT INTO signals" in s]
        assert len(insert_sqls) == 1
        assert "ON CONFLICT (signal_code) DO NOTHING" in insert_sqls[0]
        assert "DO UPDATE" not in insert_sqls[0]

    async def test_unsupported_import_type_raises(self) -> None:
        """A future import_type that the service doesn't know about → BadRequest."""
        cur = _FakeCursor()
        cur.push_one(
            {
                "id": 1,
                "job_code": "IMPORT_FUTURE",
                "import_type": "future_type_not_yet_supported",
                "strategy_id": None,
                "file_name": "x.csv",
                "file_sha256": "abc",
                "mode": "upsert",
                "status": "validated",
                "summary": {},
                "preview_rows": [],
                "validated_rows": [],
                "created_by": "admin-uuid-1",
                "committed_by": None,
                "created_at": datetime(2026, 1, 1),
                "committed_at": None,
            }
        )
        conn = _FakeConn(cur)

        with pytest.raises(BadRequest, match="unsupported import type"):
            await commit_import(
                conn, job_code="IMPORT_FUTURE", admin_user_id="admin-uuid-1",
            )


# ---------------------------------------------------------------------------
# list_import_history / get_import_job / list_import_errors
# ---------------------------------------------------------------------------


class TestReadOnlyEndpoints:
    async def test_list_import_history(self) -> None:
        """Returns the last 20 jobs, formatted via _format_job_row."""
        cur = _FakeCursor()
        cur.set_rows(
            [
                {
                    "job_code": "JOB_A",
                    "import_type": "strategy_daily_returns",
                    "file_name": "a.csv",
                    "mode": "upsert",
                    "status": "committed",
                    "summary": {"foo": 1},
                    "created_by": "admin-1",
                    "committed_by": "admin-1",
                    "created_at": datetime(2026, 1, 1),
                    "committed_at": datetime(2026, 1, 2),
                },
            ]
        )
        conn = _FakeConn(cur)

        result = await list_import_history(conn)

        assert "list" in result
        assert len(result["list"]) == 1
        row = result["list"][0]
        assert row["job_id"] == "JOB_A"
        assert row["import_type"] == "strategy_daily_returns"
        assert row["status"] == "committed"
        assert row["summary"] == {"foo": 1}
        # LIMIT 20 in the SQL
        assert "LIMIT 20" in cur.executed[0][0]

    async def test_get_import_job_happy_path(self) -> None:
        """Returns a single job by code."""
        cur = _FakeCursor()
        cur.push_one(
            {
                "id": 1,
                "job_code": "JOB_X",
                "import_type": "strategy_daily_returns",
                "strategy_id": None,
                "file_name": "x.csv",
                "file_sha256": "abc",
                "mode": "upsert",
                "status": "validated",
                "summary": {},
                "preview_rows": [],
                "validated_rows": [],
                "created_by": "admin-1",
                "committed_by": None,
                "created_at": datetime(2026, 1, 1),
                "committed_at": None,
            }
        )
        conn = _FakeConn(cur)

        result = await get_import_job(conn, job_code="JOB_X")

        assert result["job_id"] == "JOB_X"
        assert result["status"] == "validated"

    async def test_get_import_job_not_found_raises(self) -> None:
        """Job code not in DB → NotFound."""
        conn = _FakeConn(_FakeCursor())  # fetchone returns None
        with pytest.raises(NotFound, match="import job not found"):
            await get_import_job(conn, job_code="MISSING")

    async def test_list_import_errors_happy_path(self) -> None:
        """Returns per-row errors for a job."""
        cur = _FakeCursor()
        # _fetch_job: first SELECT returns the job id
        cur.push_one({"id": 42})
        # second SELECT (errors): fetchall
        cur.set_rows(
            [
                {
                    "row_number": 5,
                    "column_name": "daily_return",
                    "error_code": "invalid_number",
                    "message": "invalid number",
                    "raw_row": {"trade_date": "2026-01-02", "daily_return": "foo"},
                },
            ]
        )
        conn = _FakeConn(cur)

        result = await list_import_errors(conn, job_code="JOB_ERR")

        assert "list" in result
        assert len(result["list"]) == 1
        err = result["list"][0]
        assert err["row_number"] == 5
        assert err["column"] == "daily_return"
        assert err["error_code"] == "invalid_number"
        # ORDER BY row_number ASC, id ASC
        assert "ORDER BY row_number ASC, id ASC" in cur.executed[1][0]

    async def test_list_import_errors_job_not_found_raises(self) -> None:
        """Job code not in DB → NotFound, no errors query."""
        conn = _FakeConn(_FakeCursor())  # fetchone returns None
        with pytest.raises(NotFound, match="import job not found"):
            await list_import_errors(conn, job_code="MISSING")
        # Only 1 SELECT (the job lookup) — no errors SELECT was run
        assert len(conn._cursor.executed) == 1


# ---------------------------------------------------------------------------
# _parse_csv_rows
# ---------------------------------------------------------------------------


class TestParseCsvRows:
    def test_basic_csv(self) -> None:
        """DictReader round-trip with simple headers."""
        csv = "a,b\n1,2\n3,4\n"
        rows = _parse_csv_rows(csv)
        assert rows == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]

    def test_bom_stripped(self) -> None:
        """Excel saves CSVs with a leading BOM; we strip it before parsing."""
        csv = "﻿a,b\n1,2\n"
        rows = _parse_csv_rows(csv)
        # First column should be 'a' not 'a ' or 'ufeffa'
        assert list(rows[0].keys()) == ["a", "b"]

    def test_empty_data_raises(self) -> None:
        """Header only, no rows → BadRequest."""
        with pytest.raises(BadRequest, match="csv data row is required"):
            _parse_csv_rows("a,b\n")

    def test_no_header_raises(self) -> None:
        """Empty string → BadRequest (no header)."""
        with pytest.raises(BadRequest, match="csv header is required"):
            _parse_csv_rows("")


# ---------------------------------------------------------------------------
# _derive_daily_return_payload
# ---------------------------------------------------------------------------


class TestDeriveDailyReturnPayload:
    def test_compound_method_2_rows(self) -> None:
        """2 rows of 1% → cumulative_return ~ 2.01%, nav = 1.0201."""
        rows = [
            {"strategy_id": "s1", "trade_date": "2026-01-02", "daily_return": 0.01},
            {"strategy_id": "s1", "trade_date": "2026-01-03", "daily_return": 0.01},
        ]
        result = _derive_daily_return_payload(
            rows, method="compound", initial_nav=1.0,
            trading_days_per_year=252, risk_free_rate=0.0,
        )

        assert len(result["equity_rows"]) == 2
        # Day 1: nav = 1 * (1 + 0.01) = 1.01
        assert result["equity_rows"][0]["nav"] == pytest.approx(1.01, rel=1e-9)
        # Day 2: nav = 1.01 * 1.01 = 1.0201
        assert result["equity_rows"][1]["nav"] == pytest.approx(1.0201, rel=1e-9)
        # 1 monthly aggregate for January 2026
        assert len(result["monthly_rows"]) == 1
        assert result["monthly_rows"][0]["year"] == 2026
        assert result["monthly_rows"][0]["month"] == 1
        # 1 snapshot per strategy
        assert len(result["snapshot_rows"]) == 1

    def test_simple_method(self) -> None:
        """Simple method: cumulative_return = sum of daily returns."""
        rows = [
            {"strategy_id": "s1", "trade_date": "2026-01-02", "daily_return": 0.01},
            {"strategy_id": "s1", "trade_date": "2026-01-03", "daily_return": -0.005},
        ]
        result = _derive_daily_return_payload(
            rows, method="simple", initial_nav=1.0,
            trading_days_per_year=252, risk_free_rate=0.0,
        )

        # 0.01 + (-0.005) = 0.005
        assert result["equity_rows"][-1]["cumulative_return"] == pytest.approx(0.005, rel=1e-9)

    def test_empty_rows(self) -> None:
        """No input rows → empty outputs."""
        result = _derive_daily_return_payload(
            [], method="compound", initial_nav=1.0,
            trading_days_per_year=252, risk_free_rate=0.0,
        )
        assert result == {"equity_rows": [], "monthly_rows": [], "snapshot_rows": []}

    def test_multi_strategy_split(self) -> None:
        """2 strategies → separate equity curves, monthly, snapshot per strategy."""
        rows = [
            {"strategy_id": "s1", "trade_date": "2026-01-02", "daily_return": 0.01},
            {"strategy_id": "s2", "trade_date": "2026-01-02", "daily_return": 0.02},
        ]
        result = _derive_daily_return_payload(
            rows, method="compound", initial_nav=1.0,
            trading_days_per_year=252, risk_free_rate=0.0,
        )
        assert len(result["equity_rows"]) == 2
        # 1 monthly row per strategy
        assert len(result["monthly_rows"]) == 2
        # 1 snapshot per strategy
        assert len(result["snapshot_rows"]) == 2


# ---------------------------------------------------------------------------
# _parse_datetime / _stable_signal_code / _make_job_code
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_parse_datetime_with_timezone(self) -> None:
        """ISO with offset → converted to Asia/Shanghai."""
        dt = _parse_datetime(
            "2026-01-02T09:30:00+00:00", 1, "published_at", {}, [],
        )
        assert dt is not None
        # +00:00 → +08:00 = 17:30
        assert dt.hour == 17
        assert dt.minute == 30

    def test_parse_datetime_naive_assumes_shanghai(self) -> None:
        """Naive datetime → assumed to be Asia/Shanghai."""
        dt = _parse_datetime("2026-01-02T09:30:00", 1, "published_at", {}, [])
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 8 * 3600

    def test_parse_datetime_z_suffix(self) -> None:
        """Z suffix (UTC) → converted to Shanghai."""
        dt = _parse_datetime("2026-01-02T09:30:00Z", 1, "published_at", {}, [])
        assert dt is not None
        assert dt.hour == 17

    def test_parse_datetime_invalid(self) -> None:
        """Garbage string → None, error appended."""
        errors: list[dict[str, Any]] = []
        dt = _parse_datetime("not-a-date", 1, "published_at", {}, errors)
        assert dt is None
        assert len(errors) == 1
        assert errors[0]["error_code"] == "invalid_datetime"

    def test_stable_signal_code_deterministic(self) -> None:
        """Same seed → same code (sha1 first 16 hex)."""
        row = {"symbol": "X", "type": "entry", "action": "buy"}
        dt = datetime(2026, 1, 2, 9, 30)
        a = _stable_signal_code("S1", row, dt)
        b = _stable_signal_code("S1", row, dt)
        assert a == b
        assert a.startswith("SIG_")
        assert len(a) == 4 + 16  # "SIG_" + 16 hex

    def test_stable_signal_code_differs_on_seed(self) -> None:
        """Different strategy_code → different signal code."""
        row = {"symbol": "X", "type": "entry", "action": "buy"}
        dt = datetime(2026, 1, 2, 9, 30)
        a = _stable_signal_code("S1", row, dt)
        b = _stable_signal_code("S2", row, dt)
        assert a != b

    def test_make_job_code_format(self) -> None:
        """Job code matches IMPORT_YYYYMMDDHHMMSS_XXXXXXXX (8 hex)."""
        code = _make_job_code()
        assert code.startswith("IMPORT_")
        # 14-digit timestamp + '_' + 8 hex chars
        parts = code.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 14
        assert parts[1].isdigit()
        assert len(parts[2]) == 8
        int(parts[2], 16)  # valid hex

    def test_make_job_code_unique(self) -> None:
        """Two calls in quick succession produce different codes (uuid4 suffix)."""
        a = _make_job_code()
        b = _make_job_code()
        assert a != b
