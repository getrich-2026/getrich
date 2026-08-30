"""从 ingest 注册表和运行时归属表推导数据来源与漂移。"""

from __future__ import annotations

import importlib
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import load_config

from .model import DatasetDoc, DriftFinding, SchemaDoc, TableDoc


_PROVIDERS = ("tushare", "datayes", "insight", "ricequant", "yinhe")


def discover_datasets(raw_root: Path | None = None) -> tuple[DatasetDoc, ...]:
    """从真实 ingest 注册表推导 raw 数据集路径及文件统计。

    Time Complexity: O(r + f)，r 为注册项数、f 为可访问目录中的文件数。
    Space Complexity: O(r)。
    """
    paths = RawPaths(raw_root or load_config().raw_root)
    datasets: list[DatasetDoc] = []
    for provider in _PROVIDERS:
        registry = importlib.import_module(f"gr_data.ingest.{provider}").REGISTRY
        for dataset, importer in sorted(registry.items()):
            contract = getattr(importer, "CONTRACT", None)
            target = contract.qualified if contract is not None else None
            directory = paths.dataset_dir(provider, dataset)
            file_count: int | None = None
            total_bytes: int | None = None
            if directory.is_dir():
                try:
                    files = [p for p in directory.rglob("*") if p.is_file()]
                    file_count = len(files)
                    total_bytes = sum(p.stat().st_size for p in files)
                except OSError:
                    pass
            datasets.append(
                DatasetDoc(
                    provider=provider,
                    dataset=dataset,
                    path=str(directory),
                    file_count=file_count,
                    total_bytes=total_bytes,
                    targets=(target,) if target else (),
                )
            )
    return tuple(datasets)


def fetch_ownership(conn: Any) -> dict[str, tuple[str, str]]:
    """读取 ``ops.table_ownership`` 的运行时归属。

    Time Complexity: O(n)，n 为归属记录数。
    Space Complexity: O(n)。
    """
    with conn.cursor() as cur:
        cur.execute("SELECT target, provider, channel FROM ops.table_ownership")
        return {target: (provider, channel) for target, provider, channel in cur.fetchall()}


def enrich_provenance(
    schemas: tuple[SchemaDoc, ...],
    ownership: dict[str, tuple[str, str]],
) -> tuple[tuple[SchemaDoc, ...], tuple[DriftFinding, ...]]:
    """合并注册表、运行时归属并产生契约/注释漂移。

    多 provider 声明同一目标表是可选的接入能力；实际单表写入方以
    ``ops.table_ownership`` 为准，避免将未启用的 provider 错报为生产冲突。

    Time Complexity: O(t + r + c)，t 为表数、r 为注册项数、c 为契约列数。
    Space Complexity: O(t + r + c)。
    """
    declarations: dict[str, list[tuple[str, str, tuple[str, ...]]]] = defaultdict(list)
    for provider in _PROVIDERS:
        registry = importlib.import_module(f"gr_data.ingest.{provider}").REGISTRY
        for dataset, importer in registry.items():
            contract = getattr(importer, "CONTRACT", None)
            if contract is not None:
                declarations[contract.qualified].append((provider, dataset, contract.columns))

    findings: list[DriftFinding] = []
    known_targets = {table.qualified for schema in schemas for table in schema.tables}
    for target, _declared in declarations.items():
        if target not in known_targets:
            findings.append(DriftFinding("error", "契约目标表在活库中不存在", target))
    for target, (provider, _channel) in ownership.items():
        declared_providers = {item[0] for item in declarations.get(target, [])}
        if declared_providers and provider not in declared_providers:
            findings.append(
                DriftFinding("error", f"运行时归属 provider={provider} 与注册表不一致", target)
            )
        if target not in known_targets:
            findings.append(DriftFinding("warn", "归属记录指向活库中不存在的表", target))

    output: list[SchemaDoc] = []
    for schema in schemas:
        tables: list[TableDoc] = []
        for table in schema.tables:
            target = table.qualified
            declared = declarations.get(target, [])
            contract_columns = {
                column for _provider, _dataset, columns in declared for column in columns
            }
            actual_columns = {column.name for column in table.columns}
            for column in sorted(contract_columns - actual_columns):
                findings.append(DriftFinding("error", f"契约列 {column} 在活库中不存在", target))
            for column in sorted(actual_columns - contract_columns - {"updated_at"}):
                if declared:
                    findings.append(
                        DriftFinding("warn", f"活库列 {column} 未在 ingest 契约中声明", target)
                    )
            if declared and target not in ownership:
                findings.append(
                    DriftFinding("warn", "有 importer 声明但 ops.table_ownership 未登记", target)
                )
            if not table.comment:
                findings.append(DriftFinding("warn", "表缺少 COMMENT ON", target))
            for column in table.columns:
                if not column.comment:
                    findings.append(
                        DriftFinding("warn", f"列 {column.name} 缺少 COMMENT ON", target)
                    )
            runtime_provider = ownership.get(target, (None, ""))[0]
            providers = (
                (runtime_provider,)
                if runtime_provider
                else tuple(sorted({item[0] for item in declared}))
            )
            datasets = tuple(sorted({f"{provider}.{dataset}" for provider, dataset, _ in declared}))
            tables.append(replace(table, providers=providers, datasets=datasets))
        output.append(SchemaDoc(schema.name, tuple(tables)))
    findings.sort(key=lambda item: (item.severity != "error", item.target or "", item.message))
    return tuple(output), tuple(findings)
