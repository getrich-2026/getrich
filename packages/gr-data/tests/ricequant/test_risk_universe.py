"""日期名单、身份别名与 SDK 过滤的离线回归。"""

from __future__ import annotations

from copy import deepcopy

import pytest
from gr_data.common.ricequant_specs import (
    ContractViolationError,
    RqConfigurationError,
    semantic_hash,
)
from gr_data.common.ricequant_universe import build_universe_provider, reference_input_codes
from gr_data.config.ricequant_risk import parse_risk_options


@pytest.fixture
def metadata():
    return {
        "instruments": [
            {
                "instrument_id": 1,
                "symbol": "302132.SZ",
                "exchange": "XSHE",
                "list_date": "2010-08-27",
                "delist_date": None,
                "status": "active",
            },
            {
                "instrument_id": 2,
                "symbol": "600000.SH",
                "exchange": "XSHG",
                "list_date": "2024-01-03",
                "delist_date": "2024-01-05",
                "status": "delisted",
            },
        ],
        "aliases": [
            {"source": "tushare", "source_symbol": "300114.SZ", "instrument_id": 1},
            {"source": "tushare", "source_symbol": "302132.SZ", "instrument_id": 1},
        ],
    }


@pytest.fixture
def reference():
    return {
        "instruments": [
            {
                "order_book_id": "300114.XSHE",
                "listed_date": "2010-08-27",
                "de_listed_date": "0000-00-00",
            },
            {
                "order_book_id": "600000.XSHG",
                "listed_date": "2024-01-03",
                "de_listed_date": "2024-01-05",
            },
        ],
        "sdk_mapping": {
            "300114.XSHE": "300114.XSHE",
            "302132.XSHE": None,
            "600000.XSHG": "600000.XSHG",
        },
        "sdk_version": "fixture",
    }


def test_dynamic_boundaries_include_listing_exclude_delisting(metadata, reference):
    provider = build_universe_provider(metadata, reference)
    assert [r["instrument_id"] for r in provider("2024-01-02")["candidates"]] == [1]
    assert [r["instrument_id"] for r in provider("2024-01-03")["candidates"]] == [1, 2]
    assert [r["instrument_id"] for r in provider("2024-01-04")["candidates"]] == [1, 2]
    assert [r["instrument_id"] for r in provider("2024-01-05")["candidates"]] == [1]


def test_old_alias_survives_canonical_sdk_filter(metadata, reference):
    row = build_universe_provider(metadata, reference)("2024-01-03")["candidates"][0]
    assert row["request_code"] == "300114.XSHE" and row["instrument_id"] == 1
    assert row["canonical_symbol"] == "302132.SZ"
    assert row["input_codes"] == ["300114.XSHE", "302132.XSHE"]
    assert row["status"] is None


def test_sdk_filtered_is_not_provider_missing(metadata, reference):
    reference["sdk_mapping"]["300114.XSHE"] = None
    row = build_universe_provider(metadata, reference)("2024-01-03")["candidates"][0]
    assert row["status"] == "sdk_filtered" and row["request_code"] is None


@pytest.mark.parametrize("field,value", [("list_date", None), ("delist_date", "2024-01-06")])
def test_conflicting_or_missing_boundaries_retained(metadata, reference, field, value):
    metadata["instruments"][1][field] = value
    rows = build_universe_provider(metadata, reference)("2024-01-05")["candidates"]
    assert rows[1]["status"] == "universe_boundary_unknown"
    assert rows[1]["request_code"] is None


def test_missing_reference_keeps_canonical_candidate(metadata, reference):
    reference["instruments"].pop()
    rows = build_universe_provider(metadata, reference)("2024-01-05")["candidates"]
    assert rows[1]["status"] == "universe_boundary_unknown"


def test_unmapped_reference_is_preserved(metadata, reference):
    reference["instruments"].append(
        {
            "order_book_id": "000001.XSHE",
            "listed_date": "1991-04-03",
            "de_listed_date": "0000-00-00",
        }
    )
    result = build_universe_provider(metadata, reference)("2024-01-03")
    assert result["unresolved"][0]["status"] == "unresolved_identity"
    assert result["unresolved"][0]["evidence"]["order_book_id"] == "000001.XSHE"


