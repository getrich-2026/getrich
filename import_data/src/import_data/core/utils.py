# Utility module for import_data package
from __future__ import annotations

from pathlib import Path


def handle_path(path: str | Path) -> Path:
    """
    处理路径字符串或对象，并确保其父目录存在。

    Args:
        path: 路径字符串或 Path 对象。

    Returns:
        解析为绝对路径并确保创建好的 Path 对象。
    """
    p = Path(path).resolve()
    # 如果是文件路径（有后缀）则创建其父目录；如果是目录则直接创建该目录
    if p.suffix:
        p.parent.mkdir(parents=True, exist_ok=True)
    else:
        p.mkdir(parents=True, exist_ok=True)
    return p
