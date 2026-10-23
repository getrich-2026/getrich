"""动态日名单 raw 覆盖证据；使用假 SDK，不访问账户或工作库。"""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import (
    BudgetDeferredError,
    ContractViolationError,
    RawIntegrityError,
    semantic_hash,
)
from gr_data.common.ricequant_universe import build_universe_provider
from gr_data.config.ricequant import select_datasets
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import read_bundles, run_risk_raw


@pytest.fixture
def dynamic_setup(rq_config):
    cfg = rq_config(())
    cfg.data["providers"]["ricequant"]["risk_model"] = {
        "selected": True,
        "permission_confirmed": True,
        "model": "v1",
        "industry_mapping": "sws_2021",
        "start_date": "2024-01-02",
        "end_date": "2024-01-03",
        "universe_policy": "listed_cn_a_v1",
        "purpose": "validation",
        "batch_size": 2,
        "source_units": {
            "factor_return": "dec_daily",
            "specific_return": "dec_daily",
            "covariance": "dec2_annual",
            "specific_risk": "dec_annual",
        },
        "units_evidence": "synthetic-test-only",
    }
    _, shared = select_datasets(["rq_risk_model"], cfg, phase="raw", legacy=())
    options = shared.datasets["rq_risk_model"]
    ctx = RawContext(RawPaths(cfg.raw_root), cfg.section("providers", "ricequant")["rate_limit"])
    return ctx, options, shared


def universe(day):
    codes = ["000001.XSHE", "600000.XSHG", "600001.XSHG"]
    snapshot = {
        "instruments": [
            {
                "instrument_id": index,
                "symbol": code.replace(".XSHG", ".SH").replace(".XSHE", ".SZ"),
                "exchange": code.split(".")[1],
                "list_date": "2000-01-01",
                "delist_date": None,
                "status": "L",
            }
            for index, code in enumerate(codes, 1)
        ],
        "aliases": [],
    }
    reference = {
        "sdk_version": "fixture",
        "instruments": [
            {"order_book_id": code, "listed_date": "2000-01-01", "de_listed_date": "0000-00-00"}
            for code in codes
        ],
        "sdk_mapping": dict(zip(codes, codes, strict=True)),
    }
    return build_universe_provider(snapshot, reference)(day)


def filtered_universe(day, *, all_filtered=False):
    result = universe(day)
    reference = result["reference"]["supplier_snapshot"]
    for code in reference["sdk_mapping"]:
        if all_filtered or code == "600001.XSHG":
            reference["sdk_mapping"][code] = None
    return build_universe_provider(result["reference"]["metadata"], reference)(day)


class PartialClient:
    def __init__(self):
        self.calls = []
        self.fail_day = None
        self.defect = None

    def get_quota(self):
        return {"bytes_limit": 10000000, "bytes_used": 0}

    def get_trading_dates(self, start, end):
        return list(pd.bdate_range(start, end).date)

    def risk_piece(self, piece, day, codes, *, model, industry_mapping):
        self.calls.append((piece, day, tuple(codes)))
        if day == self.fail_day:
            raise BudgetDeferredError("fixture exhausted")
        factors = sorted(STYLE_FACTORS[model] | {"comovement", "银行"})
        if piece == "covariance":
            frame = pd.DataFrame(np.eye(len(factors)) * 0.01, columns=factors, index=factors)
        elif piece == "factor_return":
            frame = pd.DataFrame(
                [[0.001] * len(factors)], index=pd.DatetimeIndex([day]), columns=factors
            )
        else:
            present = [
                code
                for code in codes
                if code != "600001.XSHG"
                and not (code == "600000.XSHG" and piece == "specific_risk")
            ]
            if not present:
                return None if self.defect != "empty" else pd.DataFrame()
            if piece == "exposure":
                frame = pd.DataFrame(
                    1.0,
                    index=pd.MultiIndex.from_product(
                        [present, [pd.Timestamp(day)]], names=["order_book_id", "date"]
                    ),
                    columns=factors,
                )
            else:
                frame = pd.DataFrame(
                    [[0.1] * len(present)], index=pd.DatetimeIndex([day]), columns=present
                )
        if self.defect == "date" and piece == "specific_return":
            frame.index = pd.DatetimeIndex(["2024-02-01"])
        if self.defect == "unknown" and piece == "specific_return":
            frame.columns = ["600999.XSHG"] + list(frame.columns[1:])
        if self.defect == "negative" and piece == "specific_risk":
            frame.iloc[0, 0] = -1
        if self.defect == "nan_partial" and piece == "exposure":
            frame.loc[("600000.XSHG", pd.Timestamp(day)), "beta"] = np.nan
        if self.defect == "industry_partial" and piece == "exposure":
            frame.loc[("600000.XSHG", pd.Timestamp(day)), "银行"] = 0.5
        if self.defect == "covariance" and piece == "covariance":
            frame.iloc[0, 1] = frame.iloc[1, 0] = 1
        if self.defect == "duplicate" and piece == "specific_return":
            frame = pd.concat([frame, frame], axis=1)
        return frame


