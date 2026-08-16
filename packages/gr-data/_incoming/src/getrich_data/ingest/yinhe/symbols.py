"""银河代码归一化。

银河代码形如 ``600000.SH`` / ``000001.SZ`` / ``510300.SH``。
canonical：symbol 保留原始代码串，exchange 由后缀映射（SH→XSHG, SZ→XSHE）。
见 docs/conventions/symbol-mapping.md。
"""

from __future__ import annotations

SUFFIX_TO_EXCHANGE = {"SH": "XSHG", "SZ": "XSHE"}


def split_code(code: str) -> tuple[str, str]:
    """``600000.SH`` → (symbol='600000.SH', exchange='XSHG')。

    symbol 维持完整带后缀代码（与 source_symbol 一致，避免跨市场重号）。
    """
    code = str(code).strip()
    if "." in code:
        _, suffix = code.rsplit(".", 1)
        exchange = SUFFIX_TO_EXCHANGE.get(suffix.upper(), suffix.upper())
    else:
        exchange = "UNKNOWN"
    return code, exchange
