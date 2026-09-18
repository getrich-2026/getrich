"""ingest 层统一入口：按 provider 运行 importer 并写 PostgreSQL。"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.ingest.base import IngestContext, IngestResult


log = logging.getLogger(__name__)

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


def _expand(names: list[str], registry: dict[str, Any], groups: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for n in names:
        if n in groups:
            out += groups[n]
        elif n in registry:
            out.append(n)
        else:
            log.warning("未知 importer: %s，跳过", n)
    return list(dict.fromkeys(out))


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
    registry, groups = _registry_groups(provider)
    if provider == "ricequant":
        names = preflight_ricequant(cfg, only=only)
    else:
        enabled = only or cfg.get("enabled", "ingest", provider, default=list(registry.keys()))
        names = _expand(enabled, registry, groups)
    if provider == "tushare":
        # --only 的排列不能颠倒 instruments → symbol_map → 其余数据的依赖。
        names.sort(key=list(registry).index)

    ctx = IngestContext(
        paths=RawPaths(cfg.raw_root), force_ownership=force_ownership, months=months
    )
    kwargs = _provider_kwargs(provider, cfg)
    results: list[IngestResult] = []
    for name in names:
        if provider == "ricequant" and name == "rq_risk_model":
            from gr_data.config.ricequant import parse_ricequant_options
            from gr_data.ingest.ricequant.riskmodel import run_risk_ingest

            options = parse_ricequant_options(cfg, phase="ingest").datasets[name]
            results.append(run_risk_ingest(conn, ctx, options))
            continue
        importer = registry[name](conn, ctx, **kwargs)
        log.info("ingest 开始 provider=%s importer=%s", provider, name)
        results.append(importer.run())
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
