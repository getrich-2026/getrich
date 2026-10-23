from __future__ import annotations

import json

import numpy as np
import pytest
from gr_data.common.ricequant_risk_quality import (
    RiskQualityError,
    validate_covariance,
    validate_daily_risk,
    validate_source_units,
)
from gr_data.common.ricequant_specs import ContractViolationError


def test_covariance_report_is_scale_invariant_and_does_not_modify_input():
    cov = np.array([[2.0, 0.5], [0.5, 1.0]])
    original = cov.copy()
    report = validate_covariance(cov)
    scaled = validate_covariance(cov * 1e4)
    assert report["condition_number"] == pytest.approx(np.linalg.cond(cov))
    assert scaled["condition_number"] == pytest.approx(report["condition_number"])
    assert scaled["min_eigenvalue"] == pytest.approx(report["min_eigenvalue"] * 1e4)
    assert report["relative_asymmetry"] == 0
    assert report["warnings"] == []
    np.testing.assert_array_equal(cov, original)
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize(
    "cov",
    [
        [],
        [1, 2],
        [[1, 0, 0], [0, 1, 0]],
        [[1, np.nan], [0, 1]],
        [[1, np.inf], [0, 1]],
        [[1, 1j], [-1j, 1]],
        [["not-numeric"]],
        [[0, 0], [0, 1]],
        [[-1, 0], [0, 1]],
        [[1, 1], [1, 1]],
        [[1, 2], [2, 1]],
        [[1, 0], [0, 1e-8]],
        [[1, 0], [0, 1e-10]],
        [[1, 0.1], [0, 1]],
    ],
)
def test_covariance_rejects_invalid_inputs_with_serializable_context(cov):
    with pytest.raises(ContractViolationError) as raised:
        validate_covariance(cov)
    assert isinstance(raised.value, RiskQualityError)
    json.dumps(raised.value.quality_report, allow_nan=False)


@pytest.mark.parametrize("condition,warn", [(1e6, False), (1e6 + 1, True), (9e7, True)])
def test_covariance_condition_warning_boundary(condition, warn):
    report = validate_covariance(np.diag([condition, 1]))
    assert bool(report["warnings"]) is warn


def test_covariance_relative_asymmetry_boundary_is_not_repaired():
    cov = np.array([[1.0, 1e-8], [0.0, 1.0]])
    original = cov.copy()
    assert validate_covariance(cov)["relative_asymmetry"] == 1e-8
    np.testing.assert_array_equal(cov, original)
    cov[0, 1] = np.nextafter(1e-8, np.inf)
    with pytest.raises(RiskQualityError, match="asymmetry"):
        validate_covariance(cov)


def test_covariance_rejects_indefinite_stored_upper_triangle_within_asymmetry_tolerance():
    cov = np.diag([1, *([3e-8] * 5)])
    rows, columns = np.triu_indices(5, k=1)
    cov[rows + 1, columns + 1] = -1e-8
    original = cov.copy()
    # 下三角 Cholesky 会误放行，但库内上三角镜像表示已有负特征值。
    np.linalg.cholesky(cov)
    assert np.linalg.cond(cov) < 1e8
    stored_cov = np.triu(cov) + np.triu(cov, k=1).T
    assert np.linalg.eigvalsh(stored_cov)[0] == pytest.approx(-1e-8)
    with pytest.raises(RiskQualityError, match="not_positive_definite") as raised:
        validate_covariance(cov)
    assert raised.value.quality_report["relative_asymmetry"] == 1e-8
    assert raised.value.quality_report["covariance_representation"] == "upper_triangle_mirror"
    np.testing.assert_array_equal(cov, original)


def test_daily_risk_and_spectrum_use_same_stored_upper_triangle_representation():
    cov = np.array([[100.0, 1e-6], [0.0, 100.0]])
    original = cov.copy()
    stored_cov = np.array([[100.0, 1e-6], [1e-6, 100.0]])
    report = validate_daily_risk([[1, 1]], cov, [200])
    expected_variance = 400 + 2e-6
    assert report["total_volatility_pct"]["median"] == pytest.approx(
        np.sqrt(expected_variance), rel=0, abs=1e-12
    )
    assert report["covariance"]["min_eigenvalue"] == pytest.approx(
        np.linalg.eigvalsh(stored_cov)[0], rel=0, abs=1e-12
    )
    assert report["covariance"]["condition_number"] == pytest.approx(
        np.linalg.cond(stored_cov), rel=0, abs=1e-12
    )
    np.testing.assert_array_equal(cov, original)


def _daily(volatility, **kwargs):
    vol = np.asarray(volatility, dtype=float)
    return validate_daily_risk(np.zeros((len(vol), 1)), np.eye(1), vol**2, **kwargs)


def test_daily_total_variance_formula_and_no_second_annualization():
    report = validate_daily_risk(
        np.array([[1, 2], [2, 1]]),
        np.array([[100, 20], [20, 25]]),
        np.array([120, 295]),
    )
    # xΣxᵀ+d = [400, 800] 年化 %²，不再次乘 252。
    summary = report["total_volatility_pct"]
    assert summary["minimum"] == pytest.approx(20)
    assert summary["maximum"] == pytest.approx(np.sqrt(800))
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("vol", [5, 150])
def test_daily_median_inclusive_boundary(vol):
    assert _daily([vol])["total_volatility_pct"]["median"] == vol


