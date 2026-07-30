"""raw 层统一入口：按 provider 构建真实 client 并运行 fetcher。

测试可绕过本模块，直接用 Fake client 实例化 fetcher。
"""

from __future__ import annotations

from typing import Any

from getrich_data.common.config import Config
from getrich_data.common.logging import get_logger
from getrich_data.common.paths import RawPaths
from getrich_data.raw.base import RawContext

log = get_logger("raw.runner")

PROVIDERS = ("yinhe", "ricequant", "insight", "tushare")


def _registry(provider: str) -> dict[str, Any]:
    if provider == "yinhe":
        from getrich_data.raw.yinhe import REGISTRY
    elif provider == "ricequant":
        from getrich_data.raw.ricequant import REGISTRY
    elif provider == "insight":
        from getrich_data.raw.insight import REGISTRY
    elif provider == "tushare":
        from getrich_data.raw.tushare import REGISTRY
    else:
        raise ValueError(f"未知 provider: {provider}")
    return REGISTRY


def _build_client(provider: str, cfg: Config) -> Any:
    pconf = cfg.section("providers", provider)
    if provider == "yinhe":
        from getrich_data.raw.yinhe import AmazingDataClient

        return AmazingDataClient(
            username=pconf.get("username", ""),
            password=pconf.get("password", ""),
            host=pconf.get("host", ""),
            port=int(pconf.get("port", 8600)),
        )
    if provider == "ricequant":
        from getrich_data.raw.ricequant import RqdatacClient

        return RqdatacClient(
            license_key=pconf.get("license"),
            username=pconf.get("username"),
            password=pconf.get("password"),
            market=pconf.get("market", "cn"),
        )
    if provider == "insight":
        from getrich_data.raw.insight import InsightApiClient

        return InsightApiClient(
            username=pconf.get("username", ""),
            password=pconf.get("password", ""),
        )
    if provider == "tushare":
        from getrich_data.raw.tushare import TushareProClient

        return TushareProClient(token=pconf.get("token", ""))
    raise ValueError(f"未知 provider: {provider}")


def _build_context(provider: str, cfg: Config) -> RawContext:
    pconf = cfg.section("providers", provider)
    return RawContext(
        paths=RawPaths(cfg.raw_root),
        rate_limit=pconf.get("rate_limit", {}) if isinstance(pconf.get("rate_limit"), dict) else {},
        start_date=pconf.get("start_date"),
    )


def run_provider(
    provider: str,
    cfg: Config,
    *,
    mode: str = "update",
    only: list[str] | None = None,
) -> dict[str, int]:
    """运行某 provider 下启用的（或 only 指定的）所有 fetcher。返回 {dataset: 写入数}。"""
    registry = _registry(provider)
    enabled = only or cfg.get("enabled", "raw", provider, default=list(registry.keys()))
    client = _build_client(provider, cfg)
    ctx = _build_context(provider, cfg)

    results: dict[str, int] = {}
    for name in enabled:
        if name not in registry:
            log.warning("provider=%s 未知 fetcher: %s，跳过", provider, name)
            continue
        fetcher = registry[name](client, ctx)
        log.info("raw 抓取开始 provider=%s dataset=%s mode=%s", provider, name, mode)
        results[name] = fetcher.fetch(mode=mode)
    return results
