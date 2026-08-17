"""``gr_tools.io`` 的行为测试。

重点是 ``all_string=True``：证券代码列一旦被类型推断成整数，``000001``
会静默变成 ``1``，且错误一路带到数据库里。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from gr_tools import io


def _write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_read_frame_all_string_keeps_leading_zeros(tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "picks.csv",
        "symbol,rank\n000001.SZ,1\n600000.SH,2\n",
    )

    df = io.read_frame(csv_path, all_string=True)

    assert df["symbol"].to_list() == ["000001.SZ", "600000.SH"]
    assert df["rank"].dtype == pl.Utf8


def test_read_frame_without_all_string_infers_types(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "picks.csv", "symbol,rank\n000001,1\n")

    df = io.read_frame(csv_path)

    # 反面用例：这正是导入路径必须传 all_string=True 的原因。
    assert df["symbol"].to_list() == [1]


def test_read_frame_parquet_all_string(tmp_path: Path) -> None:
    parquet_path = tmp_path / "picks.parquet"
    pl.DataFrame({"symbol": ["000001.SZ"], "rank": [1]}).write_parquet(parquet_path)

    df = io.read_frame(parquet_path, all_string=True)

    assert df["rank"].to_list() == ["1"]
    assert df["symbol"].to_list() == ["000001.SZ"]


def test_read_frame_pandas_engine(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "picks.csv", "symbol\n000001.SZ\n")

    df = io.read_frame(csv_path, engine="pandas", all_string=True)

    assert df["symbol"].tolist() == ["000001.SZ"]


def test_read_frame_rejects_non_tabular_suffix(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_text("hi", encoding="utf-8")

    with pytest.raises(ValueError, match="not a tabular file"):
        io.read_frame(target)


def test_read_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        io.read_file(tmp_path / "missing.csv")


def test_load_data_rejects_unknown_engine(tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "a.csv", "x\n1\n")

    with pytest.raises(ValueError, match="unsupported engine"):
        io.load_data(csv_path, engine="duckdb")


def test_read_directory_concatenates_all_files(tmp_path: Path) -> None:
    _write_csv(tmp_path / "2026-08-11.csv", "symbol\n600000.SH\n")
    _write_csv(tmp_path / "2026-08-12.csv", "symbol\n000001.SZ\n")

    df = io.read_directory(tmp_path, all_string=True)

    assert sorted(df["symbol"].to_list()) == ["000001.SZ", "600000.SH"]


def test_read_directory_by_date_pattern_skips_missing(tmp_path: Path) -> None:
    _write_csv(tmp_path / "2026-08-11.csv", "symbol\n600000.SH\n")
    _write_csv(tmp_path / "2026-08-13.csv", "symbol\n000001.SZ\n")

    df = io.read_directory(tmp_path, sdt="2026-08-11", edt="2026-08-13", all_string=True)

    # 08-12 缺文件：告警但不报错。
    assert len(df) == 2


def test_read_directory_explicit_trading_dates(tmp_path: Path) -> None:
    _write_csv(tmp_path / "20260811.csv", "symbol\n600000.SH\n")

    df = io.read_directory(
        tmp_path,
        sdt="2026-08-11",
        edt="2026-08-11",
        file_pattern="{date}.csv",
        date_format="%Y%m%d",
        trading_dates=[20260811],
        all_string=True,
    )

    assert df["symbol"].to_list() == ["600000.SH"]


def test_read_directory_no_match_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no files matching"):
        io.read_directory(tmp_path, sdt="2026-08-11", edt="2026-08-12")


def test_read_directory_requires_both_dates(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be provided together"):
        io.read_directory(tmp_path, sdt="2026-08-11")


def test_read_directory_empty_dir_returns_empty_frame(tmp_path: Path) -> None:
    assert io.read_directory(tmp_path).is_empty()


def test_read_directory_skips_broken_file(tmp_path: Path) -> None:
    _write_csv(tmp_path / "good.csv", "symbol\n600000.SH\n")
    # 后缀是 parquet 但内容是文本：单个文件读失败不该让整批读取挂掉。
    (tmp_path / "bad.parquet").write_text("definitely not parquet", encoding="utf-8")

    df = io.read_directory(tmp_path, all_string=True)

    assert df["symbol"].to_list() == ["600000.SH"]
