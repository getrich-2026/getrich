"""Tushare 主数据快照 → meta.*_profile 的映射与门禁。"""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import pytest
from gr_data.ingest.base import IngestContext, IngestGateError
from gr_data.ingest.tushare.importers import profile


def _write_instruments(paths, asset: str, rows: list[dict]) -> None:
    from gr_data.common.parquet import write_parquet

    write_parquet(
        pd.DataFrame(rows), paths.dataset_file("tushare", "instruments", asset), append=False
    )


def _stock_row(**overrides) -> dict:
    row = {
        "ts_code": "600000.SH",
        "symbol": "600000",
        "name": "浦发银行",
        "area": "上海",
        "industry": "银行",
        "fullname": "上海浦东发展银行股份有限公司",
        "enname": "Shanghai Pudong Development Bank Co.,Ltd.",
        "cnspell": "PFYH",
        "market": "主板",
        "exchange": "SSE",
        "curr_type": "CNY",
        "list_status": "L",
        "list_date": "19991110",
        "delist_date": None,
        "is_hs": "H",
        "act_name": "无实际控制人",
        "act_ent_type": "无",
    }
    row.update(overrides)
    return row


def _build(cls, tmp_raw_root, monkeypatch, ids: dict[str, int]) -> pd.DataFrame:
    monkeypatch.setattr(profile, "resolve_by_instrument", lambda _conn, _asset: ids)
    return cls(conn=None, ctx=IngestContext(paths=tmp_raw_root)).build()


def test_stock_profile_maps_source_fields(tmp_raw_root, monkeypatch):
    """market → board、curr_type → currency 显式改名；其余字段原值，来源钉为 tushare。"""
    _write_instruments(tmp_raw_root, "stock", [_stock_row()])

    row = _build(profile.StockProfileImporter, tmp_raw_root, monkeypatch, {"600000.SH": 7}).iloc[0]

    assert row["instrument_id"] == 7
    assert (row["board"], row["currency"], row["is_hs"]) == ("主板", "CNY", "H")
    assert (row["industry"], row["area"], row["cnspell"]) == ("银行", "上海", "PFYH")
    assert row["act_name"] == "无实际控制人"
    assert row["source"] == "tushare"


def test_stock_profile_blank_text_becomes_null(tmp_raw_root, monkeypatch):
    """空串、空白与缺失统一为 NULL，不把 'nan' 之类的字面量写进库。"""
    _write_instruments(tmp_raw_root, "stock", [_stock_row(enname="  ", act_name=None)])

    row = _build(profile.StockProfileImporter, tmp_raw_root, monkeypatch, {"600000.SH": 7}).iloc[0]

    assert row["enname"] is None
    assert row["act_name"] is None


def test_profile_rejects_old_snapshot_without_profile_fields(tmp_raw_root, monkeypatch):
    """扩字段前的旧快照缺档案列：硬失败并提示重采，不能整列写 NULL 覆盖库内值。"""
    old = {k: v for k, v in _stock_row().items() if k not in {"industry", "is_hs"}}
    _write_instruments(tmp_raw_root, "stock", [old])

    with pytest.raises(IngestGateError, match="重新采集"):
        _build(profile.StockProfileImporter, tmp_raw_root, monkeypatch, {"600000.SH": 7})


def test_profile_rejects_unregistered_codes(tmp_raw_root, monkeypatch):
    """档案只补充已登记身份；代码未登记说明 instruments 尚未导入同一份快照。"""
    _write_instruments(tmp_raw_root, "stock", [_stock_row()])

    with pytest.raises(IngestGateError, match="Unregistered stock codes count=1"):
        _build(profile.StockProfileImporter, tmp_raw_root, monkeypatch, {})


def test_stock_profile_rejects_unknown_is_hs(tmp_raw_root, monkeypatch):
    """沪深港通只有 N/H/S；新取值意味着源语义变了，整批拒绝并给出取值。"""
    _write_instruments(tmp_raw_root, "stock", [_stock_row(is_hs="X")])

    with pytest.raises(IngestGateError, match="is_hs"):
        _build(profile.StockProfileImporter, tmp_raw_root, monkeypatch, {"600000.SH": 7})


