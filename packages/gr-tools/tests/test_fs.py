"""``gr_tools.fs`` 的行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from gr_tools import fs


def test_handle_path_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "c.txt"
    resolved = fs.handle_path(target)

    assert resolved.parent.is_dir()
    assert resolved.is_absolute()


def test_list_paths_is_sorted_and_filterable(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    files = fs.get_files(tmp_path)
    dirs = fs.get_dirs(tmp_path)

    assert [p.name for p in files] == ["a.txt", "b.txt"]
    assert [p.name for p in dirs] == ["sub"]
    # 排序是刻意的：不排序时 rglob 的顺序随文件系统变化，结果不可复现。
    assert files == sorted(files)


def test_list_paths_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fs.list_paths(tmp_path / "nope")


def test_move_copy_keeps_source(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "out" / "dst.txt"

    fs.move(src, dst)

    assert src.exists()
    assert dst.read_text(encoding="utf-8") == "x"


def test_move_without_exist_ok_raises(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "dst.txt"
    dst.write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError):
        fs.move(src, dst)
    assert dst.read_text(encoding="utf-8") == "old"


def test_move_rename_and_remove(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("x", encoding="utf-8")

    renamed = fs.rename(src, tmp_path / "renamed.txt")
    assert renamed.exists() and not src.exists()

    fs.remove(renamed)
    assert not renamed.exists()


def test_remove_missing_path_is_noop(tmp_path: Path) -> None:
    # 清理临时文件失败不该中断主流程。
    fs.remove(tmp_path / "not-there")


def test_file_time_rejects_bad_method(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("a", encoding="utf-8")

    assert fs.file_time(target, "m").year >= 1970
    with pytest.raises(ValueError, match="method must be"):
        fs.file_time(target, "z")
    with pytest.raises(FileNotFoundError):
        fs.file_time(tmp_path / "missing.txt")
