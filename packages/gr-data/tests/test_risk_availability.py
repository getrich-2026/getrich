from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from gr_data.common.risk_availability import RiskCoverage, RiskDay, assess_day, assess_range


def ready(day: date = date(2020, 2, 18), model: str = "v2") -> RiskDay:
    return RiskDay(
        model,
        day,
        "accepted",
        "run",
        "variant",
        "model-id",
        datetime(2026, 11, 8, tzinfo=timezone.utc),
        False,
        "daily",
        "axis",
        variance_unit="pct2_annual",
    )


def assess(row: RiskDay, holdings: dict[str, Decimal] | None = None, **kwargs):
    return assess_day(
        row,
        model="v2",
        day=date(2020, 2, 18),
        holdings=holdings or {"000001.SZ": Decimal("0.4"), "600000.SH": Decimal("-0.3")},
        coverage=RiskCoverage("v2", date(2020, 2, 18), row.run_id, ("000001.SZ", "600000.SH")),
        **kwargs,
    )


def test_accepted_day_echoes_exact_identity_and_preserves_formal_closure():
    r = assess(ready())
    assert r["diagnostic_inputs_ready"] is True
    assert (r["used_model"], r["data_day"], r["run_id"]) == ("v2", "2020-02-18", "run")
    assert r["covered_count"] == 2 and r["gross_weight_coverage"] == "1"
    assert r["formal_ready"] is False and r["calibrated"] is False


def test_missing_day_never_claims_model_date_or_falls_back():
    r = assess(RiskDay("v2", date(2020, 2, 18), "blocked_source_units"))
    assert r["diagnostic_inputs_ready"] is False
    assert r["used_model"] is None and r["data_day"] is None
    assert r["missing_symbols"] == ["000001.SZ", "600000.SH"]
    assert r["gross_weight_coverage"] is None and r["fallback_used"] is False


@pytest.mark.parametrize("row", [ready(date(2020, 2, 17)), ready(model="v2trd")])
def test_date_or_model_fallback_is_rejected(row):
    with pytest.raises(ValueError, match="fallback"):
        assess(row)


def test_missing_short_position_not_dropped_or_renormalized():
    r = assess_day(
        ready(),
        model="v2",
        day=date(2020, 2, 18),
        holdings={"000001.SZ": Decimal("0.4"), "600000.SH": Decimal("-0.6")},
        coverage=RiskCoverage("v2", date(2020, 2, 18), "run", ("000001.SZ",)),
    )
    assert r["missing_symbols"] == ["600000.SH"]
    assert r["gross_weight_coverage"] == "0.4" and r["gross_weight"] == "1.0"
    assert r["weights_renormalized"] is False and r["diagnostic_inputs_ready"] is False


def test_zero_position_does_not_require_coverage():
    r = assess(ready(), {"000001.SZ": Decimal("1"), "999999.SH": Decimal("0")})
    assert r["missing_symbols"] == [] and r["nonzero_holdings"] == 1


def test_empty_or_all_zero_positions_do_not_produce_ready_result():
    r = assess_day(
        ready(),
        model="v2",
        day=date(2020, 2, 18),
        holdings={},
        coverage=RiskCoverage("v2", date(2020, 2, 18), "run", ()),
    )
    assert r["diagnostic_inputs_ready"] is False and "empty_nonzero_holdings" in r["reasons"]


@pytest.mark.parametrize("weight", [Decimal("NaN"), Decimal("Infinity"), 0.4])
def test_invalid_weights_rejected(weight):
    with pytest.raises(ValueError, match="Decimal"):
        assess(ready(), {"000001.SZ": weight})


def test_unmapped_full_code_is_not_matched_by_six_digits():
    r = assess(ready(), {"000001.SH": Decimal("1")})
    assert r["missing_symbols"] == ["000001.SH"]


def test_late_observed_snapshot_cannot_be_used_for_historical_decision():
    r = assess(ready(), known_at=datetime(2020, 2, 18, tzinfo=timezone.utc))
    assert r["diagnostic_inputs_ready"] is False
    assert "snapshot_observed_after_knowledge_time" in r["reasons"]
    with pytest.raises(ValueError, match="timezone"):
        assess(ready(), known_at=datetime(2020, 2, 18))


def test_range_lists_missing_days_from_full_calendar_not_existing_rows():
    days = [date(2020, 2, d) for d in (14, 17, 18, 19, 20)]
    rows = {d: ready(d) for d in days[2:]}
    rows[days[0]] = RiskDay("v2", days[0], "blocked_source_units")
    r = assess_range(rows, model="v2", start=days[0], end=days[-1], expected_days=days)
    assert [x["day"] for x in r["missing_dates"]] == ["2020-02-14", "2020-02-17"]
    assert r["expected_trading_days"] == 5 and r["accepted_days"] == 3
    assert r["storage_interval_complete"] is False and r["diagnostic_inputs_ready"] is False


def test_complete_storage_range_still_needs_daily_holdings_and_formal_release():
    d = date(2020, 2, 18)
    r = assess_range({d: ready()}, model="v2", start=d, end=d, expected_days=[d])
    assert r["storage_interval_complete"] is True
    assert r["diagnostic_inputs_ready"] is False and r["formal_ready"] is False


def test_empty_calendar_not_interpreted_as_zero_risk_or_complete_history():
    d = date(2020, 2, 18)
    r = assess_range({}, model="v2", start=d, end=d, expected_days=[])
    assert r["storage_interval_complete"] is False


def test_invalid_calendar_and_cross_model_snapshot_rejected():
    d = date(2020, 2, 18)
    with pytest.raises(ValueError, match="calendar"):
        assess_range({}, model="v2", start=d, end=d, expected_days=[d, d])
    with pytest.raises(ValueError, match="different model"):
        assess_range({d: ready(model="v1")}, model="v2", start=d, end=d, expected_days=[d])


def test_other_run_coverage_cannot_make_a_day_available():
    with pytest.raises(ValueError, match="another model, day or run"):
        assess_day(
            ready(),
            model="v2",
            day=date(2020, 2, 18),
            holdings={"000001.SZ": Decimal(1)},
            coverage=RiskCoverage("v2", date(2020, 2, 18), "other", ("000001.SZ",)),
        )


@pytest.mark.parametrize("code", ["bad.symbol", "000001.XSHE", "000001", "1.SZ", "000001.sz"])
def test_both_sides_reject_noncanonical_codes(code):
    with pytest.raises(ValueError, match="canonical"):
        assess(ready(), {code: Decimal(1)})
    with pytest.raises(ValueError, match="canonical"):
        assess_day(
            ready(),
            model="v2",
            day=date(2020, 2, 18),
            holdings={"000001.SZ": Decimal(1)},
            coverage=RiskCoverage("v2", date(2020, 2, 18), "run", (code,)),
        )