@pytest.mark.parametrize("vol", [4.99, 150.01])
def test_daily_median_rejects_unit_scale_mistakes(vol):
    with pytest.raises(RiskQualityError, match="median_volatility_limit"):
        _daily([vol] * 10)


def test_daily_exactly_twenty_percent_outside_warns_then_larger_fraction_rejects():
    report = _daily([0.5, 30, 30, 30, 30])
    assert report["outside_stock_fraction"] == 0.2
    assert report["outside_stock_indices"] == [0]
    assert report["warnings"] == ["stock_annual_volatility_outside_1_300_pct"]
    with pytest.raises(RiskQualityError, match="outside_stock_fraction_limit") as raised:
        _daily([0.5, 301, 30, 30, 30])
    assert raised.value.quality_report["outside_stock_count"] == 2


def test_individual_limits_are_inclusive():
    report = _daily([1, 300, 30, 30, 30])
    assert report["outside_stock_count"] == 0
    assert report["warnings"] == []


def test_prediction_deviation_warns_without_recalibrating():
    report = _daily([30] * 5, realized_volatility_pct=[15, 60, 10, 100, 30])
    assert report["prediction_ratio_outside_indices"] == [2, 3]
    assert "prediction_realized_volatility_ratio_outside_0_5_2" in report["warnings"]
    assert report["total_volatility_pct"]["median"] == 30


@pytest.mark.parametrize(
    "x,cov,specific",
    [
        ([[np.nan]], [[1]], [400]),
        ([[1]], [[1]], [-1]),
        ([[1]], [[1]], [np.inf]),
        ([[1, 1]], [[1]], [400]),
        ([[1]], [[1]], [400, 400]),
        ([[1e308]], [[1e308]], [400]),
    ],
)
def test_daily_rejects_incomplete_negative_or_overflowing_values(x, cov, specific):
    with pytest.raises(ContractViolationError):
        validate_daily_risk(x, cov, specific)


def _unit_inputs(factor_ratios=None, specific_ratios=None):
    rng = np.random.default_rng(20261022)
    factors = rng.normal(0, 0.01, size=(120, 5))
    specifics = rng.normal(0, 0.02, size=(120, 5))
    factor_ratios = np.asarray([252] * 5 if factor_ratios is None else factor_ratios)
    specific_ratios = np.asarray([np.sqrt(252)] * 5 if specific_ratios is None else specific_ratios)
    cov = np.diag(factors.var(axis=0, ddof=1) * factor_ratios)
    sigma = specifics.std(axis=0, ddof=1) * specific_ratios
    return factors, specifics, cov, sigma


def test_source_unit_check_uses_ddof_one_and_annual_units():
    report = validate_source_units(*_unit_inputs())
    assert report["history_days"] == 120
    assert report["ddof"] == 1
    assert report["factor_variance_ratio"]["distribution"]["median"] == pytest.approx(252)
    assert report["specific_sigma_ratio"]["distribution"]["median"] == pytest.approx(np.sqrt(252))
    assert report["factor_variance_ratio"]["outside_count"] == 0
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("piece,scale", [(2, 1 / 252), (2, 10000), (3, 1 / np.sqrt(252)), (3, 100)])
def test_source_unit_check_rejects_daily_or_percent_unit_mismatch(piece, scale):
    inputs = list(_unit_inputs())
    inputs[piece] *= scale
    with pytest.raises(RiskQualityError, match="median_unit_ratio_limit"):
        validate_source_units(*inputs)


def test_source_units_twenty_percent_boundary_and_larger_tail():
    report = validate_source_units(*_unit_inputs([1, 252, 252, 252, 252]))
    assert report["factor_variance_ratio"]["outside_fraction"] == 0.2
    with pytest.raises(RiskQualityError, match="outside_unit_ratio_fraction_limit"):
        validate_source_units(*_unit_inputs([1, 1, 252, 252, 252]))
    report = validate_source_units(*_unit_inputs(specific_ratios=[1, 15, 15, 15, 15]))
    assert report["specific_sigma_ratio"]["outside_fraction"] == 0.2
    with pytest.raises(RiskQualityError, match="outside_unit_ratio_fraction_limit"):
        validate_source_units(*_unit_inputs(specific_ratios=[1, 1, 15, 15, 15]))


@pytest.mark.parametrize("factor_ratio,specific_ratio", [(80, 5), (800, 50)])
def test_source_unit_ratio_inclusive_boundaries(factor_ratio, specific_ratio):
    report = validate_source_units(*_unit_inputs([factor_ratio] * 5, [specific_ratio] * 5))
    assert report["factor_variance_ratio"]["distribution"]["median"] == pytest.approx(factor_ratio)
    assert report["specific_sigma_ratio"]["distribution"]["median"] == pytest.approx(specific_ratio)


@pytest.mark.parametrize("fault", ["short", "long", "missing", "constant", "axis", "negative"])
def test_source_units_never_fill_or_silently_change_reference_sample(fault):
    factors, specifics, cov, sigma = _unit_inputs()
    if fault == "short":
        factors = factors[:-1]
    elif fault == "long":
        specifics = np.vstack([specifics, specifics[-1]])
    elif fault == "missing":
        specifics[12, 3] = np.nan
    elif fault == "constant":
        specifics[:, 3] = 0
    elif fault == "axis":
        sigma = sigma[:-1]
    elif fault == "negative":
        sigma[0] *= -1
    with pytest.raises(ContractViolationError):
        validate_source_units(factors, specifics, cov, sigma)
