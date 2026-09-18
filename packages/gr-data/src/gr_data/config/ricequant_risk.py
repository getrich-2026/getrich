"""米筐标准风险模型：显式范围、权限和源单位，不沿用通联的口径。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from gr_data.common.ricequant_specs import RqConfigurationError, semantic_hash


@dataclass(frozen=True)
class RiskOptions:
    """日度五件套采集参数；股票范围必须显式给出，不使用当前全市场回填历史。"""

    model: str
    industry_mapping: str
    start_date: date
    end_date: date
    order_book_ids: tuple[str, ...]
    source_units: dict[str, str]
    units_evidence: str
    batch_size: int = 200
    enable_bjse: bool = False

    @property
    def variant_id(self) -> str:
        return semantic_hash(self.identity)

    @property
    def identity(self) -> dict[str, object]:
        """落盘和入库共用的身份，不含可扩展的日期范围。"""
        return {
            "contract": "rq_risk_model_v1",
            "model": self.model,
            "industry_mapping": self.industry_mapping,
            "horizon": "daily",
            "order_book_ids": list(self.order_book_ids),
            "source_units": self.source_units,
            "units_evidence": self.units_evidence,
            "universe": "whole_market",
            "method": "implicit",
        }


def parse_risk_options(data: Any) -> RiskOptions:
    """拒绝缺失、猜测单位和未确认权限；真实值不从样例自动填充。"""
    keys = {
        "selected",
        "model",
        "industry_mapping",
        "start_date",
        "end_date",
        "order_book_ids",
        "source_units",
        "units_evidence",
        "permission_confirmed",
        "batch_size",
    }
    if not isinstance(data, dict) or set(data) - keys:
        raise RqConfigurationError("risk_model 配置字段错误")
    if data.get("selected") is not True or data.get("permission_confirmed") is not True:
        raise RqConfigurationError("risk_model 必须显式启用并确认模块权限")
    if data.get("model") not in {"v1", "v2", "v2trd"}:
        raise RqConfigurationError("risk_model 仅支持标准 v1/v2/v2trd")
    if data.get("industry_mapping") not in {"sws_2021", "citics_2019"}:
        raise RqConfigurationError("risk_model 必须指定 sws_2021 或 citics_2019")
    try:
        start, end = (date.fromisoformat(str(data.get(k))) for k in ("start_date", "end_date"))
    except ValueError:
        raise RqConfigurationError("risk_model 必须填写 ISO 起止日期") from None
    if start > end or end >= date.today():
        raise RqConfigurationError("risk_model 日期倒置或包含尚未结束的日期")
    codes = data.get("order_book_ids")
    if (
        not isinstance(codes, list)
        or not codes
        or len(codes) > 10000
        or any(
            not isinstance(c, str) or not re.fullmatch(r"[0-9]{6}\.(XSHG|XSHE)", c) for c in codes
        )
        or len(codes) != len(set(codes))
    ):
        raise RqConfigurationError("risk_model 需要不重复的沪深股票代码列表，最多 10000 个")
    allowed = {
        "factor_return": {"dec_daily", "pct_daily"},
        "specific_return": {"dec_daily", "pct_daily"},
        "covariance": {"dec2_daily", "pct2_daily", "dec2_annual", "pct2_annual"},
        "specific_risk": {"dec_daily", "pct_daily", "dec_annual", "pct_annual"},
    }
    units = data.get("source_units")
    if (
        not isinstance(units, dict)
        or set(units) != set(allowed)
        or any(not isinstance(units[k], str) or units[k] not in v for k, v in allowed.items())
    ):
        raise RqConfigurationError("risk_model 四项源单位必须显式声明；特异风险为标准差")
    evidence = data.get("units_evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise RqConfigurationError("risk_model 必须记录源单位的核对依据")
    batch = data.get("batch_size", 200)
    if type(batch) is not int or not 1 <= batch <= 1000:
        raise RqConfigurationError("risk_model batch_size 必须在 1–1000 内")
    return RiskOptions(
        data["model"],
        data["industry_mapping"],
        start,
        end,
        tuple(sorted(codes)),
        dict(units),
        evidence,
        batch,
    )
