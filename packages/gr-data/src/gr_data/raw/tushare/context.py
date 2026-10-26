"""Tushare 日线日期范围与采集范围；不读取凭证或修改运行环境。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gr_data.common.retry import int_to_date
from gr_data.config.pipeline import Config
from gr_data.raw.base import RawContext


FUTURE_EXCHANGES = ("CFFEX", "DCE", "CZCE", "SHFE", "INE", "GFEX")
# 官方 fut_trade_cal（doc_id=467）只列前五所；2026-10-24 live 用例实测 GFEX 2024 全年日历
# 逐日完整、日线只返回 .GFE 合约，故默认含 GFEX。白名单仍可显式收窄。
DEFAULT_FUTURE_EXCHANGES = FUTURE_EXCHANGES
OPTION_EXCHANGES = ("SSE", "SZSE", *FUTURE_EXCHANGES)
INDEX_MARKETS = ("SSE", "SZSE", "CSI", "SW", "MSCI", "CICC", "OTH")
# 申万走独立接口（doc_id=327），不进入 index_daily 采集范围。
INDEX_DAILY_MARKETS = tuple(m for m in INDEX_MARKETS if m != "SW")


@dataclass
class TushareRawContext(RawContext):
    """可选截止日与采集白名单。日期均为上海交易日 YYYYMMDD。

    指数白名单为空时 index_daily 拒绝运行：普通指数近万个，不能默认全量逐代码请求。
    """

    end_date: int | None = None
    index_codes: tuple[str, ...] = ()
    index_markets: tuple[str, ...] = ()
    future_exchanges: tuple[str, ...] = DEFAULT_FUTURE_EXCHANGES
    option_exchanges: tuple[str, ...] = OPTION_EXCHANGES


def _names(
    section: dict[str, Any], key: str, allowed: tuple[str, ...] | None = None
) -> tuple[str, ...] | None:
    """读取字符串列表配置；未配置返回 None，去首尾空白并按首次出现去重。"""
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError(f"providers.tushare.{key} must be a list of non-empty strings")
    names = tuple(dict.fromkeys(v.strip() for v in value))
    if allowed is not None:
        unsupported = sorted(set(names) - set(allowed))
        if unsupported:
            raise ValueError(f"providers.tushare.{key} unsupported values: {unsupported}")
    return names


def build_context(cfg: Config) -> TushareRawContext:
    """校验非凭证配置；截止日留空时采集到当天。"""
    from gr_data.common.paths import RawPaths

    section = cfg.section("providers", "tushare")
    start, end = section.get("start_date"), section.get("end_date")
    for key, value in (("start_date", start), ("end_date", end)):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"providers.tushare.{key} must be YYYYMMDD integer")
            int_to_date(value)
    if start is not None and end is not None and start > end:
        raise ValueError("providers.tushare.start_date must not exceed end_date")
    index_codes = _names(section, "index_codes") or ()
    sw_codes = [c for c in index_codes if c.endswith(".SI")]
    if sw_codes:
        raise ValueError(f"providers.tushare.index_codes SW needs a separate endpoint: {sw_codes}")
    future_exchanges = _names(section, "future_exchanges", FUTURE_EXCHANGES)
    if future_exchanges == ():
        raise ValueError("providers.tushare.future_exchanges must not be empty")
    option_exchanges = _names(section, "option_exchanges", OPTION_EXCHANGES)
    if option_exchanges == ():
        raise ValueError("providers.tushare.option_exchanges must not be empty")
    return TushareRawContext(
        paths=RawPaths(cfg.raw_root),
        rate_limit=section.get("rate_limit", {})
        if isinstance(section.get("rate_limit"), dict)
        else {},
        start_date=start,
        end_date=end,
        index_codes=index_codes,
        index_markets=_names(section, "index_markets", INDEX_DAILY_MARKETS) or (),
        future_exchanges=future_exchanges or DEFAULT_FUTURE_EXCHANGES,
        option_exchanges=option_exchanges or OPTION_EXCHANGES,
    )


def as_tushare_context(ctx: RawContext) -> TushareRawContext:
    """兼容直接注入通用 RawContext 的库调用与离线测试；白名单取默认值。"""
    if isinstance(ctx, TushareRawContext):
        return ctx
    return TushareRawContext(paths=ctx.paths, rate_limit=ctx.rate_limit, start_date=ctx.start_date)
