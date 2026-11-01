"""模型口径风险纯计算：对照计算指标清单 §4～§5 的手算与模拟案例，以及 PA-10／PA-13 规则。"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pytest
from gr_api.diagnosis_calc.coverage import apply_model_coverage
from gr_api.diagnosis_calc.history import correlation_view
from gr_api.diagnosis_calc.model_risk import (
    RiskModelInputs,
    compute_model_risk,
    minimum_torsion,
    risk_sources,
)
from gr_api.diagnosis_calc.sections import risk_section, structure_section
from gr_api.schemas.diagnosis_response import RiskSection, StructureSection
from gr_api.services import diagnosis_presentation as view


def _model(
    cov: list[list[float]] | np.ndarray,
    exposures: dict[int, list[float]],
    specific: dict[int, float],
    *,
    codes: tuple[str, ...] | None = None,
    market: str | None = "comovement",
    style: frozenset[str] = frozenset(),
) -> RiskModelInputs:
    cov = np.asarray(cov, dtype=float)
    codes = codes or ("comovement", *(f"f{k}" for k in range(1, len(cov))))
    return RiskModelInputs(
        factor_codes=codes,
        factor_covariance=cov,
        exposures={i: np.asarray(x, dtype=float) for i, x in exposures.items()},
        specific_variance=specific,
        market_factor=market,
        style_factors=style,
    )


def _random_model(seed: int, k: int = 12, n: int = 30) -> tuple[RiskModelInputs, list[int]]:
    rng = np.random.default_rng(seed)
    loadings = rng.normal(size=(k, k))
    cov = loadings @ loadings.T / k * 0.04 + np.eye(k) * 0.001
    ids = list(range(1, n + 1))
    model = _model(
        cov,
        {i: rng.normal(size=k).tolist() for i in ids},
        {i: float(rng.uniform(0.01, 0.2)) for i in ids},
    )
    return model, ids


def _equal(ids: list[int]) -> list[tuple[int, float]]:
    return [(i, 1 / len(ids)) for i in ids]


def _value(metric: dict) -> Any:
    assert metric["status"] in ("ok", "degraded"), metric
    return metric["value"]


# ---------------------------------------------------------------- 设计文档案例


def test_single_stock_market_and_idiosyncratic_sources() -> None:
    """单股（市场 0.3、特质 0.7）：L4 = 1 / (0.3² + 0.7²) = 1.724。"""
    r = compute_model_risk([(1, 1.0)], _model([[0.3]], {1: [1.0]}, {1: 0.7}), high_threshold=0.7)
    assert _value(r.l4_effective_count) == pytest.approx(1 / 0.58)
    assert _value(r.l4_market_source_share) == pytest.approx(0.3)
    assert r.l4_largest_source["value"] == {
        "kind": "idiosyncratic",
        "factor_code": None,
        "instrument_id": 1,
        "share": pytest.approx(0.7),
    }
    assert _value(r.volatility) == pytest.approx(1.0)
    assert _value(r.l3_effective_count) == pytest.approx(1.0)
    assert r.correlation["reason_code"] == "not_applicable"


@pytest.mark.parametrize(
    ("factor_var", "specific", "expected"),
    [(0.3, 0.0, 1.0), (0.0, 0.7, 1.0)],  # 单股无特质；单股纯特质（因子方差为 0 不贡献风险源）
)
def test_single_stock_with_one_source_has_l4_of_one(
    factor_var: float, specific: float, expected: float
) -> None:
    model = _model([[0.3]], {1: [1.0 if factor_var else 0.0]}, {1: specific})
    r = compute_model_risk([(1, 1.0)], model, high_threshold=0.7)
    assert _value(r.l4_effective_count) == pytest.approx(expected)


def test_ten_pure_idiosyncratic_equal_weight_stocks_give_ten_sources() -> None:
    ids = list(range(10))
    model = _model([[0.3]], {i: [0.0] for i in ids}, dict.fromkeys(ids, 0.5))
    r = compute_model_risk(_equal(ids), model, high_threshold=0.7)
    assert _value(r.l4_effective_count) == pytest.approx(10.0)
    assert _value(r.l3_effective_count) == pytest.approx(10.0)


def test_hundred_stocks_single_market_factor_matches_design_simulation() -> None:
    """计算指标清单 §4 模拟表：等权 L4≈1.05、L3=100；91% 集中于一只 L4≈1.82、L3≈1.1。"""
    ids = list(range(100))
    model = _model([[0.3]], {i: [1.0] for i in ids}, dict.fromkeys(ids, 0.7))
    r = compute_model_risk(_equal(ids), model, high_threshold=0.7)
    assert round(_value(r.l4_effective_count), 2) == 1.05
    assert _value(r.l3_effective_count) == pytest.approx(100.0)
    assert _value(r.average_correlation) == pytest.approx(0.3)  # 0.3 / (0.3 + 0.7)

    concentrated = [(0, 0.91)] + [(i, 0.09 / 99) for i in ids[1:]]
    r = compute_model_risk(concentrated, model, high_threshold=0.7)
    assert round(_value(r.l4_effective_count), 2) == 1.82
    assert round(_value(r.l3_effective_count), 1) == 1.1


def test_zero_portfolio_variance_keeps_volatility_and_blocks_ratios() -> None:
    model = _model([[0.3]], {1: [0.0]}, {1: 0.0})
    r = compute_model_risk([(1, 1.0)], model, high_threshold=0.7)
    assert _value(r.volatility) == 0.0
    for metric in (r.risk_contribution_ratio, r.l3_effective_count, r.l4_effective_count):
        assert metric["reason_code"] == "zero_variance"


# ---------------------------------------------------------------- 最小扭转


def test_minimum_torsion_is_identity_for_uncorrelated_factors() -> None:
    t = minimum_torsion(np.diag([0.04, 0.09, 0.01, 0.25]))
    assert np.abs(t - np.eye(4)).max() < 1e-12


def _objective(a: np.ndarray, corr: np.ndarray) -> float:
    diff = a - np.eye(len(corr))
    return float(np.trace(diff @ corr @ diff.T))


def _best_scaling(q_c_inv_half: np.ndarray, corr: np.ndarray) -> np.ndarray:
    """给定正交化方向，取最优对角缩放后的标准化变换（与最小扭转同一目标函数）。"""
    values, vectors = np.linalg.eigh(corr)
    c_half = (vectors * np.sqrt(values)) @ vectors.T
    q = q_c_inv_half @ c_half
    d = np.diag(q @ c_half)
    return d[:, None] * q_c_inv_half


@pytest.mark.parametrize("seed", range(10))
def test_minimum_torsion_decorrelates_and_beats_zca_and_pca(seed: int) -> None:
    rng = np.random.default_rng(seed)
    loadings = rng.normal(size=(6, 6))
    cov = loadings @ loadings.T + np.eye(6) * 0.1
    t = minimum_torsion(cov)
    transformed = t @ cov @ t.T
    off = transformed - np.diag(np.diag(transformed))
    assert np.abs(off).max() < 1e-10 * np.abs(transformed).max()

    sigma = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sigma, sigma)
    a = (t * sigma[None, :]) / sigma[:, None]  # 回到标准化空间
    values, vectors = np.linalg.eigh(corr)
    inv_half = (vectors / np.sqrt(values)) @ vectors.T
    zca = _best_scaling(inv_half, corr)
    pca = _best_scaling(vectors.T @ inv_half, corr)
    assert _objective(a, corr) <= _objective(zca, corr) + 1e-10
    assert _objective(a, corr) <= _objective(pca, corr) + 1e-10


@pytest.mark.parametrize("seed", range(20))
def test_risk_sources_conserve_variance_and_are_non_negative(seed: int) -> None:
    model, ids = _random_model(seed)
    w = np.full(len(ids), 1 / len(ids))
    b = np.array([model.exposures[i] for i in ids])
    spec = np.array([model.specific_variance[i] for i in ids])
    sources = risk_sources(w, b, model.factor_covariance, spec, model.factor_codes, ids)
    total = float(w @ (b @ model.factor_covariance @ b.T + np.diag(spec)) @ w)
    assert float(sources.variances.sum()) == pytest.approx(total, rel=1e-10)
    assert (sources.variances >= 0).all()


def test_exposures_must_be_transformed_not_just_covariance_diagonalized() -> None:
    cov = np.array([[0.04, 0.03], [0.03, 0.04]])
    model = _model(cov, {1: [1.0, 1.0]}, {1: 0.0})
    r = compute_model_risk([(1, 1.0)], model, high_threshold=0.7)
    naive = 1.0 * 0.04 + 1.0 * 0.04  # 忽略因子相关、沿用原暴露的错误做法
    true_var = _value(r.volatility) ** 2
    assert true_var == pytest.approx(0.14)
    assert naive != pytest.approx(true_var)


def test_l4_is_invariant_to_factor_order_and_units() -> None:
    model, ids = _random_model(42, k=8, n=20)
    base = _value(compute_model_risk(_equal(ids), model, high_threshold=0.7).l4_effective_count)

    perm = np.random.default_rng(7).permutation(8)
    permuted = RiskModelInputs(
        factor_codes=tuple(model.factor_codes[p] for p in perm),
        factor_covariance=model.factor_covariance[np.ix_(perm, perm)],
        exposures={i: x[perm] for i, x in model.exposures.items()},
        specific_variance=model.specific_variance,
        market_factor=model.market_factor,
    )
    scale = np.linspace(0.5, 4.0, 8)
    rescaled = RiskModelInputs(
        factor_codes=model.factor_codes,
        factor_covariance=model.factor_covariance * np.outer(scale, scale),
        exposures={i: x / scale for i, x in model.exposures.items()},
        specific_variance=model.specific_variance,
        market_factor=model.market_factor,
    )
    for other in (permuted, rescaled):
        l4 = _value(compute_model_risk(_equal(ids), other, high_threshold=0.7).l4_effective_count)
        assert l4 == pytest.approx(base, abs=1e-9)


def test_perfectly_correlated_factors_cannot_be_orthogonalized() -> None:
    cov = [[0.04, 0.0, 0.0], [0.0, 0.01, 0.01], [0.0, 0.01, 0.01]]  # 两个风格相关系数为 1
    model = _model(cov, {1: [1.0, 0.5, -0.5], 2: [1.0, 0.2, 0.3]}, {1: 0.05, 2: 0.05})
    r = compute_model_risk(_equal([1, 2]), model, high_threshold=0.7)
    assert r.l4_effective_count["reason_code"] == "data_not_validated"
    assert r.l4_largest_source["status"] == "unavailable"
    # 合成协方差仍半正定，波动率与风险贡献照常出数
    assert r.volatility["status"] == "ok"
    assert r.risk_contribution["status"] == "ok"


def test_nearly_correlated_factors_stay_stable() -> None:
    def l4(rho: float) -> float:
        cov = [[0.04, 0.0, 0.0], [0.0, 0.01, 0.01 * rho], [0.0, 0.01 * rho, 0.01]]
        model = _model(cov, {1: [1.0, 0.5, -0.5], 2: [1.0, 0.2, 0.3]}, {1: 0.05, 2: 0.05})
        return _value(
            compute_model_risk(_equal([1, 2]), model, high_threshold=0.7).l4_effective_count
        )

    assert abs(l4(0.999999) - l4(0.9999)) < 0.05


# ---------------------------------------------------------------- 风险贡献（PA-10）


def test_risk_contributions_sum_to_volatility_and_keep_negative_sign() -> None:
    cov = [[0.04]]
    model = _model(cov, {1: [1.0], 2: [-0.8], 3: [0.5]}, {1: 0.01, 2: 0.01, 3: 0.02})
    weights = [(1, 0.5), (2, 0.3), (3, 0.2)]
    r = compute_model_risk(weights, model, high_threshold=0.7)
    vol = _value(r.volatility)
    rc = _value(r.risk_contribution)
    ratio = _value(r.risk_contribution_ratio)
    assert sum(rc.values()) == pytest.approx(vol)
    assert sum(ratio.values()) == pytest.approx(1.0)
    assert rc["2"] < 0  # 对冲持仓的负贡献保留符号，不截零
    assert r.facts["negative_contribution"] is True
    assert _value(r.l3_effective_count) == pytest.approx(1 / sum(v * v for v in ratio.values()))

    sigma = np.array(
        [
            [0.04 * 1 + 0.01, -0.032, 0.02],
            [-0.032, 0.0256 + 0.01, -0.016],
            [0.02, -0.016, 0.01 + 0.02],
        ]
    )
    w = np.array([0.5, 0.3, 0.2])
    mrc = _value(r.marginal_risk_contribution)
    assert [mrc[k] for k in ("1", "2", "3")] == pytest.approx((sigma @ w) / vol)


def test_model_correlation_and_strict_high_pairs() -> None:
    model = _model([[0.09]], {1: [1.0], 2: [1.0], 3: [0.0]}, {1: 0.01, 2: 0.01, 3: 0.05})
    r = compute_model_risk(_equal([1, 2, 3]), model, high_threshold=0.7)
    matrix = r.correlation["value"]
    assert matrix["instrument_ids"] == [1, 2, 3]
    assert matrix["matrix"][0][1] == pytest.approx(0.9)
    assert matrix["matrix"][0][2] == pytest.approx(0.0)
    assert [p["right_instrument_id"] for p in r.high_correlation_pairs["value"]] == [2]
    strict = compute_model_risk(_equal([1, 2, 3]), model, high_threshold=0.9)
    assert strict.high_correlation_pairs["value"] == []


def test_style_exposure_only_reports_validated_style_factors() -> None:
    model = _model(
        np.diag([0.04, 0.01, 0.01]),
        {1: [1.0, 0.4, 1.0], 2: [1.0, -0.2, 0.0]},
        {1: 0.02, 2: 0.02},
        codes=("comovement", "size", "bank"),
        style=frozenset({"size"}),
    )
    r = compute_model_risk(_equal([1, 2]), model, high_threshold=0.7)
    assert r.style_exposure["value"] == pytest.approx({"size": 0.1})


def test_model_without_market_factor_leaves_market_share_unavailable() -> None:
    model = _model([[0.3]], {1: [1.0]}, {1: 0.7}, codes=("size",), market=None)
    r = compute_model_risk([(1, 1.0)], model, high_threshold=0.7)
    assert r.l4_market_source_share["reason_code"] == "data_not_validated"
    assert r.l4_effective_count["status"] == "ok"


# ---------------------------------------------------------------- 缺数与非法输入（PA-13）


def test_missing_holding_blocks_full_portfolio_metrics_but_not_correlation() -> None:
    model = _model([[0.09]], {1: [1.0], 2: [0.8]}, {1: 0.01, 2: 0.01})
    r = compute_model_risk([(1, 0.4), (2, 0.4), (3, 0.2)], model, high_threshold=0.7)
    for metric in (
        r.volatility,
        r.risk_contribution,
        r.l3_effective_count,
        r.l4_effective_count,
        r.style_exposure,
    ):
        assert metric["reason_code"] == "coverage_below_threshold"
    assert r.correlation["status"] == "degraded"
    assert r.correlation["value"]["instrument_ids"] == [1, 2]
    assert r.facts["missing"] == [3]
    assert r.facts["coverage"] == pytest.approx(0.8)


@pytest.mark.parametrize(
    "cov",
    [
        [[0.04, 0.01], [0.0, 0.04]],  # 不对称
        [[0.04, 0.05], [0.05, 0.04]],  # 非半正定
        [[0.04, float("nan")], [float("nan"), 0.04]],
    ],
)
def test_invalid_factor_covariance_rejects_every_model_metric(cov: list[list[float]]) -> None:
    model = _model(cov, {1: [1.0, 0.0]}, {1: 0.01})
    r = compute_model_risk([(1, 1.0)], model, high_threshold=0.7)
    assert r.volatility["reason_code"] == "data_not_validated"
    assert r.correlation["reason_code"] == "data_not_validated"


def test_non_finite_exposure_counts_as_missing() -> None:
    model = _model([[0.09]], {1: [1.0], 2: [float("inf")]}, {1: 0.01, 2: 0.01})
    r = compute_model_risk(_equal([1, 2]), model, high_threshold=0.7)
    assert r.facts["missing"] == [2]


# ---------------------------------------------------------------- 区块组装与展示


def _sections(weights: list[tuple[int, float]], model: RiskModelInputs) -> tuple[dict, dict]:
    result = compute_model_risk(weights, model, high_threshold=0.7)
    ids = [i for i, _ in weights]
    na = {"status": "unavailable", "reason_code": "history_insufficient", "reason": "x"}
    hist = correlation_view(
        {i: {} for i in ids},
        window=(date(2026, 1, 5), date(2026, 1, 5)),
        min_samples=120,
        high_threshold=0.7,
    )
    risk = risk_section(ids, dict.fromkeys(ids, na), result)
    structure = structure_section(hist, single_instrument=len(ids) == 1, model=result)
    return risk, structure


def test_sections_validate_and_mark_forward_as_primary() -> None:
    model, ids = _random_model(3, k=5, n=4)
    risk, structure = _sections(_equal(ids), model)
    RiskSection.model_validate(risk)
    StructureSection.model_validate(structure)
    assert risk["volatility"]["primary"] == "forward"
    assert structure["correlation"]["primary"] == "forward"


def test_unresolved_share_blocks_full_portfolio_metrics_at_assembly() -> None:
    model, ids = _random_model(4, k=5, n=4)
    risk, structure = _sections(_equal(ids), model)
    frozen = repr((risk, structure))
    facts = {"coverage": 1.0, "missing": []}
    blocked_risk, blocked_structure = apply_model_coverage(
        risk, structure, resolved_weight=0.9, model_facts=facts, params={}
    )
    assert repr((risk, structure)) == frozen  # 共享载体不被改写
    assert blocked_risk["volatility"]["by_method"]["forward"]["reason_code"] == (
        "coverage_below_threshold"
    )
    assert blocked_risk["volatility"]["primary"] is None
    assert blocked_risk["l4_effective_count"]["status"] == "unavailable"
    assert blocked_structure["style_exposure"]["status"] == "unavailable"
    # 模型相关：热力图照常；平均两两相关按一般阈值降级（0.90 < 0.95）
    assert blocked_structure["correlation"]["by_method"]["forward"]["status"] == "ok"
    assert blocked_structure["avg_pairwise_correlation"]["by_method"]["forward"]["status"] == (
        "degraded"
    )
    full_risk, _ = apply_model_coverage(
        risk, structure, resolved_weight=1.0, model_facts=facts, params={}
    )
    assert full_risk["l4_effective_count"]["status"] == "ok"


def test_report_shows_l4_with_companions_and_caveat() -> None:
    model = _model([[0.04]], {1: [1.0], 2: [-0.8]}, {1: 0.01, 2: 0.01})
    risk, structure = _sections([(1, 0.6), (2, 0.4)], model)
    names = {"1": "甲", "2": "乙"}
    blocks = view._risk_blocks(risk, names, "pro")
    cards = {c["metric_id"]: c for b in blocks if b["type"] == "metric_cards" for c in b["items"]}
    for key in (
        "volatility.forward",
        "l3_effective_count",
        "l4_effective_count",
        "l4_market_source_share",
        "l4_largest_source",
        "risk_contribution:2",
        "marginal_risk_contribution:1",
    ):
        assert key in cards
    texts = " ".join(b["text"] for b in blocks if b["type"] == "text")
    assert "数值越大不代表越分散" in texts
    assert "风险贡献为负" in texts
    retail = view._risk_blocks(risk, names, "retail")
    retail_ids = {c["metric_id"] for b in retail if b["type"] == "metric_cards" for c in b["items"]}
    assert "risk_contribution:2" not in retail_ids
    assert "risk_contribution_ratio:2" in retail_ids
    assert math.isfinite(cards["l4_effective_count"]["value"]["value"])