def test_sdk_conversion_connects_reference_identity(metadata, reference):
    reference["instruments"][0]["order_book_id"] = "300999.XSHE"
    reference["sdk_mapping"]["300114.XSHE"] = "300999.XSHE"
    result = build_universe_provider(metadata, reference)("2024-01-03")
    assert result["unresolved"] == []
    assert result["candidates"][0]["request_code"] == "300999.XSHE"


@pytest.mark.parametrize("case", ["symbol_map", "sdk", "duplicate_ref"])
def test_identity_conflicts_rejected(metadata, reference, case):
    if case == "symbol_map":
        metadata["aliases"].append(
            {"source": "ricequant", "source_symbol": "300114.XSHE", "instrument_id": 2}
        )
    elif case == "sdk":
        reference["sdk_mapping"]["600000.XSHG"] = "300114.XSHE"
    else:
        reference["instruments"].append(deepcopy(reference["instruments"][0]))
    with pytest.raises(ContractViolationError):
        build_universe_provider(metadata, reference)


def test_freeze_hash_and_return_values_are_immutable(metadata, reference):
    provider = build_universe_provider(metadata, reference)
    result = provider("2024-01-03")
    expected = result["metadata_hash"]
    metadata["instruments"].clear()
    reference["instruments"].clear()
    result["candidates"][0]["evidence"]["canonical"]["symbol"] = "changed"
    again = provider("2024-01-03")
    assert again["metadata_hash"] == expected
    assert again["candidates"][0]["canonical_symbol"] == "302132.SZ"


def test_reference_inputs_include_historical_alias(metadata):
    assert reference_input_codes(metadata) == ["300114.XSHE", "302132.XSHE", "600000.XSHG"]


def test_common_rules_are_not_repeated_in_stock_evidence(metadata, reference):
    result = build_universe_provider(metadata, reference)("2024-01-02")
    assert result["reference"]["alias_selection_rule"] == "canonical_preferred_if_multiple_accepted"
    assert all(
        set(row["evidence"]) <= {"canonical", "supplier", "sdk_mapping", "reason"}
        for row in result["candidates"]
    )


def options_data():
    return dict(
        selected=True,
        permission_confirmed=True,
        model="v1",
        industry_mapping="sws_2021",
        start_date="2024-01-02",
        end_date="2024-01-03",
        order_book_ids=["000001.XSHE"],
        source_units=dict(
            factor_return="dec_daily",
            specific_return="dec_daily",
            covariance="dec2_annual",
            specific_risk="dec_annual",
        ),
        units_evidence="fixture",
    )


def test_fixed_identity_is_backward_compatible():
    opts = parse_risk_options(options_data())
    expected = dict(
        contract="rq_risk_model_v1",
        model="v1",
        industry_mapping="sws_2021",
        horizon="daily",
        order_book_ids=["000001.XSHE"],
        source_units=options_data()["source_units"],
        units_evidence="fixture",
        universe="whole_market",
        method="implicit",
    )
    assert opts.identity == expected and opts.variant_id == semantic_hash(expected)
    assert opts.contract_version == "v1"


def test_dynamic_identity_is_explicit_and_date_independent():
    data = options_data()
    data.pop("order_book_ids")
    data["universe_policy"] = "listed_cn_a_v1"
    opts = parse_risk_options(data)
    assert opts.contract_version == "v2" and opts.order_book_ids == ()
    assert opts.identity["purpose"] == "validation"
    assert opts.identity["mapping_version"] == "alias_v1"
    assert "order_book_ids" not in opts.identity
    data["start_date"] = "2024-01-03"
    assert parse_risk_options(data).variant_id == opts.variant_id


@pytest.mark.parametrize(
    "bad",
    [
        {"order_book_ids": []},
        {"start_date": "2023-12-29"},
        {"purpose": "production"},
        {"universe_policy": "current"},
    ],
)
def test_dynamic_invalid_scope_refused(bad):
    data = options_data()
    data.pop("order_book_ids")
    data["universe_policy"] = "listed_cn_a_v1"
    data.update(bad)
    with pytest.raises(RqConfigurationError):
        parse_risk_options(data)


