from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from gr_api.diagnosis_calc.replay import ReplayPoint, ReplayResult
from gr_api.errors import BadRequest
from gr_api.schemas.diagnosis import CalculationOptions, RecomputeRequest
from gr_api.services import diagnosis as svc
from gr_api.services.diagnosis import BaseDataVersionUnavailableError
from gr_api.services.diagnosis_benchmark import read_benchmark
from gr_api.services.diagnosis_replay import replay_snapshot
from gr_data.common.benchmark import benchmark_version
from pydantic import TypeAdapter


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


@pytest.mark.anyio
async def test_read_benchmark_distinguishes_missing_invalid_and_symbol_fallback() -> None:
    db_unused = fake_db([])
    missing = await read_benchmark(db_unused, None, None, (DAYS[0], DAYS[-1]))
    assert missing.status == "benchmark_missing"
    assert missing.returns == {}

    empty_db = fake_db([("FROM market.index_total_return_1d", lambda _: [])])
    not_found = await read_benchmark(empty_db, 40756, "v-missing", (DAYS[0], DAYS[-1]))
    assert not_found.status == "data_not_validated"

    rows = [
        {"symbol": "H00300.CSI", "name": None, "dt": DAYS[0], "simple_return": 0.01},
        {"symbol": "H00300.CSI", "name": None, "dt": DAYS[1], "simple_return": 0.02},
    ]
    valid_ver = benchmark_version("H00300.CSI", {r["dt"]: r["simple_return"] for r in rows})
    ok_db = fake_db([("FROM market.index_total_return_1d", lambda _: rows)])
    bad_hash = await read_benchmark(ok_db, 40756, "wrong-version", (DAYS[0], DAYS[-1]))
    assert bad_hash.status == "data_not_validated"

    good = await read_benchmark(ok_db, 40756, valid_ver, (DAYS[0], DAYS[1]))
    assert good.status == "ok"
    assert good.symbol == "H00300.CSI"
    assert good.name == "H00300.CSI"
    assert good.returns == {DAYS[0]: 0.01, DAYS[1]: 0.02}


@pytest.mark.anyio
async def test_resolve_options_rejects_single_day_replay_start_equal_as_of() -> None:
    """B3 单日边界：replay_start == as_of 且省略 stats_window 在提交和重算均返回 422。"""
    cal_days = [date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19)]
    as_of = cal_days[-1]

    def cal_handler(params):
        # _trading_day_on_or_before / _nth_trading_day_back
        if len(params) == 3:  # _nth_trading_day_back
            return [{"trading_day": d} for d in reversed(cal_days)]
        day = params[1]
        return [{"trading_day": d} for d in reversed(cal_days) if d <= day][:1]

    db = fake_db([("FROM meta.trading_calendar", cal_handler)])
    manifest = {
        "replay": {
            "version": "pa12-local-v1",
            "through_date": as_of.isoformat(),
            "dividend_sha256": {"23": "a" * 64},
            "dividend_signatures": {"23": [0, "b" * 64]},
            "delisting_sha256": "c" * 64,
            "delist_dates": {"23": None},
        }
    }
    params = {"cov_methods": ["forward"], "history_lookback_days": 2, "beta_lookback_days": 2}

    # 提交入口
    with pytest.raises(BadRequest) as submit_exc:
        await svc._resolve_options(
            db,
            requested=CalculationOptions(replay_start=as_of),
            params=params,
            available=manifest,
            as_of=as_of,
        )
    assert submit_exc.value.http_status == 422
    assert submit_exc.value.issues[0]["path"] == "/options/replay_start"

    # 重算入口：改 replay_start = as_of 且省略 stats_window
    base_options = {
        "industry_scheme": None,
        "industry_scheme_version": None,
        "benchmark_instrument_id": None,
        "benchmark_version": None,
        "correlation_window": {"start": cal_days[0].isoformat(), "end": as_of.isoformat()},
        "beta_window": {"start": cal_days[0].isoformat(), "end": as_of.isoformat()},
        "replay_start": cal_days[0].isoformat(),
        "stats_window": {"start": cal_days[0].isoformat(), "end": as_of.isoformat()},
    }
    with pytest.raises(BadRequest) as recompute_exc:
        await svc._resolve_options(
            db,
            requested=CalculationOptions(replay_start=as_of),
            params=params,
            available=manifest,
            as_of=as_of,
            base=base_options,
        )
    assert recompute_exc.value.http_status == 422
    assert recompute_exc.value.issues[0]["path"] == "/options/replay_start"


