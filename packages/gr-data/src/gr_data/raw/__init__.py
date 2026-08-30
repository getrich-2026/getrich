"""raw 层统一入口：按 provider 构建真实 client 并运行 fetcher。

测试可绕过本模块，直接用 Fake client 实例化 fetcher。
"""

from __future__ import annotations

from typing import Any

from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.logging import get_logger
from gr_data.raw.base import RawContext
from gr_data.raw.datayes.client import (
    DEFAULT_BASE_URL as DATAYES_DEFAULT_BASE_URL,
    NotAuthorizedError,
)


log = get_logger("raw.runner")

PROVIDERS = ("yinhe", "ricequant", "insight", "tushare", "datayes")


def _registry(provider: str) -> dict[str, Any]:
    if provider == "yinhe":
        from gr_data.raw.yinhe import REGISTRY
    elif provider == "ricequant":
        from gr_data.raw.ricequant import REGISTRY
    elif provider == "insight":
        from gr_data.raw.insight import REGISTRY
    elif provider == "tushare":
        from gr_data.raw.tushare import REGISTRY
    elif provider == "datayes":
        from gr_data.raw.datayes import REGISTRY
    else:
        raise ValueError(f"未知 provider: {provider}")
    return REGISTRY


def _build_client(provider: str, cfg: Config) -> Any:
    pconf = cfg.section("providers", provider)
    if provider == "yinhe":
        from gr_data.raw.yinhe import AmazingDataClient

        return AmazingDataClient(
            username=pconf.get("username", ""),
            password=pconf.get("password", ""),
            host=pconf.get("host", ""),
            port=int(pconf.get("port", 8600)),
        )
    if provider == "ricequant":
        from gr_data.raw.ricequant import RqdatacClient

        return RqdatacClient(
            license_key=pconf.get("license"),
            username=pconf.get("username"),
            password=pconf.get("password"),
            market=pconf.get("market", "cn"),
        )
    if provider == "insight":
        from gr_data.raw.insight import InsightApiClient

        return InsightApiClient(
            username=pconf.get("username", ""),
            password=pconf.get("password", ""),
        )
    if provider == "tushare":
        from gr_data.raw.tushare import TushareProClient

        return TushareProClient(token=pconf.get("token", ""))
    if provider == "datayes":
        from gr_data.raw.datayes import DatayesHttpClient

        rate = pconf.get("rate_limit") or {}
        return DatayesHttpClient(
            token=pconf.get("token", ""),
            base_url=pconf.get("base_url", DATAYES_DEFAULT_BASE_URL),
            sleep_between_requests=float(rate.get("sleep_between_requests_sec", 1.0)),
        )
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
        try:
            results[name] = fetcher.fetch(mode=mode)
        except NotAuthorizedError:
            # 按表购买制下「没买这张表」是可预期状态，不该让整批抓取失败。
            # 但也不能静默跳过——缺表会让下游指标降级，日志里必须留痕。
            log.error("provider=%s dataset=%s 未授权，跳过；其余 dataset 继续", provider, name)
            results[name] = 0
    return results
