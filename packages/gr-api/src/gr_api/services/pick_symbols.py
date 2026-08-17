"""选股池的代码解析与交易所码映射。

**两套交易所码，别混用：**

* ``pick.item.exchange`` 用 ``SSE`` / ``SZSE`` / ``BSE`` —— 前端接口契约
  （``选股展示模块.openapi.json`` 的 ``PickItem.exchange`` 枚举）定死的取值。
* 数据层 ``meta.*`` 用 canonical 码 ``XSHG`` / ``XSHE`` / ``XBSE``
  （见 ``gr_data.ingest.tushare.symbols``）。

查 ``meta.instruments`` / ``meta.trading_calendar`` 时必须先经
:func:`to_canonical_exchange` 转换，否则永远查不到、``instrument_id``
会整批为 NULL 且不报错。

P0 只解析股票：强制 ``600000.SH`` 这一种写法，归一化退化成「按 ``.`` 切一刀」。
期货 / 期权的解析规则（品种大小写不得归一、郑商所 3 位年月跨十年歧义、
上交所期权 8 位数字代码需回查合约表）推迟到真正接入时再写。
"""

from __future__ import annotations

import re
from typing import NamedTuple


#: CSV 里 ``symbol`` 唯一合法的写法。不匹配一律报错，不做任何推断。
SYMBOL_PATTERN = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

#: 代码后缀 → 接口契约里的交易所码。
SUFFIX_TO_EXCHANGE = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}

#: 接口契约交易所码 → 代码后缀（反向生成 ``symbol_full``）。
EXCHANGE_TO_SUFFIX = {v: k for k, v in SUFFIX_TO_EXCHANGE.items()}

#: 接口契约交易所码 → 数据层 canonical 码（查 ``meta.*`` 时用）。
EXCHANGE_TO_CANONICAL = {"SSE": "XSHG", "SZSE": "XSHE", "BSE": "XBSE"}

#: canonical 码 → 接口契约交易所码（把 ``meta.*`` 的查询结果映射回来）。
CANONICAL_TO_EXCHANGE = {v: k for k, v in EXCHANGE_TO_CANONICAL.items()}

#: 交易日计数统一用上交所日历 —— 沪深北三所交易日一致，且
#: ``meta.trading_calendar`` 目前只 ingest 了 XSHG / XSHE 两个交易所。
CALENDAR_EXCHANGE = "XSHG"


class ParsedSymbol(NamedTuple):
    """``600000.SH`` 解析结果。"""

    symbol: str  # 不含后缀的 6 位代码
    exchange: str  # SSE / SZSE / BSE
    symbol_full: str  # 带后缀全码，与导入 CSV 口径一致
    asset_class: str  # P0 恒为 'stock'
    product_code: str  # 股票无换月概念，等于 symbol


def parse_symbol(raw: str) -> ParsedSymbol:
    """把 ``600000.SH`` 拆成入库需要的几个字段。

    Args:
        raw: CSV 里的原始代码，必须带交易所后缀。

    Returns:
        :class:`ParsedSymbol`。

    Raises:
        ValueError: 不匹配 ``^\\d{6}\\.(SH|SZ|BJ)$``。调用方负责把它翻译成
            带行号的预检错误。
    """
    code = (raw or "").strip().upper()
    if not SYMBOL_PATTERN.match(code):
        raise ValueError(f"invalid symbol: {raw!r}, expected 6 digits + .SH/.SZ/.BJ")

    symbol, suffix = code.split(".", 1)
    return ParsedSymbol(
        symbol=symbol,
        exchange=SUFFIX_TO_EXCHANGE[suffix],
        symbol_full=code,
        # P0 一律标 stock：ETF（如 510050.SH）也会标成 stock，这不影响 P0 的
        # 任何展示逻辑；真正的资产类别判定留到接入期货期权时统一做，届时靠
        # instrument_id 关联 meta.instruments.asset 一次性回刷即可。
        asset_class="stock",
        product_code=symbol,
    )


def to_symbol_full(symbol: str, exchange: str) -> str:
    """``('600000', 'SSE')`` → ``'600000.SH'``。

    交易所码不认识时原样返回 ``symbol`` —— 展示字段不该因为将来新增
    交易所就抛异常。
    """
    suffix = EXCHANGE_TO_SUFFIX.get(exchange)
    return f"{symbol}.{suffix}" if suffix else symbol


def to_canonical_exchange(exchange: str) -> str:
    """接口契约交易所码 → 数据层 canonical 码；未知值原样返回。"""
    return EXCHANGE_TO_CANONICAL.get(exchange, exchange)


__all__ = [
    "CALENDAR_EXCHANGE",
    "CANONICAL_TO_EXCHANGE",
    "EXCHANGE_TO_CANONICAL",
    "EXCHANGE_TO_SUFFIX",
    "SUFFIX_TO_EXCHANGE",
    "SYMBOL_PATTERN",
    "ParsedSymbol",
    "parse_symbol",
    "to_canonical_exchange",
    "to_symbol_full",
]
