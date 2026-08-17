"""文件系统薄封装。

只做 ``pathlib`` / ``shutil`` 之上的一层便利封装，不引入任何第三方依赖，
也不依赖任何一方包 —— gr-tools 是依赖图最底层的叶子。

移植自 ``lntools.core.filesystem``（2026-08-17），改动：
* 日志换成 stdlib ``logging``，不再依赖 lntools 自己的 Logger；
* 补全类型标注与 ``from __future__ import annotations``。
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)

#: 接受 ``str`` 与 ``Path`` 两种写法的路径入参。
PathLike = str | os.PathLike[str]


def is_dir(d: PathLike) -> bool:
    """路径是否为目录。"""
    return Path(d).is_dir()


def is_file(file: PathLike) -> bool:
    """路径是否为文件。"""
    return Path(file).is_file()


def handle_path(path: PathLike) -> Path:
    """展开 ``~``、解析成绝对路径，并确保父目录存在。

    写文件前调用它，可以省掉每处都写一遍 ``mkdir(parents=True)``。

    Args:
        path: 目标路径。

    Returns:
        解析后的绝对路径（父目录已创建）。
    """
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def make_dirs(d: PathLike, parents: bool = True, exist_ok: bool = True) -> Path:
    """创建目录并返回它。

    Args:
        d: 目录路径。
        parents: 是否连带创建父目录。
        exist_ok: 目录已存在时是否静默通过。

    Returns:
        创建（或已存在）的目录路径。
    """
    target = Path(d)
    target.mkdir(parents=parents, exist_ok=exist_ok)
    return target


def move(src: PathLike, dst: PathLike, keep_old: bool = True, exist_ok: bool = False) -> None:
    """复制或移动文件 / 目录。

    Args:
        src: 源路径，文件或目录皆可。
        dst: 目标路径。
        keep_old: True 为复制（保留源），False 为移动。
        exist_ok: 目标已存在时是否允许覆盖。

    Raises:
        FileNotFoundError: 源路径不存在。
        FileExistsError: 目标已存在且 ``exist_ok=False``。
    """
    src_path, dst_path = Path(src), Path(dst)
    if not src_path.exists():
        raise FileNotFoundError(f"source path does not exist: {src_path}")

    dst_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not keep_old:
            shutil.move(str(src_path), str(dst_path))
        elif src_path.is_dir():
            shutil.copytree(str(src_path), str(dst_path), dirs_exist_ok=exist_ok)
        else:
            if dst_path.exists() and not exist_ok:
                raise FileExistsError(f"destination already exists: {dst_path}")
            shutil.copy2(str(src_path), str(dst_path))
    except FileExistsError:
        if not exist_ok:
            raise


def rename(src: PathLike, dst: PathLike) -> Path:
    """重命名文件或目录，目标存在时覆盖。

    Args:
        src: 源路径。
        dst: 目标路径。

    Returns:
        重命名后的路径。

    Raises:
        FileNotFoundError: 源路径不存在。
    """
    src_path, dst_path = Path(src), Path(dst)
    if not src_path.exists():
        raise FileNotFoundError(f"source path does not exist: {src_path}")
    if dst_path.exists():
        logger.info("rename: %s already exists, will be overwritten", dst_path)
    return src_path.replace(dst_path)


def remove(path: PathLike) -> None:
    """递归删除文件或目录。

    删除失败只记日志不抛异常 —— 调用点通常是清理临时文件，
    没有必要因为清理失败中断主流程。
    """
    target = Path(path)
    try:
        if target.is_file():
            target.unlink(missing_ok=True)
        elif target.is_dir():
            shutil.rmtree(target)
    except OSError as exc:
        logger.error("failed to remove %s: %s", target, exc)


def file_time(file_path: PathLike, method: str = "m") -> datetime:
    """取文件时间戳（跨平台）。

    Args:
        file_path: 文件路径。
        method: ``'a'`` 访问时间 / ``'m'`` 修改时间 / ``'c'`` 创建时间
            （Windows）或 inode 变更时间（Unix）。

    Returns:
        对应的 ``datetime``（本地时区 naive）。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: ``method`` 不是 a/m/c。
    """
    path_obj = Path(file_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"file does not exist: {file_path}")

    stat = path_obj.stat()
    if method == "a":
        timestamp = stat.st_atime
    elif method == "m":
        timestamp = stat.st_mtime
    elif method == "c":
        timestamp = stat.st_ctime
    else:
        raise ValueError("method must be one of 'a' (accessed), 'm' (modified), 'c' (created)")
    return datetime.fromtimestamp(timestamp)


def list_paths(rootdir: PathLike, files_only: bool = False, dirs_only: bool = False) -> list[Path]:
    """递归列出目录下的路径，结果按路径字典序排好。

    排序是刻意的：``rglob`` 的返回顺序依赖文件系统，不排序会让
    「读一个目录再拼接」的结果每次跑出来行序不同，难以复现。

    Args:
        rootdir: 根目录。
        files_only: 只要文件。
        dirs_only: 只要目录。

    Returns:
        排序后的路径列表。

    Raises:
        FileNotFoundError: 根目录不存在。
    """
    root = Path(rootdir).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"directory does not exist: {root}")

    paths = sorted(root.rglob("*"))
    if files_only and not dirs_only:
        return [p for p in paths if p.is_file()]
    if dirs_only and not files_only:
        return [p for p in paths if p.is_dir()]
    return paths


def get_dirs(root: PathLike) -> list[Path]:
    """列出根目录下的全部子目录。"""
    return list_paths(root, dirs_only=True)


def get_files(root: PathLike) -> list[Path]:
    """列出根目录下的全部文件。"""
    return list_paths(root, files_only=True)


__all__ = [
    "PathLike",
    "file_time",
    "get_dirs",
    "get_files",
    "handle_path",
    "is_dir",
    "is_file",
    "list_paths",
    "make_dirs",
    "move",
    "remove",
    "rename",
]