def test_dynamic_partial_preserves_original_and_recomputes_coverage(dynamic_setup):
    ctx, options, shared = dynamic_setup
    client = PartialClient()
    assert run_risk_raw(client, ctx, options, shared, mode="init", universe_provider=universe) > 0
    bundles = list(read_bundles(ctx.paths, options))
    assert len(bundles) == 2
    for manifest, frames in bundles:
        assert manifest["purpose"] == "validation"
        assert manifest["coverage_counts"] == {
            "included": 1,
            "partial_bundle": 1,
            "provider_not_returned": 1,
            "candidate": 3,
            "complete": 1,
            "not_returned": 1,
            "anomalous": 1,
        }
        assert list(frames["exposure"].index) == ["000001.XSHE"]
        root = ctx.paths.ricequant_variant("rq_risk_model", "v2", options.variant_id)
        folder = root / manifest["day"] / manifest["observation_id"]
        assert len(pd.read_parquet(folder / "exposure.parquet")) == 2
        assert pd.read_parquet(folder / "response-00002.parquet").index.nlevels == 2
    client.calls.clear()
    assert run_risk_raw(client, ctx, options, shared, mode="init", universe_provider=universe) == 0
    assert not client.calls


@pytest.mark.parametrize(
    "defect",
    ["date", "unknown", "negative", "nan_partial", "industry_partial", "covariance", "duplicate"],
)
def test_dynamic_invalid_data_keeps_failed_receipt_never_publishes(dynamic_setup, defect):
    ctx, options, shared = dynamic_setup
    client = PartialClient()
    client.defect = defect
    with pytest.raises(ContractViolationError):
        run_risk_raw(client, ctx, options, shared, mode="init", universe_provider=universe)
    assert not list(ctx.paths.root.glob("ricequant/rq_risk_model/v2/*/????-??-??/*/manifest.json"))
    receipt = next(ctx.paths.root.glob("ricequant/rq_risk_model/v2/*/_failed/*/*/receipt.json"))
    assert json.loads(receipt.read_text())["failure"]["error_type"] in {
        "ContractViolationError",
        "RiskQualityError",
    }
    assert list(receipt.parent.glob("response-*.parquet"))
    if defect == "covariance":
        assert len(client.calls) == 2
    elif defect in {"nan_partial", "industry_partial"}:
        assert len(client.calls) == 3


def test_dynamic_resume_freezes_universe_and_only_retries_failed_day(dynamic_setup):
    ctx, options, shared = dynamic_setup
    client = PartialClient()
    client.fail_day = "2024-01-03"
    with pytest.raises(BudgetDeferredError):
        run_risk_raw(client, ctx, options, shared, mode="update", universe_provider=universe)
    client.fail_day = None
    client.calls.clear()

    def forbidden(_):
        pytest.fail("resume must use frozen daily universe")

    run_risk_raw(client, ctx, options, shared, mode="update", universe_provider=forbidden)
    assert {call[1] for call in client.calls} == {"2024-01-03"}
    assert len(list(read_bundles(ctx.paths, options))) == 2


@pytest.mark.parametrize("defect", ["coverage", "request", "universe", "file", "path"])
def test_dynamic_tampering_rejected(dynamic_setup, defect):
    ctx, options, shared = dynamic_setup
    run_risk_raw(PartialClient(), ctx, options, shared, mode="init", universe_provider=universe)
    path = next(ctx.paths.root.rglob("manifest.json"))
    manifest = json.loads(path.read_text())
    if defect == "coverage":
        manifest["coverage"][1]["status"] = "included"
        manifest["coverage_hash"] = semantic_hash(manifest["coverage"])
    elif defect == "request":
        manifest["requests"][2]["codes"] = ["000001.XSHE"]
    elif defect == "universe":
        manifest["universe"]["candidates"][1]["request_code"] = "000001.XSHE"
        manifest["universe_hash"] = semantic_hash(manifest["universe"])
    elif defect == "path":
        manifest["requests"][0]["file"] = "../factor_return.parquet"
    else:
        (path.parent / "specific_return.parquet").write_bytes(b"broken")
    path.write_text(json.dumps(manifest))
    with pytest.raises(RawIntegrityError):
        list(read_bundles(ctx.paths, options))


