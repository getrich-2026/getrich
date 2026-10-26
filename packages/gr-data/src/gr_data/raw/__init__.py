"""raw 层统一入口：按 provider 构建真实 client 并运行 fetcher。

测试可绕过本模块，直接用 Fake client 实例化 fetcher。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.raw.base import RawContext
from gr_data.raw.datayes.client import (
    DEFAULT_BASE_URL as DATAYES_DEFAULT_BASE_URL,
    NotAuthorizedError,
)


log = logging.getLogger(__name__)

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

        return TushareProClient(
            token=pconf.get("token", ""),
            sleep_between_requests=_build_context(provider, cfg).sleep_between_requests,
        )
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
    if provider == "tushare":
        from gr_data.raw.tushare.context import build_context

        return build_context(cfg)
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
    if provider == "ricequant":
        return _run_ricequant(cfg, registry, mode=mode, only=only)
    defaults = list(registry)
    if provider == "tushare":
        from gr_data.raw.tushare.fetchers import DEFAULT_DATASETS

        defaults = list(DEFAULT_DATASETS)
    enabled = only or cfg.get("enabled", "raw", provider, default=defaults)
    if provider == "tushare":
        # 显式选择的集合不变，按注册顺序保证日历先于逐日抓取。
        order = {name: index for index, name in enumerate(registry)}
        enabled = sorted(dict.fromkeys(enabled), key=lambda name: order.get(name, len(order)))
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


def _run_ricequant(
    cfg: Config,
    registry: dict[str, Any],
    *,
    mode: str,
    only: list[str] | None,
) -> dict[str, int]:
    """先验证整批选择；新数据使用独立客户端参数，默认集合仍为旧任务。"""
    from gr_data.common.ricequant_specs import ContractViolationError, RqConfigurationError
    from gr_data.config.ricequant import select_datasets
    from gr_data.raw.ricequant.client import RqdatacClient
    from gr_data.raw.ricequant.fetchers.supplements import run_supplement
    from gr_data.raw.ricequant.riskmodel import run_risk_raw

    names, options = select_datasets(only, cfg, phase="raw", legacy=tuple(registry))
    if not names:
        return {}
    selected = [options.datasets[n] for n in names if n not in registry]
    if len({d.enable_bjse for d in selected}) > 1:
        raise RqConfigurationError("同批米筐任务必须使用一致的 enable_bjse；不同成员宇宙请分批运行")
    ctx = _build_context("ricequant", cfg)
    results: dict[str, int] = {}
    failures = []
    with ExitStack() as stack:
        # 整批预检早于 SDK 初始化与其他数据集请求，避免缺迁移时先消耗账户配额。
        capture_callbacks = {
            name: stack.enter_context(_risk_capture_callback(cfg, options.datasets[name]))
            for name in names
            if name == "rq_risk_model"
        }
        # SDK 初始化为进程全局状态；先跑旧任务，再顺序初始化各补充数据的显式参数。
        legacy_client = (
            _build_client("ricequant", cfg) if any(n in registry for n in names) else None
        )
        for name in names:
            if name in registry:
                results[name] = registry[name](legacy_client, ctx).fetch(mode=mode)
        client = (
            RqdatacClient(
                options.license_key,
                connect_timeout=options.connect_timeout,
                timeout=options.timeout,
                enable_bjse=selected[0].enable_bjse,
            )
            if selected
            else None
        )
        for name in names:
            if name in registry:
                continue
            dataset = options.datasets[name]
            try:
                if name == "rq_risk_model":
                    extra = {"capture_callback": capture_callbacks[name]}
                    if dataset.universe_policy != "fixed":
                        extra["universe_provider"] = _lazy_risk_universe_provider(
                            cfg, client, options.quota_reserve_fraction, dataset
                        )
                    results[name] = run_risk_raw(client, ctx, dataset, options, mode=mode, **extra)
                else:
                    results[name] = run_supplement(client, ctx, dataset, options, mode=mode)
            except ContractViolationError:
                failures.append(name)
                log.error("Ricequant dataset incomplete dataset=%s", name)
    if failures:
        raise ContractViolationError(f"米筐补充任务未完成：{', '.join(failures)}；成功片已保留")
    return results


@contextmanager
def _risk_capture_callback(
    cfg: Config, risk_options: Any
) -> Iterator[Callable[[dict], None] | None]:
    """生产 raw 预检迁移并登记 variant；每个捕获回执使用独立空闲连接事务。"""
    if risk_options.purpose != "production":
        yield None
        return
    from gr_tools.config import load_environment

    from gr_data.config import load_postgres
    from gr_data.db.risk_receipts import prepare_capture, record_capture
    from gr_data.db.sync import PgConfig, connect

    env = cfg.environment if cfg.environment is not None else load_environment()
    pg = load_postgres(env)
    with connect(PgConfig(pg.host, pg.port, pg.database, pg.user, pg.password)) as conn:
        prepare_capture(conn, risk_options)

        def callback(manifest: dict) -> None:
            record_capture(conn, risk_options, manifest)

        yield callback


def _lazy_risk_universe_provider(
    cfg: Config, client: Any, quota_reserve_fraction: float, risk_options: Any
) -> Callable[[str], dict[str, Any]]:
    """仅新抓取日才冻结参考；恢复已完成 raw 不初始化 SDK 或重新取名单。"""
    provider: Callable[[str], dict[str, Any]] | None = None

    def get_universe(day: str) -> dict[str, Any]:
        nonlocal provider
        if provider is None:
            provider = _risk_universe_provider(cfg, client, quota_reserve_fraction, risk_options)
        return provider(day)

    return get_universe


def _risk_universe_provider(
    cfg: Config, client: Any, quota_reserve_fraction: float, risk_options: Any
) -> Callable[[str], dict[str, Any]]:
    """动态名单只读冻结元数据；固定名单 raw 不依赖数据库。"""
    from gr_tools.config import load_environment

    from gr_data.common.ricequant_universe import (
        build_universe_provider,
        load_metadata_snapshot,
        reference_input_codes,
    )
    from gr_data.config import load_postgres
    from gr_data.db.sync import PgConfig, connect
    from gr_data.raw.ricequant.fetchers.supplements import _check_quota

    env = cfg.environment if cfg.environment is not None else load_environment()
    pg = load_postgres(env)
    with (
        connect(PgConfig(pg.host, pg.port, pg.database, pg.user, pg.password)) as conn,
        conn.transaction(),
    ):
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        snapshot = load_metadata_snapshot(conn)
    reference = client.risk_reference(
        reference_input_codes(snapshot),
        quota_guard=lambda: _check_quota(client, quota_reserve_fraction),
    )
    _check_quota(client, quota_reserve_fraction)
    return build_universe_provider(
        snapshot,
        reference,
        universe_policy=risk_options.universe_policy,
        mapping_version=risk_options.mapping_version,
    )
