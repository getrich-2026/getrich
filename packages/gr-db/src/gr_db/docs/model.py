"""数据字典的无 I/O 数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ColumnDoc:
    """一列的 catalog 元数据。"""

    name: str
    data_type: str
    nullable: bool
    default: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class TableDoc:
    """一张 PostgreSQL 或 ClickHouse 表的 catalog 元数据。"""

    schema: str
    name: str
    columns: tuple[ColumnDoc, ...] = ()
    comment: str | None = None
    constraints: tuple[str, ...] = ()
    indexes: tuple[str, ...] = ()
    row_estimate: int | None = None
    total_bytes: int | None = None
    engine: str | None = None
    partition_key: str | None = None
    sorting_key: str | None = None
    hypertable: str | None = None
    compression: str | None = None
    providers: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()

    @property
    def qualified(self) -> str:
        """返回 ``schema.table`` 形式的表名。"""
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class SchemaDoc:
    """一个 schema 及其表。"""

    name: str
    tables: tuple[TableDoc, ...] = ()


@dataclass(frozen=True)
class DatasetDoc:
    """raw parquet 数据集的约定路径和可选磁盘统计。"""

    provider: str
    dataset: str
    path: str
    file_count: int | None = None
    total_bytes: int | None = None
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class DriftFinding:
    """数据字典发现的契约或归属漂移。"""

    severity: Literal["error", "warn"]
    message: str
    target: str | None = None


@dataclass(frozen=True)
class Dictionary:
    """可渲染的数据字典完整快照。"""

    schemas: tuple[SchemaDoc, ...] = ()
    clickhouse_tables: tuple[TableDoc, ...] = ()
    datasets: tuple[DatasetDoc, ...] = ()
    findings: tuple[DriftFinding, ...] = ()
    generated_at: str | None = None
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
