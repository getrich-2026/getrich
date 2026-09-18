"""米筐补充数据的显式白名单；本模块不访问 SDK、环境或数据库。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


class RqConfigurationError(RuntimeError):
    """补充任务未通过配置、准入或实现状态检查。"""


class ContractViolationError(RuntimeError):
    """响应不满足已选定的数据契约，不得标为完成。"""


class RawIntegrityError(RuntimeError):
    """观察文件或 manifest 不完整、冲突或越界。"""


class BudgetDeferredError(RuntimeError):
    """额度不足，本次运行需保留已完成分片并等待恢复。"""


class RangeTooLargeError(ContractViolationError):
    """响应超出本地分片预算，需要缩小日期或代码范围。"""


def semantic_hash(value: object) -> str:
    """对显式、无凭证的 JSON 元数据计算稳定 SHA-256。"""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    api: str
    shape: str
    raw_keys: tuple[str, ...]


INDEX_SPECS = {
    "rq_index_daily": DatasetSpec(
        "rq_index_daily", "get_price", "frame", ("order_book_id", "date")
    ),
    "rq_index_components": DatasetSpec(
        "rq_index_components", "index_components", "tuple", ("member_source_symbol",)
    ),
    "rq_index_weights": DatasetSpec(
        "rq_index_weights", "index_weights", "series", ("member_source_symbol",)
    ),
}
CONDITIONAL_DATASETS = (
    "option_greeks_1d",
    "option_indicators_1d",
    "future_dividend_points",
    "margin_haircut",
    "equity_incentive",
    "risk_descriptor_exposure",
    "risk_stock_beta",
)
GROUPS = {
    "rq_indices": tuple(INDEX_SPECS),
    "rq_derivatives": CONDITIONAL_DATASETS[:3],
    "rq_risk_descriptors": CONDITIONAL_DATASETS[-2:],
    "rq_supplements": (*INDEX_SPECS, *CONDITIONAL_DATASETS),
}
DAILY_FIELDS = ("open", "high", "low", "close", "prev_close", "volume", "total_turnover")

# 2026-09-10 本地官方快照的首期定义；这是文档版本，不是供应商正式模型版本。
INDEX_SOURCE = "https://www.ricequant.com/doc/rqdata/python/ricequant-index"
DEFINITION_VERSION = "doc-2026-09-10"
INDEX_DEFINITIONS = {
    "866001.RI": ("米筐小市值概念全收益指数", "total_return"),
    "866002.RI": ("米筐小市值概念指数", "price"),
    "866006.RI": ("米筐微盘股指数", "price"),
    "866007.RI": ("米筐微盘股全收益指数", "total_return"),
    "866011.RI": ("米筐全A指数", "total_return"),
    "866014.RI": ("米筐全A等权指数", "total_return"),
    "866015.RI": ("米筐全A等权指数(不含北交所及ST股)", "total_return"),
    "866017.RI": ("米筐A500全收益指数", "total_return"),
    "VX0001.RI": ("米筐沪深300波动率指数", "volatility"),
    "VX0002.RI": ("米筐中证1000波动率指数", "volatility"),
    "VX0003.RI": ("米筐上证50波动率指数", "volatility"),
}
