"""用户批准的两个身份特例：不推广、不改旧哈希、不伪造边界数据。"""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import numpy as np
import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_delayed_gate import (
    APPROVED_POLICY_SHA256,
    VerifiedRiskObservation,
    evaluate_delayed_day,
    file_sha256,
    monthly_summary,
)
from gr_data.common.ricequant_specs import ContractViolationError, RqConfigurationError
from gr_data.common.ricequant_symbol_intervals import (
    APPROVED_HISTORY_SYMBOL_RULES_VERSION as V3,
    approved_boundary_coverage,
    approved_delist_boundary_exception,
    symbol_rule_evidence,
    symbol_rule_hash,
)
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant import RicequantImportOptions
from gr_data.config.ricequant_risk import parse_risk_options
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RqdatacClient
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import run_risk_raw


def options_data(day="2010-01-04", model="v1", purpose="validation"):
    return {
        "selected": True,
        "permission_confirmed": True,
        "model": model,
        "industry_mapping": "sws_2021",
        "start_date": day,
        "end_date": day,
        "universe_policy": "listed_cn_a_v2",
        "purpose": purpose,
        "source_units": {
            "factor_return": "dec_daily",
            "specific_return": "dec_daily",
            "covariance": "dec2_annual",
            "specific_risk": "dec_annual",
        },
        "units_evidence": "synthetic-test-only",
    }


@pytest.fixture
def inputs():
    metadata = {
        "instruments": [
            dict(
                instrument_id=11,
                symbol="601607.SH",
                exchange="XSHG",
                list_date="1994-03-24",
                delist_date=None,
                status="active",
            ),
            dict(
                instrument_id=22,
                symbol="600680.SH",
                exchange="XSHG",
                list_date="1993-10-18",
                delist_date="2019-05-23",
                status="delisted",
            ),
            dict(
                instrument_id=33,
                symbol="600000.SH",
                exchange="XSHG",
                list_date="1999-11-10",
                delist_date=None,
                status="active",
            ),
        ],
        "aliases": [dict(source="tushare", source_symbol="600849.SH", instrument_id=11)],
    }
    reference = {
        "instruments": [
            dict(
                order_book_id="601607.XSHG", listed_date="1994-03-24", de_listed_date="0000-00-00"
            ),
            dict(
                order_book_id="600680.XSHG", listed_date="1993-10-18", de_listed_date="2019-05-24"
            ),
            dict(
                order_book_id="600000.XSHG", listed_date="1999-11-10", de_listed_date="0000-00-00"
            ),
        ],
        "sdk_mapping": {
            "601607.XSHG": "601607.XSHG",
            "600849.XSHG": None,
            "600680.XSHG": "600680.XSHG",
            "600000.XSHG": "600000.XSHG",
        },
    }
    return metadata, reference


def provider(inputs, version=V3):
    return build_universe_provider(
        *inputs, universe_policy="listed_cn_a_v2", symbol_rules=symbol_rule_evidence(version)
    )


def test_old_rule_hashes_and_legal_cutover_unchanged():
    assert (
        symbol_rule_hash("cn_stock_code_intervals_v1")
        == "2df9bb3dc7e44eef43297c107f348a34c857bb1faffd7ca3a789ad082feb2d19"
    )
    assert (
        symbol_rule_hash("cn_stock_code_intervals_v2")
        == "61f039ead186760ce072ad0771db74d21247fc7ec01795553c7bcbe50babd69e"
    )
    assert (
        symbol_rule_evidence(V3)["rules"]
        == symbol_rule_evidence("cn_stock_code_intervals_v2")["rules"]
    )
    assert symbol_rule_hash(V3) != symbol_rule_hash("cn_stock_code_intervals_v2")


@pytest.mark.parametrize(
    "day,legal",
    [
        ("2010-01-04", "600849.SH"),
        ("2010-02-04", "600849.SH"),
        ("2010-03-04", "600849.SH"),
        ("2010-03-05", "601607.SH"),
        ("2010-03-09", "601607.SH"),
    ],
)
def test_shanghai_pharma_legal_code_and_request_code_are_separate(inputs, day, legal):
    row = provider(inputs)(day)["candidates"][0]
    assert row["request_code"] == "601607.XSHG" and row["status"] is None
    assert row["evidence"]["symbol_interval"]["selected_source_symbol"] == legal
    assert row["evidence"]["symbol_interval"]["effective_date"] == "2010-03-05"
    override = row["evidence"]["provider_request_override"]
    assert (
        override["probe_receipt_sha256"]
        == "2407bf19a5bb63ea705b2fb35ca088e04f3c70e50652af016edd7ce88f000f50"
    )
    assert (
        override["announcement_sha256"]
        == "f51fea0d6a996ba4c8b9cae6e7551358460789933edf6278702cdf772d6be5ac"
    )


def test_old_v2_does_not_gain_new_identity_permission(inputs):
    rows = provider(inputs, "cn_stock_code_intervals_v2")("2010-01-04")["candidates"]
    assert all(row["status"] == "universe_boundary_unknown" for row in rows[:2])
    assert all(row["request_code"] is None for row in rows[:2])
    assert all("provider_request_override" not in row["evidence"] for row in rows)


