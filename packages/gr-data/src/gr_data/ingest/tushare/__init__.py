"""Tushare ingest 层：$RAW_PARQUET_ROOT/tushare/ → PostgreSQL。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gr_data.ingest.tushare.importers import GROUPS, REGISTRY


if TYPE_CHECKING:
    from gr_data.common.contracts.base import TableContract


def specialized_dataset_contracts() -> dict[str, tuple[TableContract, ...]]:
    """日更／专用入库入口的原件与目标契约，不加入通用 importer 调度。"""
    from gr_data.ingest.tushare.industry import DATASET_CONTRACTS

    return DATASET_CONTRACTS


__all__ = ["REGISTRY", "GROUPS", "specialized_dataset_contracts"]