@pytest.mark.parametrize(
    "symbol,obid,exchange",
    [("200001.SZ", "200001.XSHE", "XSHE"), ("900901.SH", "900901.XSHG", "XSHG")],
)
def test_b_shares_excluded_with_receipt(metadata, reference, symbol, obid, exchange):
    metadata["instruments"].append(
        dict(
            instrument_id=3,
            symbol=symbol,
            exchange=exchange,
            list_date="1992-01-01",
            delist_date=None,
            status="active",
        )
    )
    reference["instruments"].append(
        dict(order_book_id=obid, listed_date="1992-01-01", de_listed_date="0000-00-00")
    )
    reference["sdk_mapping"][obid] = obid
    result = build_universe_provider(metadata, reference)("2024-01-03")
    assert [r["instrument_id"] for r in result["candidates"]] == [1, 2]
    assert not result["unresolved"]
    assert len(result["reference"]["excluded_b_shares"]["canonical"]) == 1
    assert len(result["reference"]["excluded_b_shares"]["supplier"]) == 1
    assert obid not in reference_input_codes(metadata)


def test_known_future_or_past_does_not_enter_denominator_on_boundary_difference(
    metadata, reference
):
    metadata["instruments"][1]["list_date"] = "2024-01-04"
    metadata["instruments"][1]["delist_date"] = "2024-01-06"
    provider = build_universe_provider(metadata, reference)
    assert [r["instrument_id"] for r in provider("2024-01-02")["candidates"]] == [1]
    assert [r["instrument_id"] for r in provider("2024-01-07")["candidates"]] == [1]
    assert provider("2024-01-03")["candidates"][1]["status"] == "universe_boundary_unknown"


def test_client_reference_executes_sdk_conversion_without_network(monkeypatch):
    import pandas as pd
    import rqdatac.services.basic as basic
    from gr_data.raw.ricequant.client import RqdatacClient

    class SDK:
        __version__ = "fixture"

        def all_instruments(self, **kwargs):
            assert kwargs == {"type": "CS", "market": "cn"}
            return pd.DataFrame(
                [
                    dict(
                        order_book_id="300114.XSHE",
                        listed_date="2010-08-27",
                        de_listed_date="0000-00-00",
                        secret_unused="not-preserved",
                    )
                ]
            )

    # 调用真实 ensure_order_book_ids，只替换其网络映射依赖。
    monkeypatch.setattr(
        basic,
        "_all_obid_to_type",
        lambda market: {"300114.XSHE": ("CS", "300114.XSHE"), "302132.XSHE": ("CS", "300114.XSHE")},
    )
    client = RqdatacClient()
    client._rq = SDK()
    guards = []
    result = client.risk_reference(
        ["302132.XSHE", "000000.XSHE"], quota_guard=lambda: guards.append(True)
    )
    assert len(guards) == 2
    assert result["sdk_mapping"] == {
        "000000.XSHE": None,
        "300114.XSHE": "300114.XSHE",
        "302132.XSHE": "300114.XSHE",
    }
    assert "secret_unused" not in result["instruments"][0]


def test_init_banner_is_suppressed(capsys):
    from gr_data.raw.ricequant.client import RqdatacClient

    def init():
        print("account-banner")
        return 3

    assert RqdatacClient._quiet_init(init) == 3
    assert capsys.readouterr().out == ""


def test_reference_date_serialization_preserves_unknown():
    from datetime import date

    import pandas as pd
    from gr_data.raw.ricequant.client import RqdatacClient

    assert RqdatacClient._reference_date(date(2024, 1, 2)) == "2024-01-02"
    assert RqdatacClient._reference_date(pd.Timestamp("2024-01-02")) == "2024-01-02"
    assert RqdatacClient._reference_date(pd.NaT) is None
    assert RqdatacClient._reference_date("0000-00-00") == "0000-00-00"