@pytest.mark.parametrize("defect", ["old_reused", "missing_alias", "sdk_other_security"])
def test_pharma_same_identity_checks_not_relaxed(inputs, defect):
    metadata, reference = inputs
    if defect == "old_reused":
        metadata["instruments"].append(
            dict(
                instrument_id=44,
                symbol="600849.SH",
                exchange="XSHG",
                list_date="2000-01-01",
                delist_date=None,
                status="active",
            )
        )
    elif defect == "missing_alias":
        metadata["aliases"].clear()
    else:
        reference["sdk_mapping"]["601607.XSHG"] = "600000.XSHG"
    with pytest.raises(ContractViolationError):
        provider(inputs)


@pytest.mark.parametrize("day", ["2010-01-04", "2011-04-28", "2018-12-31", "2019-05-22"])
def test_potevio_earlier_days_are_not_all_history_unknown(inputs, day):
    row = provider(inputs)(day)["candidates"][1]
    assert row["request_code"] == "600680.XSHG" and row["status"] is None


def test_potevio_only_ambiguous_day_is_candidate_without_request(inputs):
    row = provider(inputs)("2019-05-23")["candidates"][1]
    assert row["status"] == "universe_boundary_unknown" and row["request_code"] is None
    assert row["evidence"]["delist_boundary_exception"] == approved_delist_boundary_exception()
    for day in ("2019-05-24", "2023-12-29"):
        assert "600680.SH" not in {
            row["canonical_symbol"] for row in provider(inputs)(day)["candidates"]
        }


@pytest.mark.parametrize("defect", ["other_symbol", "wrong_list", "wrong_ts_end", "wrong_rq_end"])
def test_potevio_exception_does_not_expand_to_other_dates_or_stocks(inputs, defect):
    metadata, reference = inputs
    if defect == "other_symbol":
        metadata["instruments"][1]["symbol"] = "600681.SH"
        reference["instruments"][1]["order_book_id"] = "600681.XSHG"
        reference["sdk_mapping"]["600681.XSHG"] = "600681.XSHG"
    elif defect == "wrong_list":
        metadata["instruments"][1]["list_date"] = "1993-10-19"
    elif defect == "wrong_ts_end":
        metadata["instruments"][1]["delist_date"] = "2019-05-22"
    else:
        reference["instruments"][1]["de_listed_date"] = "2019-05-27"
    for day in ("2011-04-28", "2019-05-23"):
        row = provider(inputs)(day)["candidates"][1]
        assert row["status"] == "universe_boundary_unknown" and row["request_code"] is None
        assert "delist_boundary_exception" not in row["evidence"]


def test_explicit_approved_raw_entry_does_not_expand_default_cli():
    data = options_data()
    with pytest.raises(RqConfigurationError):
        parse_risk_options(data)
    approved = parse_risk_options(data, approved_history_raw=True)
    probe = parse_risk_options(data, historical_probe=True)
    assert approved.symbol_rules_version == V3
    assert approved.identity["approved_history_raw"] == "pre2024_v3"
    assert approved.variant_id != probe.variant_id
    prod = parse_risk_options({**data, "purpose": "production"}, approved_history_raw=True)
    assert prod.variant_id != approved.variant_id
    with pytest.raises(RqConfigurationError):
        parse_risk_options(data, approved_history_raw=True, historical_probe=True)
    with pytest.raises(RqConfigurationError):
        parse_risk_options({**data, "approved_history_raw": True})


@pytest.mark.parametrize(
    "model,day,allowed",
    [
        ("v1", "2010-01-04", True),
        ("v1", "2009-12-31", False),
        ("v2", "2011-04-27", False),
        ("v2", "2011-04-28", True),
        ("v2trd", "2011-04-28", True),
        ("v1", "2024-01-02", False),
    ],
)
def test_explicit_history_model_date_scope(model, day, allowed):
    if allowed:
        assert parse_risk_options(options_data(day, model), approved_history_raw=True)
    else:
        with pytest.raises(RqConfigurationError):
            parse_risk_options(options_data(day, model), approved_history_raw=True)


class FakeRiskClient:
    def __init__(self):
        self.requests = []

    def get_quota(self):
        return {"bytes_limit": 10000000, "bytes_used": 0}

    def get_trading_dates(self, start, end):
        return list(pd.bdate_range(start, end).date)

    def risk_piece(self, piece, day, batch, *, model, industry_mapping):
        self.requests.append((piece, day, tuple(batch)))
        factors = sorted(STYLE_FACTORS[model] | {"comovement", "银行"})
        if piece == "factor_return":
            return pd.DataFrame(
                [[0.001] * len(factors)], index=pd.DatetimeIndex([day]), columns=factors
            )
        if piece == "covariance":
            return pd.DataFrame(np.eye(len(factors)) * 0.01, index=factors, columns=factors)
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


