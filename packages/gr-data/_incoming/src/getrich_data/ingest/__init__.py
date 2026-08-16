"""ingest 层统一入口：按 provider 运行 importer 并写 PostgreSQL。"""

from __future__ import annotations

from typing import Any

import psycopg

from getrich_data.common.config import Config
from getrich_data.common.logging import get_logger
from getrich_data.common.paths import RawPaths
from getrich_data.ingest.base import IngestContext, IngestResult

log = get_logger("ingest.runner")

PROVIDERS = ("yinhe", "ricequant", "insight", "tushare")


def _registry_groups(provider: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
    if provider == "yinhe":
        from getrich_data.ingest.yinhe import GROUPS, REGISTRY
    elif provider == "ricequant":
        from getrich_data.ingest.ricequant import GROUPS, REGISTRY
    elif provider == "insight":
        from getrich_data.ingest.insight import GROUPS, REGISTRY
    elif provider == "tushare":
        from getrich_data.ingest.tushare import GROUPS, REGISTRY
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
) -> list[IngestResult]:
    """运行某 provider 下启用的（或 only 指定的）importer。"""
    registry, groups = _registry_groups(provider)
    enabled = only or cfg.get("enabled", "ingest", provider, default=list(registry.keys()))
    names = _expand(enabled, registry, groups)

    ctx = IngestContext(paths=RawPaths(cfg.raw_root), force_ownership=force_ownership)
    results: list[IngestResult] = []
    for name in names:
        importer = registry[name](conn, ctx)
        log.info("ingest 开始 provider=%s importer=%s", provider, name)
        results.append(importer.run())
    return results
