"""两阶段日更边界回归；真实事务场景另由显式隔离PG用例覆盖。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import polars as pl
import pytest
from gr_data.cli import build_parser
from gr_data.diagnosis_daily import _load, apply, prepare
from gr_data.diagnosis_daily.evidence import digest, file_hash, write_json
from gr_data.ingest.base import IngestContext
from gr_data.ingest.ricequant.riskmodel import run_risk_ingest
from psycopg.pq import TransactionStatus


def test_daily_cli_has_finite_phase_actions():
    parser = build_parser()
    args = parser.parse_args(
        ["diagnosis-daily", "run", "--start", "2026-11-06", "--end", "2026-11-12"]
    )
    assert args.start == date(2026, 11, 6) and args.end == date(2026, 11, 12)
    assert parser.parse_args(
        ["diagnosis-daily", "apply", "--artifact", "/tmp/day"]
    ).artifact == Path("/tmp/day")


def test_phase_a_configuration_failure_never_opens_writer(monkeypatch, tmp_path):
    import gr_data.diagnosis_daily as daily

    def reject(**kwargs):
        raise ValueError("uncommitted source")

    monkeypatch.setattr(daily, "get_importer_version", reject)
    connection = Mock()
    monkeypatch.setattr(daily, "connect", connection)
    with pytest.raises(ValueError, match="uncommitted"):
        prepare(Mock(), tmp_path, date(2026, 11, 6), tushare=Mock(), ricequant=Mock())
    connection.assert_not_called()
    assert json.loads((tmp_path / "status.json").read_text())["phase"] == "A"
    assert not (tmp_path / "prepared.json").exists()


def test_artifact_tampering_is_rejected_before_writer_connection(monkeypatch, tmp_path):
    import gr_data.diagnosis_daily as daily

    monkeypatch.setattr(daily, "get_importer_version", lambda **kwargs: "code")
    raw = tmp_path / "raw"
    raw.mkdir()
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    file = canonical / "meta.symbol_map.parquet"
    pl.DataFrame({"instrument_id": [1]}).write_parquet(file)
    data = {
        "importer_version": "code",
        "raw_root": str(raw),
        "canonical_files": {"canonical/meta.symbol_map.parquet": file_hash(file)},
        "raw_files": {},
    }
    data["artifact_hash"] = digest(data)
    data["version_id"] = "daily-test"
    write_json(tmp_path / "prepared.json", data)
    pl.DataFrame({"instrument_id": [2]}).write_parquet(file)
    writer = Mock()
    monkeypatch.setattr(daily, "connect", writer)
    with pytest.raises(ValueError, match="checksum"):
        apply(Mock(), tmp_path)
    writer.assert_not_called()
    data["day"] = "2026-11-07"
    write_json(tmp_path / "prepared.json", data)
    with pytest.raises(ValueError, match="identity changed"):
        _load(tmp_path)


def test_managed_risk_import_requires_outer_transaction(monkeypatch, tmp_path):
    from gr_data.common.paths import RawPaths
    from gr_data.config.ricequant_risk import RiskOptions

    options = RiskOptions(
        "v2",
        "sws_2021",
        date(2026, 11, 6),
        date(2026, 11, 6),
        (),
        {},
        "evidence",
        universe_policy="listed_cn_a_v2",
        purpose="production",
    )
    conn = Mock()
    conn.info.transaction_status = TransactionStatus.IDLE
    with pytest.raises(ValueError, match="transaction boundary"):
        run_risk_ingest(conn, IngestContext(RawPaths(tmp_path)), options, transaction_managed=True)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


def test_expired_verified_alias_is_not_a_production_history_override():
    from gr_data.diagnosis_daily.collect import current_alias_snapshot

    metadata = {
        "instruments": [{"instrument_id": 1, "symbol": "601607.SH"}],
        "aliases": [
            {"instrument_id": 1, "source": "tushare", "source_symbol": "600849.SH"},
            {"instrument_id": 1, "source": "tushare", "source_symbol": "601607.SH"},
            {"instrument_id": 1, "source": "tushare", "source_symbol": "unknown.SH"},
        ],
    }
    snapshot, evidence = current_alias_snapshot(metadata, date(2026, 11, 6))
    assert [r["source_symbol"] for r in snapshot["aliases"]] == ["601607.SH", "unknown.SH"]
    assert evidence["expired_aliases"][0]["source_symbol"] == "600849.SH"
    assert len(metadata["aliases"]) == 3
    old, _ = current_alias_snapshot(metadata, date(2010, 3, 4))
    assert len(old["aliases"]) == 3


@pytest.mark.parametrize("status", ["included", "partial_bundle"])
def test_phase_a_checks_every_risk_identity_including_exclusions(status):
    from gr_data.diagnosis_daily.collect import validate_risk_identities

    metadata = {
        "instruments": [
            {
                "instrument_id": 42,
                "symbol": "688827.SH",
                "list_date": "2026-11-10",
                "delist_date": None,
            }
        ]
    }
    raw = {"coverage": [{"instrument_id": 7, "canonical_symbol": "688827.SH", "status": status}]}
    with pytest.raises(ValueError, match="identities differ"):
        validate_risk_identities(raw, metadata, date(2026, 11, 10))
    raw["coverage"][0]["instrument_id"] = 42
    validate_risk_identities(raw, metadata, date(2026, 11, 10))


@pytest.mark.anyio
async def test_new_code_can_replay_valid_publication_but_cannot_write_old_artifact(
    monkeypatch, tmp_path
):
    import gr_data.diagnosis_daily as daily
    from gr_data.common.paths import RawPaths

    conn = Mock()
    conn.info.transaction_status = TransactionStatus.INTRANS
    data = {
        "day": "2026-11-06",
        "history_start": "2025-10-22",
        "version_id": "published",
        "importer_version": "old",
    }
    monkeypatch.setattr(daily, "get_importer_version", lambda **kwargs: "new")
    monkeypatch.setattr(daily, "_row", lambda *args: {"valid": True})
    result = await daily._apply(conn, data, {}, RawPaths(tmp_path), Mock())
    assert result["replay"] and result["business_rows_written"] == 0
    monkeypatch.setattr(daily, "_row", lambda *args: None)
    with pytest.raises(ValueError, match="Importer changed"):
        await daily._apply(conn, data, {}, RawPaths(tmp_path), Mock())
    assert not any(
        "INSERT" in str(call) or "UPDATE" in str(call) for call in conn.execute.call_args_list
    )


def test_new_listing_bootstraps_annual_source_with_old_announcement(tmp_path):
    from decimal import Decimal

    import pandas as pd
    from gr_data.common.paths import RawPaths
    from gr_data.diagnosis_daily.collect import collect_annual_backfill
    from gr_data.ingest.tushare.financial import normalize_annual_roe

    class Supplier:
        def query_all(self, endpoint, **params):
            assert endpoint == "fina_indicator" and params["ts_code"] == "688827.SH"
            return pd.DataFrame(
                {
                    "ts_code": ["688827.SH"],
                    "end_date": [params["period"]],
                    "ann_date": ["20260430"],
                    "roe_waa": [20.0],
                    "update_flag": ["1"],
                }
            )

    raw, observed = collect_annual_backfill(
        Supplier(), RawPaths(tmp_path), ["688827.SH"], date(2026, 11, 10)
    )
    frame = normalize_annual_roe(
        raw, symbol_ids={"688827.SH": 42}, as_of=date(2026, 11, 10), observed_at=observed
    )
    assert set(frame["roe"]) == {Decimal(".2")} and frame.height == 2
    latest_announcement = frame["ann_date"].max()
    assert isinstance(latest_announcement, date)
    assert latest_announcement < date(2026, 11, 10)


def test_default_prepare_failure_status_preserves_target_and_failed_stage(monkeypatch, tmp_path):
    from argparse import Namespace
    from types import SimpleNamespace

    from gr_data.diagnosis_daily import cli

    monkeypatch.setattr("gr_data.cli._pg", lambda cfg: Mock())
    monkeypatch.setattr("gr_data.raw.tushare.client.TushareProClient", Mock())
    monkeypatch.setattr("gr_data.raw.ricequant.client.RqdatacClient", Mock())

    def missing(pg, artifact, day, **kwargs):
        write_json(
            artifact / "status.json",
            {"phase": "A", "stage": "ricequant_capture_preflight", "status": "failed"},
        )
        raise ValueError("No complete risk input")

    monkeypatch.setattr(cli, "prepare", missing)
    args = Namespace(
        action="prepare", artifact=None, day=date(2026, 11, 6), start=None, end=None, reuse_raw=None
    )
    cfg = Mock(raw_root=tmp_path, environment=SimpleNamespace(values={}))
    assert cli.run(args, cfg) == 1
    status = json.loads((tmp_path / "diagnosis/daily/last-run.json").read_text())
    assert status["day"] == "2026-11-06" and status["failed_stage"] == "ricequant_capture_preflight"
    assert status["artifact"].endswith("diagnosis/daily/2026-11-06")
    assert status["reason"] == "No complete risk input"


def test_repeated_date_range_skips_completed_dates_without_preparing_or_writing(
    monkeypatch, tmp_path
):
    from argparse import Namespace
    from contextlib import contextmanager
    from types import SimpleNamespace

    from gr_data.diagnosis_daily import cli

    conn = Mock()
    conn.transaction.return_value.__enter__ = Mock()
    conn.transaction.return_value.__exit__ = Mock(return_value=False)
    conn.execute.return_value.fetchall.return_value = [(date(2026, 11, n),) for n in (6, 9, 10)]
    conn.execute.return_value.fetchone.return_value = (5,)

    @contextmanager
    def connection(pg):
        yield conn

    monkeypatch.setattr("gr_data.cli._pg", lambda cfg: Mock())
    monkeypatch.setattr("gr_data.raw.tushare.client.TushareProClient", Mock())
    monkeypatch.setattr("gr_data.raw.ricequant.client.RqdatacClient", Mock())
    monkeypatch.setattr(cli, "connect", connection)
    monkeypatch.setattr(
        cli, "latest_publication", lambda c: {"as_of_date": date(2026, 11, 10), "valid": True}
    )
    prepare_call, apply_call = Mock(), Mock()
    monkeypatch.setattr(cli, "prepare", prepare_call)
    monkeypatch.setattr(cli, "apply", apply_call)
    args = Namespace(
        action="run",
        artifact=None,
        day=None,
        start=date(2026, 11, 6),
        end=date(2026, 11, 10),
        reuse_raw=None,
    )
    cfg = Mock(raw_root=tmp_path, environment=SimpleNamespace(values={}))
    assert cli.run(args, cfg) == 0
    prepare_call.assert_not_called()
    apply_call.assert_not_called()
    state = json.loads((tmp_path / "diagnosis/daily/last-run.json").read_text())
    assert state["result"]["skipped_dates"] == ["2026-11-06", "2026-11-09", "2026-11-10"]


def test_daily_cli_supports_probe_and_probe_upstream_flag():
    parser = build_parser()
    probe_args = parser.parse_args(["diagnosis-daily", "probe", "--day", "2026-11-20"])
    assert probe_args.action == "probe" and probe_args.day == date(2026, 11, 20)
    run_args = parser.parse_args(["diagnosis-daily", "run", "--probe-upstream"])
    assert run_args.action == "run" and run_args.probe_upstream is True


def test_probe_upstream_exposure_distinguishes_pending_and_ready():
    import pandas as pd
    from gr_data.config.ricequant_risk import RiskOptions
    from gr_data.diagnosis_daily.collect import probe_upstream_exposure

    day = date(2026, 11, 20)
    options = RiskOptions(
        "v2",
        "sws_2021",
        day,
        day,
        (),
        {},
        "evidence",
        universe_policy="listed_cn_a_v2",
        purpose="production",
    )
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.fetchall.side_effect = [
        [
            (1, "900901.SH", "XSHG", date(1992, 1, 1), None, "listed"),
            (2, "600000.SH", "XSHG", date(1999, 11, 10), None, "listed"),
            (3, "000001.SZ", "XSHE", date(1991, 4, 3), None, "listed"),
        ],
        [],
    ]
    conn = Mock()
    conn.cursor.return_value = cursor
    client = Mock()
    client.get_quota.return_value = {"bytes_limit": 10000, "bytes_used": 100}
    client.risk_piece.return_value = None
    pending = probe_upstream_exposure(conn, client, day, options)
    assert pending == {
        "ready": False,
        "status": "pending_upstream",
        "day": "2026-11-20",
        "reason": "ricequant_v2_exposure_not_ready",
        "probe_code": "000001.XSHE",
    }
    client.risk_piece.assert_called_once_with(
        "exposure", "2026-11-20", ["000001.XSHE"], model="v2", industry_mapping="sws_2021"
    )

    cursor.fetchall.side_effect = [
        [(3, "000001.SZ", "XSHE", date(1991, 4, 3), None, "listed")],
        [],
    ]
    client.risk_piece.return_value = pd.DataFrame()
    assert probe_upstream_exposure(conn, client, day, options)["ready"] is False

    cursor.fetchall.side_effect = [
        [(3, "000001.SZ", "XSHE", date(1991, 4, 3), None, "listed")],
        [],
    ]
    client.risk_piece.return_value = pd.DataFrame(
        {"beta": [1.0]},
        index=pd.MultiIndex.from_tuples(
            [("000001.XSHE", pd.Timestamp("2026-11-20"))], names=["order_book_id", "date"]
        ),
    )
    ready = probe_upstream_exposure(conn, client, day, options)
    assert ready == {
        "ready": True,
        "status": "ready",
        "day": "2026-11-20",
        "probe_code": "000001.XSHE",
    }


def test_cli_probe_upstream_pending_exits_zero_without_archiving_or_fetching(monkeypatch, tmp_path):
    from argparse import Namespace
    from contextlib import contextmanager
    from types import SimpleNamespace

    from gr_data.diagnosis_daily import cli

    day1, day2 = date(2026, 11, 19), date(2026, 11, 20)
    conn = Mock()
    conn.transaction.return_value.__enter__ = Mock()
    conn.transaction.return_value.__exit__ = Mock(return_value=False)
    conn.execute.return_value.fetchall.return_value = [(day1,), (day2,)]
    conn.execute.return_value.fetchone.return_value = (2,)

    @contextmanager
    def connection(pg):
        yield conn

    monkeypatch.setattr("gr_data.cli._pg", lambda cfg: Mock())
    monkeypatch.setattr("gr_data.raw.tushare.client.TushareProClient", Mock())
    monkeypatch.setattr("gr_data.raw.ricequant.client.RqdatacClient", Mock())
    monkeypatch.setattr(cli, "connect", connection)
    monkeypatch.setattr(
        cli, "latest_publication", lambda c: {"as_of_date": date(2026, 11, 18), "valid": True}
    )

    residual = tmp_path / "diagnosis/daily/2026-11-20/residual.json"
    write_json(residual, {"keep": True})
    monkeypatch.setattr(
        cli,
        "probe_upstream",
        lambda pg, d, **kw: (
            {"ready": True, "status": "ready", "day": str(d), "probe_code": "000001.XSHE"}
            if d == day1
            else {
                "ready": False,
                "status": "pending_upstream",
                "day": str(d),
                "reason": "ricequant_v2_exposure_not_ready",
                "probe_code": "000001.XSHE",
            }
        ),
    )
    prepare_call = Mock(return_value={"version_id": "v-day1"})
    apply_call = Mock(return_value={"version_id": "v-day1", "day": str(day1)})
    monkeypatch.setattr(cli, "prepare", prepare_call)
    monkeypatch.setattr(cli, "apply", apply_call)
    cfg = Mock(raw_root=tmp_path, environment=SimpleNamespace(values={}))

    # 独立 probe 只读检查不覆盖 last-run.json。
    probe_only = Namespace(
        action="probe",
        artifact=None,
        day=day2,
        start=None,
        end=None,
        reuse_raw=None,
        probe_upstream=False,
    )
    assert cli.run(probe_only, cfg) == 0
    assert not (tmp_path / "diagnosis/daily/last-run.json").exists()

    # 单日未就绪：零写退出 0，不归档 _failed，不调用 prepare。
    prep_args = Namespace(
        action="prepare",
        artifact=None,
        day=day2,
        start=None,
        end=None,
        reuse_raw=None,
        probe_upstream=True,
    )
    assert cli.run(prep_args, cfg) == 0
    prepare_call.assert_not_called()
    assert residual.exists() and not (tmp_path / "diagnosis/daily/_failed").exists()
    state = json.loads((tmp_path / "diagnosis/daily/last-run.json").read_text())
    assert state == {
        "status": "pending_upstream",
        "day": "2026-11-20",
        "reason": "ricequant_v2_exposure_not_ready",
    }

    # 多日 run：day1 已就绪正常发布，day2 未就绪干净停步并返回 0。
    run_args = Namespace(
        action="run",
        artifact=None,
        day=None,
        start=day1,
        end=day2,
        reuse_raw=None,
        probe_upstream=True,
    )
    assert cli.run(run_args, cfg) == 0
    assert prepare_call.call_count == 1 and apply_call.call_count == 1
    assert residual.exists() and not (tmp_path / "diagnosis/daily/_failed").exists()
    run_state = json.loads((tmp_path / "diagnosis/daily/last-run.json").read_text())
    assert run_state["status"] == "pending_upstream" and run_state["day"] == "2026-11-20"
    assert run_state["publications"] == [{"version_id": "v-day1", "day": "2026-11-19"}]


def test_collect_risk_reuse_raw_skips_live_sdk_when_bundle_exists(tmp_path):
    from typing import Any, cast

    import numpy as np
    import pandas as pd
    from gr_data.common.paths import RawPaths
    from gr_data.common.ricequant_symbol_intervals import symbol_rule_evidence
    from gr_data.common.ricequant_universe import build_universe_provider
    from gr_data.config.ricequant import RicequantImportOptions
    from gr_data.config.ricequant_risk import RiskOptions
    from gr_data.diagnosis_daily.collect import collect_risk
    from gr_data.raw.base import RawContext
    from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
    from gr_data.raw.ricequant.riskmodel import run_risk_raw

    day = date(2026, 11, 20)
    options = RiskOptions(
        "v2",
        "sws_2021",
        day,
        day,
        (),
        {
            "factor_return": "dec_daily",
            "specific_return": "dec_daily",
            "covariance": "dec2_annual",
            "specific_risk": "dec_annual",
        },
        "verified",
        universe_policy="listed_cn_a_v2",
        purpose="production",
        production_symbol_rules_version="cn_stock_code_intervals_v4",
    )
    metadata = {
        "instruments": [
            {
                "instrument_id": 1,
                "symbol": "000001.SZ",
                "exchange": "XSHE",
                "list_date": "1991-04-03",
                "delist_date": None,
                "status": "listed",
            }
        ],
        "aliases": [{"source": "tushare", "source_symbol": "000001.SZ", "instrument_id": 1}],
    }
    reference = {
        "sdk_version": "fixture",
        "instruments": [
            {
                "order_book_id": "000001.XSHE",
                "listed_date": "1991-04-03",
                "de_listed_date": "0000-00-00",
            }
        ],
        "sdk_mapping": {"000001.XSHE": "000001.XSHE"},
    }
    factors = sorted(STYLE_FACTORS["v2"] | {"comovement", "银行"})

    class CaptureClient:
        def get_quota(self):
            return {"bytes_limit": 1000000, "bytes_used": 0}

        def get_trading_dates(self, start, end):
            return [day]

        def risk_piece(self, piece, d, codes, *, model, industry_mapping):
            if piece == "covariance":
                return pd.DataFrame(np.eye(len(factors)) * 0.001, columns=factors, index=factors)
            if piece == "factor_return":
                return pd.DataFrame(
                    [[0.001] * len(factors)], index=pd.DatetimeIndex([d]), columns=factors
                )
            if piece == "exposure":
                row = {f: (1.0 if f in {"comovement", "银行"} else 0.0) for f in factors}
                return pd.DataFrame(
                    [row],
                    index=pd.MultiIndex.from_tuples(
                        [("000001.XSHE", pd.Timestamp(d))], names=["order_book_id", "date"]
                    ),
                )
            return pd.DataFrame([[0.2]], index=pd.DatetimeIndex([d]), columns=["000001.XSHE"])

    paths = RawPaths(tmp_path / "raw")
    provider = build_universe_provider(
        metadata,
        reference,
        universe_policy="listed_cn_a_v2",
        mapping_version="alias_v2",
        symbol_rules=symbol_rule_evidence("cn_stock_code_intervals_v4"),
    )
    run_risk_raw(
        cast(Any, CaptureClient()),
        RawContext(paths),
        options,
        RicequantImportOptions(datasets={"rq_risk_model": options}),
        mode="init",
        universe_provider=provider,
        capture_callback=lambda _: None,
    )

    class OfflineClient:
        def __getattr__(self, name):
            pytest.fail(f"reuse_raw must not call live RiceQuant SDK: {name}")

    result = collect_risk(OfflineClient(), paths, day, options, metadata, reuse_raw=True)
    assert result["security_ids"] == [1]
    assert (paths.dataset_dir("ricequant", "daily_capture") / "manifest.json").exists()
    assert (paths.dataset_dir("ricequant", "daily_capture") / "preflight.json").exists()


def test_quota_expiry_warning_and_snapshot_metadata(caplog):
    import logging

    from gr_data.raw.ricequant.fetchers.supplements import _check_quota
    from gr_data.raw.ricequant.riskmodel import _quota_snapshot

    client = Mock()
    client.get_quota.return_value = {"bytes_limit": 1000, "bytes_used": 100}
    with caplog.at_level(logging.WARNING):
        _check_quota(client, 0.1)
        plain = _quota_snapshot(client)
    assert set(plain) == {"observed_at", "bytes_used", "bytes_limit"}
    assert not caplog.records

    client.get_quota.return_value = {
        "bytes_limit": 1000,
        "bytes_used": 100,
        "remaining_days": 45,
    }
    with caplog.at_level(logging.WARNING):
        ok_snap = _quota_snapshot(client)
    assert ok_snap["remaining_days"] == 45 and not caplog.records

    client.get_quota.return_value = {
        "bytes_limit": 1000,
        "bytes_used": 100,
        "remaining_days": 18,
        "expire_date": "2026-12-11",
        "account_secret": "must-not-persist",
    }
    with caplog.at_level(logging.WARNING):
        _check_quota(client, 0.1)
        warn_snap = _quota_snapshot(client)
    assert warn_snap["remaining_days"] == 18
    assert warn_snap["expire_date"] == "2026-12-11"
    assert "account_secret" not in warn_snap
    assert len(caplog.records) == 2
    assert all("remaining_days=18" in r.message and "30-day" in r.message for r in caplog.records)


def test_v4_daily_contract_and_l4_covariance_preflight(monkeypatch):
    import numpy as np
    from gr_data.diagnosis_daily import (
        CONTRACT,
        METRICS,
        V3_METRICS,
        V4_METRICS,
        collect as daily_collect,
    )
    from gr_data.diagnosis_daily.collect import validate_l4_covariance
    from gr_data.diagnostic_publication import admit_risk_universe, publish_version
    from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS

    assert CONTRACT == "diag-publication-v4"
    assert METRICS == V4_METRICS
    assert len(V3_METRICS) == 7 and len(V4_METRICS) == 12
    assert set(V3_METRICS) < set(V4_METRICS)

    factors = sorted(STYLE_FACTORS["v2"] | {"comovement", "银行"})
    # 模拟存储层 pct2_annual（非对角相关矩阵，需要真实迭代收敛）
    k = len(factors)
    rng = np.random.default_rng(7)
    a = rng.normal(size=(k, k))
    cov = (a @ a.T / k + np.eye(k) * 0.5) * 100.0
    checked = validate_l4_covariance(cov, factors, model="v2")
    assert checked["l4_orth_verified"] is True
    assert checked["l4_min_corr_eigenvalue"] > 1e-12
    assert checked["l4_max_orth_offdiag"] <= 1e-8
    assert checked["l4_max_conservation_rel_err"] <= 1e-8
    assert checked["l4_torsion_iterations"] >= 1

    # 最小扭转不收敛的协方差矩阵必须被预检拒绝（不能签发 l4_orth_verified=true）。
    monkeypatch.setattr(daily_collect, "_L4_TORSION_MAX_ITER", 1)
    with pytest.raises(ValueError, match="did not converge"):
        validate_l4_covariance(cov, factors, model="v2")
    monkeypatch.undo()

    # 18 维病态反例：矩阵最大元素归一化误差远小于 1e-8 且迭代快速收敛，但低方差单股方向
    # 相对守恒误差 > 1e-8（超 API 阈值）；按原协方差归一化的预检必须拒绝。
    ill_corr = np.eye(k)
    ill_corr[0, 1] = ill_corr[1, 0] = 1.0 - 5e-9
    ill_stds = np.ones(k) * 0.2
    ill_stds[0] = ill_stds[1] = 0.005
    ill_stds[2] = 0.8
    ill_cov = ill_corr * np.outer(ill_stds, ill_stds) * 10000.0
    with pytest.raises(ValueError, match="not conserved"):
        validate_l4_covariance(ill_cov, factors, model="v2")

    # 高条件数边界（~9e7）：即使单次预检误差略低于 1e-8，条件数浮点舍入预算也必须阻断。
    cond_corr = np.eye(k)
    cond_corr[0, 1] = cond_corr[1, 0] = 1.0 - 1e-7
    cond_stds = np.ones(k) * 0.2
    cond_stds[0] = cond_stds[1] = 0.01
    cond_stds[2] = 0.5
    cond_cov = cond_corr * np.outer(cond_stds, cond_stds) * 10000.0
    with pytest.raises(ValueError, match="not conserved"):
        validate_l4_covariance(cond_cov, factors, model="v2")

    # 缺少市场因子或风格因子必须阻断。
    with pytest.raises(ValueError, match="comovement"):
        validate_l4_covariance(
            np.eye(len(factors) - 1), [f for f in factors if f != "comovement"], model="v2"
        )
    with pytest.raises(ValueError, match="style factors missing"):
        validate_l4_covariance(
            np.eye(len(factors) - 1), [f for f in factors if f != "beta"], model="v2"
        )

    # 未知模型或重复因子名必须阻断。
    with pytest.raises(ValueError, match="unsupported risk model"):
        validate_l4_covariance(cov, factors, model="unknown_model")
    with pytest.raises(ValueError, match="duplicate factor codes"):
        validate_l4_covariance(np.eye(2), ["comovement", "comovement"], model="v2")

    # 近奇异因子相关矩阵必须阻断。
    singular = np.eye(k) * 100.0
    singular[0, 1] = singular[1, 0] = 100.0
    with pytest.raises(ValueError, match="near-singular"):
        validate_l4_covariance(singular, factors, model="v2")

    # 通用发布入口拒绝不完整 v4 指标清单（须恰好 12 项）。
    import asyncio
    from uuid import uuid4

    with pytest.raises(ValueError, match="exact 12"):
        asyncio.run(
            admit_risk_universe(
                Mock(),
                run_id=uuid4(),
                receipt_id=uuid4(),
                as_of_date=date(2026, 11, 23),
                instrument_ids=[1],
                factor_order_hash="h",
                units_evidence={"x": 1},
                evidence={"l4_orth_verified": True},
                metrics=V3_METRICS,
                contract_version="diag-publication-v4",
            )
        )
    with pytest.raises(ValueError, match="exact 12"):
        asyncio.run(
            publish_version(
                Mock(),
                version_id="v4-partial",
                as_of_date=date(2026, 11, 23),
                components=[],
                available_options={
                    "publication_scope": {
                        "scope_type": "security_universe",
                        "metrics": V3_METRICS,
                    }
                },
                contract_version="diag-publication-v4",
            )
        )
