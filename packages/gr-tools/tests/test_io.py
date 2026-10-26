"""``gr_tools.io`` 的行为测试。

重点是 ``all_string=True``：证券代码列一旦被类型推断成整数，``000001``
会静默变成 ``1``，且错误一路带到数据库里。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from gr_tools import io


def _write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("names", [["Picks"], ["Picks", "Notes"]])
def test_excel_sheet_names(tmp_path: Path, names: list[str]) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    target = tmp_path / "sheets.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = names[0]
    for name in names[1:]:
        workbook.create_sheet(name)
    workbook.save(target)

    assert io.excel_sheet_names(target) == names


def test_excel_sheet_names_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        io.excel_sheet_names(tmp_path / "missing.xlsx")


def test_excel_sheet_names_corrupt_file(tmp_path: Path) -> None:
    target = _write_csv(tmp_path / "broken.xlsx", "not an Excel workbook")

    with pytest.raises(RuntimeError, match="failed to read sheet names of .*broken.xlsx") as caught:
        io.excel_sheet_names(target)

    assert caught.value.__cause__ is not None


def test_excel_sheet_names_propagates_memory_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fastexcel

    target = _write_csv(tmp_path / "picks.xlsx", "placeholder")
    failure = MemoryError("test allocation failure")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(fastexcel, "read_excel", fail)
    with pytest.raises(MemoryError) as caught:
        io.excel_sheet_names(target)
    assert caught.value is failure


def test_read_frame_nested_column_all_string_raises_value_error(tmp_path: Path) -> None:
    target = tmp_path / "nested.parquet"
    pl.DataFrame({"symbol": ["600000.SH"], "nested": [[1, 2]]}).write_parquet(target)

    with pytest.raises(ValueError, match="cannot read .*nested.parquet as all-string") as caught:
        io.read_frame(target, all_string=True)

    assert isinstance(caught.value.__cause__, pl.exceptions.PolarsError)


def test_read_directory_skips_failed_all_string_conversion(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_csv(tmp_path / "good.csv", "symbol\n000001.SZ\n")
    pl.DataFrame({"symbol": ["600000.SH"], "nested": [[1, 2]]}).write_parquet(
        tmp_path / "nested.parquet"
    )

    frame = io.read_directory(tmp_path, all_string=True)

    assert frame["symbol"].to_list() == ["000001.SZ"]
    assert "failed to read nested.parquet" in caplog.text
    assert "1/2 files failed" in caplog.text


def test_read_frame_cast_propagates_memory_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_csv(tmp_path / "picks.csv", "symbol\n600000.SH\n")
    failure = MemoryError("test allocation failure")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(io, "cast_all_utf8", fail)
    with pytest.raises(MemoryError) as caught:
        io.read_frame(target, all_string=True)
    assert caught.value is failure


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


def test_read_frame_rejects_non_tabular_suffix(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    target.write_text("hi", encoding="utf-8")

    with pytest.raises(ValueError, match="not a tabular file"):
        io.read_frame(target)


def test_read_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        io.read_file(tmp_path / "missing.csv")


@pytest.mark.parametrize("reader", [io.load_data, io.read_file])
def test_reader_rejects_unsupported_suffix(tmp_path: Path, reader) -> None:
    target = _write_csv(tmp_path / "a.md", "x\n1\n")

    with pytest.raises(ValueError, match="does not support file format"):
        reader(target)


def test_read_directory_concatenates_all_files(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    _write_csv(nested / "2026-08-12.csv", "symbol\n000001.SZ\n")
    _write_csv(tmp_path / "2026-08-11.csv", "symbol\n600000.SH\n")

    df = io.read_directory(tmp_path, all_string=True)

    # 递归读取的拼接顺序沿用 get_files 的路径排序，不受创建顺序影响。
    assert df["symbol"].to_list() == ["600000.SH", "000001.SZ"]


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


def test_read_directory_skips_broken_file(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_csv(tmp_path / "good.csv", "symbol\n600000.SH\n")
    # 后缀是 parquet 但内容是文本：单个文件读失败不该让整批读取挂掉。
    (tmp_path / "bad.parquet").write_text("definitely not parquet", encoding="utf-8")

    df = io.read_directory(tmp_path, all_string=True)

    assert df["symbol"].to_list() == ["600000.SH"]
    assert "1/2 files failed" in caplog.text


def test_read_frame_excel_reads_without_extra_setup(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    target = tmp_path / "picks.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["symbol"])
    workbook.active.append(["000001.SZ"])
    workbook.save(target)

    assert io.read_frame(target)["symbol"].to_list() == ["000001.SZ"]


def test_read_frame_excel_all_string_keeps_leading_zeros(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    target = tmp_path / "picks.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["symbol", "label"])
    # 超过默认 100 行采样后才出现文本代码，旧实现会先推断为整数并丢掉前导零。
    for number in range(100):
        workbook.active.append([number + 100, "NA"])
    workbook.active.append(["000001", "NA"])
    workbook.save(target)

    frame = io.read_frame(target, all_string=True)

    assert frame.tail(1).to_dict(as_series=False) == {"symbol": ["000001"], "label": ["NA"]}
    assert frame.dtypes == [pl.Utf8, pl.Utf8]


def test_read_frame_excel_numeric_and_date_cells(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    target = tmp_path / "cells.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["number", "date"])
    workbook.active.append([1, datetime(2026, 10, 26)])
    workbook.save(target)

    frame = io.read_frame(target, all_string=True)

    # calamine 按字符串读取：数字不补零，Excel 日期按解析器的日期时间文本输出。
    assert frame.to_dict(as_series=False) == {"number": ["1"], "date": ["2026-10-26 00:00:00"]}
    assert frame.dtypes == [pl.Utf8, pl.Utf8]


@pytest.mark.parametrize("options", [{"sheet_id": 0}, {"sheet_name": ["Sheet"]}])
def test_read_frame_excel_rejects_multiple_sheets(tmp_path: Path, options) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    target = tmp_path / "sheets.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["symbol"])
    workbook.active.append(["000001"])
    workbook.save(target)

    with pytest.raises(ValueError, match="only a single worksheet"):
        io.read_frame(target, **options)


def test_read_directory_trading_dates_without_bounds(tmp_path: Path) -> None:
    _write_csv(tmp_path / "2026-08-11.csv", "symbol\n000001\n")
    _write_csv(tmp_path / "2026-08-12.csv", "symbol\n600000\n")

    frame = io.read_directory(tmp_path, trading_dates=[20260811], all_string=True)

    assert frame["symbol"].to_list() == ["000001"]


def test_read_directory_filters_trading_dates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    for day in (10, 11, 12, 13):
        _write_csv(tmp_path / f"2026-08-{day}.csv", f"day\n{day}\n")

    frame = io.read_directory(
        tmp_path,
        sdt="2026-08-11",
        edt="2026-08-12",
        trading_dates=[20260810, 20260811, 20260812, 20260813],
    )

    assert frame["day"].to_list() == [11, 12]
    assert "2 trading dates outside" in caplog.text


def test_read_directory_deduplicates_and_sorts_trading_dates(tmp_path: Path) -> None:
    for day in (11, 12):
        _write_csv(tmp_path / f"2026-08-{day}.csv", f"day\n{day}\n")

    frame = io.read_directory(
        tmp_path,
        sdt="2026-08-11",
        edt="2026-08-12",
        trading_dates=[20260812, 20260811, "2026-08-12"],
    )

    assert frame["day"].to_list() == [11, 12]


@pytest.mark.parametrize("dates", [[], [20260810]])
def test_read_directory_no_remaining_dates_raises(tmp_path: Path, dates) -> None:
    with pytest.raises(ValueError, match="no trading dates"):
        io.read_directory(tmp_path, sdt="2026-08-11", edt="2026-08-12", trading_dates=dates)


def test_read_directory_all_broken_raises(tmp_path: Path) -> None:
    (tmp_path / "bad.parquet").write_text("not parquet", encoding="utf-8")
    (tmp_path / "other.feather").write_text("not feather", encoding="utf-8")

    with pytest.raises(RuntimeError, match="bad.parquet.*other.feather"):
        io.read_directory(tmp_path)


def test_read_directory_failure_message_is_bounded(tmp_path: Path) -> None:
    for index in range(12):
        (tmp_path / f"bad{index:02}.parquet").write_text("not parquet", encoding="utf-8")

    with pytest.raises(RuntimeError, match="12 total") as caught:
        io.read_directory(tmp_path)

    assert "bad00.parquet" in str(caught.value)
    assert "bad09.parquet" in str(caught.value)
    assert "bad10.parquet" not in str(caught.value)


def test_read_directory_empty_tables_return_empty_frame(tmp_path: Path) -> None:
    pl.DataFrame(schema={"symbol": pl.String}).write_parquet(tmp_path / "empty.parquet")

    assert io.read_directory(tmp_path).is_empty()


@pytest.mark.parametrize("reader", [io.read_file, io.read_directory])
def test_reader_propagates_memory_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader
) -> None:
    target = _write_csv(tmp_path / "a.csv", "x\n1\n")
    failure = MemoryError("test allocation failure")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setitem(io._READERS, ".csv", fail)
    with pytest.raises(MemoryError) as caught:
        reader(tmp_path if reader is io.read_directory else target)
    assert caught.value is failure


def test_read_file_wraps_reader_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _write_csv(tmp_path / "a.csv", "x\n1\n")

    def fail(*args, **kwargs):
        raise ValueError("invalid reader option")

    monkeypatch.setitem(io._READERS, ".csv", fail)
    with pytest.raises(RuntimeError, match="a.csv") as caught:
        io.read_file(target)
    assert isinstance(caught.value.__cause__, ValueError)
