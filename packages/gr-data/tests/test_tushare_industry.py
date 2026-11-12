"""行业目标日区间、缺失和异常输入回归。"""

from __future__ import annotations

from datetime import date, datetime, timezone

import polars as pl
import pytest
from gr_data.ingest.tushare.industry import normalize_industry


NODES = pl.DataFrame(
    {
        "index_code": ["801780.SI", "801120.SI"],
        "industry_name": ["银行", "食品饮料"],
        "level": ["L1", "L1"],
    }
)


def normalize(rows: list[dict], **kwargs):
    return normalize_industry(
        NODES,
        pl.DataFrame(rows),
        symbol_ids={"600000.SH": 1, "600519.SH": 2},
        as_of=date(2026, 11, 5),
        observed_at=datetime.now(timezone.utc),
        **kwargs,
    )


def member(code="801780.SI", first="20200101", last=None):
    return {"ts_code": "600000.SH", "l1_code": code, "in_date": first, "out_date": last}


def test_target_interval_and_missing_are_explicit():
    result = normalize([member(), member(first="20100101", last="20200101")])
    assert result.members.height == 1
    assert result.members["in_date"][0] == date(2020, 1, 1)
    assert result.missing_ids == (2,)


def test_out_date_exclusive_and_future_assignment_not_backfilled():
    result = normalize([member(last="20261105"), member(first="20261106")])
    assert result.members.is_empty()
    assert result.missing_ids == (1, 2)


@pytest.mark.parametrize(
    "rows",
    [
        [member(), member("801120.SI")],
        [member(first="20261106", last="20261105")],
        [member("unknown")],
        [member(first="bad-date")],
    ],
)
def test_conflicts_invalid_dates_and_unknown_nodes_rejected(rows):
    with pytest.raises((ValueError, pl.exceptions.InvalidOperationError)):
        normalize(rows)


def test_exact_source_duplicates_do_not_duplicate_weights():
    assert normalize([member(), member()]).members.height == 1


@pytest.mark.anyio
async def test_writer_requires_outer_transaction_and_unchanged_owner():
    from unittest.mock import AsyncMock, Mock

    from gr_data.ingest.tushare.industry import write_industry_snapshot
    from psycopg.pq import TransactionStatus

    snapshot = normalize([member()])
    owners: dict[str, str | None] = dict.fromkeys(
        ("classify.scheme", "classify.industry_node", "classify.instrument_industry")
    )
    conn = Mock()
    conn.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(ValueError, match="outer publication transaction"):
        await write_industry_snapshot(conn, snapshot, expected_owners=owners)
    conn.info.transaction_status = TransactionStatus.INTRANS
    cursor = Mock()
    cursor.fetchone = AsyncMock(return_value={"provider": "unexpected"})
    conn.execute = AsyncMock(return_value=cursor)
    with pytest.raises(ValueError, match="ownership changed"):
        await write_industry_snapshot(conn, snapshot, expected_owners=owners)
    assert not any(
        "INSERT" in str(call) or "DELETE" in str(call) for call in conn.execute.call_args_list
    )


def test_same_security_changes_industry_closes_old_interval():
    from gr_data.ingest.tushare.industry import industry_changes

    old = normalize([member()]).members.to_dicts()
    source = normalize([member(last="20261105"), member("801120.SI", first="20261105")])
    changes = industry_changes(old, source)
    assert len(changes) == 2
    assert changes[0]["out_date"] == date(2026, 11, 5)
    assert changes[1]["industry_code"] == "801120.SI"


def test_security_removed_without_replacement_closes_interval():
    from gr_data.ingest.tushare.industry import industry_changes

    old = normalize([member()]).members.to_dicts()
    source = normalize([member(last="20261105")])
    assert source.members.is_empty()
    changes = industry_changes(old, source)
    assert len(changes) == 1 and changes[0]["out_date"] == date(2026, 11, 5)


def test_unchanged_industry_preserves_first_observation():
    from gr_data.ingest.tushare.industry import industry_changes

    old = normalize([member()]).members.to_dicts()
    before = old[0]["available_at"]
    assert industry_changes(old, normalize([member()])) == []
    assert old[0]["available_at"] == before


def test_missing_source_row_cannot_leave_old_membership_open():
    from gr_data.ingest.tushare.industry import industry_changes, validate_missing_closures

    old = normalize([member()]).members.to_dicts()
    absent = normalize([member(first="20261106")])
    with pytest.raises(ValueError, match="leaves a stored interval open"):
        validate_missing_closures(old, industry_changes(old, absent), absent)
    closed = normalize([member(last="20261105")])
    validate_missing_closures(old, industry_changes(old, closed), closed)
