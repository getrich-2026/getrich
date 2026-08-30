"""Canonical 表契约。

定义入库目标表的「规范列」，是 ingest transform 的输出标准，与 gr-db 的
`ddl/postgres/*.sql` 严格对齐。**若 DDL 变更，必须同步本包**。

按 schema 分模块（meta / market / …），本文件只做 re-export，因此
`from gr_data.common import contracts` 之后仍然是 `contracts.INSTRUMENTS`、
`contracts.bar_1d("stock")` 这样的扁平访问，调用方无需关心分在哪个模块。
"""

from __future__ import annotations

from gr_data.common.contracts.base import TableContract
from gr_data.common.contracts.factor import (
    COVARIANCE,
    DEFINITION,
    EXPOSURE,
    FACTOR_RETURN,
    MODEL,
    MODEL_RUN,
    SPECIFIC_RETURN,
    SPECIFIC_RISK,
)
from gr_data.common.contracts.fundamental import VALUATION_1D
from gr_data.common.contracts.market import (
    ADJ_FACTOR_TS,
    STOCK_DAILY_BASIC,
    VALID_ASSETS,
    bar_1d,
    bar_1m,
)
from gr_data.common.contracts.meta import INSTRUMENTS, SYMBOL_MAP, TRADING_CALENDAR


__all__ = [
    "ADJ_FACTOR_TS",
    "COVARIANCE",
    "DEFINITION",
    "EXPOSURE",
    "FACTOR_RETURN",
    "INSTRUMENTS",
    "MODEL",
    "MODEL_RUN",
    "SPECIFIC_RETURN",
    "SPECIFIC_RISK",
    "STOCK_DAILY_BASIC",
    "SYMBOL_MAP",
    "TRADING_CALENDAR",
    "VALID_ASSETS",
    "VALUATION_1D",
    "TableContract",
    "bar_1d",
    "bar_1m",
]
