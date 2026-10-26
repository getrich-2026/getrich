"""目录递归遍历：统一路径解析、类型筛选与结果排序。"""

from __future__ import annotations

import os
from pathlib import Path


#: 接受字符串与实现 ``os.PathLike[str]`` 协议的路径。
PathLike = str | os.PathLike[str]


def list_paths(rootdir: PathLike, files_only: bool = False, dirs_only: bool = False) -> list[Path]:
    """递归列出目录下的路径，结果按路径字典序排好。

    排序是刻意的：``rglob`` 的返回顺序依赖文件系统，不排序会让
    「读一个目录再拼接」的结果每次跑出来行序不同，难以复现。

    Args:
        rootdir: 根目录，展开 ``~`` 并解析为绝对路径。
        files_only: 只要文件，不能与 ``dirs_only`` 同时为 True。
        dirs_only: 只要目录，不能与 ``files_only`` 同时为 True。

    Returns:
        排序后的绝对路径列表，不包含根目录；空目录返回空列表。

    Raises:
        FileNotFoundError: 根目录不存在。
        NotADirectoryError: 根路径不是目录。
        ValueError: 两个筛选参数同时为 True。
    """
    if files_only and dirs_only:
        raise ValueError("files_only and dirs_only cannot both be True")
    root = Path(rootdir).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"path is not a directory: {root}")

    paths = sorted(root.rglob("*"))
    if files_only:
        return [p for p in paths if p.is_file()]
    if dirs_only:
        return [p for p in paths if p.is_dir()]
    return paths


def get_files(root: PathLike) -> list[Path]:
    """递归列出全部文件；路径解析、排序与异常约定同 ``list_paths``。"""
    return list_paths(root, files_only=True)


__all__ = ["PathLike", "get_files", "list_paths"]