@pytest.mark.anyio
async def test_recompute_snapshot_reuses_replay_state_per_plan_across_benchmark_and_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B3 按方案复用：切基准或裁窗时零次调用 replay_snapshot，且混合不可用方案不误抛 409。"""
    base_id = uuid4()
    new_id = uuid4()
    as_of = DAYS[-1]
    saved_replay = ReplayResult(
        (
            ReplayPoint(DAYS[0], Decimal("1.0"), Decimal("1.0"), Decimal("0")),
            ReplayPoint(DAYS[1], Decimal("1.02"), Decimal("1.02"), Decimal("0")),
            ReplayPoint(DAYS[2], Decimal("1.0404"), Decimal("1.0404"), Decimal("0")),
        ),
        None,
        None,
        None,
    )
    saved_state = TypeAdapter(ReplayResult).dump_python(saved_replay, mode="json")
    base_options = {
        "industry_scheme": None,
        "industry_scheme_version": None,
        "benchmark_instrument_id": 40756,
        "benchmark_version": "v-300",
        "correlation_window": {"start": DAYS[0].isoformat(), "end": as_of.isoformat()},
        "beta_window": {"start": DAYS[0].isoformat(), "end": as_of.isoformat()},
        "replay_start": DAYS[0].isoformat(),
        "stats_window": {"start": DAYS[0].isoformat(), "end": as_of.isoformat()},
    }
    base_snapshot = {
        "snapshot_id": base_id,
        "data_fingerprint": "dv-1",
        "resolved_spec_version": "v1",
        "resolved_as_of_date": as_of,
        "resolved_intent": "multi_portfolio",
        "resolved_options": base_options,
    }
    data_version = {
        "data_version_id": "dv-1",
        "available_options": {
            "benchmarks": [
                {"instrument_id": 40756, "symbol": "H00300.CSI", "version": "v-300"},
                {"instrument_id": 40805, "symbol": "H00905.CSI", "version": "v-500"},
            ],
            "replay": {
                "version": "pa12-local-v1",
                "through_date": as_of.isoformat(),
                "dividend_sha256": {"23": "a" * 64},
                "dividend_signatures": {"23": [0, "b" * 64]},
                "delisting_sha256": "c" * 64,
                "delist_dates": {"23": None},
            },
        },
    }
    plan_rows = [
        {
            "plan_index": 0,
            "plan_id": "p_ok",
            "label": "可回放方案",
            "weight_mode": "user",
            "requested_holdings": [],
            "resolved_holdings": [{"instrument_id": 23, "weight_units": 100_000_000}],
            "input_context": {"calculation_holdings": [], "holdings": []},
        },
        {
            "plan_index": 1,
            "plan_id": "p_na",
            "label": "未覆盖方案",
            "weight_mode": "user",
            "requested_holdings": [],
            "resolved_holdings": [{"instrument_id": 99, "weight_units": 100_000_000}],
            "input_context": {"calculation_holdings": [], "holdings": []},
        },
    ]

    captured_plans: list[svc.PlanInput] = []
    replay_calls = 0

    async def fail_if_replay_called(*args, **kwargs):
        nonlocal replay_calls
        replay_calls += 1
        raise AssertionError("replay_snapshot must not be called when reusing state")

    async def fake_persist(db, **kwargs):
        captured_plans.clear()
        captured_plans.extend(kwargs["plans"])
        return new_id

    async def fake_with_idempotency(db, *, create, **kwargs):
        return {"snapshot_id": str(await create("hash"))}, 200

    monkeypatch.setattr(svc, "replay_snapshot", fail_if_replay_called)
    monkeypatch.setattr(svc, "_load_snapshot", AsyncMock(return_value=base_snapshot))
    monkeypatch.setattr(svc, "_base_data_version_available", AsyncMock(return_value=True))
    monkeypatch.setattr(svc, "get_active_spec_version", AsyncMock(return_value={"params": {}}))
    monkeypatch.setattr(svc, "_get_data_version_by_id", AsyncMock(return_value=data_version))
    monkeypatch.setattr(svc, "_persist_snapshot", fake_persist)
    monkeypatch.setattr(svc, "_with_idempotency", fake_with_idempotency)
    token = svc.publication.enabled.set(False)
    try:
        # 1) 混合多方案切基准：plan 0 复用状态，plan 1 继承 unavailable（不抛 409）
        db_mixed = fake_db(
            [
                ("FROM diag.portfolio_plan", lambda _: plan_rows),
                (
                    "FROM diag.snapshot_run",
                    lambda _: [
                        {
                            "plan_index": 0,
                            "state": saved_state,
                            "section_c": {"status": "ready", "value": {}},
                        },
                        {
                            "plan_index": 1,
                            "state": None,
                            "section_c": {
                                "status": "unavailable",
                                "reason_code": "coverage_below_threshold",
                                "reason": "回放发布范围未覆盖全部正权重持仓。",
                            },
                        },
                    ],
                ),
            ]
        )
        await svc.recompute_snapshot(
            db_mixed,
            base_id,
            RecomputeRequest(options=CalculationOptions(benchmark="H00905.CSI")),
            user_id="u1",
        )
        assert replay_calls == 0
        assert captured_plans[0].base_replay == saved_replay
        assert captured_plans[0].base_replay_unavailable is None
        assert captured_plans[1].base_replay is None
        assert captured_plans[1].base_replay_unavailable is not None
        assert (
            captured_plans[1].base_replay_unavailable["reason_code"] == "coverage_below_threshold"
        )

        # 2) 原方案声称 ready 但 replay_state 损坏：必须报 409 BaseDataVersionUnavailableError
        db_corrupt = fake_db(
            [
                ("FROM diag.portfolio_plan", lambda _: plan_rows[:1]),
                (
                    "FROM diag.snapshot_run",
                    lambda _: [
                        {
                            "plan_index": 0,
                            "state": None,
                            "section_c": {"status": "ready", "value": {}},
                        }
                    ],
                ),
            ]
        )
        with pytest.raises(BaseDataVersionUnavailableError):
            await svc.recompute_snapshot(
                db_corrupt,
                base_id,
                RecomputeRequest(options=CalculationOptions(benchmark="H00905.CSI")),
                user_id="u1",
            )
    finally:
        svc.publication.enabled.reset(token)