@pytest.fixture
def legacy_code(metadata):
    row = dict(
        instrument_id=33510,
        symbol="T600018.SH",
        exchange="XSHG",
        list_date="2000-07-19",
        delist_date="2006-10-20",
        status="delisted",
    )
    metadata["instruments"].append(row)
    metadata["aliases"].append(
        dict(source="tushare", source_symbol="T600018.SH", instrument_id=33510)
    )
    return row


def test_legacy_nonstandard_code_outside_known_dates_excluded(metadata, reference, legacy_code):
    provider = build_universe_provider(metadata, reference)
    for day in ("1999-12-31", "2006-10-21", "2026-10-22"):
        assert 33510 not in {row["instrument_id"] for row in provider(day)["candidates"]}
    assert "T600018.SH" not in reference_input_codes(metadata)
    assert "600018.XSHG" not in reference_input_codes(metadata)


@pytest.mark.parametrize("day", ["2000-07-19", "2004-01-02", "2006-10-20"])
def test_legacy_nonstandard_code_possible_active_keeps_identity_without_request(
    metadata, reference, legacy_code, day
):
    result = build_universe_provider(metadata, reference)(day)
    row = next(r for r in result["candidates"] if r["instrument_id"] == 33510)
    assert row["canonical_symbol"] == "T600018.SH"
    assert row["input_codes"] == ["T600018.SH"]
    assert row["status"] == "unmapped_symbol" and row["request_code"] is None
    assert row["evidence"]["canonical"] == legacy_code
    assert row["evidence"]["sdk_mapping"] == {"T600018.SH": None}


def test_legacy_code_does_not_merge_same_digits_or_sdk_guess(metadata, reference, legacy_code):
    metadata["instruments"].append(
        dict(
            instrument_id=99,
            symbol="600018.SH",
            exchange="XSHG",
            list_date="2000-01-01",
            delist_date=None,
            status="active",
        )
    )
    reference["instruments"].append(
        dict(order_book_id="600018.XSHG", listed_date="2000-01-01", de_listed_date="0000-00-00")
    )
    reference["sdk_mapping"].update({"T600018.SH": "600018.XSHG", "600018.XSHG": "600018.XSHG"})
    result = build_universe_provider(metadata, reference)("2004-01-02")
    rows = {r["instrument_id"]: r for r in result["candidates"]}
    assert rows[33510]["request_code"] is None
    assert rows[99]["request_code"] == "600018.XSHG"
    assert rows[99]["status"] is None
    assert not result["unresolved"]


@pytest.mark.parametrize(
    "dates",
    [
        (None, "2006-10-20"),
        ("bad-date", "2006-10-20"),
        ("2007-01-01", "2006-10-20"),
        ("2000-07-19", "invalid"),
    ],
)
def test_legacy_code_bad_dates_never_silently_excluded(metadata, reference, legacy_code, dates):
    legacy_code["list_date"], legacy_code["delist_date"] = dates
    result = build_universe_provider(metadata, reference)("2026-10-22")
    row = next(r for r in result["candidates"] if r["instrument_id"] == 33510)
    assert row["status"] == "unmapped_symbol" and row["request_code"] is None


@pytest.mark.parametrize("exchange", ["UNKNOWN", "XSHE"])
def test_nonstandard_code_still_rejects_exchange_conflict(
    metadata, reference, legacy_code, exchange
):
    legacy_code["exchange"] = exchange
    with pytest.raises(ContractViolationError, match="exchange mismatch"):
        build_universe_provider(metadata, reference)


def test_nonstandard_code_still_rejects_alias_identity_conflict(metadata, reference, legacy_code):
    metadata["aliases"].append(
        dict(source="tushare", source_symbol="302132.SZ", instrument_id=33510)
    )
    with pytest.raises(ContractViolationError, match="Conflicting stock identity aliases"):
        build_universe_provider(metadata, reference)


