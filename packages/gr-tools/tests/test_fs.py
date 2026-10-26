"""``gr_tools.fs`` 的行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from gr_tools import fs


def test_list_paths_is_sorted_and_filterable(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    paths = fs.list_paths(tmp_path)
    files = fs.get_files(tmp_path)
    dirs = fs.list_paths(tmp_path, dirs_only=True)

    # 排序是刻意的：不排序时 rglob 的返回顺序依赖文件系统。
    assert files == [tmp_path / "a.txt", tmp_path / "sub" / "b.txt"]
    assert dirs == [tmp_path / "sub", tmp_path / "sub" / "nested"]
    assert paths == sorted([*files, *dirs])


@pytest.mark.parametrize("files_only,dirs_only", [(False, False), (True, False), (False, True)])
def test_list_paths_empty_directory(tmp_path: Path, files_only: bool, dirs_only: bool) -> None:
    assert fs.list_paths(tmp_path, files_only=files_only, dirs_only=dirs_only) == []


def test_list_paths_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="directory does not exist"):
        fs.list_paths(tmp_path / "nope")


def test_list_paths_rejects_file_root(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("data", encoding="utf-8")

    with pytest.raises(NotADirectoryError, match="path is not a directory"):
        fs.list_paths(target)


def test_list_paths_rejects_conflicting_filters(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot both be True"):
        fs.list_paths(tmp_path, files_only=True, dirs_only=True)


def test_list_paths_normalizes_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "item.txt").write_text("data", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    expected = [(root / "item.txt").resolve()]
    assert fs.list_paths("data") == expected
    assert fs.get_files(Path("data")) == expected
