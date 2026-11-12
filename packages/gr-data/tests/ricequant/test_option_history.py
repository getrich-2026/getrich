from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest
from gr_data.ingest.ricequant.option_history import (
    GREEK_METHOD,
    GREEK_UNITS,
    GREEKS_RULE,
    SEED_GREEKS_RULE,
    SEED_POLICY_SHA256,
    HistoryError,
    Observation,
    match_reference,
    prepare_greeks,
    prepare_term_candidates,
    prepare_terms,
    verify_existing_greek_methods,
)


def observation() -> Observation:
    return Observation(
        "sample", "a" * 64, datetime(2026, 11, 8, tzinfo=timezone.utc), "archived_at"
    )


def test_terms_preserves_two_evidenced_dates_and_adjustment() -> None:
    frame = pd.DataFrame(
        [
            {
                "order_book_id": "10002752",
                "trading_date": "2021-01-15",
                "strike_price": 4.4,
                "contract_multiplier": 10000,
                "product_name": "510300P2103M04400",
            },
            {
                "order_book_id": "10002752",
                "trading_date": "2021-01-18",
                "strike_price": 4.343,
                "contract_multiplier": 10132,
                "product_name": "510300P2103A04400",
            },
        ]
    )
    rows = prepare_terms(frame, observation())
    assert len(rows) == 2
    assert [r["strike"] for r in rows] == [Decimal("4.4000"), Decimal("4.3430")]
    assert [r["multiplier"] for r in rows] == [Decimal("10000.0000"), Decimal("10132.0000")]
    assert {r["trading_day"].isoformat() for r in rows} == {"2021-01-15", "2021-01-18"}
    assert all(r["available_at"] is None for r in rows)


def test_terms_accepts_ieee_noise_but_not_real_extra_precision() -> None:
    base = {
        "order_book_id": "10000691",
        "trading_date": "2016-11-29",
        "strike_price": 2.3480000000000003,
        "contract_multiplier": 10220,
        "product_name": "510050C1612A02400",
    }
    assert prepare_terms(pd.DataFrame([base]), observation())[0]["strike"] == Decimal("2.3480")
    with pytest.raises(HistoryError, match="precision"):
        prepare_terms(pd.DataFrame([{**base, "strike_price": 2.34805}]), observation())


def test_terms_expansion_retains_independent_valid_dates_without_filling() -> None:
    row = {
        "order_book_id": "10002752",
        "trading_date": "2021-01-15",
        "strike_price": 4.4,
        "contract_multiplier": 10000,
        "product_name": "code",
    }
    valid, pending = prepare_term_candidates(
        pd.DataFrame(
            [
                row,
                {**row, "trading_date": "2021-01-18", "strike_price": None},
            ]
        ),
        observation(),
    )
    assert len(valid) == len(pending) == 1
    assert valid[0]["trading_day"] == date(2021, 1, 15)
    assert pending[0]["trading_day"] == date(2021, 1, 18)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), 0, -1])
def test_terms_rejects_missing_nonfinite_or_nonpositive(bad: object) -> None:
    with pytest.raises(HistoryError):
        prepare_terms(
            pd.DataFrame(
                [
                    {
                        "order_book_id": "1",
                        "trading_date": "2021-01-15",
                        "strike_price": bad,
                        "contract_multiplier": 10000,
                        "product_name": "code",
                    }
                ]
            ),
            observation(),
        )


def greek(**updates: object) -> dict[str, object]:
    return {
        "order_book_id": "LC2612C95000",
        "trading_date": "2026-11-06",
        "iv": 0.114,
        "delta": 0.043,
        "gamma": 0.00016,
        "vega": 454.4,
        "theta": -10297.120805886261,
        "rho": 11.19,
        **updates,
    }


def test_greek_overflow_is_pending_without_blocking_independent_row() -> None:
    rows, pending = prepare_greeks(pd.DataFrame([greek(), greek(order_book_id="other", theta=-3)]))
    assert len(rows) == 1 and rows[0]["rq_code"] == "other"
    assert len(pending) == 1 and pending[0]["field"] == "theta"
    assert pending[0]["raw_value"] == "-10297.120805886261"


@pytest.mark.parametrize("field,value", [("iv", None), ("gamma", float("inf")), ("delta", 2)])
def test_greek_invalid_values_remain_pending(field: str, value: object) -> None:
    rows, pending = prepare_greeks(pd.DataFrame([greek(theta=-3, **{field: value})]))
    assert not rows and pending


def test_duplicate_contract_day_is_rejected_even_if_equal() -> None:
    with pytest.raises(HistoryError, match="duplicate"):
        prepare_greeks(pd.DataFrame([greek(theta=-3), greek(theta=-3)]))


