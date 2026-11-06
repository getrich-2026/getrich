"""生产规则升级显式换身份，旧观察及历史专用权限保持不变。"""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from gr_data.common.ricequant_specs import ContractViolationError, RqConfigurationError
from gr_data.common.ricequant_symbol_intervals import (
    PRODUCTION_SYMBOL_RULES_VERSION,
    symbol_rule_evidence,
    symbol_rule_hash,
)
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant_risk import parse_risk_options


def config(model="v2", day="2024-01-02", purpose="production"):
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


@pytest.mark.parametrize(
    "mode,model,variant,serialized",
    [
        (
            "production",
            "v1",
            "2160b54b4472d911a6a148314c5e473818f4e57fe56da083d2fa302b31a46c14",
            "7d42f703f859edb958965b3564eb78529f94328496cd80ceee87f2e857b17a32",
        ),
        (
            "production",
            "v2",
            "7540e4c24e6339bc0464662e1ba2f8faddb7e8bc7af83b790c5217ff8be2174a",
            "39ede1fd7f539317f5f7e9219d4538f47d1e177b9a1c22508ddc09432a4022d6",
        ),
        (
            "production",
            "v2trd",
            "8c0f47f2f43f9b0c637346f00bdc2830ab9a6f51a7d9554474280568be6bd1ff",
            "79b9f496854203f3fd2405d31335a0e988352a2f0262d6be03e1116528aecc39",
        ),
        (
            "historical_probe",
            "v1",
            "293802778dd59ad894ca37c0094141deaf6e4b2a3cda377138066b4ff0d2e72d",
            "67ea5883bd3fcdfb209662bf38cb68e3b4f4677bb7b3baacb362d47f198e2466",
        ),
        (
            "historical_probe",
            "v2",
            "8dcbd113f9a6e15bb1526e770404630fbc172edac60958013081dcdcf61f61b8",
            "34b4f1e2e838c0a3a5bc5736b83b2529ff47b5b346f50d6b86afeb0a196ab60d",
        ),
        (
            "historical_probe",
            "v2trd",
            "d348909688f7833315002a0e86fd595cde4b2f97e99c9a06200decc5185b002f",
            "7d6f16963635f1b271a739e989a62daaab8173692ce9877650cec85316da5c34",
        ),
        (
            "approved_history_raw",
            "v1",
            "a9739ca259adb3005c3f2732df5b8f48a6289ad33b27bd3224bf9cda6b74493e",
            "1e2efe6580ca17a7faa85f77a430b12245ad6c374a35f5e4439b8a0c0d08bf5b",
        ),
        (
            "approved_history_raw",
            "v2",
            "ea32acfc4c0f5cc63bdf3aae494c1dd0f3450489ff4ad84ae42fc98a77b90a53",
            "e57f9f5b513722ee9f57d34d5e40a667074a97a89ac8548477c55337bd9be66c",
        ),
        (
            "approved_history_raw",
            "v2trd",
            "4b2706c95007553fd039656eca146584d9c8acf51cb38bb8b3514d8c752a41b7",
            "33b1563c612045c911fb9924ec21a69eae8abc4935bce6541336ced6b79d9bec",
        ),
    ],
)
def test_legacy_identity_and_serialized_bytes_unchanged(mode, model, variant, serialized):
    data = config(
        model,
        "2024-01-02" if mode == "production" else "2014-01-06",
        "validation" if mode == "historical_probe" else "production",
    )
    opts = parse_risk_options(data, **({mode: True} if mode != "production" else {}))
    assert opts.variant_id == variant
    assert (
        hashlib.sha256(
            json.dumps(opts.identity, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        == serialized
    )


@pytest.mark.parametrize("model", ["v1", "v2", "v2trd"])
def test_explicit_production_upgrade_changes_only_rule_identity(model):
    data = config(model)
    old = parse_risk_options(data)
    data["symbol_rules_version"] = PRODUCTION_SYMBOL_RULES_VERSION
    new = parse_risk_options(data)
    expected = dict(
        old.identity,
        symbol_rules_version=PRODUCTION_SYMBOL_RULES_VERSION,
        symbol_rules_hash=symbol_rule_hash(PRODUCTION_SYMBOL_RULES_VERSION),
    )
    assert new.identity == expected and new.variant_id != old.variant_id


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        "cn_stock_code_intervals_v1",
        "cn_stock_code_intervals_v2",
        "cn_stock_code_intervals_v3",
        "unknown",
    ],
)
def test_unapproved_production_rule_version_rejected(value):
    with pytest.raises(RqConfigurationError, match="代码区间升级"):
        parse_risk_options(dict(config(), symbol_rules_version=value))


@pytest.mark.parametrize(
    "mode", ["validation", "historical_probe", "approved_history_raw", "fixed", "listed_cn_a_v1"]
)
def test_new_rule_cannot_expand_historical_or_validation_permissions(mode):
    data = config(
        day="2014-01-06" if mode in {"historical_probe", "approved_history_raw"} else "2024-01-02",
        purpose="validation" if mode in {"validation", "historical_probe"} else "production",
    )
    if mode in {"fixed", "listed_cn_a_v1"}:
        data["universe_policy"] = mode
    data["symbol_rules_version"] = PRODUCTION_SYMBOL_RULES_VERSION
    with pytest.raises(RqConfigurationError):
        parse_risk_options(
            data, **({mode: True} if mode in {"historical_probe", "approved_history_raw"} else {})
        )


