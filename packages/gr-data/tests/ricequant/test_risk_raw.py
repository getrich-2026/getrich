"""风险五件套配置、SDK 契约、原子发布和恢复；不访问真实账户。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_specs import (
    BudgetDeferredError,
    ContractViolationError,
    RawIntegrityError,
    RqConfigurationError,
)
from gr_data.config.ricequant import select_datasets
from gr_data.config.ricequant_risk import parse_risk_options
from gr_data.ingest import preflight_ricequant
from gr_data.raw import run_provider
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RqdatacClient
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS, decode_piece, validate_bundle
from gr_data.raw.ricequant.riskmodel import read_bundles, run_risk_raw


@pytest.fixture
def risk_config(rq_config):
    cfg = rq_config(())
    cfg.data["providers"]["ricequant"]["risk_model"] = dict(
        selected=True,
        permission_confirmed=True,
        model="v1",
        industry_mapping="sws_2021",
        start_date="2024-01-02",
        end_date="2024-01-03",
        order_book_ids=["000001.XSHE", "600000.XSHG"],
        batch_size=1,
        source_units=dict(
            factor_return="dec_daily",
            specific_return="pct_daily",
            covariance="pct2_annual",
            specific_risk="pct_annual",
        ),
        units_evidence="synthetic-test-only",
    )
    return cfg


@pytest.fixture
def risk_setup(risk_config):
    names, shared = select_datasets(["rq_risk_model"], risk_config, phase="raw", legacy=())
    opts = shared.datasets[names[0]]
    ctx = RawContext(
        RawPaths(risk_config.raw_root), risk_config.section("providers", "ricequant")["rate_limit"]
    )
    return ctx, opts, shared


class FakeRiskClient:
    def __init__(self):
        self.calls = []
        self.fail_day = None
        self.error = None
        self.bad_piece = None

    def get_quota(self):
        return {"bytes_limit": 10000000, "bytes_used": 0}

    def get_trading_dates(self, start, end):
        return list(pd.bdate_range(start, end).date)

    def risk_piece(self, piece, day, codes, *, model, industry_mapping):
        self.calls.append((piece, day, tuple(codes)))
        if day == self.fail_day:
            raise self.error or BudgetDeferredError("fixture exhausted")
        factors = sorted(STYLE_FACTORS[model] | {"comovement", "银行"})
        if piece == "exposure":
            idx = pd.MultiIndex.from_product(
                [codes, [pd.Timestamp(day)]], names=["order_book_id", "date"]
            )
            frame = pd.DataFrame(np.ones((len(codes), len(factors))), index=idx, columns=factors)
        elif piece == "covariance":
            frame = pd.DataFrame(np.eye(len(factors)), index=factors[::-1], columns=factors[::-1])
        else:
            cols = factors[::-1] if piece == "factor_return" else codes
            frame = pd.DataFrame([[0.01] * len(cols)], index=pd.DatetimeIndex([day]), columns=cols)
        if self.bad_piece == piece:
            frame.iloc[0, 0] = np.nan
        return frame


def test_raw_bundle_and_resume(risk_setup):
    ctx, opts, shared = risk_setup
    client = FakeRiskClient()
    client.fail_day = "2024-01-03"
    with pytest.raises(BudgetDeferredError):
        run_risk_raw(client, ctx, opts, shared, mode="update")
    assert len(list(read_bundles(ctx.paths, opts))) == 1
    assert len([c for c in client.calls if c[1] == client.fail_day]) == 1
    client.calls.clear()
    client.fail_day = None
    assert run_risk_raw(client, ctx, opts, shared, mode="update") > 0
    assert {c[1] for c in client.calls} == {"2024-01-03"}
    bundles = list(read_bundles(ctx.paths, opts))
    assert len(bundles) == 2
    for manifest, frames in bundles:
        assert pd.Timestamp(manifest["observed_at"]).tz is not None
        assert frames["exposure"].columns.tolist() == frames["covariance"].columns.tolist()
        assert list(frames["exposure"].index) == list(opts.order_book_ids)
        assert frames["specific_risk"].iloc[0, 0] == 0.01  # raw 不平方、不换算
    client.calls.clear()
    assert run_risk_raw(client, ctx, opts, shared, mode="init") == 0
    assert client.calls == []
    run_risk_raw(client, ctx, opts, shared, mode="update")
    assert len(list(read_bundles(ctx.paths, opts))) == 4


@pytest.mark.parametrize(
    "piece", ["exposure", "covariance", "factor_return", "specific_risk", "specific_return"]
)
def test_invalid_piece_never_publishes(risk_setup, piece):
    ctx, opts, shared = risk_setup
    client = FakeRiskClient()
    client.bad_piece = piece
    with pytest.raises(ContractViolationError):
        run_risk_raw(client, ctx, opts, shared, mode="init")
    assert not list(ctx.paths.root.rglob("manifest.json"))


def test_checksum_and_scope(risk_setup):
    ctx, opts, shared = risk_setup
    run_risk_raw(FakeRiskClient(), ctx, opts, shared, mode="init")
    assert len(list(read_bundles(ctx.paths, opts, months=("2024-01",)))) == 2
    with pytest.raises(RawIntegrityError):
        list(read_bundles(ctx.paths, opts, months=("2024-02",)))
    target = next(ctx.paths.root.rglob("specific_risk.parquet"))
    target.write_bytes(b"corrupted")
    with pytest.raises(RawIntegrityError):
        list(read_bundles(ctx.paths, opts))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("permission_confirmed", False),
        ("model", "AHv1"),
        ("industry_mapping", "unknown"),
        ("start_date", "2024-01-04"),
        ("end_date", str(date.today())),
        ("units_evidence", ""),
        ("source_units", {}),
        ("order_book_ids", ["1.XSHE"]),
        ("order_book_ids", ["000001.XSHE"] * 2),
        ("batch_size", 0),
        ("batch_size", True),
    ],
)
def test_risk_config_rejects_invalid(risk_config, key, value):
    data = dict(risk_config.section("providers", "ricequant")["risk_model"])
    data[key] = value
    with pytest.raises(RqConfigurationError):
        parse_risk_options(data)


def test_explicit_selection_preflight_and_dispatch(risk_config, monkeypatch):
    assert preflight_ricequant(risk_config, only=["rq_risk_model"]) == ["rq_risk_model"]
    assert preflight_ricequant(risk_config, only=[]) == []
    monkeypatch.setattr(
        "gr_data.raw.ricequant.client.RqdatacClient", lambda *a, **k: FakeRiskClient()
    )
    assert run_provider("ricequant", risk_config, only=["rq_risk_model"])["rq_risk_model"] > 0
    risk_config.data["providers"]["ricequant"]["risk_model"]["selected"] = False
    with pytest.raises(RqConfigurationError):
        preflight_ricequant(risk_config, only=["rq_risk_model"])


def test_raw_requires_key_offline_ingest_does_not(risk_config):
    risk_config.environment = replace(risk_config.environment, values={})
    with pytest.raises(RqConfigurationError):
        select_datasets(["rq_risk_model"], risk_config, phase="raw", legacy=())
    assert preflight_ricequant(risk_config, only=["rq_risk_model"])


@pytest.mark.parametrize(
    "piece", ["exposure", "covariance", "factor_return", "specific_return", "specific_risk"]
)
def test_sdk_signatures(piece):
    client = RqdatacClient("fixture")
    client._rq = Mock()
    client.risk_piece(piece, "2024-01-02", ["000001.XSHE"], model="v2", industry_mapping="sws_2021")
    api_name = (
        "get_factor_exposure"
        if piece == "exposure"
        else "get_factor_" + piece
        if piece == "covariance"
        else "get_" + piece
    )
    call = getattr(client._rq, api_name).call_args
    assert call.kwargs["model"] == "v2"
    assert call.kwargs["industry_mapping"] == "sws_2021"
    if piece in {"specific_risk", "covariance"}:
        assert call.kwargs["horizon"] == "daily"
    if piece in {"specific_return", "specific_risk", "covariance"}:
        assert "market" not in call.kwargs
    if piece == "factor_return":
        assert call.kwargs["method"] == "implicit"
        assert call.kwargs["universe"] == "whole_market"


@pytest.mark.parametrize(
    "defect",
    [
        "factor_mismatch",
        "asymmetric",
        "negative_diagonal",
        "non_psd",
        "negative_sigma",
        "wrong_day",
        "missing_stock",
        "duplicate",
        "nan",
        "infinity",
    ],
)
def test_joint_validation(risk_setup, defect):
    _, opts, _ = risk_setup
    client = FakeRiskClient()
    day = opts.start_date
    frames = {
        piece: decode_piece(
            piece,
            client.risk_piece(
                piece,
                str(day),
                list(opts.order_book_ids),
                model=opts.model,
                industry_mapping=opts.industry_mapping,
            ),
            day,
            opts.order_book_ids,
        )
        for piece in ["exposure", "covariance", "factor_return", "specific_return", "specific_risk"]
    }
    if defect == "factor_mismatch":
        frames["factor_return"] = frames["factor_return"].iloc[:, 1:]
    elif defect == "asymmetric":
        frames["covariance"].iloc[0, 1] = 2
    elif defect == "negative_diagonal":
        frames["covariance"].iloc[0, 0] = -1
    elif defect == "non_psd":
        frames["covariance"].iloc[0, 1] = frames["covariance"].iloc[1, 0] = 2
    elif defect == "negative_sigma":
        frames["specific_risk"].iloc[0, 0] = -1
    elif defect == "wrong_day":
        frames["specific_return"].index = [date(2024, 1, 3)]
    elif defect == "missing_stock":
        frames["exposure"] = frames["exposure"].iloc[:1]
    elif defect == "duplicate":
        frames["exposure"].index = [opts.order_book_ids[0]] * 2
    elif defect == "nan":
        frames["exposure"].iloc[0, 0] = np.nan
    else:
        frames["covariance"].iloc[0, 0] = np.inf
    with pytest.raises(ContractViolationError):
        validate_bundle(frames, opts, day)


@pytest.mark.integration
def test_risk_fake_sdk_parquet_pg_pipeline(risk_config, pg_conn, monkeypatch):
    """真实 DDL/COPY/JSONB 与事务；SDK 和 raw 路径仍完全隔离。"""
    from gr_data.common.ownership import OwnershipError
    from gr_data.ingest import run_provider as ingest_provider

    monkeypatch.setattr(
        "gr_data.raw.ricequant.client.RqdatacClient", lambda *a, **k: FakeRiskClient()
    )
    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meta.instruments (symbol, asset, exchange) VALUES "
            "('000001.SZ', 'stock', 'XSHE'), ('600000.SH', 'stock', 'XSHG')"
        )
    pg_conn.commit()
    run_provider("ricequant", risk_config, only=["rq_risk_model"], mode="init")
    result = ingest_provider("ricequant", pg_conn, risk_config, only=["rq_risk_model"])
    assert result[0].rows_written == 16
    result = ingest_provider("ricequant", pg_conn, risk_config, only=["rq_risk_model"])
    assert result[0].rows_written == 16
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM factor.model_run")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT COUNT(*) FROM factor.exposure")
        assert cur.fetchone()[0] == 4
        cur.execute("SELECT factor_order, units, calibrated, source FROM factor.model_run LIMIT 1")
        order, units, calibrated, source = cur.fetchone()
        assert order == sorted(STYLE_FACTORS["v1"] | {"comovement", "银行"})
        assert units["covariance"] == "pct2_annual"
        assert calibrated is False and source == "ricequant"
        cur.execute(
            "SELECT specific_var, available_at, trading_day FROM factor.specific_risk LIMIT 1"
        )
        variance, available, day = cur.fetchone()
        assert variance == pytest.approx(0.0001)
        assert available.tzinfo is not None and available.date() > day
        cur.execute(
            "SELECT source_symbol FROM meta.symbol_map WHERE source = 'ricequant' "
            "ORDER BY source_symbol"
        )
        assert [r[0] for r in cur.fetchall()] == ["000001.XSHE", "600000.XSHG"]
        cur.execute(
            "UPDATE ops.table_ownership SET provider='datayes' WHERE target='factor.exposure'"
        )
    pg_conn.commit()
    with pytest.raises(OwnershipError):
        ingest_provider("ricequant", pg_conn, risk_config, only=["rq_risk_model"])
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM factor.model_run")
        assert cur.fetchone()[0] == 2
    pg_conn.commit()


@pytest.mark.parametrize(
    "defect", ["missing_industry", "fractional_industry", "multiple_industries", "market"]
)
def test_market_and_industry_exposure_contract(risk_setup, defect):
    ctx, opts, shared = risk_setup
    client = FakeRiskClient()
    original = client.risk_piece

    def bad_response(piece, *args, **kwargs):
        frame = original(piece, *args, **kwargs)
        if defect == "multiple_industries":
            if piece in {"factor_return", "exposure"}:
                frame["电子"] = 1.0
            elif piece == "covariance":
                frame["电子"] = 0.0
                frame.loc["电子"] = 0.0
                frame.loc["电子", "电子"] = 1.0
        if piece == "exposure":
            if defect == "missing_industry":
                frame["银行"] = 0.0
            elif defect == "fractional_industry":
                frame["银行"] = 0.5
            elif defect == "market":
                frame["comovement"] = 0.0
        return frame

    client.risk_piece = bad_response
    with pytest.raises(ContractViolationError, match="行业归属"):
        run_risk_raw(client, ctx, opts, shared, mode="init")
    assert not list(ctx.paths.root.rglob("manifest.json"))
