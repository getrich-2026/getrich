"""模型口径风险：合成协方差、波动率、风险贡献、L3／L4、模型相关性与风格暴露。

口径来源：设计仓计算指标清单 §3～§6，PA-04、PA-07、PA-09、PA-10、PA-13。

* 合成协方差 ``Σ = B Σ_f Bᵀ + D``，``D`` 为特质方差（特异波动率的平方）对角阵；
  输入须已统一为同一预测期限的年化小数方差，单位与期限换算在取数层完成（DS13）。
* 波动率 ``σ_p = sqrt(wᵀ Σ w)``；风险贡献 ``RC_i = w_i (Σw)_i / σ_p``（Σ RC_i = σ_p），
  占比 ``RC_i / σ_p``，边际 ``MRC_i = (Σw)_i / σ_p``；L3 = 1 / Σ(占比²)。负贡献保留符号。
* L4：对完整因子集合做最小扭转正交化（Meucci、Santangelo、Deguest 2015），暴露同步转换
  ``ẽ = t⁻ᵀ e``，风险源为各正交因子与各股特质风险，L4 = 1 / Σ p_s²。L4 描述风险源之间
  的方差集中度，数值越大不代表越分散，须同时展示市场源占比与最大风险源占比。

数值容差（``*_TOL``）只用于判定矩阵能否计算，不是业务阈值；真实数据下的近奇异阈值
仍待用米筐数据复核（计算指标清单 §4「开放前仍须补的验证」）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from gr_api.diagnosis_calc.metrics import degraded, ok, unavailable
from numpy.typing import NDArray


METHOD = "forward"

#: 因子协方差相对对称误差上限；超过即视为输入错误而不是浮点误差。
SYMMETRY_TOL = 1e-8
#: 半正定判定：最小特征值不得低于 -PSD_TOL × 最大特征值。
PSD_TOL = 1e-10
#: 最小扭转要求因子相关矩阵可逆：最小特征值须大于 SINGULAR_TOL（相关矩阵特征值和为 K）。
SINGULAR_TOL = 1e-12
#: 最小扭转迭代：相邻两次变换的相对变化小于 TORSION_TOL 即收敛。
TORSION_TOL = 1e-12
TORSION_MAX_ITER = 10_000
#: 风险源方差合计与组合因子方差的相对误差上限，超出说明数值失败，拒绝出数。
CONSERVATION_TOL = 1e-8

Matrix = NDArray[np.float64]


class ModelInputError(ValueError):
    """风险模型输入不满足有限、对称、半正定或维度一致等检查。"""


@dataclass(frozen=True)
class RiskModelInputs:
    """同一米筐模型、日期、版本的风险截面（PA-04）。

    Attributes:
        factor_codes: 因子代码，顺序与 ``factor_covariance`` 行列及暴露向量一致。
        factor_covariance: 因子协方差，年化小数方差。
        exposures: instrument_id → 暴露向量（长度 K）；缺失的股票不在映射中。
        specific_variance: instrument_id → 特质方差（特异波动率的平方，年化小数）。
        market_factor: 市场联动因子代码（如 ``comovement``）；模型没有时为 None。
        style_factors: 已验证的风格因子代码，用于风格暴露（PA-07）。
    """

    factor_codes: tuple[str, ...]
    factor_covariance: Matrix
    exposures: Mapping[int, Matrix]
    specific_variance: Mapping[int, float]
    market_factor: str | None = None
    style_factors: frozenset[str] = field(default_factory=frozenset)


def validated_factor_covariance(model: RiskModelInputs) -> Matrix:
    """检查维度、有限、对称与半正定，返回对称化后的因子协方差。

    Raises:
        ModelInputError: 任一检查不通过。
    """
    cov = np.asarray(model.factor_covariance, dtype=float)
    k = len(model.factor_codes)
    if k == 0 or cov.shape != (k, k):
        raise ModelInputError("factor covariance shape does not match factor codes")
    if len(set(model.factor_codes)) != k:
        raise ModelInputError("factor codes must be unique")
    if not np.isfinite(cov).all():
        raise ModelInputError("factor covariance must be finite")
    scale = float(np.abs(cov).max()) or 1.0
    if float(np.abs(cov - cov.T).max()) > SYMMETRY_TOL * scale:
        raise ModelInputError("factor covariance must be symmetric")
    cov = (cov + cov.T) / 2
    eig = np.linalg.eigvalsh(cov)
    if float(eig.min()) < -PSD_TOL * max(float(eig.max()), 0.0):
        raise ModelInputError("factor covariance must be positive semidefinite")
    return cov


def _sym_sqrt(matrix: Matrix, *, inverse: bool = False) -> Matrix:
    """对称正定矩阵的平方根（或逆平方根），用特征分解实现。"""
    values, vectors = np.linalg.eigh(matrix)
    if float(values.min()) <= 0:
        raise ModelInputError("matrix is not positive definite")
    roots = np.sqrt(values)
    if inverse:
        roots = 1.0 / roots
    return (vectors * roots) @ vectors.T


def minimum_torsion(covariance: Matrix) -> Matrix:
    """最小扭转变换 ``t``：``f̃ = t f`` 两两不相关且与原因子偏离最小。

    在标准化空间求 ``A = diag(d) Q C^{-1/2}``（``Q`` 正交，保证 ``Var(Az)`` 为对角阵），
    最小化 ``Σ_k Var(y_k − z_k)``：固定 ``d`` 时 ``Q`` 为正交 Procrustes 解
    ``(DCD)^{-1/2} D C^{1/2}``，固定 ``Q`` 时 ``d = diag(Q C^{1/2})``，交替迭代目标单调不增。
    原空间 ``t = σ A σ^{-1}``。

    Raises:
        ModelInputError: 因子方差非正或相关矩阵近奇异，无法正交化（不截断、不正则化）。

    Complexity:
        每次迭代 O(K³)；K≈40 时数次迭代即收敛。
    """
    sigma = np.sqrt(np.diag(covariance))
    if not np.all(sigma > 0):
        raise ModelInputError("every factor must have positive variance")
    corr = covariance / np.outer(sigma, sigma)
    corr = (corr + corr.T) / 2
    if float(np.linalg.eigvalsh(corr).min()) <= SINGULAR_TOL:
        raise ModelInputError("factor correlation is singular; cannot orthogonalize")
    c_half = _sym_sqrt(corr)
    d = np.ones(len(sigma))
    previous: Matrix | None = None
    pi = np.diag(d)
    for _ in range(TORSION_MAX_ITER):
        dcd = (d[:, None] * corr) * d[None, :]
        q = _sym_sqrt(dcd, inverse=True) @ (d[:, None] * c_half)
        d = np.diag(q @ c_half).copy()
        pi = d[:, None] * q
        if previous is not None:
            change = float(np.linalg.norm(pi - previous)) / max(
                float(np.linalg.norm(previous)), 1e-300
            )
            if change <= TORSION_TOL:
                break
        previous = pi
    else:
        raise ModelInputError("minimum torsion did not converge")
    a = pi @ _sym_sqrt(corr, inverse=True)
    return (sigma[:, None] * a) / sigma[None, :]


@dataclass(frozen=True)
class RiskSources:
    """L4 的风险源方差：前 K 个为正交因子，其后为各计算持仓的特质风险。"""

    variances: Matrix
    labels: list[tuple[str, str | int]]  # ("factor", code) 或 ("idiosyncratic", instrument_id)


def risk_sources(
    weights: Matrix,
    exposures: Matrix,
    factor_cov: Matrix,
    specific_var: Matrix,
    factor_codes: Sequence[str],
    instrument_ids: Sequence[int],
) -> RiskSources:
    """组合因子暴露经最小扭转转换后拆成正交风险源，加上逐股特质风险源。

    暴露必须同时转换为 ``ẽ = t⁻ᵀ e``：只对角化协方差而沿用原暴露，方差合计会偏离组合方差。
    """
    e = exposures.T @ weights
    t = minimum_torsion(factor_cov)
    e_tilde = np.linalg.solve(t.T, e)
    var_tilde = np.diag(t @ factor_cov @ t.T)
    factor_part = e_tilde**2 * var_tilde
    total_factor = float(e @ factor_cov @ e)
    if abs(float(factor_part.sum()) - total_factor) > CONSERVATION_TOL * max(
        abs(total_factor), 1e-300
    ):
        raise ModelInputError("orthogonalized factor variance is not conserved")
    idio = weights**2 * specific_var
    labels: list[tuple[str, str | int]] = [("factor", code) for code in factor_codes]
    labels += [("idiosyncratic", iid) for iid in instrument_ids]
    return RiskSources(variances=np.concatenate([factor_part, idio]), labels=labels)


@dataclass(frozen=True)
class ModelRiskResult:
    """模块 B／D 模型口径指标（MetricValue 同形字典）与跨用户安全的数据事实。"""

    volatility: dict[str, Any]
    risk_contribution: dict[str, Any]
    risk_contribution_ratio: dict[str, Any]
    marginal_risk_contribution: dict[str, Any]
    l3_effective_count: dict[str, Any]
    l4_effective_count: dict[str, Any]
    l4_market_source_share: dict[str, Any]
    l4_largest_source: dict[str, Any]
    style_exposure: dict[str, Any]
    correlation: dict[str, Any]
    average_correlation: dict[str, Any]
    high_correlation_pairs: dict[str, Any]
    facts: dict[str, Any]


def _keyed(ids: Sequence[int], values: Matrix) -> dict[str, float]:
    return {str(iid): float(v) for iid, v in zip(ids, values, strict=True)}


def _all_unavailable(code: str, reason: str, facts: dict[str, Any]) -> ModelRiskResult:
    def na() -> dict[str, Any]:
        return unavailable(reason_code=code, reason=reason)

    return ModelRiskResult(
        na(), na(), na(), na(), na(), na(), na(), na(), na(), na(), na(), na(), facts
    )


def compute_model_risk(
    holdings: Sequence[tuple[int, float]],
    model: RiskModelInputs,
    *,
    high_threshold: float,
    include_risk_sources: bool = True,
) -> ModelRiskResult:
    """在已识别子集的计算权重上计算全部模型口径指标。

    Args:
        holdings: ``(instrument_id, 计算权重)``，权重合计为 1。
        model: 同一模型、日期、版本的风险截面。
        high_threshold: 模型相关性的高相关阈值（严格大于，一期 0.7）。
        include_risk_sources: 是否计算L4风险源；仅准入RC/L3时关闭。

    Returns:
        完整组合模型指标要求全部正权重持仓的暴露与特质方差都有效（PA-13）；否则这些指标
        不可用，模型相关性只在有数据的股票上计算并标降级。输入矩阵异常时全部不可用。
    """
    facts: dict[str, Any] = {"missing": [], "negative_contribution": False}
    try:
        factor_cov = validated_factor_covariance(model)
    except ModelInputError as exc:
        return _all_unavailable("data_not_validated", f"风险模型输入未通过检查：{exc}。", facts)
    k = len(model.factor_codes)

    def usable(iid: int) -> bool:
        x = model.exposures.get(iid)
        s = model.specific_variance.get(iid)
        return (
            x is not None
            and np.shape(x) == (k,)
            and bool(np.isfinite(x).all())
            and s is not None
            and math.isfinite(s)
            and s >= 0
        )

    ids = [iid for iid, w in holdings if w > 0]
    covered = [iid for iid in ids if usable(iid)]
    missing = [iid for iid in ids if iid not in set(covered)]
    facts["missing"] = missing
    weight_of = dict(holdings)
    covered_weight = sum(weight_of[i] for i in covered)
    facts["coverage"] = covered_weight

    correlation, average, pairs, excluded = _model_correlation(
        covered,
        model,
        factor_cov,
        missing=bool(missing),
        high_threshold=high_threshold,
        single_instrument=len(ids) == 1,
    )
    facts["correlation_excluded"] = excluded

    if missing:
        na_reason = f"{len(missing)} 只持仓缺少模型暴露或特质风险，完整组合模型指标不可用。"

        def full_na() -> dict[str, Any]:
            return unavailable(reason_code="coverage_below_threshold", reason=na_reason)

        return ModelRiskResult(
            full_na(),
            full_na(),
            full_na(),
            full_na(),
            full_na(),
            full_na(),
            full_na(),
            full_na(),
            full_na(),
            correlation,
            average,
            pairs,
            facts,
        )

    w = np.array([weight_of[i] for i in ids], dtype=float)
    b = np.array([model.exposures[i] for i in ids], dtype=float)
    spec = np.array([model.specific_variance[i] for i in ids], dtype=float)
    sigma_w = b @ (factor_cov @ (b.T @ w)) + spec * w
    variance = float(w @ sigma_w)
    if variance < 0 and abs(variance) > PSD_TOL * float(np.abs(sigma_w).sum()):
        return _all_unavailable("data_not_validated", "组合模型方差为负，模型输入异常。", facts)
    variance = max(variance, 0.0)
    vol = math.sqrt(variance)

    style = {
        code: float(value)
        for code, value in zip(model.factor_codes, b.T @ w, strict=True)
        if code in model.style_factors
    }
    style_metric = (
        ok(style, method=METHOD)
        if model.style_factors
        else unavailable(reason_code="data_not_validated", reason="所选模型的风格因子尚未核验。")
    )

    if vol == 0:
        zero = "组合模型波动为零，风险贡献、L3 与 L4 无法计算。"

        def zero_na() -> dict[str, Any]:
            return unavailable(reason_code="zero_variance", reason=zero)

        return ModelRiskResult(
            ok(0.0, method=METHOD),
            zero_na(),
            zero_na(),
            zero_na(),
            zero_na(),
            zero_na(),
            zero_na(),
            zero_na(),
            style_metric,
            correlation,
            average,
            pairs,
            facts,
        )

    mrc = sigma_w / vol
    rc = w * mrc
    ratio = rc / vol
    facts["negative_contribution"] = bool((rc < 0).any())
    l3 = 1.0 / float((ratio**2).sum())

    if not include_risk_sources:
        l4 = share = largest = unavailable(
            reason_code="data_not_validated", reason="风险源指标未准入。"
        )
    else:
        try:
            sources = risk_sources(w, b, factor_cov, spec, model.factor_codes, ids)
            total = float(sources.variances.sum())
            if abs(total - variance) > CONSERVATION_TOL * variance:
                raise ModelInputError("risk source variances do not sum to portfolio variance")
        except ModelInputError as exc:
            reason = f"无法完成最小扭转正交化（{exc}），L4 及配套指标不可用。"
            l4 = share = largest = unavailable(reason_code="data_not_validated", reason=reason)
        else:
            # 各源方差非负（正交因子方差 × 平方暴露、权重平方 × 特质方差），占比不会为负
            shares = sources.variances / total
            l4 = ok(1.0 / float((shares**2).sum()), method=METHOD)
            top = int(np.argmax(shares))
            kind, ident = sources.labels[top]
            largest = ok(
                {
                    "kind": kind,
                    "factor_code": ident if kind == "factor" else None,
                    "instrument_id": ident if kind == "idiosyncratic" else None,
                    "share": float(shares[top]),
                },
                method=METHOD,
            )
            if model.market_factor is not None and model.market_factor in model.factor_codes:
                share = ok(
                    float(shares[model.factor_codes.index(model.market_factor)]), method=METHOD
                )
            else:
                share = unavailable(
                    reason_code="data_not_validated",
                    reason="所选模型没有已核验的市场联动因子，市场源占比不可用。",
                )
    return ModelRiskResult(
        volatility=ok(vol, method=METHOD),
        risk_contribution=ok(_keyed(ids, rc), method=METHOD),
        risk_contribution_ratio=ok(_keyed(ids, ratio), method=METHOD),
        marginal_risk_contribution=ok(_keyed(ids, mrc), method=METHOD),
        l3_effective_count=ok(l3, method=METHOD),
        l4_effective_count=l4,
        l4_market_source_share=share,
        l4_largest_source=largest,
        style_exposure=style_metric,
        correlation=correlation,
        average_correlation=average,
        high_correlation_pairs=pairs,
        facts=facts,
    )


def _model_correlation(
    ids: list[int],
    model: RiskModelInputs,
    factor_cov: Matrix,
    *,
    missing: bool,
    high_threshold: float,
    single_instrument: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[int]]:
    """``ρ_ij = Σ_ij / (σ_i σ_j)``；只在有模型数据的股票上计算，缺失股票另行披露。"""
    if single_instrument:
        na = unavailable(reason_code="not_applicable", reason="单只股票不适用两两相关性。")
        return dict(na), dict(na), dict(na), []
    ordered = sorted(ids)
    if len(ordered) >= 2:
        b = np.array([model.exposures[i] for i in ordered], dtype=float)
        cov = b @ factor_cov @ b.T + np.diag([model.specific_variance[i] for i in ordered])
        var = np.diag(cov)
        keep = [n for n, v in enumerate(var) if v > 0]
    else:
        cov, keep = np.zeros((0, 0)), []
    excluded = [ordered[n] for n in range(len(ordered)) if n not in keep]
    if len(keep) < 2:
        na = unavailable(
            reason_code="coverage_below_threshold" if missing else "zero_variance",
            reason="具备模型数据且方差为正的股票不足两只，模型相关性不可用。",
        )
        return dict(na), dict(na), dict(na), excluded
    kept = [ordered[n] for n in keep]
    sub = cov[np.ix_(keep, keep)]
    sd = np.sqrt(np.diag(sub))
    corr = np.clip(sub / np.outer(sd, sd), -1.0, 1.0)
    corr = (corr + corr.T) / 2
    np.fill_diagonal(corr, 1.0)
    upper = [
        (kept[a], kept[b], float(corr[a, b]))
        for a in range(len(kept))
        for b in range(a + 1, len(kept))
    ]
    average = sum(c for _, _, c in upper) / len(upper)
    pairs = [
        {"left_instrument_id": left, "right_instrument_id": right, "correlation": c}
        for left, right, c in sorted(upper, key=lambda p: (-p[2], p[0], p[1]))
        if c > high_threshold
    ]
    matrix = {"instrument_ids": kept, "matrix": corr.tolist()}
    if missing or excluded:
        reason = "缺少模型数据或模型方差为零的股票未进入相关矩阵。"

        def make(value: Any) -> dict[str, Any]:
            return degraded(
                value, reason_code="coverage_below_threshold", reason=reason, method=METHOD
            )
    else:

        def make(value: Any) -> dict[str, Any]:
            return ok(value, method=METHOD)

    return make(matrix), make(average), make(pairs), excluded