def test_dynamic_filtered_candidates_and_empty_responses(dynamic_setup):
    ctx, options, shared = dynamic_setup

    client = PartialClient()
    client.defect = "empty"
    run_risk_raw(client, ctx, options, shared, mode="init", universe_provider=filtered_universe)
    manifest, _ = next(read_bundles(ctx.paths, options))
    assert manifest["coverage_counts"]["sdk_filtered"] == 1
    assert manifest["coverage"][2]["pieces"] == dict.fromkeys(
        ["exposure", "specific_return", "specific_risk"], False
    )


def test_dynamic_zero_complete_and_unknown_identity_block(dynamic_setup):
    ctx, options, shared = dynamic_setup
    for unknown in (False, True):

        def blocked(day, unknown=unknown):
            snapshot = universe(day)
            if unknown:
                snapshot["unresolved"] = [{"source_symbol": "600999.XSHG"}]
            else:
                snapshot = filtered_universe(day, all_filtered=True)
            return snapshot

        scoped = replace(options, units_evidence=f"fixture-{unknown}")
        with pytest.raises((ContractViolationError, RawIntegrityError)):
            run_risk_raw(
                PartialClient(), ctx, scoped, shared, mode="init", universe_provider=blocked
            )
    assert not list(ctx.paths.root.glob("ricequant/rq_risk_model/v2/*/????-??-??/*/manifest.json"))


def test_reader_does_not_depend_on_new_batch_size(dynamic_setup):
    ctx, options, shared = dynamic_setup
    run_risk_raw(PartialClient(), ctx, options, shared, mode="init", universe_provider=universe)
    assert len(list(read_bundles(ctx.paths, replace(options, batch_size=500)))) == 2


def test_snapshot_recomputes_candidate_and_metadata_fingerprint(dynamic_setup):
    ctx, options, shared = dynamic_setup
    run_risk_raw(PartialClient(), ctx, options, shared, mode="init", universe_provider=universe)
    path = next(ctx.paths.root.rglob("manifest.json"))
    manifest = json.loads(path.read_text())
    # 修改快照却只重算外层哈希，不得通过读门禁。
    manifest["universe"]["reference"]["metadata"]["instruments"][0]["list_date"] = "2025-01-01"
    manifest["universe_hash"] = semantic_hash(manifest["universe"])
    path.write_text(json.dumps(manifest))
    with pytest.raises(RawIntegrityError):
        list(read_bundles(ctx.paths, options))


def test_historical_unmapped_identity_stays_in_coverage_without_request(dynamic_setup):
    ctx, options, shared = dynamic_setup

    def provider(day):
        original = universe(day)
        snapshot = original["reference"]["metadata"]
        snapshot["instruments"].append(
            {
                "instrument_id": 99,
                "symbol": "T600018.SH",
                "exchange": "XSHG",
                "list_date": "2000-07-19",
                "delist_date": "2024-01-03",
                "status": "delisted",
            }
        )
        return build_universe_provider(snapshot, original["reference"]["supplier_snapshot"])(day)

    client = PartialClient()
    run_risk_raw(client, ctx, options, shared, mode="init", universe_provider=provider)
    for manifest, _ in read_bundles(ctx.paths, options):
        row = next(row for row in manifest["coverage"] if row["instrument_id"] == 99)
        assert row["status"] == "unmapped_symbol"
        assert row["input_codes"] == ["T600018.SH"]
        assert row["request_code"] is None and not any(row["pieces"].values())
    assert all("T600018.SH" not in codes for _, _, codes in client.calls)


def temporal_universe(day):
    old = universe(day)
    return build_universe_provider(
        old["reference"]["metadata"],
        old["reference"]["supplier_snapshot"],
        universe_policy="listed_cn_a_v2",
        mapping_version="alias_v2",
    )(day)


def test_new_policy_roundtrip_does_not_reinterpret_old_raw(dynamic_setup):
    ctx, legacy, shared = dynamic_setup
    run_risk_raw(PartialClient(), ctx, legacy, shared, mode="init", universe_provider=universe)
    old = [
        (manifest, frames["exposure"].copy())
        for manifest, frames in read_bundles(ctx.paths, legacy)
    ]
    new = replace(legacy, universe_policy="listed_cn_a_v2")
    run_risk_raw(
        PartialClient(), ctx, new, shared, mode="init", universe_provider=temporal_universe
    )
    new_bundles = list(read_bundles(ctx.paths, new))
    assert len(new_bundles) == 2 and new.variant_id != legacy.variant_id
    for manifest, _ in new_bundles:
        ref = manifest["universe"]["reference"]
        assert ref["symbol_rules_hash"] == new.symbol_rules_hash
        assert semantic_hash(ref["symbol_rules"]) == new.symbol_rules_hash
        assert ref["symbol_rules_version"] == new.symbol_rules_version
    replay = list(read_bundles(ctx.paths, legacy))
    for (before, exposure), (after, frames) in zip(old, replay, strict=True):
        assert before == after and "symbol_rules" not in after["universe"]["reference"]
        pd.testing.assert_frame_equal(exposure, frames["exposure"])


