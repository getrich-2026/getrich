"""准入与任务选择在网络或数据库副作用之前失败。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from gr_data.common.ricequant_specs import RqConfigurationError
from gr_data.config.pipeline import Config
from gr_data.config.ricequant import parse_ricequant_options, select_datasets
from gr_tools.config import load_environment


LEGACY = ("instruments", "calendar", "bars_1d")


@pytest.mark.parametrize("requested,expected", [(None, LEGACY), ([], ()), (["all"], LEGACY)])
def test_defaults_stay_legacy(requested, expected):
    assert select_datasets(requested, Config(), phase="raw", legacy=LEGACY)[0] == expected


def test_explicit_empty_config():
    cfg = Config({"enabled": {"raw": {"ricequant": []}}})
    assert select_datasets(None, cfg, phase="raw", legacy=LEGACY)[0] == ()


@pytest.mark.parametrize(
    "requested",
    [
        ["bad"],
        ["instruments", "bad"],
        ["rq_indices"],
        ["rq_supplements"],
        ["rq_derivatives"],
        ["rq_risk_descriptors"],
    ],
)
def test_unknown_disabled_and_groups_fail(requested):
    with pytest.raises(RqConfigurationError):
        select_datasets(requested, Config(), phase="raw", legacy=LEGACY)


@pytest.mark.parametrize(
    "overrides",
    [
        {"selected": "true"},
        {"start_date": None},
        {"start_date": "2025-01-01"},
        {"index_codes": ["000300.XSHG"]},
        {"fields": ["volume"]},
        {"fields": ["close", "typo"]},
        {"fields": ["close", "close"]},
        {"contract_version": "v2"},
        {"evidence": {}},
        {"max_pending_bytes": 0},
        {"replay_trading_days": True},
        {"enable_bjse": "yes"},
    ],
)
def test_invalid_options_fail(rq_config, overrides):
    with pytest.raises(RqConfigurationError):
        parse_ricequant_options(rq_config(**overrides), phase="ingest")


@pytest.mark.parametrize(
    "key,value",
    [
        ("rq_permission", "unknown"),
        ("tushare_overlap", "overlap"),
        ("datayes_overlap", "unknown"),
        ("contract_status", "unknown"),
        ("references", []),
        ("checked_on", "bad"),
    ],
)
def test_each_evidence_is_required(rq_config, key, value):
    cfg = rq_config()
    cfg.data["providers"]["ricequant"]["supplements"]["datasets"]["rq_index_daily"]["evidence"][
        key
    ] = value
    with pytest.raises(RqConfigurationError):
        parse_ricequant_options(cfg, phase="ingest")


def test_environment_snapshot_and_offline_mode(rq_config, tmp_path, monkeypatch):
    cfg = rq_config()
    monkeypatch.setenv("RICEQUANT_API_KEY", "wrong-secret")
    opts = parse_ricequant_options(cfg, phase="raw")
    assert opts.license_key == "fixture-secret"
    assert "fixture-secret" not in repr(opts) + repr(cfg)
    cfg.environment = load_environment(root=tmp_path, environ={})
    assert parse_ricequant_options(cfg, phase="ingest").datasets
    with pytest.raises(RqConfigurationError, match="RICEQUANT_ENABLED"):
        parse_ricequant_options(cfg, phase="raw")
    cfg.environment = load_environment(root=tmp_path, environ={"RICEQUANT_ENABLED": "true"})
    with pytest.raises(RqConfigurationError, match="RICEQUANT_API_KEY"):
        parse_ricequant_options(cfg, phase="raw")


def test_group_requires_all_members_but_selected_subset_can_run(rq_config):
    cfg = rq_config(("rq_index_daily", "rq_index_components", "rq_index_weights"))
    names, _ = select_datasets(["rq_indices"], cfg, phase="raw", legacy=LEGACY)
    assert names == ("rq_index_daily", "rq_index_components", "rq_index_weights")
    assert select_datasets(["rq_index_daily"], cfg, phase="raw", legacy=LEGACY)[0] == (
        "rq_index_daily",
    )


def test_variant_separates_semantics_from_scope(rq_options):
    options = rq_options()
    assert (
        replace(
            options,
            end_date=date(2025, 1, 1),
            max_symbols_per_request=1,
            index_codes=("866006.RI",),
        ).variant_id
        == options.variant_id
    )
    assert replace(options, fields=("close", "volume")).variant_id != options.variant_id
    assert replace(options, enable_bjse=True).variant_id != options.variant_id


def test_member_sdk_filter_must_be_explicit(rq_config):
    cfg = rq_config(("rq_index_components",))
    del cfg.data["providers"]["ricequant"]["supplements"]["datasets"]["rq_index_components"][
        "enable_bjse"
    ]
    with pytest.raises(RqConfigurationError, match="enable_bjse"):
        parse_ricequant_options(cfg, phase="ingest")


@pytest.mark.parametrize(
    "rate",
    [
        {"max_retries": 0},
        {"max_retries": "2"},
        {"sleep_between_requests_sec": float("nan")},
        {"retry_backoff_base_sec": -1},
    ],
)
def test_invalid_retry_budget(rq_config, rate):
    cfg = rq_config()
    cfg.data["providers"]["ricequant"]["rate_limit"] = rate
    with pytest.raises(RqConfigurationError):
        parse_ricequant_options(cfg, phase="raw")