def test_observation_requires_aware_time_and_sha() -> None:
    with pytest.raises(HistoryError):
        Observation("sample", "a" * 64, datetime(2026, 11, 8), "archived_at")
    with pytest.raises(HistoryError):
        Observation("sample", "bad", datetime.now(timezone.utc), "response_completed_at")


def identity_fixture() -> tuple[dict, dict]:
    canonical = {
        "symbol": "10002752.SH",
        "exchange": "XSHG",
        "asset": "option",
        "list_date": date(2020, 12, 24),
        "option_list_date": date(2020, 12, 24),
        "delist_date": date(2021, 3, 24),
        "last_trade_date": date(2021, 3, 24),
        "maturity_date": date(2021, 3, 24),
        "option_type": "P",
        "exercise_style": "european",
        "strike": Decimal("4.343"),
        "multiplier": Decimal("10132"),
        "underlying_symbol": "510300.SH",
        "underlying_exchange": "XSHG",
        "trading_code": "latest",
    }
    reference = {
        "order_book_id": "10002752",
        "type": "Option",
        "exchange": "XSHG",
        "listed_date": "2020-12-24",
        "de_listed_date": "2021-03-24",
        "maturity_date": "2021-03-24",
        "option_type": "P",
        "exercise_type": "E",
        "strike_price": 4.343,
        "contract_multiplier": 10132,
        "underlying_order_book_id": "510300.XSHG",
    }
    return canonical, reference


def test_reference_match_checks_lifecycle_underlying_and_current_parameters() -> None:
    canonical, reference = identity_fixture()
    matched, pending = match_reference([canonical], pd.DataFrame([reference]))
    assert set(matched) == {"10002752"} and not pending
    for field, value in (
        ("de_listed_date", "2031-03-24"),
        ("underlying_order_book_id", "510050.XSHG"),
        ("exchange", "XSHE"),
        ("option_type", "C"),
        ("strike_price", 4.344),
    ):
        matched, pending = match_reference([canonical], pd.DataFrame([{**reference, field: value}]))
        assert not matched and pending


def test_reference_ambiguity_and_repeated_source_identity_never_choose_last() -> None:
    canonical, reference = identity_fixture()
    assert not match_reference([canonical, canonical], pd.DataFrame([reference]))[0]
    assert not match_reference([canonical], pd.DataFrame([reference, reference, reference]))[0]


class AuditConnection:
    def __init__(self, audits: list) -> None:
        self.audits = audits

    def execute(self, *_args: object) -> AuditConnection:
        return self

    def fetchall(self) -> list:
        return self.audits


def test_existing_greek_requires_method_provenance_even_when_values_equal() -> None:
    row = (42, date(2026, 11, 6), "ricequant", *([Decimal(0)] * 6))
    with pytest.raises(HistoryError, match="provenance"):
        verify_existing_greek_methods(AuditConnection([]), [row], "2026-11")  # type: ignore[arg-type]
    detail = {
        "key_masks": {"42": 1 << 5},
        "evidence": {"method": GREEK_METHOD},
        "units": GREEK_UNITS,
    }
    verify_existing_greek_methods(AuditConnection([(GREEKS_RULE, detail)]), [row], "2026-11")  # type: ignore[arg-type]
    wrong = {**detail, "evidence": {"method": {**GREEK_METHOD, "model": "last"}}}
    with pytest.raises(HistoryError, match="method"):
        verify_existing_greek_methods(AuditConnection([(GREEKS_RULE, wrong)]), [row], "2026-11")  # type: ignore[arg-type]


def test_month_key_mask_does_not_infer_adjacent_dates() -> None:
    row = (42, date(2026, 11, 7), "ricequant", *([Decimal(0)] * 6))
    detail = {
        "key_masks": {"42": 1 << 5},
        "evidence": {"method": GREEK_METHOD},
        "units": GREEK_UNITS,
    }
    with pytest.raises(HistoryError, match="provenance"):
        verify_existing_greek_methods(AuditConnection([(GREEKS_RULE, detail)]), [row], "2026-11")  # type: ignore[arg-type]


def test_legacy_seed_units_must_agree_with_fixed_policy() -> None:
    row = (42, date(2026, 11, 6), "ricequant", *([Decimal(0)] * 6))
    detail = {
        **GREEK_METHOD,
        "instrument_id": 42,
        "trading_day": "2026-11-06",
        "policy_sha256": SEED_POLICY_SHA256,
        "stored_values": dict.fromkeys(("iv", "delta", "gamma", "vega", "theta", "rho"), "0"),
        "units": {**GREEK_UNITS, "theta": "per day"},
    }
    with pytest.raises(HistoryError, match="method"):
        verify_existing_greek_methods(
            AuditConnection([(SEED_GREEKS_RULE, detail)]), [row], "2026-11"
        )  # type: ignore[arg-type]
