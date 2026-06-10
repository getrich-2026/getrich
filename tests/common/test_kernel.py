"""common 内核单元测试（不需要 PG / SDK）。"""

from __future__ import annotations

import pandas as pd

from getrich_data.common import contracts
from getrich_data.common.parquet import last_index_date, read_parquet_if_exists, write_parquet
from getrich_data.common.quality import check_dataframe
from getrich_data.common.retry import chunk_date_range, chunk_list, to_int_date, today_int


def test_contracts_assets():
    s = contracts.bar_1d("stock")
    assert "adj_factor" in s.columns and s.qualified == "market.stock_bar_1d"
    f = contracts.bar_1d("future")
    assert "adj_factor" not in f.columns
    assert {"open_interest", "settle", "pre_settle"} <= set(f.columns)
    m = contracts.bar_1m("option")
    assert m.conflict_keys == ("instrument_id", "dt")


def test_chunking():
    assert list(chunk_list([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    ranges = list(chunk_date_range(20240101, 20240110, 3))
    assert ranges[0] == (20240101, 20240103)
    assert ranges[-1][1] == 20240110


def test_int_date():
    assert to_int_date("2024-01-02") == 20240102
    assert to_int_date(pd.Timestamp("2024-01-02")) == 20240102
    assert today_int() > 20200101


def test_parquet_atomic_and_merge(tmp_path):
    p = tmp_path / "x.parquet"
    df1 = pd.DataFrame({"v": [1, 2]}, index=pd.Index([20240101, 20240102], name="date"))
    write_parquet(df1, p, append=False)
    assert read_parquet_if_exists(p) is not None
    # 追加带重叠键，应去重保留后值
    df2 = pd.DataFrame({"v": [99, 3]}, index=pd.Index([20240102, 20240103], name="date"))
    write_parquet(df2, p, append=True)
    out = read_parquet_if_exists(p)
    assert len(out) == 3
    assert out.loc[20240102, "v"] == 99
    assert last_index_date(out) == 20240103


def test_quality_checks():
    df = pd.DataFrame({"a": [1, 1], "b": [None, 2]})
    rep = check_dataframe(df, dataset="t", required_columns=["a", "b"],
                          key_columns=["a"], not_null_columns=["b"])
    assert not rep.ok
    assert any("重复主键" in i for i in rep.issues)
    assert any("null" in i for i in rep.issues)

    empty = check_dataframe(pd.DataFrame(), dataset="t", required_columns=["a"])
    assert "空数据集" in empty.issues
