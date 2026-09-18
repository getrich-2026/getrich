"""SDK 日度风险五件套的严格轴、数值与联合契约。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from gr_data.common.ricequant_specs import ContractViolationError
from gr_data.config.ricequant_risk import RiskOptions


STYLE_FACTORS = {
    "v1": frozenset(
        [
            "residual_volatility",
            "growth",
            "liquidity",
            "beta",
            "non_linear_size",
            "leverage",
            "earnings_yield",
            "size",
            "momentum",
            "book_to_price",
        ]
    ),
    "v2": frozenset(
        [
            "liquidity",
            "leverage",
            "earnings_variability",
            "earnings_quality",
            "profitability",
            "investment_quality",
            "book_to_price",
            "earnings_yield",
            "longterm_reversal",
            "growth",
            "momentum",
            "mid_cap",
            "size",
            "beta",
            "residual_volatility",
            "dividend_yield",
        ]
    ),
}
STYLE_FACTORS["v2trd"] = STYLE_FACTORS["v2"] | {
    "sentiment",
    "seasonality",
    "shortterm_reversal",
    "industry_momentum",
}
PIECES = ("exposure", "factor_return", "covariance", "specific_return", "specific_risk")


def _frame(frame: object) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ContractViolationError("米筐风险响应为空或不是 DataFrame")
    if not frame.index.is_unique or not frame.columns.is_unique:
        raise ContractViolationError("米筐风险响应含重复轴标签")
    if any(not isinstance(c, str) or not c or len(c) > 32 for c in frame.columns):
        raise ContractViolationError("米筐风险列标签非法")
    try:
        values = frame.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError):
        raise ContractViolationError("米筐风险响应包含非数值") from None
    if not np.isfinite(values).all():
        raise ContractViolationError("米筐风险响应有缺失或非有限值，整日拒绝完成")
    return frame.astype(float)


def _dated(frame: pd.DataFrame, day: date) -> pd.DataFrame:
    try:
        dates = pd.to_datetime(frame.index).date
    except (TypeError, ValueError):
        raise ContractViolationError("风险响应日期轴非法") from None
    if len(dates) != 1 or dates[0] != day:
        raise ContractViolationError("风险响应日期不等于请求日")
    frame = frame.copy()
    frame.index = pd.Index([day], name="date")
    return frame


def decode_piece(name: str, response: object, day: date, codes: tuple[str, ...]) -> pd.DataFrame:
    """只归一轴结构，值保持供应商原单位；不补缺失股票或因子。"""
    frame = _frame(response)
    if name == "exposure":
        if (
            not isinstance(frame.index, pd.MultiIndex)
            or set(frame.index.names) != {"date", "order_book_id"}
            or frame.index.nlevels != 2
        ):
            raise ContractViolationError("exposure 必须有 date/order_book_id 两级索引")
        if not (pd.to_datetime(frame.index.get_level_values("date")).date == day).all():
            raise ContractViolationError("exposure 返回了请求日以外的数据")
        frame.index = frame.index.get_level_values("order_book_id")
        if not frame.index.is_unique or set(frame.index) != set(codes):
            raise ContractViolationError("exposure 股票范围缺失或越界")
        return frame.loc[list(codes)]
    if name == "covariance":
        if set(frame.index) != set(frame.columns):
            raise ContractViolationError("covariance 行列因子不一致")
        return frame
    frame = _dated(frame, day)
    if name in {"specific_return", "specific_risk"}:
        if set(frame.columns) != set(codes):
            raise ContractViolationError("特异风险或收益率的股票范围不完整")
        frame = frame.loc[:, list(codes)]
    return frame


def validate_bundle(
    frames: dict[str, pd.DataFrame], options: RiskOptions, day: date
) -> dict[str, pd.DataFrame]:
    """对齐到稳定因子顺序，核对完整性、非负 σ 与半正定协方差。"""
    if set(frames) != set(PIECES):
        raise ContractViolationError("风险五件套不完整")
    out = {k: _frame(v) for k, v in frames.items()}
    factors = sorted(out["exposure"].columns)
    expected = STYLE_FACTORS[options.model] | {"comovement"}
    if not expected < set(factors):
        raise ContractViolationError("风险模型缺少风格、行业或市场因子")
    if any(not all("\u4e00" <= ch <= "\u9fff" for ch in f) for f in set(factors) - expected):
        raise ContractViolationError("风险模型出现未知因子类型，请先核对供应商契约")
    codes = list(options.order_book_ids)
    if set(out["exposure"].index) != set(codes):
        raise ContractViolationError("风险暴露股票范围不完整")
    out["exposure"] = out["exposure"].loc[codes, factors]
    industry = out["exposure"].loc[:, sorted(set(factors) - expected)].to_numpy()
    if (
        not (out["exposure"]["comovement"] == 1).all()
        or not np.isin(industry, [0.0, 1.0]).all()
        or not (industry.sum(axis=1) == 1).all()
    ):
        raise ContractViolationError("风险暴露必须有单位市场载荷和唯一的 0/1 行业归属")
    for key in ("factor_return", "covariance"):
        if set(out[key].columns) != set(factors):
            raise ContractViolationError("风险五件套的因子集合不一致")
        out[key] = out[key].loc[:, factors]
    if set(out["covariance"].index) != set(factors):
        raise ContractViolationError("协方差行因子集合不一致")
    out["covariance"] = out["covariance"].loc[factors]
    for key in ("factor_return", "specific_return", "specific_risk"):
        out[key] = _dated(out[key], day)
        if key != "factor_return":
            if set(out[key].columns) != set(codes):
                raise ContractViolationError("风险五件套股票集合不一致")
            out[key] = out[key].loc[:, codes]
    cov = out["covariance"].to_numpy()
    tolerance = max(float(np.max(np.abs(cov))), 1e-15) * 1e-8
    if (
        not np.allclose(cov, cov.T, rtol=1e-8, atol=tolerance)
        or np.diag(cov).min() < 0
        or np.linalg.eigvalsh(cov).min() < -tolerance
    ):
        raise ContractViolationError("风险协方差不对称、负对角或非半正定")
    if (out["specific_risk"].to_numpy() < 0).any():
        raise ContractViolationError("特异波动率不得为负")
    return out
