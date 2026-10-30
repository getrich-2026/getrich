"""从 ingest 注册表和运行时归属表推导数据来源与漂移。"""

from __future__ import annotations

import importlib
import logging
import stat
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import load_config
from psycopg import errors as pg_errors

from gr_db.ddl_lint import SELF_EXPLANATORY_COLUMNS

from .model import DatasetDoc, DriftFinding, SchemaDoc, TableDoc


logger = logging.getLogger(__name__)

_PROVIDERS = ("tushare", "datayes", "insight", "ricequant", "yinhe")

RegistryEntry = tuple[str, str, Any]
"""``(provider, dataset, importer)``。"""


def load_registry() -> tuple[RegistryEntry, ...]:
    """导入各 provider 的 ingest 注册表，按 provider、dataset 排序展开。

    Time Complexity: O(r log r)，r 为注册项数。
    Space Complexity: O(r)。
    """
    entries: list[RegistryEntry] = []
    for provider in _PROVIDERS:
        registry = importlib.import_module(f"gr_data.ingest.{provider}").REGISTRY
        entries.extend(
            (provider, dataset, importer) for dataset, importer in sorted(registry.items())
        )
    return tuple(entries)


def _directory_stats(directory: Path) -> tuple[int | None, int | None]:
    """统计目录下的文件数和总字节数；目录不存在或不可读时返回 ``(None, None)``。

    每个条目只 stat 一次。

    Time Complexity: O(f)，f 为目录下的条目数。
    Space Complexity: O(1)。
    """
    if not directory.is_dir():
        return None, None
    file_count = 0
    total_bytes = 0
    try:
        for path in directory.rglob("*"):
            info = path.stat()
            if stat.S_ISREG(info.st_mode):
                file_count += 1
                total_bytes += info.st_size
    except OSError as exc:
        logger.warning("cannot scan raw dataset directory %s: %s", directory, exc)
        return None, None
    return file_count, total_bytes


def discover_datasets(
    raw_root: Path | None = None,
    registry: tuple[RegistryEntry, ...] | None = None,
) -> tuple[DatasetDoc, ...]:
    """从真实 ingest 注册表推导 raw 数据集路径及文件统计。

    Args:
        raw_root: raw parquet 根目录；缺省读 ``gr_data`` 配置。
        registry: 预先加载的注册表；缺省调用 :func:`load_registry`。

    Time Complexity: O(r + f)，r 为注册项数、f 为可访问目录中的文件数。
    Space Complexity: O(r)。
    """
    paths = RawPaths(raw_root or load_config().raw_root)
    datasets: list[DatasetDoc] = []
    for provider, dataset, importer in registry if registry is not None else load_registry():
        contract = getattr(importer, "CONTRACT", None)
        target = contract.qualified if contract is not None else None
        directory = paths.dataset_dir(provider, dataset)
        file_count, total_bytes = _directory_stats(directory)
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


def fetch_ownership(conn: Any) -> dict[str, tuple[str, str]] | None:
    """读取 ``ops.table_ownership`` 的运行时归属。

    表尚未迁移时返回 ``None``，由调用方降级为漂移提示，而不是让整个字典生成失败。

    Time Complexity: O(n)，n 为归属记录数。
    Space Complexity: O(n)。
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT target, provider, channel FROM ops.table_ownership")
            rows = cur.fetchall()
    except pg_errors.UndefinedTable as exc:
        logger.warning("ops.table_ownership unavailable, ownership checks skipped: %s", exc)
        return None
    return {target: (provider, channel) for target, provider, channel in rows}


def _missing_comment_columns(table: TableDoc) -> list[str]:
    """列出缺少注释且不在豁免集合内的列名，保持原列序。"""
    return [
        column.name
        for column in table.columns
        if not column.comment and column.name not in SELF_EXPLANATORY_COLUMNS
    ]


def enrich_provenance(
    schemas: tuple[SchemaDoc, ...],
    ownership: dict[str, tuple[str, str]] | None,
    registry: tuple[RegistryEntry, ...] | None = None,
) -> tuple[tuple[SchemaDoc, ...], tuple[DriftFinding, ...]]:
    """合并注册表、运行时归属并产生契约/注释漂移。

    多 provider 声明同一目标表是可选的接入能力；实际单表写入方以
    ``ops.table_ownership`` 为准，避免将未启用的 provider 错报为生产冲突。
    主键与审计列（见 ``SELF_EXPLANATORY_COLUMNS``）不要求注释，也不要求出现在契约中；
    缺注释的列按表汇总为一条 warn。

    Args:
        schemas: 活库反射结果。
        ownership: ``ops.table_ownership`` 内容；``None`` 表示该表不存在，
            此时跳过全部归属检查并给出一条 warn。
        registry: 预先加载的注册表；缺省调用 :func:`load_registry`。

    Time Complexity: O(t + r + c)，t 为表数、r 为注册项数、c 为契约列数。
    Space Complexity: O(t + r + c)。
    """
    declarations: dict[str, list[tuple[str, str, tuple[str, ...]]]] = defaultdict(list)
    for provider, dataset, importer in registry if registry is not None else load_registry():
        contract = getattr(importer, "CONTRACT", None)
        if contract is not None:
            declarations[contract.qualified].append((provider, dataset, contract.columns))

    findings: list[DriftFinding] = []
    known_targets = {table.qualified for schema in schemas for table in schema.tables}
    for target in declarations:
        if target not in known_targets:
            findings.append(DriftFinding("error", "契约目标表在活库中不存在", target))
    if ownership is None:
        findings.append(
            DriftFinding(
                "warn", "ops.table_ownership 不存在，已跳过运行时归属检查", "ops.table_ownership"
            )
        )
    else:
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
            if declared:
                for column in sorted(actual_columns - contract_columns - SELF_EXPLANATORY_COLUMNS):
                    findings.append(
                        DriftFinding("warn", f"活库列 {column} 未在 ingest 契约中声明", target)
                    )
            if declared and ownership is not None and target not in ownership:
                findings.append(
                    DriftFinding("warn", "有 importer 声明但 ops.table_ownership 未登记", target)
                )
            if not table.comment:
                findings.append(DriftFinding("warn", "表缺少 COMMENT ON", target))
            missing_comments = _missing_comment_columns(table)
            if missing_comments:
                findings.append(
                    DriftFinding(
                        "warn",
                        f"{len(missing_comments)} 列缺少 COMMENT ON：{', '.join(missing_comments)}",
                        target,
                    )
                )
            runtime_provider = (ownership or {}).get(target, (None, ""))[0]
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
