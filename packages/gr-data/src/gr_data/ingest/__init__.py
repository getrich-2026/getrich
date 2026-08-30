"""ingest 层统一入口：按 provider 运行 importer 并写 PostgreSQL。"""

from __future__ import annotations

from typing import Any

import psycopg

from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.ingest.base import IngestContext, IngestResult
from gr_data.logging import get_logger


log = get_logger("ingest.runner")

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
    enabled = only or cfg.get("enabled", "ingest", provider, default=list(registry.keys()))
    names = _expand(enabled, registry, groups)

    ctx = IngestContext(
        paths=RawPaths(cfg.raw_root), force_ownership=force_ownership, months=months
    )
    kwargs = _provider_kwargs(provider, cfg)
    results: list[IngestResult] = []
    for name in names:
        importer = registry[name](conn, ctx, **kwargs)
        log.info("ingest 开始 provider=%s importer=%s", provider, name)
        results.append(importer.run())
    return results


def _provider_kwargs(provider: str, cfg: Config) -> dict[str, Any]:
    """provider 专属的构造参数。

    datayes 的量纲系数**没有默认值**：配置里缺任何一个键都直接拒绝启动，
    而不是按一套猜的系数换算。理由见 ingest/datayes/scaling.py。
    """
    if provider == "datayes":
        from gr_data.ingest.datayes.scaling import load_scaling

        return {"scaling": load_scaling(cfg.section("providers", "datayes").get("scaling"))}
    return {}
