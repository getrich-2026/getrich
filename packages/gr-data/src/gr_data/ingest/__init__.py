"""ingest 层统一入口：按 provider 运行 importer 并写 PostgreSQL。"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from gr_data.common.ownership import OwnershipError
from gr_data.common.parquet import CorruptRawError
from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.ingest.base import IngestContext, IngestGateError, IngestResult


log = logging.getLogger(__name__)

_EXPECTED_FAILURES = (IngestGateError, CorruptRawError, OwnershipError)


class UnknownImporterError(RuntimeError):
    """配置里有不存在的 importer 名；属配置问题，CLI 返回 2，且在连库之前报出。"""


PROVIDERS = ("yinhe", "ricequant", "insight", "tushare", "datayes")


def _registry_groups(provider: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if provider == "yinhe":
        from gr_data.ingest.yinhe import GROUPS, REGISTRY
    elif provider == "ricequant":
        from gr_data.ingest.ricequant import GROUPS, REGISTRY
    elif provider == "insight":
        from gr_data.ingest.insight import GROUPS, REGISTRY
    elif provider == "tushare":
        from gr_data.ingest.tushare import GROUPS, REGISTRY
    elif provider == "datayes":
        from gr_data.ingest.datayes import GROUPS, REGISTRY
    else:
        raise ValueError(f"未知 provider: {provider}")
    return REGISTRY, GROUPS


class IngestRunError(Exception):  # 不继承 RuntimeError：cli.main 把后者当配置问题返回 2
    """某个 importer 硬失败：已提交的保留，失败者已回滚并记 failed，其后 importer 未执行。"""

    def __init__(
        self,
        provider: str,
        importer: str,
        completed: list[IngestResult],
        skipped: list[str],
        error: str,
    ) -> None:
        super().__init__(f"ingest {provider}.{importer} failed: {error}")
        self.provider = provider
        self.importer = importer
        self.completed = completed
        self.skipped = skipped
        self.error = error


def _expand(names: list[str], registry: dict[str, Any], groups: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    unknown: list[str] = []
    for n in names:
        if n in groups:
            out += groups[n]
        elif n in registry:
            out.append(n)
        else:
            unknown.append(n)
    if unknown:
        # 配置写错不能静默跳过：少跑一个 importer 看起来和「没有数据」一样。
        raise UnknownImporterError(f"Unknown importer(s): {unknown}")
    return list(dict.fromkeys(out))


def plan_importers(provider: str, cfg: Config, only: list[str] | None = None) -> list[str]:
    """解析本次要运行的 importer 名单；在连接数据库前调用，未知名称直接报错。"""
    registry, groups = _registry_groups(provider)
    if provider == "ricequant":
        return preflight_ricequant(cfg, only=only)
    enabled = only or cfg.get("enabled", "ingest", provider, default=list(registry.keys()))
    names = _expand(enabled, registry, groups)
    if provider == "tushare":
        # --only 的排列不能颠倒 instruments → symbol_map → 其余数据的依赖。
        names.sort(key=list(registry).index)
    return names


def _error_summary(exc: BaseException) -> str:
    """失败记录只保留异常类型与截断后的消息，避免把数据库错误里的整行值写进流水。"""
    return f"{type(exc).__name__}: {str(exc)[:500]}"


def _record_failure(conn: psycopg.Connection, provider: str, dataset: str, error: str) -> None:
    """失败流水用独立短事务写入；写不进去只记日志，不掩盖原始异常。"""
    try:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.etl_job_run
                  (job_name, provider, dataset_name, status, rows_written, warning_count,
                   started_at, finished_at, error)
                VALUES (%s, %s, %s, 'failed', 0, 0, now(), now(), %s)
                """,
                (f"ingest.{provider}.{dataset}", provider, dataset, error),
            )
        conn.commit()
    except psycopg.Error:
        log.exception("Failed to record ingest failure provider=%s dataset=%s", provider, dataset)
        try:
            conn.rollback()
        except psycopg.Error:
            # 连接已断：原异常必须照常以 IngestRunError 抛出，这里只留痕。
            log.warning(
                "Rollback after failure record failed provider=%s dataset=%s", provider, dataset
            )


def run_provider(
    provider: str,
    conn: psycopg.Connection,
    cfg: Config,
    *,
    only: list[str] | None = None,
    force_ownership: bool = False,
    months: tuple[str, ...] | None = None,
) -> list[IngestResult]:
    """运行某 provider 下启用的（或 only 指定的）importer。

    `months` 限定只处理哪些自然月，用于把大数据集分批入库（见
    `IngestContext.months` 里关于内存的说明）。None = 全部。
    """
    registry, _ = _registry_groups(provider)
    names = plan_importers(provider, cfg, only=only)

    ctx = IngestContext(
        paths=RawPaths(cfg.raw_root), force_ownership=force_ownership, months=months
    )
    kwargs = _provider_kwargs(provider, cfg)
    results: list[IngestResult] = []
    for i, name in enumerate(names):
        try:
            if provider == "ricequant" and name == "rq_risk_model":
                from gr_data.config.ricequant import parse_ricequant_options
                from gr_data.ingest.ricequant.riskmodel import run_risk_ingest

                options = parse_ricequant_options(cfg, phase="ingest").datasets[name]
                results.append(run_risk_ingest(conn, ctx, options))
                continue
            importer = registry[name](conn, ctx, **kwargs)
            log.info("ingest 开始 provider=%s importer=%s", provider, name)
            results.append(importer.run())
        except Exception as exc:
            # 后续 importer 依赖前面的结果（symbol_map、停复牌覆盖等），失败后不再继续。
            error = _error_summary(exc)
            # 门禁、坏文件与归属冲突是可操作的预期失败，只记摘要；其他异常多为程序缺陷，保留堆栈。
            log.error(
                "Ingest failed provider=%s importer=%s error=%s",
                provider,
                name,
                error,
                exc_info=not isinstance(exc, _EXPECTED_FAILURES),
            )
            dataset = getattr(registry.get(name), "DATASET", name) or name
            _record_failure(conn, provider, dataset, error)
            raise IngestRunError(provider, name, results, names[i + 1 :], error) from exc
    return results


def preflight_ricequant(cfg: Config, *, only: list[str] | None) -> list[str]:
    """在连接 PG 前拒绝未知、未准入或 writer 尚未实现的补充任务。"""
    from gr_data.common.ricequant_specs import INDEX_SPECS, RqConfigurationError
    from gr_data.config.ricequant import select_datasets

    registry, groups = _registry_groups("ricequant")
    names, _ = select_datasets(
        only, cfg, phase="ingest", legacy=tuple(registry), legacy_groups=groups
    )
    if any(name in INDEX_SPECS for name in names):
        raise RqConfigurationError(
            "米筐补充 ingest 尚未开放：需先完成 P0 样本准入，"
            "再实现对应 DDL 和 writer；本次未连接数据库"
        )
    return list(names)


def _provider_kwargs(provider: str, cfg: Config) -> dict[str, Any]:
    """provider 专属的构造参数。

    datayes 的量纲系数**没有默认值**：配置里缺任何一个键都直接拒绝启动，
    而不是按一套猜的系数换算。理由见 ingest/datayes/scaling.py。
    """
    if provider == "datayes":
        from gr_data.ingest.datayes.scaling import load_scaling

        return {"scaling": load_scaling(cfg.section("providers", "datayes").get("scaling"))}
    return {}
