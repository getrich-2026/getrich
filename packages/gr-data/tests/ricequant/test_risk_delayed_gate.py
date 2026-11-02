"""四条件 IPO 延迟验收、官方交易日与 next manifest 严格哈希绑定。"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import numpy as np
import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_delayed_gate import (
    DelayedEvidenceError,
    VerifiedRiskObservation,
    VerifiedTradingCalendar,
    evaluate_delayed_day,
    file_sha256,
    ipo_first_day_conditions,
    monthly_summary,
)
from gr_data.common.ricequant_symbol_intervals import (
    APPROVED_HISTORY_SYMBOL_RULES_VERSION,
    HISTORY_SYMBOL_RULES_VERSION,
    symbol_rule_evidence,
)
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import parse_risk_options
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RqdatacClient
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import run_risk_raw


CURRENT = "2010-01-08"
NEXT = "2010-01-11"


def setup(
    tmp_path,
    *,
    absent_piece="specific_return",
    listed=CURRENT,
    not_recovered=False,
    following=NEXT,
    model="v1",
    approved=False,
):
    codes = [f"{index:06d}.XSHG" for index in range(1, 7)]
    absent = set(codes[:4])
    metadata = {
        "instruments": [
            {
                "instrument_id": iid,
                "symbol": code.replace(".XSHG", ".SH"),
                "exchange": "XSHG",
                "list_date": listed if code in absent else "2000-01-01",
                "delist_date": None,
                "status": "L",
            }
            for iid, code in enumerate(codes, 1)
        ],
        "aliases": [],
    }
    reference = {
        "sdk_mapping": dict(zip(codes, codes, strict=True)),
        "instruments": [
            {"order_book_id": code, "listed_date": row["list_date"], "de_listed_date": "0000-00-00"}
            for code, row in zip(codes, metadata["instruments"], strict=True)
        ],
    }
    provider = build_universe_provider(
        metadata,
        reference,
        universe_policy="listed_cn_a_v2",
        symbol_rules=symbol_rule_evidence(
            APPROVED_HISTORY_SYMBOL_RULES_VERSION if approved else HISTORY_SYMBOL_RULES_VERSION
        ),
    )
    options = parse_risk_options(
        {
            "selected": True,
            "permission_confirmed": True,
            "model": model,
            "industry_mapping": "sws_2021",
            "start_date": CURRENT,
            "end_date": following,
            "universe_policy": "listed_cn_a_v2",
            "purpose": "validation",
            "source_units": {
                "factor_return": "dec_daily",
                "specific_return": "dec_daily",
                "covariance": "dec2_annual",
                "specific_risk": "dec_annual",
            },
            "units_evidence": "synthetic-test-only",
        },
        historical_probe=not approved,
        approved_history_raw=approved,
    )

    class Client:
        def get_quota(self):
            return {"bytes_limit": 10000000, "bytes_used": 0}

        def get_trading_dates(self, start, end):
            return list(pd.bdate_range(start, end).date)

        def risk_piece(self, piece, day, batch, *, model, industry_mapping):
            factors = sorted(STYLE_FACTORS[model] | {"comovement", "银行"})
            if piece == "factor_return":
                return pd.DataFrame(
                    [[0.001] * len(factors)], index=pd.DatetimeIndex([day]), columns=factors
                )
            if piece == "covariance":
                return pd.DataFrame(np.eye(len(factors)) * 0.01, index=factors, columns=factors)
            if (day == CURRENT and piece == absent_piece) or (
                day == following and not_recovered and piece == "specific_return"
            ):
                batch = [code for code in batch if code not in absent]
            if piece == "exposure":
                frame = pd.DataFrame(
                    0.1,
                    index=pd.MultiIndex.from_product(
                        [batch, [pd.Timestamp(day)]], names=["order_book_id", "date"]
                    ),
                    columns=factors,
                )
                frame["comovement"] = frame["银行"] = 1.0
                return frame
            return pd.DataFrame(
                [[0.2 if piece == "specific_risk" else 0.001] * len(batch)],
                index=pd.DatetimeIndex([day]),
                columns=batch,
            )

    ctx = RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0})
    for value in (CURRENT, following):
        opts = replace(
            options, start_date=pd.Timestamp(value).date(), end_date=pd.Timestamp(value).date()
        )
        run_risk_raw(
            cast(RqdatacClient, Client()),
            ctx,
            opts,
            RicequantImportOptions({}),
            mode="init",
            universe_provider=provider,
        )
    root = ctx.paths.ricequant_variant("rq_risk_model", "v2", options.variant_id)
    paths = [next((root / value).glob("*/manifest.json")) for value in (CURRENT, following)]
    observations = [
        VerifiedRiskObservation.load(path, file_sha256(path), options) for path in paths
    ]
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "market": "cn",
                "source": "synthetic-complete-calendar",
                "query_start": CURRENT,
                "query_end": following,
                "complete_query": True,
                "trading_days": [CURRENT, NEXT]
                if following == NEXT
                else [CURRENT, NEXT, following],
            }
        )
    )
    calendar = VerifiedTradingCalendar.load(calendar_path, file_sha256(calendar_path))
    return observations[0], observations[1], calendar


@pytest.mark.parametrize("approved", [False, True])
def test_four_ipo_first_day_missing_returns_are_allowed_without_count_cap(tmp_path, approved):
    current, next_day, calendar = setup(tmp_path, approved=approved)
    result = evaluate_delayed_day(current, calendar=calendar, next_observation=next_day)
    assert result["status"] == "accepted" and len(result["missing"]) == 4
    assert result["policy"]["uses_count_cap"] is False
    assert all(row["next_included"] for row in result["missing"])
    assert result["next_observation"]["file_sha256"] == file_sha256(next_day.path)
    assert all(
        row["source_record_sha256"] and row["next_record_sha256"] for row in result["missing"]
    )


@pytest.mark.parametrize("approved", [False, True])
def test_missing_exposure_is_rejected_even_on_listing_day(tmp_path, approved):
    current, next_day, calendar = setup(tmp_path, approved=approved, absent_piece="exposure")
    result = evaluate_delayed_day(current, calendar=calendar, next_observation=next_day)
    assert result["status"] == "rejected"
    assert all(row["reason"] == "exposure_missing" for row in result["missing"])


@pytest.mark.parametrize("approved", [False, True])
def test_next_trading_day_not_recovered_is_rejected(tmp_path, approved):
    current, next_day, calendar = setup(tmp_path, approved=approved, not_recovered=True)
    result = evaluate_delayed_day(current, calendar=calendar, next_observation=next_day)
    assert result["status"] == "rejected" and result["reject_reasons"]
    assert result["next_observation"]["file_sha256"] == next_day.file_sha256


@pytest.mark.parametrize("approved", [False, True])
def test_missing_on_non_listing_day_is_rejected(tmp_path, approved):
    current, next_day, calendar = setup(tmp_path, approved=approved, listed="2010-01-07")
    result = evaluate_delayed_day(current, calendar=calendar, next_observation=next_day)
    assert result["status"] == "rejected"
    assert all(row["reason"] == "non_listing_day_missing" for row in result["missing"])


@pytest.mark.parametrize("approved", [False, True])
def test_next_day_absent_is_pending_and_weekend_is_not_a_trading_day(tmp_path, approved):
    current, next_day, calendar = setup(tmp_path, approved=approved)
    result = evaluate_delayed_day(current, calendar=calendar)
    assert result["status"] == "pending" and result["expected_next_trading_day"] == NEXT
    assert result["expected_next_trading_day"] != "2010-01-09"
    assert evaluate_delayed_day(current)["status"] == "pending"


@pytest.mark.parametrize("approved", [False, True])
def test_wrong_next_day_is_rejected(tmp_path, approved):
    current, wrong, calendar = setup(tmp_path, approved=approved, following="2010-01-12")
    result = evaluate_delayed_day(current, calendar=calendar, next_observation=wrong)
    assert result["status"] == "rejected" and result["reject_reasons"] == [
        "next_observation_day_or_variant_differs"
    ]


@pytest.mark.parametrize("approved", [False, True])
def test_manifest_sha_and_postload_drift_are_rejected(tmp_path, approved):
    current, next_day, calendar = setup(tmp_path, approved=approved)
    with pytest.raises(DelayedEvidenceError, match="SHA-256 differs"):
        VerifiedRiskObservation.load(next_day.path, "a" * 64, next_day.options)
    next_day.path.write_text(next_day.path.read_text() + " ")
    with pytest.raises(DelayedEvidenceError, match="SHA-256 differs"):
        evaluate_delayed_day(current, calendar=calendar, next_observation=next_day)


@pytest.mark.parametrize("approved", [False, True])
def test_incomplete_or_wrong_calendar_evidence_is_rejected(tmp_path, approved):
    current, next_day, calendar = setup(tmp_path, approved=approved)
    payload = dict(calendar.payload)
    payload["complete_query"] = False
    path = tmp_path / "sparse-calendar.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(DelayedEvidenceError, match="complete Chinese-market"):
        VerifiedTradingCalendar.load(path, file_sha256(path))
    with pytest.raises(DelayedEvidenceError, match="SHA-256 differs"):
        VerifiedTradingCalendar.load(calendar.path, "a" * 64)


def test_month_summary_counts_by_reason_and_keeps_per_security_proofs(tmp_path):
    current, next_day, calendar = setup(tmp_path)
    result = evaluate_delayed_day(current, calendar=calendar, next_observation=next_day)
    summary = monthly_summary([result, result])[0]
    assert summary["model_days_by_status"] == {"accepted": 1}
    assert summary["reason_metrics"]["ipo_next_trading_day_recovered"] == {
        "missing_security_days": 4,
        "unique_missing_instruments": 4,
    }
    assert len(summary["per_security_evidence"]) == 4
    assert summary["observation_bindings"][0]["next"]["file_sha256"] == next_day.file_sha256


def test_shared_ipo_predicate_is_exact_and_does_not_depend_on_next_day():
    good = {"exposure": True, "specific_return": False, "specific_risk": True}
    assert ipo_first_day_conditions(CURRENT, CURRENT, good)
    assert not ipo_first_day_conditions(CURRENT, "2010-01-07", good)
    assert not ipo_first_day_conditions(CURRENT, CURRENT, {**good, "exposure": False})
    assert not ipo_first_day_conditions(CURRENT, CURRENT, {**good, "exposure": 1})