def observe(tmp_path, inputs, *, day="2019-05-23", purpose="validation", capture=None):
    opts = parse_risk_options(options_data(day, purpose=purpose), approved_history_raw=True)
    client = FakeRiskClient()
    ctx = RawContext(RawPaths(tmp_path), {"sleep_between_requests_sec": 0})
    run_risk_raw(
        cast(RqdatacClient, client),
        ctx,
        opts,
        RicequantImportOptions({}),
        mode="init",
        universe_provider=provider(inputs),
        capture_callback=capture,
    )
    root = ctx.paths.ricequant_variant("rq_risk_model", "v2", opts.variant_id)
    path = next((root / day).glob("*/manifest.json"))
    return VerifiedRiskObservation.load(path, file_sha256(path), opts), client


def test_approved_boundary_gate_accepts_without_request_or_next_day(tmp_path, inputs):
    current, client = observe(tmp_path, inputs)
    result = evaluate_delayed_day(current)
    assert result["status"] == "accepted" and result["policy_sha256"] == APPROVED_POLICY_SHA256
    assert result["candidate"] == 3 and result["complete"] == 2
    assert len(result["missing"]) == 1
    missing = result["missing"][0]
    assert missing["reason"] == "approved_delist_boundary_uncertainty"
    assert missing["pieces"] == dict.fromkeys(
        ("exposure", "specific_return", "specific_risk"), False
    )
    assert missing["identity_exception_evidence"] == approved_delist_boundary_exception()
    assert all("600680.XSHG" not in batch for _, _, batch in client.requests)
    assert (
        monthly_summary([result])[0]["reason_metrics"][missing["reason"]]["missing_security_days"]
        == 1
    )
    # 旧 raw 复用路径仍运行相同 gate，但不再请求五件套。
    again, repeated = observe(tmp_path, inputs, capture=lambda manifest: None)
    assert evaluate_delayed_day(again)["status"] == "accepted"
    assert repeated.requests == []


def test_whole_interface_empty_still_rejected_with_boundary_exception(tmp_path, inputs):
    current, _ = observe(tmp_path, inputs)

    class EmptyInterfaceObservation(VerifiedRiskObservation):
        def verify(self):
            pass

    simulated = EmptyInterfaceObservation(
        current.path,
        current.file_sha256,
        current.manifest,
        current.options,
        {**current.interface_nonempty, "specific_risk": False},
    )
    assert evaluate_delayed_day(simulated)["reject_reasons"] == ["whole_interface_empty"]


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_day",
        "wrong_hash",
        "old_version",
        "evidence_missing",
        "other_symbol",
        "request_present",
    ],
)
def test_boundary_gate_rejects_imprecise_exception_proof(tmp_path, inputs, defect):
    current, _ = observe(tmp_path, inputs)
    row = deepcopy(current.manifest["coverage"][1])
    identity = dict(current.manifest["identity"])
    day = current.manifest["day"]
    assert approved_boundary_coverage(row, day, identity)
    if defect == "wrong_day":
        day = "2019-05-22"
    elif defect == "wrong_hash":
        identity["symbol_rules_hash"] = "a" * 64
    elif defect == "old_version":
        identity["symbol_rules_version"] = "cn_stock_code_intervals_v2"
    elif defect == "evidence_missing":
        row["evidence"].pop("delist_boundary_exception")
    elif defect == "other_symbol":
        row["canonical_symbol"] = "600681.SH"
    else:
        row["request_code"] = "600680.XSHG"
    assert not approved_boundary_coverage(row, day, identity)


def test_nonexception_identity_unknown_remains_rejected(tmp_path, inputs):
    inputs[1]["instruments"][1]["de_listed_date"] = "2019-05-27"
    current, _ = observe(tmp_path, inputs)
    result = evaluate_delayed_day(current)
    assert result["status"] == "rejected"
    assert result["missing"][0]["reason"] == "identity_universe_boundary_unknown"


def test_approved_history_production_still_requires_explicit_capture(tmp_path, inputs):
    with pytest.raises(ValueError, match="capture callback"):
        observe(tmp_path, inputs, purpose="production")


@pytest.mark.parametrize("purpose", ["validation", "production"])
def test_final_next_day_helper_has_same_variant_and_narrow_explicit_scope(purpose):
    last = parse_risk_options(
        options_data("2023-12-29", purpose=purpose), approved_history_raw=True
    )
    helper_data = options_data("2024-01-02", purpose=purpose)
    helper = parse_risk_options(
        helper_data, approved_history_raw=True, approved_history_lookahead=True
    )
    assert helper.variant_id == last.variant_id
    assert "approved_history_lookahead" not in helper.identity
    with pytest.raises(RqConfigurationError):
        parse_risk_options(helper_data, approved_history_raw=True)
    with pytest.raises(RqConfigurationError):
        parse_risk_options(helper_data, approved_history_lookahead=True)
    for wrong in ("2023-12-29", "2024-01-03"):
        with pytest.raises(RqConfigurationError):
            parse_risk_options(
                options_data(wrong), approved_history_raw=True, approved_history_lookahead=True
            )
    with pytest.raises(RqConfigurationError):
        parse_risk_options(
            {**helper_data, "start_date": "2023-12-29"},
            approved_history_raw=True,
            approved_history_lookahead=True,
        )
