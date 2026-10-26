"""指数与期货的按月质量门禁、去重和金额精度回归。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import cast

import pandas as pd
import psycopg
import pytest
from gr_data.common.parquet import write_parquet
from gr_data.ingest.base import IngestContext
from gr_data.ingest.tushare.importers.market import FutureBars1dImporter, IndexBars1dImporter


def _row(future=False, **overrides):
    row = {
        "ts_code": "CU2401.SHF" if future else "000300.SH",
        "trade_date": "20240102",
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "pre_close": 10.0,
        "vol": 100.0,
        "amount": 0.123456789,
    }
    if future:
        row.update(settle=10.5, pre_settle=10.0, oi=50.0)
    row.update(overrides)
    return row


def _importer(paths, future, rows, months=None):
    name = "fut_daily" if future else "index_daily"
    write_parquet(pd.DataFrame(rows), paths.dataset_file("tushare", name, "2024-01"), append=False)
    cls = FutureBars1dImporter if future else IndexBars1dImporter
    # 只测 build()，不连库；没有连接时 _record_missing_price 等写库路径会显式跳过。
    importer = cls(cast(psycopg.Connection, None), IngestContext(paths=paths, months=months))
    importer._id_map = lambda: {"CU2401.SHF": 1, "000300.SH": 2}
    return importer


@pytest.mark.parametrize("future", [False, True])
def test_keys_normalized_before_dedup(tmp_raw_root, future):
    first = _row(future, trade_date=20240102)
    second = {**first, "ts_code": first["ts_code"] + " ", "trade_date": 20240102, "close": 11.5}
    frame = _importer(tmp_raw_root, future, [first, second]).build()
    assert len(frame) == 1
    assert frame.iloc[0]["close"] == 11.5
    assert frame.iloc[0]["dt"] == date(2024, 1, 2)


@pytest.mark.parametrize("future", [False, True])
@pytest.mark.parametrize("column", ["vol", "amount"])
@pytest.mark.parametrize("value", [-1, float("inf"), "bad"])
def test_invalid_activity_rejected(tmp_raw_root, future, column, value):
    with pytest.raises(ValueError, match="invalid activity"):
        _importer(tmp_raw_root, future, [_row(future, **{column: value})]).build()


@pytest.mark.parametrize("value", [-1, float("inf"), "bad"])
def test_invalid_future_open_interest_rejected(tmp_raw_root, value):
    with pytest.raises(ValueError, match="invalid activity"):
        _importer(tmp_raw_root, True, [_row(True, oi=value)]).build()


@pytest.mark.parametrize("future,multiplier", [(False, 1000), (True, 10000)])
def test_amount_conversion_uses_decimal(tmp_raw_root, future, multiplier):
    importer = _importer(tmp_raw_root, future, [_row(future)])
    frame = importer.build()
    assert frame.iloc[0]["amount"] == Decimal("0.123456789") * multiplier
    assert isinstance(frame.iloc[0]["amount"], Decimal)
    rows = importer._df_to_rows(frame)
    assert (
        rows[0][list(importer.contract.columns).index("amount")]
        == Decimal("0.123456789") * multiplier
    )


@pytest.mark.parametrize("future", [False, True])
def test_skipped_prices_are_soft_warnings(tmp_raw_root, future):
    good = _row(future)
    bad = _row(future, trade_date="20240103", close=None)
    if future:
        bad["settle"] = None
    importer = _importer(tmp_raw_root, future, [good, bad])
    assert len(importer.build()) == 1
    assert importer.collect_soft_warnings()


@pytest.mark.parametrize("future", [False, True])
def test_each_partition_requires_its_own_columns(tmp_raw_root, future):
    importer = _importer(tmp_raw_root, future, [_row(future)], months=("2024-01", "2024-02"))
    name = "fut_daily" if future else "index_daily"
    bad = _row(future, trade_date="20240201")
    del bad["amount"]
    write_parquet(
        pd.DataFrame([bad]), tmp_raw_root.dataset_file("tushare", name, "2024-02"), append=False
    )
    with pytest.raises(ValueError, match=r"2024-02.*amount"):
        importer.build()


@pytest.mark.parametrize("tas_code", ["SCTAS2510.INE", "SCTASL.INE", "SCTAS.INE"])
def test_tas_spread_rows_excluded_not_stored_as_prices(tmp_raw_root, tas_code):
    # D-025：SCTAS 的 OHLC／前收是相对结算价的价差，settle 是绝对价；不能进绝对价格表。
    ordinary = _row(True)
    tas = _row(
        True,
        ts_code=tas_code,
        open=0.1,
        high=0.1,
        low=-0.1,
        close=-0.1,
        pre_close=0.0,
        settle=491.8,
        pre_settle=490.0,
    )
    importer = _importer(tmp_raw_root, True, [ordinary, tas])
    frame = importer.build()
    assert frame["instrument_id"].tolist() == [1]
    assert frame.iloc[0]["close"] == 11.0
    warnings = importer.collect_soft_warnings()
    assert any("TAS" in w and ": 1" in w for w in warnings)


def test_tas_only_partition_returns_empty(tmp_raw_root):
    importer = _importer(tmp_raw_root, True, [_row(True, ts_code="SCTAS2510.INE", close=-0.1)])
    assert importer.build().empty
    assert importer.collect_soft_warnings()


def test_ordinary_ine_contract_not_treated_as_tas(tmp_raw_root):
    importer = _importer(tmp_raw_root, True, [_row(True, ts_code="SC2510.INE")])
    importer._id_map = lambda: {"SC2510.INE": 3}
    frame = importer.build()
    assert frame["instrument_id"].tolist() == [3]
    assert not importer.collect_soft_warnings()
