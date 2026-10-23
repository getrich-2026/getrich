from __future__ import annotations

from typing import Never, TypedDict, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

from gr_data.common.ricequant_specs import ContractViolationError


class RiskQualityError(ContractViolationError):
    """数值门禁拒收；quality_report 只含可用于 ETL 追溯的非敏感量化摘要。"""

    def __init__(self, message: str, quality_report: dict[str, object]) -> None:
        super().__init__(message)
        self.quality_report = quality_report


class Distribution(TypedDict):
    count: int
    minimum: float
    p05: float
    p25: float
    median: float
    p75: float
    p95: float
    maximum: float


def _reject(stage: str, violation: str, report: dict[str, object] | None = None) -> Never:
    raise RiskQualityError(
        f"RiceQuant risk quality rejected: {stage}/{violation}",
        {**(report or {}), "stage": stage, "violation": violation},
    )


def _array(value: ArrayLike, name: str, ndim: int) -> NDArray[np.float64]:
    try:
        if np.iscomplexobj(value):
            _reject(name, "complex_input")
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        _reject(name, "non_numeric_input")
    if result.ndim != ndim or not result.size or not np.isfinite(result).all():
        _reject(name, "invalid_shape_or_non_finite_input")
    return result


def _distribution(values: NDArray[np.float64]) -> Distribution:
    quantiles = np.quantile(values, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1])
    return Distribution(
        count=int(values.size),
        minimum=float(quantiles[0]),
        p05=float(quantiles[1]),
        p25=float(quantiles[2]),
        median=float(quantiles[3]),
        p75=float(quantiles[4]),
        p95=float(quantiles[5]),
        maximum=float(quantiles[6]),
    )


def _stored_covariance(covariance: NDArray[np.float64]) -> NDArray[np.float64]:
    """按 PG cov_flat 的上三角存储契约重建，不修改源值或添加正则项。"""
    return np.triu(covariance) + np.triu(covariance, k=1).T


def validate_covariance(covariance: ArrayLike) -> dict[str, object]:
    """执行 R2 严格正定门禁，检验实际持久化的上三角镜像矩阵。

    Args:
        covariance: 同一因子顺序下的非空方阵，源单位或归一化单位均可。

    Returns:
        可 JSON 序列化的特征值、2 范数条件数、相对非对称误差和告警。
        特征值保留输入单位。源矩阵仅检查非对称容差；正定性、特征值与
        条件数使用 PG 上三角镜像表示，不平均上下三角或正则化，也不改 raw。
        时间复杂度 O(k³)，内存 O(k²)。

    Raises:
        ContractViolationError: 非有限、不对称、非正定或条件数达到 1e8。
    """
    cov = _array(covariance, "covariance", 2)
    if cov.shape[0] != cov.shape[1]:
        _reject("covariance", "not_square")
    scale = float(np.max(np.abs(cov)))
    if scale == 0 or (np.diag(cov) <= 0).any():
        _reject("covariance", "non_positive_diagonal")
    # 先缩放再相减，避免极大有限值相减产生 Inf；不修改原矩阵。
    scaled = cov / scale
    asymmetry = float(np.max(np.abs(scaled - scaled.T)))
    report: dict[str, object] = {
        "relative_asymmetry": asymmetry,
        "covariance_representation": "upper_triangle_mirror",
        "warnings": [],
    }
    if asymmetry > 1e-8:
        _reject("covariance", "asymmetry", report)
    stored_cov = _stored_covariance(cov)
    try:
        np.linalg.cholesky(stored_cov)
        eigenvalues = np.linalg.eigvalsh(stored_cov)
        condition = float(np.linalg.cond(stored_cov, p=2))
    except np.linalg.LinAlgError:
        _reject("covariance", "not_positive_definite", report)
    if not np.isfinite(eigenvalues).all() or not np.isfinite(condition):
        _reject("covariance", "non_finite_spectrum", report)
    report.update(
        min_eigenvalue=float(eigenvalues[0]),
        max_eigenvalue=float(eigenvalues[-1]),
        condition_number=condition,
    )
    if eigenvalues[0] <= 0:
        _reject("covariance", "not_positive_definite", report)
    if condition >= 1e8:
        _reject("covariance", "condition_number_limit", report)
    if condition > 1e6:
        report["warnings"] = ["covariance_condition_number_above_1e6"]
    return report


