from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from gr_api.services.diagnosis_replay import replay_snapshot


DAYS = [date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19)]
WEIGHTS = {"000001.SZ": Decimal(1)}


def fake_db(handlers):
    cursor = AsyncMock()

    def execute(query, params):
        for match, response in handlers:
            if match in query:
                rows = response(params)
                cursor.fetchall.return_value = rows
                cursor.fetchone.return_value = rows[0] if rows else None
                return
        raise AssertionError(query)

    cursor.execute.side_effect = execute
    db = MagicMock()
    db.cursor.return_value.__aenter__.return_value = cursor
    return db


@pytest.mark.anyio
@pytest.mark.parametrize("known_payment", [True, False])
async def test_event_applied_only_to_matching_snapshot_and_only_from_ex_date(
    known_payment: bool,
) -> None:
    digest, ds07 = "0" * 64, "9" * 64

    def events(params):
        assert params[1] == digest
        return [
            {
                "ex_date": DAYS[1],
                "pay_date": DAYS[1] if known_payment else None,
                "cash_per_share": Decimal(1),
                "shares_per_share": Decimal(0),
                "record_date": DAYS[0],
                "implementation_date": DAYS[0],
                "share_listing_date": None,
            }
        ]

    db = fake_db(
        [
            ("SELECT 1 FROM market.stock_delisting", lambda p: [{"ok": 1}] if p == (ds07,) else []),
            (
                "FROM meta.instruments i",
                lambda _: [
                    {
                        "instrument_id": 23,
                        "symbol": "000001.SZ",
                        "exchange": "XSHE",
                        "list_date": date(1991, 1, 1),
                        "raw_sha256": digest,
                        "metadata_delist_date": None,
                        "delist_date": None,
                        "through_date": DAYS[-1],
                    }
                ],
            ),
            (
                "FROM meta.trading_calendar",
                lambda _: [
                    {
                        "trading_day": day,
                        "prev_trading_day": DAYS[i - 1] if i else date(2026, 11, 16),
                    }
                    for i, day in enumerate(DAYS)
                ],
            ),
            ("AS row_count", lambda _: [{"row_count": 1, "digest": digest}]),
            ("SELECT * FROM finance.dividend", events),
            (
                "FROM market.stock_suspend_coverage",
                lambda _: [
                    {
                        "trading_day": day,
                        "bar_id": 23,
                        "event_count": 0,
                        "full_suspend": False,
                        "open": Decimal(10),
                        "close": Decimal(10),
                        "price_limit_status": "LIMITED",
                        "limit_up": Decimal(11),
                    }
                    for day in DAYS
                ],
            ),
        ]
    )
    result = await replay_snapshot(
        db,
        WEIGHTS,
        DAYS[0],
        DAYS[-1],
        expected_hashes={"23": digest},
        dividend_signatures={"23": [1, digest]},
        delisting_hash=ds07,
        delist_dates={"23": None},
    )
    assert result.points[0].nav == 1
    if known_payment:
        assert result.points[1].cash == Decimal(".1")
        assert result.points[2].cash == 0 and result.points[2].nav == Decimal("1.1")
    else:
        assert result.stopped_on == DAYS[1] and len(result.points) == 1


@pytest.mark.anyio
async def test_missing_delisting_source_rejects_manifest_before_any_data_read() -> None:
    db = fake_db([("SELECT 1 FROM market.stock_delisting", lambda _: [])])
    with pytest.raises(ValueError, match="Missing admitted delisting"):
        await replay_snapshot(
            db,
            WEIGHTS,
            DAYS[0],
            DAYS[-1],
            expected_hashes={"23": "0" * 64},
            dividend_signatures={"23": [0, "a" * 64]},
            delisting_hash="1" * 64,
            delist_dates={"23": None},
        )
    with pytest.raises(ValueError, match="bind both"):
        await replay_snapshot(db, WEIGHTS, DAYS[0], DAYS[-1], expected_hashes={"23": "0" * 64})


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("symbol", "quotes", "nav"),
    [
        # Tushare 000582.SZ：两个交易日全天 S 无 bar，随后 R 有真实收盘，
        # 复牌日开盘价等于涨停价；已有仓位仍按复牌收盘价估值。
        (
            "000582.SZ",
            [
                ("20260930", "9.00", "8.97", 0, False, "9.87"),
                ("20261008", None, None, 1, True, None),
                ("20261009", None, None, 1, True, None),
                ("20261012", "9.87", "9.30", 1, False, "9.87"),
            ],
            Decimal("9.30") / Decimal("9.00"),
        ),
        # Tushare 301718.SZ：10/23 有 11:01–11:11 盘中停牌和真实收盘。
        (
            "301718.SZ",
            [
                ("20261022", "78.00", "72.99", 0, False, None),
                ("20261023", "61.00", "64.90", 1, False, None),
            ],
            Decimal("64.90") / Decimal("78.00"),
        ),
    ],
)
async def test_real_resume_and_intraday_close_after_entry(symbol, quotes, nav) -> None:
    bars = [
        {
            "trading_day": date.fromisoformat(day),
            "open": Decimal(op) if op else None,
            "close": Decimal(cl) if cl else None,
            "event_count": count,
            "full_suspend": full,
            "bar_id": None if full else 23,
            "price_limit_status": "LIMITED" if cap else "NO_LIMIT",
            "limit_up": Decimal(cap) if cap else None,
        }
        for day, op, cl, count, full, cap in quotes
    ]
    days = [b["trading_day"] for b in bars]
    calendar = [
        {"trading_day": d, "prev_trading_day": days[i - 1] if i else None}
        for i, d in enumerate(days)
    ]
    db = fake_db(
        [
            (
                "FROM meta.instruments i",
                lambda _: [
                    {
                        "instrument_id": 23,
                        "symbol": symbol,
                        "exchange": "XSHE",
                        "list_date": days[0],
                        "raw_sha256": "a" * 64,
                        "metadata_delist_date": None,
                        "delist_date": None,
                        "through_date": days[-1],
                    }
                ],
            ),
            (
                "FROM meta.trading_calendar",
                lambda args: [r for r in calendar if r["trading_day"] >= args[1]],
            ),
            ("SELECT * FROM finance.dividend", lambda _: []),
            ("FROM market.stock_suspend_coverage", lambda _: bars),
        ]
    )
    result = await replay_snapshot(db, {symbol: Decimal(1)}, days[0], days[-1])
    assert result.stopped_on is None and len(result.points) == len(days)
    assert result.points[-1].nav == pytest.approx(nav)
    # 从仅有日级事件证据的当天开始买入，已有收盘价不能证明开盘可执行。
    initial = await replay_snapshot(db, {symbol: Decimal(1)}, days[-1], days[-1])
    assert not initial.points and initial.reason == "execution_undetermined"
