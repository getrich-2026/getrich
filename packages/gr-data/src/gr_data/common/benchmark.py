"""DS08 版本身份；写入与读取以同一份规范化收益内容核对快照。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date


def benchmark_version(symbol: str, simple_returns: Mapping[date, float]) -> str:
    """对完整标的代码、升序交易日和精确浮点日简单收益计算快照版本。"""
    digest = hashlib.sha256(symbol.encode())
    for day, value in sorted(simple_returns.items()):
        digest.update(f"{day}:{value.hex()}\n".encode())
    return f"tushare-tr-{digest.hexdigest()}"