@pytest.mark.parametrize("field", ["symbol_rules", "symbol_rules_hash", "symbol_rules_version"])
def test_new_policy_reader_rejects_tampered_rule_evidence(dynamic_setup, field):
    ctx, legacy, shared = dynamic_setup
    options = replace(legacy, universe_policy="listed_cn_a_v2")
    run_risk_raw(
        PartialClient(), ctx, options, shared, mode="init", universe_provider=temporal_universe
    )
    path = next(ctx.paths.root.rglob("manifest.json"))
    manifest = json.loads(path.read_text())
    reference = manifest["universe"]["reference"]
    reference[field] = {} if field == "symbol_rules" else "unknown"
    manifest["universe_hash"] = semantic_hash(manifest["universe"])
    path.write_text(json.dumps(manifest))
    with pytest.raises(RawIntegrityError):
        list(read_bundles(ctx.paths, options))


def test_production_purpose_is_separate_variant_and_requires_capture(dynamic_setup):
    ctx, legacy, shared = dynamic_setup
    validation = replace(legacy, universe_policy="listed_cn_a_v2")
    production = replace(validation, purpose="production")
    assert production.variant_id != validation.variant_id
    assert production.identity == {**validation.identity, "purpose": "production"}
    with pytest.raises(ValueError, match="capture callback"):
        run_risk_raw(
            PartialClient(),
            ctx,
            production,
            shared,
            mode="init",
            universe_provider=temporal_universe,
        )
    with pytest.raises(ValueError, match="listed_cn_a_v2"):
        run_risk_raw(
            PartialClient(),
            ctx,
            replace(legacy, purpose="production"),
            shared,
            mode="init",
            universe_provider=universe,
            capture_callback=lambda _: None,
        )
    assert not list(ctx.paths.root.rglob("manifest.json"))


def test_capture_failure_keeps_published_raw_and_replays_without_sdk(dynamic_setup):
    ctx, legacy, shared = dynamic_setup
    options = replace(legacy, universe_policy="listed_cn_a_v2", purpose="production")
    captured = []

    def fail_second(manifest):
        captured.append(manifest["observation_id"])
        if len(captured) == 2:
            raise ConnectionError("fixture postgres unavailable")

    with pytest.raises(ConnectionError):
        run_risk_raw(
            PartialClient(),
            ctx,
            options,
            shared,
            mode="update",
            universe_provider=temporal_universe,
            capture_callback=fail_second,
        )
    before = list(read_bundles(ctx.paths, options))
    assert len(before) == 2
    assert all(manifest["purpose"] == "production" for manifest, _ in before)
    assert not list(ctx.paths.root.glob("ricequant/rq_risk_model/v2/*/_failed/*/*"))

    def forbidden_universe(_):
        pytest.fail("completed journal must not rebuild universe")

    class OfflineClient:
        def __getattr__(self, name):
            pytest.fail(f"completed journal must not call SDK: {name}")

    replay = []
    assert (
        run_risk_raw(
            OfflineClient(),
            ctx,
            options,
            shared,
            mode="update",
            universe_provider=forbidden_universe,
            capture_callback=lambda manifest: replay.append(manifest["observation_id"]),
        )
        == 0
    )
    assert replay == captured
    after = list(read_bundles(ctx.paths, options))
    assert [m for m, _ in before] == [m for m, _ in after]
    # 已完成 plan 被正常移除后，init 仅允许重查日历，不重复风险接口或参考接口。
    client = PartialClient()
    replay.clear()
    assert (
        run_risk_raw(
            client,
            ctx,
            options,
            shared,
            mode="init",
            universe_provider=forbidden_universe,
            capture_callback=lambda manifest: replay.append(manifest["observation_id"]),
        )
        == 0
    )
    assert replay == captured and not client.calls


def test_validation_stays_optional_and_callback_observation_is_immutable(dynamic_setup):
    ctx, options, shared = dynamic_setup
    run_risk_raw(PartialClient(), ctx, options, shared, mode="init", universe_provider=universe)
    before = [manifest for manifest, _ in read_bundles(ctx.paths, options)]
    callbacks = []
    run_risk_raw(
        PartialClient(),
        ctx,
        options,
        shared,
        mode="init",
        universe_provider=universe,
        capture_callback=callbacks.append,
    )
    assert callbacks == before
    assert [manifest for manifest, _ in read_bundles(ctx.paths, options)] == before