def test_stock_profile_requires_stock_snapshot(tmp_raw_root, monkeypatch):
    """股票主数据是全部按月数据的前提，缺失时硬失败。"""
    with pytest.raises(IngestGateError, match=r"instruments\[stock\]"):
        _build(profile.StockProfileImporter, tmp_raw_root, monkeypatch, {})


def test_index_profile_parses_dates_and_numbers(tmp_raw_root, monkeypatch):
    """基期解析为 DATE、基点为数值；desc 映射到 description。"""
    _write_instruments(
        tmp_raw_root,
        "index",
        [
            {
                "ts_code": "000300.SH",
                "name": "沪深300",
                "fullname": "沪深300指数",
                "market": "SSE",
                "publisher": "中证指数有限公司",
                "index_type": None,
                "category": "规模指数",
                "base_date": "20041231",
                "base_point": 1000.0,
                "list_date": "20050408",
                "weight_rule": "分档自由流通市值加权",
                "desc": "沪深300指数",
                "exp_date": None,
            }
        ],
    )

    row = _build(profile.IndexProfileImporter, tmp_raw_root, monkeypatch, {"000300.SH": 3}).iloc[0]

    assert row["base_date"].isoformat() == "2004-12-31"
    assert row["base_point"] == 1000.0
    assert row["publish_market"] == "SSE"
    assert row["description"] == "沪深300指数"
    assert row["index_type"] is None


def test_index_profile_missing_snapshot_is_soft(tmp_raw_root, monkeypatch):
    """指数主数据缺失时与 instruments importer 一致：软告警并跳过。"""
    # 不触库：缺快照时在解析身份之前就返回。
    imp = profile.IndexProfileImporter(conn=cast(Any, None), ctx=IngestContext(paths=tmp_raw_root))

    assert imp.build().empty
    assert imp.collect_soft_warnings()


def _future_row(**overrides) -> dict:
    row = {
        "ts_code": "CU2401.SHF",
        "symbol": "CU2401",
        "exchange": "SHFE",
        "name": "沪铜2401",
        "fut_code": "CU",
        "multiplier": None,
        "trade_unit": "吨",
        "per_unit": 5.0,
        "quote_unit": "人民币元/吨",
        "quote_unit_desc": "10人民币元/吨",
        "d_mode_desc": "实物交割",
        "list_date": "20230117",
        "delist_date": "20240115",
        "d_month": "202401",
        "last_ddate": "20240119",
        "trade_time_desc": "上午9:00－11:30",
    }
    row.update(overrides)
    return row


def test_future_profile_maps_delivery_fields(tmp_raw_root, monkeypatch):
    """最后交割日落 delivery_date；每手单位保持源数值，不当作合约乘数。"""
    _write_instruments(tmp_raw_root, "future", [_future_row()])

    row = _build(profile.FutureProfileImporter, tmp_raw_root, monkeypatch, {"CU2401.SHF": 9}).iloc[
        0
    ]

    assert row["product_code"] == "CU"
    assert row["per_unit"] == 5.0
    assert row["delivery_date"].isoformat() == "2024-01-19"
    assert (row["delivery_mode"], row["delivery_month"]) == ("实物交割", "202401")
    assert "multiplier" not in row.index


def test_future_profile_rejects_non_numeric_per_unit(tmp_raw_root, monkeypatch):
    """无法解析的数值硬失败，不静默变成 NULL。"""
    _write_instruments(tmp_raw_root, "future", [_future_row(per_unit="五吨")])

    with pytest.raises(IngestGateError, match="per_unit"):
        _build(profile.FutureProfileImporter, tmp_raw_root, monkeypatch, {"CU2401.SHF": 9})


def test_index_profile_accepts_zero_base_point(pg_conn):
    """股息点指数从 0 起算（2026-10-30 真实快照 5 只 CSI 股息点指数），基点 0 必须能入库。"""
    import psycopg

    with pg_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO meta.instruments(symbol, asset, exchange) "
            "VALUES ('H30401.CSI', 'index', 'CSI') RETURNING instrument_id"
        )
        iid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO meta.index_profile(instrument_id, base_point, source) "
            "VALUES (%s, 0, 'tushare')",
            (iid,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "UPDATE meta.index_profile SET base_point = -1 WHERE instrument_id = %s", (iid,)
            )
    pg_conn.rollback()
