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
from gr_data.raw.tushare.asset_rules import numeric_values, read_asset_observation, validate_bars
from gr_data.raw.tushare.client import PAGE_LIMITS, TushareProClient
from gr_data.raw.tushare.context import OPTION_EXCHANGES, TushareRawContext, build_context
from gr_data.raw.tushare.fetchers import asset_markets as raw_asset_markets
from gr_data.raw.tushare.fetchers.asset_markets import (
    EtfInstrumentsFetcher,
    FundAdjFetcher,
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
        etf_type="QDII",
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
            assert meta["ts_code"] == params["ts_code"]
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
    assert reference.loc["159999.SZ", "status"] == "pending"


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
            ("159999.SZ", 4, "XSHE"),
        ],
        [("510300.SH", 999)],
    ]
    with pytest.raises(IngestGateError, match="Conflicting existing"):
        EtfSymbolMapImporter(conn, IngestContext(paths=paths)).build()


@pytest.mark.integration
def test_etf_options_pg_roundtrip_and_replay(pg_conn, asset_setup):
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
        assert [r.rows_written for r in results] == [4, 4, 8, 8, 8, 2, 8]
        assert [r.dataset for r in results if r.warnings] == ["option_contracts", "option_bar_1d"]
        with pg_conn.cursor() as cur:
            cur.execute("SELECT volume,amount,adj_factor,close FROM market.etf_bar_1d")
            assert (
                cur.fetchall()
                == [(1025, Decimal("123.4000"), Decimal("1.12500000"), Decimal("1.250000"))] * 2
            )
            cur.execute("SELECT volume,amount,open_interest,settle FROM market.option_bar_1d")
            assert cur.fetchall() == [(10, Decimal("1234.0000"), None, Decimal("1.220000"))] * 8
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
    return [params["ts_code"] for api, params in client.calls if api == "opt_basic"]


def _prepare_option_daily(asset_setup):
    paths, ctx, client = asset_setup
    OptionDailyFetcher(client, ctx).fetch("init")
    return paths, ctx, client


def test_update_skips_contracts_observed_after_expiry(asset_setup):
    """P2-5：合约到期后已观察过的参数不再变化，update 不应再查 opt_basic。"""
    paths, ctx, client = _prepare_option_daily(asset_setup)
    OptionInstrumentsFetcher(client, ctx).fetch("init")  # 真实今天远晚于夹具到期日 20240228
    first = len(_opt_basic_calls(client))
    assert first == 8
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
    assert len(_opt_basic_calls(client)) == 16


def test_init_forces_full_reobservation(asset_setup):
    """P2-5 边界：init 仍全量重查，供人工复核参数调整时使用。"""
    paths, ctx, client = _prepare_option_daily(asset_setup)
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    OptionInstrumentsFetcher(client, ctx).fetch("init")
    assert len(_opt_basic_calls(client)) == 16


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
    assert len(_opt_basic_calls(client)) == 16


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