def test_nonstandard_canonical_tushare_conflict_rejected_before_future_filter(
    metadata, reference, legacy_code
):
    # 2004 年 T600018.SH 尚可能在市；ID 2 要到 2024 年上市，本应被逐日过滤。
    # 移除同源重复的干扰，单独复现 canonical 与 Tushare 命名空间的身份冲突。
    metadata["aliases"] = [
        row for row in metadata["aliases"] if row["source_symbol"] != "T600018.SH"
    ]
    metadata["aliases"].append(dict(source="tushare", source_symbol="T600018.SH", instrument_id=2))
    assert metadata["instruments"][1]["list_date"] > "2004-01-02"
    with pytest.raises(ContractViolationError, match="Conflicting stock identity aliases"):
        build_universe_provider(metadata, reference)("2004-01-02")


@pytest.fixture
def temporal_reference(reference):
    reference["instruments"][0]["de_listed_date"] = "2025-02-17"
    reference["instruments"].append(
        dict(order_book_id="302132.XSHE", listed_date="2010-08-27", de_listed_date="0000-00-00")
    )
    reference["sdk_mapping"]["302132.XSHE"] = "302132.XSHE"
    return reference


def temporal_provider(metadata, reference):
    return build_universe_provider(
        metadata, reference, universe_policy="listed_cn_a_v2", mapping_version="alias_v2"
    )


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2024-01-02", "300114.XSHE"),
        ("2025-02-14", "300114.XSHE"),
        ("2025-02-17", "302132.XSHE"),
        ("2026-10-22", "302132.XSHE"),
    ],
)
def test_temporal_alias_uses_effective_date_not_supplier_listing(
    metadata, temporal_reference, day, expected
):
    result = temporal_provider(metadata, temporal_reference)(day)
    row = next(r for r in result["candidates"] if r["instrument_id"] == 1)
    assert row["status"] is None and row["request_code"] == expected
    assert row["canonical_symbol"] == "302132.SZ"
    interval = row["evidence"]["symbol_interval"]
    assert interval["effective_date"] == "2025-02-17"
    assert interval["evidence_url"].endswith("1222544408.PDF")
    assert interval["selected_source_symbol"] == expected.replace(".XSHE", ".SZ")


def test_temporal_identity_resolves_verified_alias_not_hardcoded_id(metadata, temporal_reference):
    metadata["instruments"][0]["instrument_id"] = 98989
    for alias in metadata["aliases"]:
        alias["instrument_id"] = 98989
    row = temporal_provider(metadata, temporal_reference)("2024-01-02")["candidates"][0]
    assert row["instrument_id"] == 98989 and row["request_code"] == "300114.XSHE"


def test_temporal_does_not_fallback_to_new_code_when_sdk_transforms_old(
    metadata, temporal_reference
):
    temporal_reference["sdk_mapping"]["300114.XSHE"] = "302132.XSHE"
    row = temporal_provider(metadata, temporal_reference)("2024-01-02")["candidates"][0]
    assert row["status"] == "sdk_filtered" and row["request_code"] is None
    assert row["evidence"]["sdk_mapping"]["300114.XSHE"] == "302132.XSHE"


@pytest.mark.parametrize("defect", ["missing_alias", "other_alias", "wrong_end"])
def test_temporal_unknown_rules_or_unexpected_boundary_not_invented(
    metadata, temporal_reference, defect
):
    if defect == "missing_alias":
        metadata["aliases"] = [r for r in metadata["aliases"] if r["source_symbol"] != "300114.SZ"]
    elif defect == "other_alias":
        metadata["aliases"].append(
            dict(source="tushare", source_symbol="300777.SZ", instrument_id=1)
        )
    else:
        temporal_reference["instruments"][0]["de_listed_date"] = "2024-12-31"
        row = temporal_provider(metadata, temporal_reference)("2024-01-02")["candidates"][0]
        assert row["status"] == "universe_boundary_unknown" and row["request_code"] is None
        return
    with pytest.raises(ContractViolationError):
        temporal_provider(metadata, temporal_reference)


