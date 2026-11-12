"""期权原始观察读取：根目录、整份清单、收据和响应摘要必须一致。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from gr_data.common.paths import RawPaths


def sha256_file(path: Path) -> str:
    """有界计算原件 SHA256。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_option_observation(
    paths: RawPaths, folder: Path, *, manifest_sha256: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """只读已发布观察；不得以临时文件或自行重算摘要替代登记的摘要。

    Args:
        paths: 当前明确配置的 raw 根。
        folder: 含 response.parquet／receipt.json／sha256-manifest.json 的目录。
        manifest_sha256: 运行登记中事先冻结的清单摘要。

    Returns:
        原始 DataFrame 与来源收据，不修改字段、日期或数据值。

    Raises:
        ValueError: 路径越界、清单不完整、文件或收据摘要不符。
    """
    base = folder.resolve()
    root = paths.root.resolve()
    if not base.is_relative_to(root) or base == root:
        raise ValueError("Option observation outside configured raw root")
    manifest = base / "sha256-manifest.json"
    if not manifest.resolve().is_relative_to(base) or sha256_file(manifest) != manifest_sha256:
        raise ValueError("Option observation manifest changed")
    files = json.loads(manifest.read_text())
    if not isinstance(files, dict) or not {"response.parquet", "receipt.json"} <= files.keys():
        raise ValueError("Incomplete option observation manifest")
    for relative, digest in files.items():
        path = (base / relative).resolve()
        if not path.is_relative_to(base) or sha256_file(path) != digest:
            raise ValueError("Option observation artifact changed")
    receipt = json.loads((base / "receipt.json").read_text())
    if receipt.get("provider") != "ricequant":
        raise ValueError("Option observation provider differs")
    response = base / "response.parquet"
    if receipt.get("response_sha256") != files["response.parquet"]:
        raise ValueError("Option response and receipt differ")
    frame = pd.read_parquet(response)
    if len(frame) != receipt.get("rows"):
        raise ValueError("Option response row count differs")
    # 检查读取期间没有换清单，避免检查后再替换文件的常见竞态。
    if (
        sha256_file(response) != files["response.parquet"]
        or sha256_file(base / "receipt.json") != files["receipt.json"]
        or sha256_file(manifest) != manifest_sha256
    ):
        raise ValueError("Option observation changed during read")
    return frame, receipt
