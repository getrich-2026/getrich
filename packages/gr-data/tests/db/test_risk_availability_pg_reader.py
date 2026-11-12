from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from gr_data.common.risk_availability import RiskDay
from gr_data.db.postgres.risk_availability import assess_postgres_day


def snapshot() -> RiskDay:
    return RiskDay(
        "v2",
        date(2020, 2, 18),
        "accepted",
        "run",
        "variant",
        "model",
        datetime(2026, 11, 8, tzinfo=timezone.utc),
        False,
        "daily",
        "axis",
        variance_unit="pct2_annual",
    )


def connection():
    conn = MagicMock()
    conn.read_only = True
    row = snapshot()
    meta = {
        "model_id": "model",
        "observed_at": row.observed_at,
        "factor_order_hash": "axis",
        "horizon": "daily",
        "calibrated": False,
        "units": {
            "model": "v2",
            "trading_day": "2020-02-18",
            "variant_id": "variant",
            "covariance": "pct2_annual",
            "specific_risk": "pct2_annual",
        },
    }
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.side_effect = [[meta], [{"symbol": "000001.SZ"}]]
    return conn, cur, meta


def call(conn, row=None):
    return assess_postgres_day(
        conn,
        row or snapshot(),
        model="v2",
        day=date(2020, 2, 18),
        holdings={"000001.SZ": Decimal(1)},
    )


def test_actual_coverage_is_bound_to_canonical_day_run_and_does_not_open_reading():
    conn, cur, _ = connection()
    r = call(conn)
    assert r["diagnostic_inputs_ready"] is True and r["formal_ready"] is False
    assert cur.execute.call_args_list[1].args[1] == (
        "run",
        date(2020, 2, 18),
        date(2020, 2, 18),
        date(2020, 2, 18),
        ["000001.SZ"],
    )


def test_requires_readonly_connection():
    conn, cur, _ = connection()
    conn.read_only = False
    with pytest.raises(ValueError, match="read-only"):
        call(conn)
    cur.execute.assert_not_called()


def test_known_gap_does_not_query_other_day_or_model():
    conn, cur, _ = connection()
    r = call(conn, RiskDay("v2", date(2020, 2, 18), "blocked_source_units"))
    assert r["data_day"] is None and r["diagnostic_inputs_ready"] is False
    cur.execute.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [("horizon", "monthly"), ("factor_order_hash", "other"), ("model_id", "different")],
)
def test_changed_database_metadata_does_not_reuse_inventory_snapshot(field, value):
    conn, _, meta = connection()
    meta[field] = value
    with pytest.raises(ValueError, match="differs"):
        call(conn)


def test_missing_atomic_receipt_binding_stops():
    conn, cur, _ = connection()
    cur.fetchall.side_effect = [[]]
    with pytest.raises(ValueError, match="binding"):
        call(conn)


@pytest.mark.parametrize("value", [None, "dec2_daily"])
def test_specific_variance_unit_mismatch_or_missing_blocks(value):
    conn, _, meta = connection()
    meta["units"]["specific_risk"] = value
    with pytest.raises(ValueError, match="differs"):
        call(conn)


def test_changed_calibration_cannot_reuse_previous_snapshot():
    conn, _, meta = connection()
    meta["calibrated"] = True
    with pytest.raises(ValueError, match="differs"):
        call(conn)
