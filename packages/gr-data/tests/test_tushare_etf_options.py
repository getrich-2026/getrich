"""ETF / 三类期权从源请求到隔离入库的单位、身份、门禁与幂等回归。"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, patch

import pandas as pd
import psycopg
import pytest
from gr_data.common.parquet import read_parquet_strict, write_parquet
from gr_data.config.pipeline import Config
from gr_data.ingest import plan_importers, run_provider
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.tushare.importers.asset_markets import (
    EtfBars1dImporter,
    EtfInstrumentsImporter,
    EtfSymbolMapImporter,
    OptionBars1dImporter,
    OptionContractsImporter,
    OptionInstrumentsImporter,
    OptionSymbolMapImporter,
)
from gr_data.raw.tushare.asset_rules import (
    czce_settlement_only_mask,
    numeric_values,
    read_asset_observation,
    validate_bars,
)
from gr_data.raw.tushare.client import PAGE_LIMITS, TushareProClient
from gr_data.raw.tushare.context import OPTION_EXCHANGES, TushareRawContext, build_context
from gr_data.raw.tushare.fetchers import asset_markets as raw_asset_markets
from gr_data.raw.tushare.fetchers.asset_markets import (
    EtfInstrumentsFetcher,
    FundAdjFetcher,
    FundBasicFetcher,
    FundDailyFetcher,
    OptionCalendarFetcher,
    OptionDailyFetcher,
    OptionInstrumentsFetcher,
)
from gr_data.raw.tushare.fetchers.reference import CalendarFetcher
from gr_tools.config import Environment


OPTIONS = {
    "SSE": ("10000001.SH", "510300.SH"),
    "SZSE": ("90000001.SZ", "159919.SZ"),
    "CFFEX": ("IO2402-C-3500.CFX", "000300.SH"),
    "DCE": ("M2405-C-3000.DCE", "M2405.DCE"),
    "CZCE": ("AP405C8000.ZCE", "AP2405.ZCE"),
    "SHFE": ("CU2402C70000.SHF", "CU2402.SHF"),
    "INE": ("SC2402C500.INE", "SC2402.INE"),
    "GFEX": ("SI2402-C-14000.GFE", "SI2402.GFE"),
}


def bar(code="510300.SH", **overrides) -> dict[str, object]:
    row: dict[str, object] = dict(
        ts_code=code,
        trade_date="20240102",
        open=1.2,
        high=1.3,
        low=1.1,
        close=1.25,
        pre_close=1.21,
        vol=10.25,
        amount=0.1234,
    )
    row.update(overrides)
    return row


def option_meta(exchange):
    code, underlying = OPTIONS[exchange]
    return dict(
        ts_code=code,
        exchange=exchange,
        name="测试期权",
        symbol=code.split(".")[0],
        opt_code=f"OP{underlying}",
        call_put="C",
        opt_type="期权",
        exercise_type="欧式" if exchange in ("SSE", "SZSE", "CFFEX") else "美式",
        exercise_price=3500,
        per_unit=1,
        opt_multiplier=10,
        list_date="20230102",
        delist_date="20240228",
        last_edate="20240301",
        quote_unit="人民币元",
        min_price_chg="0.0001",
    )


def etf_meta(code="510300.SH", status="L"):
    return dict(
        ts_code=code,
        exchange=code[-2:],
        list_status=status,
        list_date="20230102",
        extname="测试ETF",
        csname="测试ETF",
        cname="测试交易型开放式指数证券投资基金",
        index_code="000300.SH",
        index_name="沪深300指数",
        setup_date="20221220",
        mgr_name="测试基金",
        custod_name="测试银行股份有限公司",
        mgt_fee=0.5,
        etf_type="QDII",
    )


def fund_meta(code, status, fund_type="股票型"):
    """场内 fund_basic 一行；只给 etf_profile 用到的字段与采集门禁检查的字段。"""
    return dict(
        ts_code=code,
        name="测试ETF",
        management="测试基金管理有限公司",
        custodian="测试银行股份有限公司",
        fund_type=fund_type,
        found_date="20221220",
        due_date=None,
        list_date="20230102",
        issue_date="20221201",
        delist_date="20240601" if status == "D" else None,
        issue_amount=12.5,
        m_fee=0.5,
        c_fee=0.1,
        duration_year=None,
        p_value=1.0,
        min_amount=0.1,
        exp_return=None,
        benchmark="沪深300指数收益率×100%",
        status=status,
        invest_type="被动指数型",
        type="契约型开放式",
        trustee=None,
        purc_startdate="20230102",
        redm_startdate="20230102",
        market="E",
    )


class AssetClient:
    """只实现本轮五类 API；记录真实请求参数以检查白名单和依赖。"""

    def __init__(self):
        self.calls = []
        self.override = {}

    def query_all(self, api_name, **params):
        self.calls.append((api_name, dict(params)))
        if api_name in self.override:
            return self.override[api_name](params)
        if api_name in ("trade_cal", "fut_trade_cal"):
            days = pd.date_range(params["start_date"], params["end_date"])
            return pd.DataFrame(
                [
                    dict(
                        exchange=params["exchange"],
                        cal_date=d.strftime("%Y%m%d"),
                        is_open=int(d.strftime("%Y%m%d") in ("20240102", "20240103")),
                        pretrade_date="20231229",
                    )
                    for d in days
                ]
            )
        if api_name == "etf_basic":
            exchange, status = params["exchange"], params["list_status"]
            code = {
                ("SH", "L"): "510300.SH",
                ("SZ", "L"): "159919.SZ",
                ("SH", "D"): "510999.SH",
                ("SZ", "P"): "159999.SZ",
            }.get((exchange, status))
            return pd.DataFrame([etf_meta(code, status)]) if code else pd.DataFrame()
        if api_name == "fund_basic":
            assert params["market"] == "E"
            rows = {
                "L": [fund_meta("510300.SH", "L"), fund_meta("159919.SZ", "L", "债券型")],
                "D": [fund_meta("510999.SH", "D", "货币型")],
            }.get(params["status"], [])
            return pd.DataFrame(rows)
        if api_name == "fund_daily":
            return pd.DataFrame(
                [
                    bar(code, trade_date=params["trade_date"])
                    for code in ("510300.SH", "159919.SZ", "160641.SZ")
                ]
            )
        if api_name == "fund_adj":
            return pd.DataFrame(
                [
                    dict(ts_code=code, trade_date=params["trade_date"], adj_factor=1.125)
                    for code in ("510300.SH", "159919.SZ", "160641.SZ")
                ]
            )
        if api_name == "opt_daily":
            exchange = params["exchange"]
            return pd.DataFrame(
                [
                    bar(
                        OPTIONS[exchange][0],
                        exchange=exchange,
                        trade_date=params["trade_date"],
                        vol=10,
                        oi=None,
                        settle=1.22,
                        pre_settle=1.2,
                    )
                ]
            )
        if api_name == "opt_basic":
            meta = option_meta(params["exchange"])
            if "ts_code" in params:
                assert meta["ts_code"] == params["ts_code"]
            else:
                assert meta["opt_code"] == params["opt_code"]
            return pd.DataFrame([meta])
        raise AssertionError(f"Unexpected endpoint {api_name}")


@pytest.fixture
def asset_setup(tmp_raw_root):
    ctx = TushareRawContext(
        paths=tmp_raw_root,
        start_date=20240102,
        end_date=20240102,
        rate_limit={"max_retries": 1, "retry_backoff_base_sec": 0, "sleep_between_requests_sec": 0},
    )
    client = AssetClient()
    CalendarFetcher(client, ctx).fetch()
    OptionCalendarFetcher(client, ctx).fetch()
    return tmp_raw_root, ctx, client


def prepare_assets(setup):
    paths, ctx, client = setup
    for cls in (
        EtfInstrumentsFetcher,
        FundBasicFetcher,
        FundDailyFetcher,
        FundAdjFetcher,
        OptionDailyFetcher,
        OptionInstrumentsFetcher,
    ):
        cls(client, ctx).fetch("init")
    return paths


def importer(cls, paths):
    obj = cls(cast(psycopg.Connection, None), IngestContext(paths=paths, months=("2024-01",)))

    def ids(codes, asset):
        all_codes = ["510300.SH", "159919.SZ", *[c for pair in OPTIONS.values() for c in pair]]
        return {code: all_codes.index(code) + 1 for code in codes}

    obj._ids = ids
    return obj


def replace_fixture(path, frame):
    """模拟新源观察，让数值门禁用例通过完整性层，而非误测文件篡改。"""
    write_parquet(frame, path)
    receipt_path = path.with_suffix(".json")
    receipt = json.loads(receipt_path.read_text())
    receipt["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt))


def test_raw_request_order_scope_and_source_values(asset_setup):
    paths = prepare_assets(asset_setup)
    _, _, client = asset_setup
    assert {p["list_status"] for api, p in client.calls if api == "etf_basic"} == {"L", "D", "P"}
    assert {p["exchange"] for api, p in client.calls if api == "opt_daily"} == set(OPTION_EXCHANGES)
    options = pd.read_parquet(paths.dataset_file("tushare", "instruments", "option"))
    assert set(options.ts_code) == {x[0] for x in OPTIONS.values()}
    assert options.loc[options.exchange.eq("CZCE"), "opt_code"].iloc[0] == "OPAP2405.ZCE"
    assert "AP405C8000.ZCE" in set(options.ts_code)
    fund = pd.read_parquet(paths.dataset_file("tushare", "fund_daily", "2024-01"))
    assert len(fund) == 3 and "160641.SZ" in set(fund.ts_code)
    assert fund.vol.iloc[0] == 10.25
    receipt = json.loads(
        paths.dataset_file("tushare", "instruments", "option").with_suffix(".json").read_text()
    )
    assert receipt["scope"]["coverage"] == "observed_daily_codes"
    assert receipt["historical_parameters_verified"] is False


def test_new_raw_endpoints_are_opt_in(monkeypatch, asset_setup):
    import gr_data.raw as raw
    from gr_data.raw.tushare.fetchers import DEFAULT_DATASETS

    paths, ctx, client = asset_setup
    selected = []

    class Fetcher:
        def __init__(self, *_):
            pass

        def fetch(self, **kwargs):
            return 1

    class Registry(dict):
        def __getitem__(self, name):
            selected.append(name)
            return Fetcher

    from gr_data.raw.tushare.fetchers import REGISTRY

    monkeypatch.setattr(raw, "_registry", lambda _: Registry(REGISTRY))
    monkeypatch.setattr(raw, "_build_client", lambda *_: client)
    monkeypatch.setattr(raw, "_build_context", lambda *_: ctx)
    raw.run_provider("tushare", Config())
    assert tuple(selected) == DEFAULT_DATASETS
    assert "opt_daily" not in selected and "fund_daily" not in selected


def test_new_ingest_endpoints_are_opt_in():
    from gr_data.ingest.tushare.importers import DEFAULT_DATASETS

    assert plan_importers("tushare", Config()) == list(DEFAULT_DATASETS)
    assert plan_importers("tushare", Config(), ["all"]) == list(DEFAULT_DATASETS)
    assert plan_importers("tushare", Config(), ["etf_bars_1d", "etf_reference"]) == [
        "etf_instruments",
        "etf_symbol_map",
        "etf_profile",
        "etf_bar_1d",
    ]


def test_option_exchange_filter_and_calendar(asset_setup):
    paths, ctx, client = asset_setup
    ctx.option_exchanges = ("CZCE",)
    client.calls.clear()
    OptionCalendarFetcher(client, ctx).fetch()
    OptionDailyFetcher(client, ctx).fetch()
    assert {p["exchange"] for _, p in client.calls} == {"CZCE"}
    assert len(pd.read_parquet(paths.dataset_file("tushare", "opt_daily", "2024-01"))) == 1


@pytest.mark.parametrize("value", [[], ["BAD"], ["SSE", ""], "SSE"])
def test_option_exchange_config_rejects_bad_values(value):
    with pytest.raises(ValueError):
        build_context(Config({"providers": {"tushare": {"option_exchanges": value}}}))


def test_option_scope_narrowing_and_partial_updates_preserve_old_rows(asset_setup):
    paths, ctx, client = asset_setup
    OptionDailyFetcher(client, ctx).fetch("init")
    ctx.option_exchanges = ("CZCE",)
    ctx.start_date = ctx.end_date = 20240103
    OptionDailyFetcher(client, ctx).fetch("update")
    raw = pd.read_parquet(paths.dataset_file("tushare", "opt_daily", "2024-01"))
    assert len(raw) == 9
    assert set(raw.loc[raw.trade_date.eq("20240102"), "exchange"]) == set(OPTION_EXCHANGES)
    assert raw.loc[raw.trade_date.eq("20240103"), "exchange"].tolist() == ["CZCE"]


@pytest.mark.parametrize("kind", ["empty", "wrong_date", "wrong_exchange", "conflict"])
def test_failed_option_response_preserves_partition(asset_setup, kind):
    paths, ctx, client = asset_setup
    OptionDailyFetcher(client, ctx).fetch()
    path = paths.dataset_file("tushare", "opt_daily", "2024-01")
    before = path.read_bytes()

    def broken(params):
        row = bar(OPTIONS["SSE"][0], exchange="SSE", vol=1, oi=1, settle=1.2, pre_settle=1)
        if kind == "empty":
            return pd.DataFrame()
        if kind == "wrong_date":
            row["trade_date"] = "20240103"
        if kind == "wrong_exchange":
            row["exchange"] = "SZSE"
        rows = [row, {**row, "close": 1.22}] if kind == "conflict" else [row]
        return pd.DataFrame(rows)

    client.override["opt_daily"] = broken
    with pytest.raises(ValueError):
        OptionDailyFetcher(client, ctx).fetch()
    assert path.read_bytes() == before


def test_missing_calendar_day_is_not_a_holiday(asset_setup):
    paths, ctx, client = asset_setup
    file = paths.dataset_file("tushare", "calendar", "SSE")
    frame = pd.read_parquet(file)
    write_parquet(frame.loc[frame.cal_date.ne("20240102")], file)
    with pytest.raises(ValueError, match="Incomplete trading calendar"):
        FundDailyFetcher(client, ctx).fetch()


def test_option_metadata_requires_exact_source_identity(asset_setup):
    paths, ctx, client = asset_setup
    OptionDailyFetcher(client, ctx).fetch()
    client.override["opt_basic"] = lambda p: pd.DataFrame(
        [{**option_meta(p["exchange"]), "ts_code": "AP2405C8000.ZCE"}]
    )
    with pytest.raises(RuntimeError, match="Unresolved"):
        OptionInstrumentsFetcher(client, ctx).fetch()
    assert not paths.dataset_file("tushare", "instruments", "option").exists()


def test_observations_preserve_previous_raw(asset_setup):
    paths, ctx, client = asset_setup
    FundDailyFetcher(client, ctx).fetch()
    before = pd.read_parquet(paths.dataset_file("tushare", "fund_daily", "2024-01"))
    FundDailyFetcher(client, ctx).fetch()
    roots = list(paths.dataset_dir("tushare", "observations").glob("fund_daily/*"))
    assert len(roots) == 2
    previous = next(p / "previous.parquet" for p in roots if (p / "previous.parquet").exists())
    pd.testing.assert_frame_equal(before, pd.read_parquet(previous))


def test_etf_transform_uses_authoritative_subset_factors_and_units(asset_setup):
    paths = prepare_assets(asset_setup)
    obj = importer(EtfBars1dImporter, paths)
    frame = obj.build()
    assert len(frame) == 2
    assert frame.volume.tolist() == [1025, 1025]
    assert frame.amount.tolist() == [Decimal("123.4000")] * 2
    assert frame.adj_factor.tolist() == [Decimal("1.125")] * 2
    assert frame.close.iloc[0] == Decimal("1.25")
    assert frame.dt.tolist() == [date(2024, 1, 2)] * 2
    reference = importer(EtfInstrumentsImporter, paths).build().set_index("symbol")
    assert reference.loc["510999.SH", "status"] == "delisted"
    assert pd.isna(reference.loc["510999.SH", "delist_date"])
    assert "159999.SZ" not in reference.index


def test_option_transform_preserves_hands_and_contract_metadata(asset_setup):
    paths = prepare_assets(asset_setup)
    bars = importer(OptionBars1dImporter, paths).build()
    assert len(bars) == 8
    assert bars.volume.tolist() == [10] * 8
    assert bars.amount.tolist() == [Decimal("1234.0000")] * 8
    assert bars.open_interest.isna().all()
    assert bars.settle.iloc[0] == Decimal("1.22")
    contract = importer(OptionContractsImporter, paths).build()
    assert contract.multiplier.tolist() == [Decimal("10")] * 8
    assert contract.option_type.tolist() == ["C"] * 8
    assert contract.exercise_style.value_counts().to_dict() == {"american": 5, "european": 3}
    assert contract.exercise_date.tolist() == [date(2024, 3, 1)] * 8
    assert contract.last_trade_date.tolist() == [date(2024, 2, 28)] * 8


@pytest.mark.parametrize("cls", [OptionBars1dImporter, OptionContractsImporter])
def test_option_production_writes_blocked_before_connection(cls, tmp_raw_root):
    obj = importer(cls, tmp_raw_root)
    with pytest.raises(IngestGateError, match="validation-only"):
        obj.run()


@pytest.mark.parametrize("value", [0, -1, float("inf"), None, "bad"])
def test_etf_factor_never_filled_or_rounded(asset_setup, value):
    paths = prepare_assets(asset_setup)
    file = paths.dataset_file("tushare", "fund_adj", "2024-01")
    rows = pd.read_parquet(file).astype(object)
    rows.loc[0, "adj_factor"] = value
    # 字符串坏值以完整字符串列写入，避免 Arrow 的 mixed dtype 干扰目标门禁。
    if value == "bad":
        rows["adj_factor"] = rows.adj_factor.astype(str)
    replace_fixture(file, rows)
    with pytest.raises(ValueError):
        importer(EtfBars1dImporter, paths).build()


@pytest.mark.parametrize(
    "column,value",
    [
        ("vol", -1),
        ("vol", 0.001),
        ("amount", "bad"),
        ("amount", float("inf")),
        ("close", -0.1),
        ("high", 1.0),
    ],
)
def test_etf_bad_values_fail_before_copy(asset_setup, column, value):
    paths = prepare_assets(asset_setup)
    file = paths.dataset_file("tushare", "fund_daily", "2024-01")
    rows = pd.read_parquet(file).astype(object)
    rows.loc[0, column] = value
    if value == "bad":
        rows[column] = rows[column].astype(str)
    replace_fixture(file, rows)
    with pytest.raises(ValueError):
        importer(EtfBars1dImporter, paths).build()


def test_settlement_only_option_nulls_are_preserved():
    row = bar(
        "10000001.SH",
        exchange="SSE",
        vol=0,
        oi=None,
        open=None,
        high=None,
        low=None,
        close=None,
        pre_close=None,
        settle=1.2,
        pre_settle=None,
    )
    frame = validate_bars(pd.DataFrame([row]), option=True)
    assert frame.close.isna().all() and frame.vol.tolist() == [0]
    row["settle"] = None
    with pytest.raises(ValueError, match="No usable"):
        validate_bars(pd.DataFrame([row]), option=True)


@pytest.mark.parametrize("value", [-1, float("inf"), "bad", 0.5, 2**63])
def test_option_hand_counts_are_exact_nonnegative_bigint(value):
    with pytest.raises(ValueError):
        numeric_values(pd.Series([value]), "oi", integer=True)


def test_null_integer_does_not_become_float_and_precision_is_checked():
    values = numeric_values(pd.Series([10, None]), "oi", integer=True)
    assert values.tolist() == [10, None] and type(values.iloc[0]) is int
    with pytest.raises(ValueError, match="precision loss"):
        numeric_values(pd.Series(["0.0000001"]), "close")
    with pytest.raises(ValueError, match="overflow"):
        numeric_values(pd.Series(["100000000000000"]), "close")


@pytest.mark.parametrize("api", ["fund_daily", "fund_adj", "etf_basic", "opt_basic", "opt_daily"])
def test_new_pagination_exact_multiple_and_repeated_page(api):
    client = TushareProClient("unused", sleep_between_requests=0)
    limit = PAGE_LIMITS[api]
    calls = []

    def query(api_name, **params):
        calls.append(params["offset"])
        if params["offset"]:
            return pd.DataFrame()
        return pd.DataFrame({"ts_code": [f"code{i}" for i in range(limit)]})

    client.query = query
    assert len(client.query_all(api)) == limit
    assert calls == [0, limit]

    def repeat(api_name, **params):
        return pd.DataFrame({"ts_code": [f"code{i}" for i in range(limit)]})

    client.query = repeat
    with pytest.raises(RuntimeError, match="Repeated pagination"):
        client.query_all(api)


def test_missing_underlying_is_a_hard_failure(asset_setup):
    paths = prepare_assets(asset_setup)
    obj = importer(OptionContractsImporter, paths)
    original = obj._ids

    def resolve(codes, asset):
        if asset == "future":
            raise IngestGateError("Unresolved future symbols")
        return original(codes, asset)

    obj._ids = resolve
    with pytest.raises(IngestGateError, match="Unresolved future"):
        obj.build()


def test_symbol_map_conflict_is_not_overwritten(asset_setup):
    paths = prepare_assets(asset_setup)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.side_effect = [
        [
            ("510300.SH", 1, "XSHG"),
            ("159919.SZ", 2, "XSHE"),
            ("510999.SH", 3, "XSHG"),
        ],
        [("510300.SH", 999)],
    ]
    with pytest.raises(IngestGateError, match="Conflicting existing"):
        EtfSymbolMapImporter(conn, IngestContext(paths=paths)).build()


@pytest.mark.parametrize(
    ("cls", "expected_rows"),
    [(EtfInstrumentsImporter, 3), (EtfSymbolMapImporter, 3), (EtfBars1dImporter, 2)],
)
def test_pending_etf_warning_reaches_ingest_result(asset_setup, monkeypatch, cls, expected_rows):
    """待上市排除告警必须进入运行结果和记账，离线验证不依赖 PG 可用性。"""
    paths = prepare_assets(asset_setup)
    obj = importer(cls, paths)
    obj.conn = MagicMock()
    obj.conn.cursor.return_value.__enter__.return_value.fetchall.side_effect = [
        [
            ("510300.SH", 1, "XSHG"),
            ("159919.SZ", 2, "XSHE"),
            ("510999.SH", 3, "XSHG"),
        ],
        [],
    ]
    record_run = MagicMock()
    monkeypatch.setattr(obj, "_record_run", record_run)
    with (
        patch("gr_data.ingest.base.OwnershipManager"),
        patch(
            "gr_data.ingest.base.upsert_rows", side_effect=lambda _conn, _contract, rows: len(rows)
        ),
    ):
        result = obj.run()
    assert result.rows_written == expected_rows
    assert result.warnings == ["Skipped pending ETF rows=1 samples=['159999.SZ']"]
    assert not result.ok
    record_run.assert_called_once_with(expected_rows, result.warnings)


@pytest.mark.integration
@pytest.mark.parametrize("quote_case", ["ordinary", "settlement_only", "expiry_zero"])
def test_etf_options_pg_roundtrip_and_replay(pg_conn, asset_setup, quote_case):
    if quote_case != "ordinary":
        client = asset_setup[2]
        original = client.query_all

        def source(api, **params):
            frame = original(api, **params)
            if api == "opt_daily" and params["exchange"] == "CZCE":
                frame.loc[:, ["open", "high", "low", "close", "vol", "amount"]] = 0
                frame["oi"] = 33
            if quote_case == "expiry_zero" and params.get("exchange") in ("CZCE", "GFEX"):
                if api == "opt_daily":
                    frame.loc[:, ["open", "high", "low", "close", "settle", "amount", "oi"]] = 0
                    frame["vol"] = 5 if params["exchange"] == "GFEX" else 0
                elif api == "opt_basic":
                    frame["delist_date"] = "20240102"
            return frame

        client.query_all = source
    paths = prepare_assets(asset_setup)
    # 标的期货 / 指数只有参考身份，本用例不写其行情或修改已有表归属。
    with pg_conn.cursor() as cur:
        for exchange, (_code, underlying) in OPTIONS.items():
            if exchange in ("SSE", "SZSE"):
                continue
            asset = "index" if exchange == "CFFEX" else "future"
            canonical = "XSHG" if asset == "index" else exchange
            cur.execute(
                "INSERT INTO meta.instruments(symbol,asset,exchange,list_date) "
                "VALUES(%s,%s,%s,%s) RETURNING instrument_id",
                (underlying, asset, canonical, date(2023, 1, 2)),
            )
            iid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meta.symbol_map(instrument_id,source,source_symbol) "
                "VALUES(%s,'tushare',%s)",
                (iid, underlying),
            )
    pg_conn.commit()
    cfg = Config(
        {
            "paths": {"raw_root": str(paths.root)},
        },
        Environment(paths.root, {"TUSHARE_OPTION_VALIDATION_ONLY": "1"}),
    )
    for _ in range(2):
        results = run_provider(
            "tushare",
            pg_conn,
            cfg,
            only=["etf_reference", "option_reference", "etf_bars_1d", "option_bars_1d"],
            months=("2024-01",),
        )
        assert [r.rows_written for r in results] == [3, 3, 3, 8, 8, 8, 2, 8]
        assert [r.dataset for r in results if r.warnings] == [
            "etf_instruments",
            "etf_symbol_map",
            "etf_profile",
            "option_contracts",
            "etf_bar_1d",
            "option_bar_1d",
        ]
        profile_warnings = next(r.warnings for r in results if r.dataset == "etf_profile")
        assert all("Skipped pending ETF" in w for w in profile_warnings)
        with pg_conn.cursor() as cur:
            # fund_basic 精确连接：单位换算（亿份→份、万元→元）与类型原样落库
            cur.execute(
                "SELECT i.symbol, p.fund_type, p.channel, p.issue_amount, p.min_amount "
                "FROM meta.etf_profile p JOIN meta.instruments i USING (instrument_id) "
                "ORDER BY i.symbol"
            )
            assert cur.fetchall() == [
                ("159919.SZ", "债券型", "QDII", Decimal("1250000000.0000"), Decimal("1000.0000")),
                ("510300.SH", "股票型", "QDII", Decimal("1250000000.0000"), Decimal("1000.0000")),
                ("510999.SH", "货币型", "QDII", Decimal("1250000000.0000"), Decimal("1000.0000")),
            ]
            cur.execute("SELECT volume,amount,adj_factor,close FROM market.etf_bar_1d")
            assert (
                cur.fetchall()
                == [(1025, Decimal("123.4000"), Decimal("1.12500000"), Decimal("1.250000"))] * 2
            )
            cur.execute(
                "SELECT volume,amount,open_interest,settle FROM market.option_bar_1d "
                "WHERE close IS NOT NULL"
            )
            assert (
                cur.fetchall()
                == [(10, Decimal("1234.0000"), None, Decimal("1.220000"))]
                * ({"ordinary": 8, "settlement_only": 7, "expiry_zero": 6}[quote_case])
            )
            cur.execute(
                "SELECT open,high,low,close,volume,amount,open_interest,settle "
                "FROM market.option_bar_1d WHERE close IS NULL"
            )
            expected_null = (
                [(None, None, None, None, 0, Decimal("0"), 33, Decimal("1.22"))]
                if quote_case == "settlement_only"
                else []
            )
            if quote_case == "expiry_zero":
                expected_null = [
                    (None, None, None, None, vol, Decimal("0"), 0, Decimal("0")) for vol in (0, 5)
                ]
            assert sorted(cur.fetchall(), key=lambda r: r[4]) == expected_null
            cur.execute("SELECT multiplier,underlying_id FROM meta.option_contracts")
            assert all(m == 10 and iid is not None for m, iid in cur.fetchall())
            cur.execute("SELECT count(*) FROM meta.option_contracts")
            assert cur.fetchone()[0] == 8
        # 全部 canonical 字段逐项核对，不能只靠行数和少数字段证明链路正确。
        for cls in (EtfBars1dImporter, OptionBars1dImporter, OptionContractsImporter):
            obj = cls(pg_conn, ctx=IngestContext(paths=paths, months=("2024-01",)))
            expected = obj._df_to_rows(obj.build())
            with pg_conn.cursor() as cur:
                cur.execute(
                    f"SELECT {','.join(obj.contract.columns)} FROM {obj.contract.qualified}"
                )
                assert sorted(cur.fetchall(), key=lambda r: r[0]) == sorted(
                    expected, key=lambda r: r[0]
                )


@pytest.mark.parametrize("setting", [None, "false", "", "invalid"])
def test_option_group_preflight_refuses_unapproved_writes(tmp_path, setting):
    values = {} if setting is None else {"TUSHARE_OPTION_VALIDATION_ONLY": setting}
    cfg = Config({}, Environment(tmp_path, values))
    with pytest.raises(RuntimeError, match="validation-only|boolean"):
        plan_importers("tushare", cfg, ["option_reference"])


def test_option_validation_cannot_be_enabled_in_prod(tmp_path):
    cfg = Config(
        {}, Environment(tmp_path, {"TUSHARE_OPTION_VALIDATION_ONLY": "1", "APP_ENV": "prod"})
    )
    with pytest.raises(RuntimeError, match="APP_ENV=prod"):
        plan_importers("tushare", cfg, ["option_reference"])


@pytest.mark.parametrize("kind", ["missing", "hash_mismatch", "invalid_json"])
def test_asset_receipt_integrity_is_required(asset_setup, kind):
    paths = prepare_assets(asset_setup)
    path = paths.dataset_file("tushare", "fund_daily", "2024-01").with_suffix(".json")
    if kind == "missing":
        path.unlink()
    elif kind == "invalid_json":
        path.write_text("{")
    else:
        data = json.loads(path.read_text())
        data["sha256"] = "0" * 64
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="receipt"):
        importer(EtfBars1dImporter, paths).build()


def test_raw_without_receipt_is_not_overwritten(asset_setup):
    """收据缺失且文件对不上任何观察清单（手工放置／改动）时拒绝，字节不变。"""
    paths, ctx, client = asset_setup
    FundDailyFetcher(client, ctx).fetch()
    path = paths.dataset_file("tushare", "fund_daily", "2024-01")
    frame = pd.read_parquet(path)
    frame["amount"] = frame["amount"] + 1
    write_parquet(frame, path)
    path.with_suffix(".json").unlink()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="receipt"):
        FundDailyFetcher(client, ctx).fetch()
    assert path.read_bytes() == before


@pytest.mark.parametrize("asset", ["etf", "option"])
def test_asset_mapping_rejects_wrong_exchange(asset_setup, asset):
    paths = prepare_assets(asset_setup)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    code = "510300.SH" if asset == "etf" else OPTIONS["SSE"][0]
    cur.fetchall.return_value = [(code, 1, "XSHE")]
    cls = EtfBars1dImporter if asset == "etf" else OptionBars1dImporter
    with pytest.raises(IngestGateError, match="wrong asset exchange"):
        cls(conn, IngestContext(paths=paths))._ids([code], asset)


@pytest.mark.parametrize(
    "field,value",
    [
        ("call_put", "X"),
        ("exercise_type", "unknown"),
        ("opt_multiplier", 0),
        ("opt_multiplier", None),
        ("exercise_price", -1),
    ],
)
def test_invalid_option_contract_parameters_rejected(asset_setup, field, value):
    paths = prepare_assets(asset_setup)
    file = paths.dataset_file("tushare", "instruments", "option")
    data = pd.read_parquet(file).astype(object)
    data.loc[0, field] = value
    replace_fixture(file, data)
    with pytest.raises(ValueError):
        importer(OptionContractsImporter, paths).build()


def test_put_and_missing_optional_last_date_are_preserved(asset_setup):
    paths = prepare_assets(asset_setup)
    file = paths.dataset_file("tushare", "instruments", "option")
    data = pd.read_parquet(file).astype(object)
    # ETF 期权代码是数字，C/P 只能从显式源字段读，不能从代码猜。
    data.loc[0, "call_put"] = "P"
    data.loc[0, "delist_date"] = None
    replace_fixture(file, data)
    frame = importer(OptionContractsImporter, paths).build()
    assert frame.option_type.iloc[0] == "P"
    assert pd.isna(frame.last_trade_date.iloc[0])
    assert len(importer(OptionBars1dImporter, paths).build()) == 8


def test_daily_lifecycle_and_partition_boundaries_are_enforced(asset_setup):
    paths = prepare_assets(asset_setup)
    file = paths.dataset_file("tushare", "instruments", "option")
    data = pd.read_parquet(file).astype(object)
    data.loc[0, "list_date"] = "20240103"
    replace_fixture(file, data)
    with pytest.raises(IngestGateError, match="precedes"):
        importer(OptionBars1dImporter, paths).build()
    file = paths.dataset_file("tushare", "fund_daily", "2024-01")
    data = pd.read_parquet(file).astype(object)
    data.loc[0, "trade_date"] = "20240201"
    replace_fixture(file, data)
    with pytest.raises(IngestGateError, match="Out-of-partition"):
        importer(EtfBars1dImporter, paths).build()


def test_factor_date_does_not_carry_forward_or_backward(asset_setup):
    paths = prepare_assets(asset_setup)
    file = paths.dataset_file("tushare", "fund_adj", "2024-01")
    data = pd.read_parquet(file).astype(object)
    data.loc[0, "trade_date"] = "20240103"
    replace_fixture(file, data)
    with pytest.raises(IngestGateError, match="Missing ETF adjustment factor"):
        importer(EtfBars1dImporter, paths).build()


def test_multiple_months_require_explicit_batching(asset_setup):
    paths = prepare_assets(asset_setup)
    obj = importer(EtfBars1dImporter, paths)
    obj.ctx.months = ("2024-01", "2024-02")
    # 缺分区和大范围隐式加载都不能悄悄变成单月成功。
    with pytest.raises(IngestGateError, match="missing raw partitions"):
        obj.build()


# ---- 以下用例追加到 packages/gr-data/tests/test_tushare_etf_options.py 末尾 ----
# 需补充的 import（放到文件顶部 import 区）：
#   import os
#   from unittest.mock import patch
#   from gr_data.common.parquet import read_parquet_strict
#   from gr_data.ingest.tushare.importers.asset_markets import (
#       OptionInstrumentsImporter, OptionSymbolMapImporter)
#   from gr_data.raw.tushare.asset_rules import read_asset_observation
#   from gr_data.raw.tushare.fetchers import asset_markets as raw_asset_markets


def _two_day_setup(tmp_raw_root):
    """0102、0103 两个开市日；today 由各用例单独钉住。"""
    ctx = TushareRawContext(
        paths=tmp_raw_root,
        start_date=20240102,
        end_date=20240103,
        rate_limit={"max_retries": 1, "retry_backoff_base_sec": 0, "sleep_between_requests_sec": 0},
    )
    client = AssetClient()
    CalendarFetcher(client, ctx).fetch()
    OptionCalendarFetcher(client, ctx).fetch()
    return ctx, client


def _empty_on(client, api, day):
    original = client.query_all

    def query_all(api_name, **params):
        if api_name == api and params.get("trade_date") == day:
            return pd.DataFrame()
        return original(api_name, **params)

    client.query_all = query_all


@pytest.mark.parametrize("cls", [FundDailyFetcher, FundAdjFetcher, OptionDailyFetcher])
def test_unpublished_today_is_not_a_failure(tmp_raw_root, monkeypatch, cls):
    """P0-1：今天开市但供应商尚未发布，空响应不能让整月失败，与旧日线 d < today 规则一致。"""
    ctx, client = _two_day_setup(tmp_raw_root)
    _empty_on(client, cls.API_NAME, "20240103")
    monkeypatch.setattr(raw_asset_markets, "today_int", lambda: 20240103)
    assert cls(client, ctx).fetch("update") == 1
    frame = read_parquet_strict(tmp_raw_root.dataset_file("tushare", cls.DATASET, "2024-01"))
    assert frame is not None
    assert set(frame["trade_date"].astype(str)) == {"20240102"}


@pytest.mark.parametrize("cls", [FundDailyFetcher, FundAdjFetcher, OptionDailyFetcher])
def test_past_empty_open_day_still_fails(tmp_raw_root, monkeypatch, cls):
    """P0-1 边界：已过去的开市日空响应仍须失败，修复不能放宽成“空就跳过”。"""
    ctx, client = _two_day_setup(tmp_raw_root)
    _empty_on(client, cls.API_NAME, "20240103")
    monkeypatch.setattr(raw_asset_markets, "today_int", lambda: 20240104)
    with pytest.raises(ValueError, match="Unexplained empty"):
        cls(client, ctx).fetch("update")


@pytest.mark.parametrize("names", [["option_instruments"], ["option_symbol_map"]])
def test_option_identity_writes_are_gated_before_connection(tmp_path, names):
    """P0-2：期权身份写入同属正式期权写入，未开验证开关时在连库前拒绝。"""
    cfg = Config({}, Environment(tmp_path, {}))
    with pytest.raises(RuntimeError, match="validation-only"):
        plan_importers("tushare", cfg, names)


@pytest.mark.parametrize("cls", [OptionInstrumentsImporter, OptionSymbolMapImporter])
def test_option_identity_library_writes_blocked(cls, tmp_raw_root):
    """P0-2：库调用 .run() 也须在 claim／写库前拒绝，不能只靠 CLI 计划。"""
    obj = importer(cls, tmp_raw_root)
    with pytest.raises(IngestGateError, match="validation-only"):
        obj.run()


def test_crash_before_receipt_is_recoverable_by_refetch(asset_setup):
    """P1-3：parquet 已替换、收据未写时崩溃，文件哈希能对上本轮观察清单，重新采集应自愈。"""
    paths, ctx, client = asset_setup
    FundDailyFetcher(client, ctx).fetch("init")
    original = client.query_all

    def revised(api_name, **params):
        frame = original(api_name, **params)
        if api_name == "fund_daily":
            frame["amount"] = frame["amount"] + 1  # 供应商修订
        return frame

    client.query_all = revised
    real_replace = os.replace

    def crash_on_receipt(src, dst):
        if str(dst).endswith(".json"):
            raise OSError("simulated crash before receipt")
        return real_replace(src, dst)

    with (
        patch("os.replace", side_effect=crash_on_receipt),
        pytest.raises(OSError, match="simulated crash"),
    ):
        FundDailyFetcher(client, ctx).fetch("update")
    path = paths.dataset_file("tushare", "fund_daily", "2024-01")
    with pytest.raises(ValueError, match="receipt"):
        read_asset_observation(path)  # 修复前后入库侧都必须拒绝
    assert FundDailyFetcher(client, ctx).fetch("update") == 1
    frame, receipt = read_asset_observation(path)
    assert frame is not None
    assert receipt["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_tampered_raw_is_still_not_overwritten(asset_setup):
    """P1-3 边界：哈希对不上任何观察清单的文件（手工改动）仍拒绝覆盖。"""
    paths, ctx, client = asset_setup
    FundDailyFetcher(client, ctx).fetch("init")
    path = paths.dataset_file("tushare", "fund_daily", "2024-01")
    frame = pd.read_parquet(path)
    frame["amount"] = frame["amount"] + 1
    write_parquet(frame, path)
    tampered = path.read_bytes()
    with pytest.raises(ValueError, match="receipt"):
        FundDailyFetcher(client, ctx).fetch("update")
    assert path.read_bytes() == tampered


def _opt_basic_calls(client):
    return [
        params.get("ts_code", params.get("opt_code"))
        for api, params in client.calls
        if api == "opt_basic"
    ]


def _prepare_option_daily(asset_setup):
    paths, ctx, client = asset_setup
    OptionDailyFetcher(client, ctx).fetch("init")
    return paths, ctx, client


def test_update_skips_contracts_observed_after_expiry(asset_setup):
    """P2-5：合约到期后已观察过的参数不再变化，update 不应再查 opt_basic。"""
    paths, ctx, client = _prepare_option_daily(asset_setup)
    OptionInstrumentsFetcher(client, ctx).fetch("init")  # 真实今天远晚于夹具到期日 20240228
    first = len(_opt_basic_calls(client))
    assert first == 16  # 首次每个未知标的一次引导、一次批量查询。
    OptionInstrumentsFetcher(client, ctx).fetch("update")
    assert len(_opt_basic_calls(client)) == first  # 增量后不再发起请求
    frame, _ = read_asset_observation(paths.dataset_file("tushare", "instruments", "option"))
    assert frame is not None and len(frame) == 8  # 已有记录原样保留


def test_update_requeries_contracts_still_listed(asset_setup, monkeypatch):
    """P2-5 边界：上次观察时合约尚未到期，参数可能被调整，update 必须重查。"""
    paths, ctx, client = _prepare_option_daily(asset_setup)
    monkeypatch.setattr(raw_asset_markets, "today_int", lambda: 20240110)
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    OptionInstrumentsFetcher(client, ctx).fetch("update")
    assert len(_opt_basic_calls(client)) == 24


def test_init_forces_full_reobservation(asset_setup):
    """P2-5 边界：init 仍全量重查，供人工复核参数调整时使用。"""
    paths, ctx, client = _prepare_option_daily(asset_setup)
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    assert len(_opt_basic_calls(client)) == 24


@pytest.mark.parametrize("cls", [FundDailyFetcher, FundAdjFetcher, OptionDailyFetcher])
def test_pending_today_preserves_existing_rows_and_receipt(tmp_raw_root, monkeypatch, cls):
    ctx, client = _two_day_setup(tmp_raw_root)
    cls(client, ctx).fetch("init")
    path = tmp_raw_root.dataset_file("tushare", cls.DATASET, "2024-01")
    before = pd.read_parquet(path)
    _empty_on(client, cls.API_NAME, "20240103")
    monkeypatch.setattr(raw_asset_markets, "today_int", lambda: 20240103)
    cls(client, ctx).fetch("update")
    after, receipt = read_asset_observation(path)
    assert after is not None
    pd.testing.assert_frame_equal(
        before.sort_values(["trade_date", "ts_code"]).reset_index(drop=True),
        after.sort_values(["trade_date", "ts_code"]).reset_index(drop=True),
    )
    pending = receipt["scope"]["pending_days"]
    assert {item["trade_date"] for item in pending} == {"20240103"}
    assert {item["exchange"] for item in pending} == (
        set(OPTION_EXCHANGES) if cls is OptionDailyFetcher else {"fund"}
    )


def test_one_option_market_pending_does_not_block_other_markets(tmp_raw_root, monkeypatch):
    ctx, client = _two_day_setup(tmp_raw_root)
    OptionDailyFetcher(client, ctx).fetch("init")
    original = client.query_all

    def delayed(api_name, **params):
        if api_name == "opt_daily" and params["trade_date"] == "20240103":
            if params["exchange"] == "SSE":
                return pd.DataFrame()
            frame = original(api_name, **params)
            frame["amount"] += 1
            return frame
        return original(api_name, **params)

    client.query_all = delayed
    monkeypatch.setattr(raw_asset_markets, "today_int", lambda: 20240103)
    OptionDailyFetcher(client, ctx).fetch("update")
    frame, receipt = read_asset_observation(
        tmp_raw_root.dataset_file("tushare", "opt_daily", "2024-01")
    )
    assert frame is not None
    today = frame.loc[frame.trade_date.eq("20240103")].set_index("exchange")
    assert today.loc["SSE", "amount"] == pytest.approx(0.1234)
    assert today.loc["DCE", "amount"] == pytest.approx(1.1234)
    assert receipt["scope"]["pending_days"] == [{"trade_date": "20240103", "exchange": "SSE"}]


@pytest.mark.parametrize("missing_receipt", [True, False])
def test_invalid_old_asset_does_not_create_empty_observation(asset_setup, missing_receipt):
    paths, ctx, client = asset_setup
    FundDailyFetcher(client, ctx).fetch("init")
    observations = paths.dataset_dir("tushare", "observations") / "fund_daily"
    before = set(observations.iterdir())
    path = paths.dataset_file("tushare", "fund_daily", "2024-01")
    # 该用例针对无合法观察证据的旧文件；首发崩溃的合法恢复由专门用例覆盖。
    frame = pd.read_parquet(path)
    frame["amount"] += 1
    write_parquet(frame, path)
    if missing_receipt:
        path.with_suffix(".json").unlink()
    with pytest.raises(ValueError, match="receipt"):
        FundDailyFetcher(client, ctx).fetch("update")
    assert set(observations.iterdir()) == before


@pytest.mark.parametrize("damage", ["missing", "hash", "corrupt"])
def test_unverified_observation_dates_force_requery(asset_setup, damage):
    paths, ctx, client = _prepare_option_daily(asset_setup)
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    out = paths.dataset_file("tushare", "instruments", "option")
    _, receipt = read_asset_observation(out)
    observation = paths.dataset_dir("tushare", "observations") / "option_instruments"
    dates_file = observation / receipt["observation_id"] / "observation_dates.parquet"
    if damage == "missing":
        dates_file.unlink()
    elif damage == "hash":
        receipt["observation_dates_sha256"] = "0" * 64
    else:
        dates_file.write_bytes(b"broken parquet")
        receipt["observation_dates_sha256"] = hashlib.sha256(dates_file.read_bytes()).hexdigest()
    out.with_suffix(".json").write_text(json.dumps(receipt))
    assert OptionInstrumentsFetcher(client, ctx).fetch("update") == 1
    assert len(_opt_basic_calls(client)) == 24


def test_expired_update_no_query_means_no_new_observation(asset_setup):
    paths, ctx, client = _prepare_option_daily(asset_setup)
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    root = paths.dataset_dir("tushare", "observations") / "option_instruments"
    before = set(root.iterdir())
    path = paths.dataset_file("tushare", "instruments", "option")
    receipt = path.with_suffix(".json").read_bytes()
    assert OptionInstrumentsFetcher(client, ctx).fetch("update") == 0
    assert set(root.iterdir()) == before
    assert path.with_suffix(".json").read_bytes() == receipt


def _crash_on_receipt(real_replace):
    def replace(src, dst):
        if str(dst).endswith(".json"):
            raise OSError("simulated crash before receipt")
        return real_replace(src, dst)

    return replace


@pytest.mark.parametrize("volume", [0, 1])
def test_sample_fix_ohl_placeholder_preserved_raw_mapped_ingest(asset_setup, volume):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "opt_daily":
            frame.loc[:, ["open", "high", "low"]] = 0
            frame["vol"] = volume
        return frame

    client.query_all = source
    prepare_assets(asset_setup)
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", "opt_daily", "2024-01"))
    assert raw is not None and raw[["open", "high", "low"]].eq(0).all().all()
    for exchange in OPTION_EXCHANGES:
        counts = receipt["scope"]["ohl_zero_placeholder_rows"][exchange]
        assert counts["rows"] == 1 and counts["nonzero_volume_rows"] == int(volume > 0)
        assert counts["samples"] == [{"ts_code": OPTIONS[exchange][0], "trade_date": "20240102"}]
    obj = importer(OptionBars1dImporter, paths)
    result = obj.build()
    assert result[["open", "high", "low"]].isna().all().all()
    assert result.close.tolist() == [Decimal("1.25")] * 8
    assert result.settle.tolist() == [Decimal("1.22")] * 8
    assert result.volume.tolist() == [volume] * 8
    assert result.amount.tolist() == [Decimal("1234")] * 8
    assert any(
        "OHL zero placeholders" in message and f"nonzero_volume_rows={int(volume > 0)}" in message
        for message in obj.soft_warnings
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"open": 0},
        {"open": 0, "high": 0, "low": 0, "close": 0},
        {"close": 1.4},
        {"high": 1.0},
    ],
)
def test_sample_fix_rejects_other_option_bounds(overrides):
    row = bar(
        OPTIONS["DCE"][0], exchange="DCE", vol=1, oi=0, settle=1.22, pre_settle=1.2, **overrides
    )
    with pytest.raises(ValueError, match="OHLC"):
        validate_bars(pd.DataFrame([row]), option=True)


def test_sample_fix_fund_zero_ohl_still_rejected():
    with pytest.raises(ValueError, match="OHLC"):
        validate_bars(pd.DataFrame([bar(open=0, high=0, low=0)]))


@pytest.mark.parametrize("cls", [FundDailyFetcher, FundAdjFetcher])
def test_sample_fix_nonstandard_fund_codes_retained_and_counted(asset_setup, cls):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == cls.API_NAME:
            frame.loc[frame.ts_code.eq("160641.SZ"), "ts_code"] = "161022!1.SZ"
        return frame

    client.query_all = source
    cls(client, ctx).fetch("init")
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", cls.DATASET, "2024-01"))
    assert raw is not None and "161022!1.SZ" in set(raw.ts_code)
    assert receipt["scope"]["nonstandard_code_rows"] == {"rows": 1, "samples": ["161022!1.SZ"]}


def test_sample_fix_nonstandard_codes_excluded_only_at_etf_ingest(asset_setup, caplog):
    paths = prepare_assets(asset_setup)
    for dataset in ("fund_daily", "fund_adj"):
        path = paths.dataset_file("tushare", dataset, "2024-01")
        frame = pd.read_parquet(path)
        frame.loc[frame.ts_code.eq("160641.SZ"), "ts_code"] = "1610221.SZ"
        replace_fixture(path, frame)
    with caplog.at_level("INFO"):
        assert len(importer(EtfBars1dImporter, paths).build()) == 2
    assert "nonstandard_code_rows=1" in caplog.text


def test_sample_fix_invalid_listed_etf_still_rejected(asset_setup):
    paths = prepare_assets(asset_setup)
    path = paths.dataset_file("tushare", "instruments", "etf")
    frame = pd.read_parquet(path)
    frame.loc[frame.ts_code.eq("510300.SH"), "ts_code"] = "515470.OF"
    replace_fixture(path, frame)
    with pytest.raises(IngestGateError, match="ETF exchange"):
        importer(EtfInstrumentsImporter, paths).build()


@pytest.mark.parametrize("canonical_present", [False, True])
def test_verified_etf_conflict_preserved_raw_quarantined_ingest(asset_setup, canonical_present):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "etf_basic" and params["exchange"] == "SZ" and params["list_status"] == "L":
            added = [etf_meta("158008.OF")]
            if canonical_present:
                added.append(etf_meta("158008.SZ"))
            frame = pd.concat([frame, pd.DataFrame(added)], ignore_index=True)
            frame.loc[frame.ts_code.eq("158008.OF"), "exchange"] = "SZ"
        return frame

    client.query_all = source
    prepare_assets(asset_setup)
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", "instruments", "etf"))
    assert raw is not None and "158008.OF" in set(raw.ts_code)
    assert receipt["scope"]["quarantined_rows"] == {"rows": 1, "samples": ["158008.OF"]}
    obj = importer(EtfInstrumentsImporter, paths)
    identities = obj.build()
    assert "158008.OF" not in set(identities.symbol)
    assert ("158008.SZ" in set(identities.symbol)) == canonical_present
    assert any("Quarantined unverified ETF identity rows=1" in s for s in obj.soft_warnings)
    assert len(importer(EtfBars1dImporter, paths).build()) == 2


@pytest.mark.parametrize("exchange,status", [("SH", "L"), ("SZ", "D")])
def test_etf_quarantine_does_not_hide_other_scope_conflicts(asset_setup, exchange, status):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        if (
            api == "etf_basic"
            and params["exchange"] == exchange
            and params["list_status"] == status
        ):
            return pd.DataFrame([dict(etf_meta("158008.OF", status), exchange=exchange)])
        return original(api, **params)

    client.query_all = source
    with pytest.raises(ValueError, match="ETF metadata scope"):
        EtfInstrumentsFetcher(client, ctx).fetch()
    assert not paths.dataset_file("tushare", "instruments", "etf").exists()


def test_czce_settlement_only_raw_and_canonical_mapping(asset_setup):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "opt_daily" and params["exchange"] == "CZCE":
            frame.loc[:, ["open", "high", "low", "close", "vol", "amount"]] = 0
            frame["oi"] = 33
        return frame

    client.query_all = source
    prepare_assets(asset_setup)
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", "opt_daily", "2024-01"))
    assert raw is not None
    czce = raw.loc[raw.exchange.eq("CZCE")]
    assert czce[["open", "high", "low", "close", "vol", "amount"]].eq(0).all().all()
    assert receipt["scope"]["czce_settlement_only_rows"] == {
        "CZCE": {
            "rows": 1,
            "nonzero_activity_rows": 0,
            "samples": [{"ts_code": OPTIONS["CZCE"][0], "trade_date": "20240102"}],
        }
    }
    obj = importer(OptionBars1dImporter, paths)
    out = obj.build()
    iid = obj._ids([OPTIONS["CZCE"][0]], "option")[OPTIONS["CZCE"][0]]
    row = out.loc[out.instrument_id.eq(iid)].iloc[0]
    assert row[["open", "high", "low", "close"]].isna().all()
    assert row.settle == Decimal("1.22") and row.open_interest == 33
    assert row.volume == 0 and row.amount == 0
    assert any("settlement-only OHLC to NULL exchange=CZCE rows=1" in s for s in obj.soft_warnings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"exchange": "DCE", "ts_code": OPTIONS["DCE"][0]},
        {"settle": 0},
        {"settle": None},
        {"close": None},
    ],
)
def test_czce_settlement_only_requires_exact_pattern(overrides):
    row = bar(OPTIONS["CZCE"][0], exchange="CZCE", oi=33, settle=1.22, pre_settle=1.2)
    row.update(open=0, high=0, low=0, close=0, vol=0, amount=0)
    row.update(overrides)
    with pytest.raises(ValueError, match="OHLC|expiry date"):
        validate_bars(pd.DataFrame([row]), option=True)


@pytest.mark.parametrize("volume,amount", [(3, 4.3), (0, 0), (None, None)])
def test_czce_missing_ohlc_preserves_activity(asset_setup, volume, amount):
    paths, _ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "opt_daily" and params["exchange"] == "CZCE":
            frame.loc[:, ["open", "high", "low", "close"]] = 0
            frame["vol"], frame["amount"] = volume, amount
        return frame

    client.query_all = source
    prepare_assets(asset_setup)
    obj = importer(OptionBars1dImporter, paths)
    frame = obj.build()
    iid = obj._ids([OPTIONS["CZCE"][0]], "option")[OPTIONS["CZCE"][0]]
    row = frame.loc[frame.instrument_id.eq(iid)].iloc[0]
    assert row[["open", "high", "low", "close"]].isna().all()
    assert row.settle == Decimal("1.22")
    assert pd.isna(row.volume) if volume is None else row.volume == volume
    assert pd.isna(row.amount) if amount is None else row.amount == Decimal(str(amount)) * 10000
    count = int(volume is not None and volume > 0 or amount is not None and amount > 0)
    assert any(f"nonzero_activity_rows={count}" in s for s in obj.soft_warnings)


@pytest.mark.parametrize("column,value", [("vol", -1), ("amount", -1), ("oi", float("inf"))])
def test_missing_option_ohlc_still_rejects_invalid_activity(column, value):
    row = bar(OPTIONS["CZCE"][0], exchange="CZCE", oi=0, settle=1, pre_settle=1)
    row.update(open=0, high=0, low=0, close=0, vol=0, amount=0)
    row[column] = value
    with pytest.raises(ValueError, match="Invalid numeric"):
        validate_bars(pd.DataFrame([row]), option=True)


@pytest.mark.parametrize("exchange", ["CZCE", "GFEX"])
def test_zero_settlement_requires_verified_expiry(exchange):
    code = OPTIONS[exchange][0]
    row = bar(code, exchange=exchange, oi=0, settle=0, pre_settle=1)
    row.update(open=0, high=0, low=0, close=0, vol=5, amount=0)
    frame = pd.DataFrame([row])
    assert validate_bars(frame, option=True, capture_unverified_expiry=True).equals(frame)
    for expiry_dates in (None, {}, {code: None}, {code: date(2024, 1, 3)}):
        with pytest.raises(ValueError, match="Unverified zero settlement expiry date"):
            validate_bars(frame, option=True, expiry_dates=expiry_dates)
    assert validate_bars(frame, option=True, expiry_dates={code: date(2024, 1, 2)}).equals(frame)


@pytest.mark.parametrize("expiry", [None, "20240103", "20240101"])
def test_ingest_rechecks_zero_settlement_lifecycle(asset_setup, expiry):
    paths = prepare_assets(asset_setup)
    daily = paths.dataset_file("tushare", "opt_daily", "2024-01")
    frame = pd.read_parquet(daily)
    frame.loc[frame.exchange.eq("GFEX"), ["open", "high", "low", "close", "settle"]] = 0
    replace_fixture(daily, frame)
    meta = paths.dataset_file("tushare", "instruments", "option")
    frame = pd.read_parquet(meta)
    frame.loc[frame.exchange.eq("GFEX"), "delist_date"] = expiry
    replace_fixture(meta, frame)
    with pytest.raises(ValueError, match="expiry date"):
        importer(OptionBars1dImporter, paths).build()


@pytest.mark.parametrize("missing", [None, ""])
def test_missing_listed_etf_date_is_retained_and_quarantined(asset_setup, missing):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "etf_basic" and params["exchange"] == "SH" and params["list_status"] == "L":
            frame = pd.concat(
                [frame, pd.DataFrame([dict(etf_meta("581050.SH"), list_date=missing)])],
                ignore_index=True,
            )
        return frame

    client.query_all = source
    EtfInstrumentsFetcher(client, ctx).fetch()
    path = paths.dataset_file("tushare", "instruments", "etf")
    raw, receipt = read_asset_observation(path)
    assert raw is not None and raw.loc[raw.ts_code.eq("581050.SH"), "list_status"].tolist() == ["L"]
    assert receipt["scope"]["missing_listing_date_rows"] == {"rows": 1, "samples": ["581050.SH"]}
    obj = importer(EtfInstrumentsImporter, paths)
    assert "581050.SH" not in set(obj.build().symbol)
    assert any("Quarantined unverified ETF identity rows=1" in s for s in obj.soft_warnings)


@pytest.mark.parametrize("bad", ["20260230", "00000000", " "])
def test_etf_invalid_date_is_not_quarantined(asset_setup, bad):
    _paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "etf_basic" and params["list_status"] == "L":
            frame["list_date"] = bad
        return frame

    client.query_all = source
    with pytest.raises(ValueError):
        EtfInstrumentsFetcher(client, ctx).fetch()


def test_czce_settlement_only_does_not_reinterpret_partial_null_prices():
    row = bar(OPTIONS["CZCE"][0], exchange="CZCE", oi=33, settle=1.22, pre_settle=1.2)
    row.update(open=0, high=0, low=None, close=0, vol=0, amount=0)
    frame = validate_bars(pd.DataFrame([row]), option=True)
    assert not czce_settlement_only_mask(frame).any()
    assert frame.close.iloc[0] == 0 and pd.isna(frame.low.iloc[0])


def test_sample_fix_pending_etf_incomplete_raw_kept_ingest_skipped(asset_setup):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        if api == "etf_basic" and params["exchange"] == "SH" and params["list_status"] == "P":
            return pd.DataFrame(
                [dict(etf_meta("515470.OF", "P"), exchange="SH", list_date=None, extname=None)]
            )
        return original(api, **params)

    client.query_all = source
    EtfInstrumentsFetcher(client, ctx).fetch("init")
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", "instruments", "etf"))
    assert raw is not None and "515470.OF" in set(raw.ts_code)
    assert receipt["scope"]["pending_rows"]["nonstandard_code_rows"] == 1
    assert receipt["scope"]["pending_rows"]["missing_list_date_rows"] == 1
    reference = importer(EtfInstrumentsImporter, paths)
    built = reference.build()
    assert set(built.symbol) == {"510300.SH", "510999.SH", "159919.SZ"}
    assert any("Skipped pending ETF rows=2" in message for message in reference.soft_warnings)
    obj = EtfSymbolMapImporter(MagicMock(), IngestContext(paths=paths))
    assert set(obj._metadata().ts_code) == set(built.symbol)
    assert any("Skipped pending ETF rows=2" in message for message in obj.soft_warnings)


def test_sample_fix_delisted_etf_requires_list_date(asset_setup):
    _, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "etf_basic" and params["list_status"] == "D":
            return pd.DataFrame(
                [dict(etf_meta(f"999999.{params['exchange']}", "D"), list_date=None)]
            )
        return frame

    client.query_all = source
    with pytest.raises(ValueError, match="date"):
        EtfInstrumentsFetcher(client, ctx).fetch("init")


def _sample_fix_warm_option_group(asset_setup):
    paths, ctx, client = _prepare_option_daily(asset_setup)
    first = option_meta("DCE")
    second = dict(first, ts_code="M2405-P-3000.DCE", call_put="P")
    path = paths.dataset_file("tushare", "opt_daily", "2024-01")
    daily = pd.read_parquet(path)
    daily = pd.concat(
        [
            daily,
            pd.DataFrame(
                [dict(daily[daily.exchange.eq("DCE")].iloc[0], ts_code=second["ts_code"])]
            ),
        ],
        ignore_index=True,
    )
    replace_fixture(path, daily)
    ctx.option_exchanges = ("DCE",)
    lookup = {first["ts_code"]: first, second["ts_code"]: second}
    client.override["opt_basic"] = lambda p: (
        pd.DataFrame([lookup[p["ts_code"]]])
        if "ts_code" in p
        else pd.DataFrame(list(lookup.values()))
    )
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    client.calls.clear()
    return paths, ctx, client, first, second


def test_sample_fix_option_metadata_one_request_per_known_underlying(asset_setup):
    paths, ctx, client, first, second = _sample_fix_warm_option_group(asset_setup)
    assert OptionInstrumentsFetcher(client, ctx).fetch("init") == 1
    calls = [p for api, p in client.calls if api == "opt_basic"]
    assert len(calls) == 1 and calls[0]["opt_code"] == first["opt_code"]
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", "instruments", "option"))
    assert raw is not None and set(raw.ts_code) == {first["ts_code"], second["ts_code"]}
    assert receipt["scope"]["underlying_queries"] == 1


def test_sample_fix_option_batch_missing_code_falls_back(asset_setup, caplog):
    paths, ctx, client, first, second = _sample_fix_warm_option_group(asset_setup)
    client.override["opt_basic"] = lambda p: pd.DataFrame(
        [second if p.get("ts_code") == second["ts_code"] else first]
    )
    with caplog.at_level("WARNING"):
        OptionInstrumentsFetcher(client, ctx).fetch("init")
    calls = [p for api, p in client.calls if api == "opt_basic"]
    assert (
        len(calls) == 2
        and calls[0]["opt_code"] == first["opt_code"]
        and calls[1]["ts_code"] == second["ts_code"]
    )
    assert "fallback" in caplog.text and second["ts_code"] in caplog.text


@pytest.mark.parametrize("damage", ["underlying", "exchange"])
def test_sample_fix_option_batch_scope_mismatch_refused(asset_setup, damage):
    paths, ctx, client, first, _ = _sample_fix_warm_option_group(asset_setup)
    before = paths.dataset_file("tushare", "instruments", "option").read_bytes()
    wrong = dict(
        first, **({"opt_code": "OPM2409.DCE"} if damage == "underlying" else {"exchange": "GFEX"})
    )
    client.override["opt_basic"] = lambda _p: pd.DataFrame([wrong])
    with pytest.raises(ValueError, match="scope"):
        OptionInstrumentsFetcher(client, ctx).fetch("init")
    assert paths.dataset_file("tushare", "instruments", "option").read_bytes() == before


@pytest.mark.parametrize("repeat", [False, True])
def test_sample_fix_option_batch_pagination_guard(asset_setup, monkeypatch, repeat):
    paths, ctx, _, first, second = _sample_fix_warm_option_group(asset_setup)
    pages = []

    class PagedClient(TushareProClient):
        def query(self, api_name, **params):
            pages.append(params)
            assert api_name == "opt_basic" and params["opt_code"] == first["opt_code"]
            frame = pd.DataFrame([first, second])
            offset = 0 if repeat else params["offset"]
            return frame.iloc[offset : offset + params["limit"]]

    monkeypatch.setitem(PAGE_LIMITS, "opt_basic", 1)
    if repeat:
        with pytest.raises(RuntimeError, match="Repeated pagination"):
            OptionInstrumentsFetcher(PagedClient(), ctx).fetch("init")
    else:
        OptionInstrumentsFetcher(PagedClient(), ctx).fetch("init")
        assert [p["offset"] for p in pages] == [0, 1, 2]


def test_sample_fix_placeholder_receipt_samples_bounded(asset_setup):
    paths, ctx, client = asset_setup
    ctx.option_exchanges = ("DCE",)
    client.override["opt_daily"] = lambda _p: pd.DataFrame(
        [
            bar(
                f"M2405-C-{3000 + i}.DCE",
                exchange="DCE",
                open=0,
                high=0,
                low=0,
                settle=1.22,
                pre_settle=1.2,
                vol=int(i > 0),
                oi=0,
            )
            for i in range(8)
        ]
    )
    OptionDailyFetcher(client, ctx).fetch("init")
    _, receipt = read_asset_observation(paths.dataset_file("tushare", "opt_daily", "2024-01"))
    counts = receipt["scope"]["ohl_zero_placeholder_rows"]["DCE"]
    assert counts["rows"] == 8 and counts["nonzero_volume_rows"] == 7
    assert len(counts["samples"]) == len(counts["nonzero_volume_samples"]) == 5


@pytest.mark.parametrize("cls", [FundDailyFetcher, FundAdjFetcher])
@pytest.mark.parametrize("bad_code", [None, "", " 1610221.SZ"])
def test_sample_fix_source_codes_remain_strict(asset_setup, cls, bad_code):
    _, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == cls.API_NAME:
            frame.loc[0, "ts_code"] = bad_code
        return frame

    client.query_all = source
    with pytest.raises(ValueError, match="source ts_code"):
        cls(client, ctx).fetch("init")


def test_sample_fix_fund_closed_market_only_checks_standard_codes(asset_setup):
    paths, ctx, client = asset_setup
    path = paths.dataset_file("tushare", "calendar", "SZSE")
    calendar = pd.read_parquet(path)
    calendar["is_open"] = 0
    write_parquet(calendar, path)
    client.override["fund_daily"] = lambda _p: pd.DataFrame([bar(), bar("1610221.SZ")])
    assert FundDailyFetcher(client, ctx).fetch("init") == 1
    client.override["fund_daily"] = lambda _p: pd.DataFrame([bar(), bar("159919.SZ")])
    with pytest.raises(ValueError, match="closed-market"):
        FundDailyFetcher(client, ctx).fetch("update")


def test_sample_fix_cold_start_seeds_underlying_once(asset_setup):
    paths, _, _, _, _ = _sample_fix_warm_option_group(asset_setup)
    _, receipt = read_asset_observation(paths.dataset_file("tushare", "instruments", "option"))
    assert receipt["scope"]["bootstrap_queries"] == 1
    assert receipt["scope"]["underlying_queries"] == 1
    assert len(receipt["requests"]) == 2


def test_sample_fix_empty_batch_falls_back_for_all_required_codes(asset_setup):
    paths, ctx, client, first, second = _sample_fix_warm_option_group(asset_setup)
    lookup = {r["ts_code"]: r for r in (first, second)}
    client.override["opt_basic"] = lambda p: (
        pd.DataFrame([lookup[p["ts_code"]]]) if "ts_code" in p else pd.DataFrame()
    )
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    _, receipt = read_asset_observation(paths.dataset_file("tushare", "instruments", "option"))
    assert len(client.calls) == 3 and receipt["scope"]["fallback_queries"] == 2


def test_sample_fix_full_batch_response_kept_beyond_target_scope(asset_setup):
    paths, ctx, client, first, second = _sample_fix_warm_option_group(asset_setup)
    extra = dict(first, ts_code="M2405-C-4000.DCE")
    client.override["opt_basic"] = lambda _p: pd.DataFrame([first, second, extra])
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", "instruments", "option"))
    assert raw is not None and set(raw.ts_code) == {first["ts_code"], second["ts_code"]}
    root = (
        paths.dataset_dir("tushare", "observations")
        / "option_instruments"
        / receipt["observation_id"]
    )
    source = receipt["source_responses"][0]
    assert hashlib.sha256((root / source["file"]).read_bytes()).hexdigest() == source["sha256"]
    assert extra["ts_code"] in set(pd.read_parquet(root / source["file"]).ts_code)


def test_sample_fix_expired_row_not_refreshed_with_active_sibling(asset_setup):
    paths, ctx, client, first, second = _sample_fix_warm_option_group(asset_setup)
    path = paths.dataset_file("tushare", "instruments", "option")
    second["delist_date"] = "20261231"
    OptionInstrumentsFetcher(client, ctx)._publish(
        pd.DataFrame([first, second]),
        path,
        {"coverage": "observed_daily_codes"},
        observed_dates={cast(str, r["ts_code"]): 20250101 for r in (first, second)},
    )
    client.override["opt_basic"] = lambda _p: pd.DataFrame(
        [
            dict(first, exercise_price=9999),
            dict(second, exercise_price=4000),
        ]
    )
    OptionInstrumentsFetcher(client, ctx).fetch("update")
    raw, receipt = read_asset_observation(path)
    assert raw is not None
    prices = raw.set_index("ts_code").exercise_price
    assert prices[first["ts_code"]] == first["exercise_price"]
    assert prices[second["ts_code"]] == 4000
    assert len(client.calls) == 1 and receipt["scope"]["bootstrap_queries"] == 0


def test_sample_fix_all_pending_etf_symbol_map_is_typed_empty(asset_setup):
    paths, ctx, client = asset_setup
    EtfInstrumentsFetcher(client, ctx).fetch("init")
    path = paths.dataset_file("tushare", "instruments", "etf")
    frame = pd.read_parquet(path)
    replace_fixture(path, frame.loc[frame.list_status.eq("P")])
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    result = EtfSymbolMapImporter(conn, IngestContext(paths=paths)).build()
    assert result.empty and list(result.columns) == ["instrument_id", "source", "source_symbol"]


def test_sample_fix_pending_response_need_not_have_listing_columns(asset_setup):
    paths, ctx, client = asset_setup
    original = client.query_all

    def source(api, **params):
        frame = original(api, **params)
        if api == "etf_basic" and not frame.empty and params["list_status"] == "P":
            return frame.drop(columns=["list_date", "extname"])
        return frame

    client.query_all = source
    EtfInstrumentsFetcher(client, ctx).fetch("init")
    raw, receipt = read_asset_observation(paths.dataset_file("tushare", "instruments", "etf"))
    assert raw is not None and raw.loc[raw.list_status.eq("P"), "list_date"].isna().all()
    assert receipt["scope"]["pending_rows"]["missing_list_date_rows"] == 1


def test_first_publish_crash_before_receipt_is_recoverable(asset_setup):
    """首次发布：parquet 已落地、收据未写时崩溃，update 应按本系统观察清单自愈。"""
    paths, ctx, client = asset_setup
    with (
        patch("os.replace", side_effect=_crash_on_receipt(os.replace)),
        pytest.raises(OSError, match="simulated crash"),
    ):
        FundDailyFetcher(client, ctx).fetch("init")
    path = paths.dataset_file("tushare", "fund_daily", "2024-01")
    with pytest.raises(ValueError, match="receipt"):
        read_asset_observation(path)  # 入库侧仍拒绝
    assert FundDailyFetcher(client, ctx).fetch("update") == 1
    frame, receipt = read_asset_observation(path)
    assert frame is not None
    assert receipt["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_receipt_does_not_roll_back_to_superseded_observation(asset_setup):
    """首个观察已被后续发布取代时，换回旧文件并删收据不能借首次发布恢复回滚。"""
    paths, ctx, client = asset_setup
    FundDailyFetcher(client, ctx).fetch("init")
    path = paths.dataset_file("tushare", "fund_daily", "2024-01")
    first = path.read_bytes()
    original = client.query_all

    def revised(api_name, **params):
        frame = original(api_name, **params)
        if api_name == "fund_daily":
            frame["amount"] = frame["amount"] + 1  # 供应商修订
        return frame

    client.query_all = revised
    FundDailyFetcher(client, ctx).fetch("update")
    path.write_bytes(first)
    path.with_suffix(".json").unlink()
    with pytest.raises(ValueError, match="receipt"):
        FundDailyFetcher(client, ctx).fetch("update")
    assert path.read_bytes() == first
