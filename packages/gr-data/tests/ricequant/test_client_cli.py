"""SDK 调用契约和 CLI 无副作用预检。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gr_data import cli
from gr_data.common.retry import PermanentError
from gr_data.common.ricequant_specs import (
    BudgetDeferredError,
    ContractViolationError,
    RqConfigurationError,
)
from gr_data.config.pipeline import Config
from gr_data.ingest import run_provider as ingest
from gr_data.raw import run_provider as raw
from gr_data.raw.ricequant.client import RqdatacClient


def test_client_lazy_single_init_and_exact_signatures(monkeypatch):
    sdk = SimpleNamespace(
        init=Mock(),
        get_price=Mock(),
        index_components=Mock(),
        index_weights=Mock(),
        user=SimpleNamespace(get_quota=Mock(return_value={"bytes_limit": 0})),
    )
    monkeypatch.setitem(sys.modules, "rqdatac", sdk)
    client = RqdatacClient("fixture-secret", enable_bjse=True)
    sdk.init.assert_not_called()
    client.get_price(["866002.RI"], "2024-01-02", "2024-01-03", fields=["close"], expect_df=True)
    sdk.init.assert_called_once_with(
        "license", "fixture-secret", connect_timeout=5, timeout=60, enable_bjse=True
    )
    sdk.get_price.assert_called_once_with(
        ["866002.RI"],
        start_date="2024-01-02",
        end_date="2024-01-03",
        frequency="1d",
        adjust_type="none",
        market="cn",
        fields=["close"],
        expect_df=True,
    )
    client.index_components("866002.RI", date="2024-01-02")
    sdk.index_components.assert_called_once_with(
        "866002.RI", date="2024-01-02", market="cn", return_create_tm=True
    )
    client.index_weights("866002.RI", date="2024-01-02")
    sdk.index_weights.assert_called_once_with("866002.RI", date="2024-01-02")
    assert client.get_quota() == {"bytes_limit": 0}
    assert sdk.init.call_count == 1
    client.get_price(["000001.XSHE"], "2024-01-02", "2024-01-03")
    assert "fields" not in sdk.get_price.call_args.kwargs
    assert "expect_df" not in sdk.get_price.call_args.kwargs


@pytest.mark.parametrize(
    "code,error",
    [
        (2, PermanentError),
        (4, PermanentError),
        (5, BudgetDeferredError),
        (400, PermanentError),
        (-1, ConnectionError),
        (-2, ConnectionError),
        (None, PermanentError),
    ],
)
def test_sdk_failures_are_classified_and_sanitized(code, error):
    class SdkError(Exception):
        rqerrno = code

    with pytest.raises(error) as caught:
        RqdatacClient._call(Mock(side_effect=SdkError("fixture-secret payload")))
    assert "fixture-secret" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.parametrize(
    "only", [[], ["bad"], ["instruments", "bad"], ["rq_indices"], ["rq_index_daily"]]
)
def test_raw_preflight_before_client_or_files(only, monkeypatch):
    monkeypatch.setattr("gr_data.raw._build_client", Mock(side_effect=AssertionError("client")))
    if only:
        with pytest.raises(RqConfigurationError):
            raw("ricequant", Config(), only=only)
    else:
        assert raw("ricequant", Config(), only=only) == {}


@pytest.mark.parametrize("only", ["", "bad", "rq_index_daily"])
def test_ingest_preflight_before_pg_and_sdk(only, rq_config, monkeypatch):
    monkeypatch.setattr(cli, "_pg", Mock(side_effect=AssertionError("PG config")))
    monkeypatch.setattr(cli, "connect", Mock(side_effect=AssertionError("PG connection")))
    monkeypatch.setattr(RqdatacClient, "_sdk", Mock(side_effect=AssertionError("SDK")))
    args = SimpleNamespace(provider="ricequant", only=only, months=None, force_ownership=False)
    if only:
        with pytest.raises(RqConfigurationError):
            cli.cmd_ingest(args, rq_config())
    else:
        assert cli.cmd_ingest(args, rq_config()) == 0
    assert ingest("ricequant", None, Config(), only=[]) == []


@pytest.mark.parametrize(
    "error",
    [
        RqConfigurationError("disabled"),
        BudgetDeferredError("quota"),
        ContractViolationError("partial"),
    ],
)
def test_cli_failure_exit_code(error, rq_config, monkeypatch):
    cfg = rq_config()
    monkeypatch.setattr(cli, "load_environment", lambda **kwargs: cfg.environment)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: cfg)
    monkeypatch.setattr(cli, "_configure_logging_from", lambda cfg: None)
    monkeypatch.setattr("gr_data.raw.run_provider", Mock(side_effect=error))
    assert cli.main(["raw", "ricequant", "--only", "rq_index_daily"]) == 2


def test_raw_group_shares_one_session(rq_config, rq_context, rq_client, monkeypatch):
    factory = Mock(return_value=rq_client)
    monkeypatch.setattr("gr_data.raw.ricequant.client.RqdatacClient", factory)
    cfg = rq_config(("rq_index_daily", "rq_index_components", "rq_index_weights"))
    assert raw("ricequant", cfg, mode="init", only=["rq_indices"]) == {
        "rq_index_daily": 1,
        "rq_index_components": 2,
        "rq_index_weights": 2,
    }
    assert factory.call_count == 1


def test_inconsistent_bj_flags_fail_before_any_client(rq_config, monkeypatch):
    cfg = rq_config(("rq_index_daily", "rq_index_components"))
    cfg.data["providers"]["ricequant"]["supplements"]["datasets"]["rq_index_components"][
        "enable_bjse"
    ] = True
    monkeypatch.setattr(
        "gr_data.raw.ricequant.client.RqdatacClient", Mock(side_effect=AssertionError("client"))
    )
    with pytest.raises(RqConfigurationError, match="enable_bjse"):
        raw("ricequant", cfg, only=["rq_index_daily", "rq_index_components"])