def test_temporal_tushare_membership_excludes_delist_day_including_halted_days(
    metadata, temporal_reference
):
    stock = metadata["instruments"][1]
    stock.update(
        symbol="000016.SZ",
        exchange="XSHE",
        list_date="1992-03-27",
        delist_date="2026-10-23",
        status="delisted",
    )
    temporal_reference["instruments"][1].update(
        order_book_id="000016.XSHE", listed_date="1992-03-27", de_listed_date="2026-10-23"
    )
    temporal_reference["sdk_mapping"]["000016.XSHE"] = "000016.XSHE"
    provider = temporal_provider(metadata, temporal_reference)
    for day in ("2026-10-21", "2026-10-22"):
        row = next(r for r in provider(day)["candidates"] if r["instrument_id"] == 2)
        assert row["status"] is None and row["request_code"] == "000016.XSHE"
        assert "symbol_interval" not in row["evidence"]
    assert 2 not in {r["instrument_id"] for r in provider("2026-10-23")["candidates"]}


@pytest.mark.parametrize("defect", ["missing_end", "conflicting_end", "missing_start", "bad_order"])
def test_temporal_boundary_unknown_retained_without_invented_override(
    metadata, temporal_reference, defect
):
    stock = metadata["instruments"][1]
    if defect == "missing_end":
        stock["delist_date"] = None
    elif defect == "conflicting_end":
        stock["delist_date"] = "2024-01-08"
    elif defect == "missing_start":
        stock["list_date"] = None
    else:
        stock["list_date"] = "2024-01-10"
    row = next(
        r
        for r in temporal_provider(metadata, temporal_reference)("2024-01-04")["candidates"]
        if r["instrument_id"] == 2
    )
    assert row["status"] == "universe_boundary_unknown" and row["request_code"] is None


def test_legacy_universe_and_identity_not_reinterpreted(metadata, temporal_reference):
    legacy = build_universe_provider(metadata, temporal_reference)("2024-01-02")
    temporal = temporal_provider(metadata, temporal_reference)("2024-01-02")
    assert legacy["candidates"][0]["status"] == "universe_boundary_unknown"
    assert temporal["candidates"][0]["status"] is None
    assert legacy["policy"] == "listed_cn_a_v1" and legacy["mapping_version"] == "alias_v1"
    assert "symbol_rules_hash" not in legacy["reference"]
    data = options_data()
    data.pop("order_book_ids")
    data["universe_policy"] = "listed_cn_a_v1"
    old = parse_risk_options(data)
    assert "symbol_rules_hash" not in old.identity
    assert old.identity == dict(
        contract="rq_risk_model_v2",
        model="v1",
        industry_mapping="sws_2021",
        horizon="daily",
        source_units=data["source_units"],
        units_evidence="fixture",
        universe="whole_market",
        method="implicit",
        universe_policy="listed_cn_a_v1",
        mapping_version="alias_v1",
        purpose="validation",
    )
    data["universe_policy"] = "listed_cn_a_v2"
    new = parse_risk_options(data)
    assert new.variant_id != old.variant_id and new.mapping_version == "alias_v2"
    assert new.symbol_rules_hash == semantic_hash(temporal["reference"]["symbol_rules"])
    assert new.identity["symbol_rules_version"] == "cn_stock_code_intervals_v1"


@pytest.mark.parametrize("defect", ["policy", "mapping", "rule"])
def test_policy_dispatch_refuses_unknown_versions(metadata, temporal_reference, defect):
    kwargs = dict(universe_policy="listed_cn_a_v2", mapping_version="alias_v2")
    if defect == "policy":
        kwargs["universe_policy"] = "listed_cn_a_v3"
    elif defect == "mapping":
        kwargs["mapping_version"] = "alias_v1"
    else:
        kwargs["symbol_rules"] = {"version": "unknown", "rules": []}
    with pytest.raises(ContractViolationError):
        build_universe_provider(metadata, temporal_reference, **kwargs)


def test_temporal_nonstandard_alias_cannot_silently_fall_back_to_canonical(
    metadata, temporal_reference
):
    metadata["aliases"].append(dict(source="tushare", source_symbol="T600000.SH", instrument_id=2))
    with pytest.raises(ContractViolationError, match="verified code interval"):
        temporal_provider(metadata, temporal_reference)
