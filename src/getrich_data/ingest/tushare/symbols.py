"""Tushare 代码归一化。

Tushare ``ts_code`` 形如 ``600000.SH`` / ``000001.SZ`` / ``CU2401.SHF``。
canonical：symbol 保留完整原始代码串，exchange 由后缀映射。
见 docs/conventions/symbol-mapping.md。

注意 Tushare 的交易所后缀与通行简称并不一致（``SHF`` 而非 ``SHFE``、
``ZCE`` 而非 ``CZCE``、``CFX`` 而非 ``CFFEX``），必须显式映射，
不能靠字符串截断猜测。
"""

from __future__ import annotations

SUFFIX_TO_EXCHANGE = {
    # 股票 / ETF / 指数
    "SH": "XSHG",
    "SZ": "XSHE",
    "BJ": "BSE",
    # 指数发布机构（非交易所，但 Tushare 用同一后缀位表达）
    "CSI": "CSI",
    "SI": "SW",
    # 期货
    "CFX": "CFFEX",
    "SHF": "SHFE",
    "DCE": "DCE",
    "ZCE": "CZCE",
    "INE": "INE",
    "GFE": "GFEX",
}


def split_ts_code(code: str) -> tuple[str, str]:
    """``600000.SH`` → (symbol='600000.SH', exchange='XSHG')。

    symbol 维持完整带后缀代码（与 source_symbol 一致，避免跨市场重号）。
    未知后缀原样大写返回，不静默改写，便于在质量校验中暴露。
    """
    code = str(code).strip()
    if "." in code:
        _, suffix = code.rsplit(".", 1)
        exchange = SUFFIX_TO_EXCHANGE.get(suffix.upper(), suffix.upper())
    else:
        exchange = "UNKNOWN"
    return code, exchange