def validate_daily_risk(
    exposure: ArrayLike,
    covariance: ArrayLike,
    specific_variance: ArrayLike,
    *,
    realized_volatility_pct: ArrayLike | None = None,
) -> dict[str, object]:
    """执行归一化后的 R1 每日量级与 R2 检查，不校准或填补数据。

    Args:
        exposure: n 股 × k 因子载荷，因子轴与协方差顺序一致。
        covariance: k × k 年化百分比平方协方差。
        specific_variance: n 股年化百分比平方特异方差，已由源标准差平方。
        realized_volatility_pct: 可选的同 n 股过去实现年化波动率（百分数）。
            调用方保证日期、股票轴及简单收益口径一致；比值仅告警，不用于校准。

    Returns:
        JSON 数值摘要、异常股票的零基位置和 warnings 字符串列表。
        总波动率 sqrt(xΣxᵀ + d) 的单位是百分数，无额外乘 252。
        Σ 使用 PG 实际存储的上三角镜像表示，与 R2 和下游读取口径一致。

    Raises:
        ContractViolationError: 缺失、维度错误、负特异方差、非正定协方差，
            或总年化波动率中位数不在 [5,150]，或超过 20% 股票不在 [1,300]。
    """
    x = _array(exposure, "exposure", 2)
    cov = _array(covariance, "covariance", 2)
    variance = _array(specific_variance, "specific_variance", 1)
    if cov.shape != (x.shape[1], x.shape[1]) or variance.shape != (x.shape[0],):
        _reject("daily_risk", "axis_mismatch")
    if (variance < 0).any():
        _reject("daily_risk", "negative_specific_variance")
    covariance_report = validate_covariance(cov)
    stored_cov = _stored_covariance(cov)
    try:
        with np.errstate(over="raise", invalid="raise"):
            total_variance = np.einsum("ij,ij->i", x @ stored_cov, x) + variance
            volatility = np.sqrt(total_variance)
    except FloatingPointError:
        _reject("daily_risk", "invalid_total_variance")
    if not np.isfinite(volatility).all():
        _reject("daily_risk", "non_finite_total_volatility")
    outside = np.flatnonzero((volatility < 1) | (volatility > 300))
    distribution = _distribution(volatility)
    warnings = list(cast(list[str], covariance_report["warnings"]))
    report: dict[str, object] = {
        "covariance": covariance_report,
        "total_volatility_pct": distribution,
        "outside_stock_count": int(outside.size),
        "outside_stock_fraction": float(outside.size / volatility.size),
        "outside_stock_indices": outside.tolist(),
        "warnings": warnings,
    }
    if not 5 <= distribution["median"] <= 150:
        _reject("daily_risk", "median_volatility_limit", report)
    if outside.size * 5 > volatility.size:
        _reject("daily_risk", "outside_stock_fraction_limit", report)
    if outside.size:
        warnings.append("stock_annual_volatility_outside_1_300_pct")
    if realized_volatility_pct is not None:
        realized = _array(realized_volatility_pct, "realized_volatility_pct", 1)
        if realized.shape != volatility.shape or (realized <= 0).any():
            _reject("daily_risk", "invalid_realized_volatility", report)
        with np.errstate(over="ignore", divide="ignore"):
            ratios = volatility / realized
        if not np.isfinite(ratios).all():
            _reject("daily_risk", "non_finite_prediction_ratio", report)
        ratio_outside = np.flatnonzero((ratios < 0.5) | (ratios > 2))
        report["prediction_realized_ratio"] = _distribution(ratios)
        report["prediction_ratio_outside_indices"] = ratio_outside.tolist()
        if ratio_outside.size:
            warnings.append("prediction_realized_volatility_ratio_outside_0_5_2")
    return report


def _check_unit_ratio(
    ratios: NDArray[np.float64], lower: float, upper: float, stage: str
) -> dict[str, object]:
    if not np.isfinite(ratios).all():
        _reject(stage, "non_finite_ratio")
    distribution = _distribution(ratios)
    outside = np.flatnonzero((ratios < lower) | (ratios > upper))
    report: dict[str, object] = {
        "distribution": distribution,
        "allowed_interval": [lower, upper],
        "outside_count": int(outside.size),
        "outside_fraction": float(outside.size / ratios.size),
        "outside_indices": outside.tolist(),
    }
    if not lower <= distribution["median"] <= upper:
        _reject(stage, "median_unit_ratio_limit", report)
    if outside.size * 5 > ratios.size:
        _reject(stage, "outside_unit_ratio_fraction_limit", report)
    return report


def validate_source_units(
    factor_returns: ArrayLike,
    specific_returns: ArrayLike,
    covariance: ArrayLike,
    specific_risk: ArrayLike,
) -> dict[str, object]:
    """用固定 120 交易日完整历史复核已声明的年化小数源单位。

    Args:
        factor_returns: 120 × k 因子的日频小数简单收益。
        specific_returns: 同 120 日 × n 只事先固定股票的日频小数特异收益。
        covariance: 窗口终点同 k 因子顺序的年化小数平方协方差。
        specific_risk: 窗口终点同 n 股顺序的年化小数特异标准差。
            调用方须验证两个历史矩阵的日期完整、唯一、升序且完全相同；
            本纯数值接口不接收日期，不以改样本或补值解决缺失。

    Returns:
        rf=diag(Σ)/var(f)、rs=σ/std(u) 的分布及区间外数量，ddof=1。
        该历史对照只检查单位，不证明预测准确或模型已校准。

    Raises:
        ContractViolationError: 非完整 120 行、缺失、零实现方差、轴不一致；
            rf 中位不在 [80,800]，rs 不在 [5,50]，或任一组区间外超过 20%。
    """
    factors = _array(factor_returns, "factor_returns", 2)
    specifics = _array(specific_returns, "specific_returns", 2)
    cov = _array(covariance, "covariance", 2)
    sigma = _array(specific_risk, "specific_risk", 1)
    if factors.shape[0] != 120 or specifics.shape[0] != 120:
        _reject("source_units", "requires_120_complete_trading_days")
    if cov.shape != (factors.shape[1], factors.shape[1]) or sigma.shape != (specifics.shape[1],):
        _reject("source_units", "axis_mismatch")
    if (sigma < 0).any():
        _reject("source_units", "negative_specific_risk")
    covariance_report = validate_covariance(cov)
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            factor_variance = factors.var(axis=0, ddof=1)
            specific_std = specifics.std(axis=0, ddof=1)
            if (factor_variance <= 0).any() or (specific_std <= 0).any():
                _reject("source_units", "zero_realized_variance")
            rf = np.diag(cov) / factor_variance
            rs = sigma / specific_std
    except FloatingPointError:
        _reject("source_units", "invalid_realized_variance")
    return {
        "history_days": 120,
        "ddof": 1,
        "factor_variance_ratio": _check_unit_ratio(rf, 80, 800, "factor_source_units"),
        "specific_sigma_ratio": _check_unit_ratio(rs, 5, 50, "specific_source_units"),
        "covariance": covariance_report,
        "warnings": covariance_report["warnings"],
    }