def inputs():
    pairs = [("000022.SZ", "001872.SZ", "1993-05-05"), ("000043.SZ", "001914.SZ", "1994-09-28")]
    stocks = [
        dict(
            instrument_id=i,
            symbol=new,
            exchange="XSHE",
            list_date=listed,
            delist_date=None,
            status="active",
        )
        for i, (_, new, listed) in enumerate(pairs, 1)
    ]
    aliases = [
        dict(source="tushare", source_symbol=old, instrument_id=i)
        for i, (old, _, _) in enumerate(pairs, 1)
    ]
    codes = [s.replace(".SZ", ".XSHE") for old, new, _ in pairs for s in [old, new]]
    ref = dict(
        instruments=[
            dict(
                order_book_id=new.replace(".SZ", ".XSHE"),
                listed_date=listed,
                de_listed_date="0000-00-00",
            )
            for _, new, listed in pairs
        ],
        sdk_mapping={s: s for s in codes},
    )
    return dict(instruments=stocks, aliases=aliases), ref


def test_two_registered_aliases_work_without_removing_old_identity_gate():
    metadata, ref = inputs()
    with pytest.raises(ContractViolationError, match="lacks a verified"):
        build_universe_provider(metadata, ref, universe_policy="listed_cn_a_v2")
    upgraded = symbol_rule_evidence(PRODUCTION_SYMBOL_RULES_VERSION)
    assert [
        (r["old_source_symbol"], r["new_source_symbol"], r["effective_date"])
        for r in upgraded["rules"]
    ] == [
        ("300114.SZ", "302132.SZ", "2025-02-17"),
        ("000022.SZ", "001872.SZ", "2018-12-26"),
        ("000043.SZ", "001914.SZ", "2019-12-16"),
    ]
    assert set(upgraded) == {"version", "rules"}
    provider = build_universe_provider(
        metadata, ref, universe_policy="listed_cn_a_v2", symbol_rules=upgraded
    )
    rows = provider("2026-10-22")["candidates"]
    assert [r["request_code"] for r in rows] == ["001872.XSHE", "001914.XSHE"]
    assert [r["instrument_id"] for r in rows] == [1, 2]
    mutated = deepcopy(upgraded)
    mutated["rules"].clear()
    with pytest.raises(ContractViolationError, match="Unknown historical"):
        build_universe_provider(
            metadata, ref, universe_policy="listed_cn_a_v2", symbol_rules=mutated
        )


@pytest.mark.parametrize("defect", ["conflict", "missing", "exchange", "unknown_alias"])
def test_production_upgrade_preserves_identity_hard_failures(defect):
    metadata, ref = inputs()
    if defect == "conflict":
        metadata["aliases"][0]["instrument_id"] = 2
    elif defect == "missing":
        metadata["aliases"].pop(0)
    elif defect == "exchange":
        metadata["instruments"][0]["exchange"] = "XSHG"
    else:
        metadata["aliases"].append(
            dict(source="tushare", source_symbol="000099.SZ", instrument_id=1)
        )
    with pytest.raises(ContractViolationError):
        build_universe_provider(
            metadata,
            ref,
            universe_policy="listed_cn_a_v2",
            symbol_rules=symbol_rule_evidence(PRODUCTION_SYMBOL_RULES_VERSION),
        )


def test_raw_entrypoint_passes_explicit_rule_to_real_universe_builder(monkeypatch):
    from gr_data.config.pipeline import Config
    from gr_data.raw import _lazy_risk_universe_provider
    from gr_tools.config import Environment

    metadata, reference = inputs()
    statements = []

    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, statement):
            statements.append(statement)

    monkeypatch.setattr(
        "gr_data.config.load_postgres",
        lambda _: SimpleNamespace(
            host="fake", port=5432, database="fake", user="fake", password=""
        ),
    )
    monkeypatch.setattr("gr_data.db.postgres.sync.connect", lambda _: nullcontext(Connection()))
    monkeypatch.setattr(
        "gr_data.common.ricequant_universe.load_metadata_snapshot", lambda _: metadata
    )
    client = SimpleNamespace(
        risk_reference=lambda codes, quota_guard: reference,
        get_quota=lambda: {"bytes_used": 0, "bytes_limit": 1000},
    )
    cfg = Config({}, Environment(root=Path.cwd(), values={}))
    opts = parse_risk_options(dict(config(), symbol_rules_version=PRODUCTION_SYMBOL_RULES_VERSION))
    provider = _lazy_risk_universe_provider(cfg, client, 0.1, opts)
    rows = provider("2026-10-22")["candidates"]
    assert [r["request_code"] for r in rows] == ["001872.XSHE", "001914.XSHE"]
    assert statements == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"]
