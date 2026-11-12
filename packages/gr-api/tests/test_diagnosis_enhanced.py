"""v3风险指标准入与波动率贡献约定。"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import numpy as np
import pytest
from gr_api.diagnosis_calc.exposure import CalcHolding
from gr_api.diagnosis_calc.model_risk import RiskModelInputs
from gr_api.errors import BadRequest
from gr_api.services.diagnosis import LoadedRiskModel, _scoped_risk
from gr_api.services.diagnosis_scope import ENHANCED_METRICS, METRICS, scope


@pytest.mark.parametrize("zero", [False, True])
def test_scoped_enhanced_contributions_and_gating(zero, monkeypatch):
    from gr_api.diagnosis_calc import model_risk

    def forbidden(*args):
        raise AssertionError("L4 must not be calculated for RC admission")

    monkeypatch.setattr(model_risk, "minimum_torsion", forbidden)
    model = RiskModelInputs(
        ("factor",),
        np.array([[0 if zero else 0.04]]),
        {1: np.array([1.0]), 2: np.array([-0.8])},
        {1: 0 if zero else 0.01, 2: 0 if zero else 0.01},
    )
    loaded = LoadedRiskModel(
        model,
        "model",
        "v2",
        date(2026, 11, 5),
        {
            "metrics": sorted(ENHANCED_METRICS),
            "calibrated": False,
            "run_id": "run",
            "receipt_id": "receipt",
            "units_evidence": {},
        },
    )
    result = _scoped_risk([CalcHolding(1, Decimal(".6")), CalcHolding(2, Decimal(".4"))], loaded)
    if zero:
        assert result.risk_contribution["status"] == "unavailable"
        assert result.l3_effective_count["status"] == "unavailable"
    else:
        rc = result.risk_contribution["value"]
        ratio = result.risk_contribution_ratio["value"]
        mrc = result.marginal_risk_contribution["value"]
        assert math.isclose(
            sum(rc.values()),
            math.sqrt(result.facts["annual_variance"]),
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
        assert math.isclose(sum(ratio.values()), 1, rel_tol=1e-12)
        assert math.isclose(
            result.l3_effective_count["value"],
            1 / sum(r * r for r in ratio.values()),
            rel_tol=1e-12,
        )
        assert rc["2"] < 0 and result.facts["negative_contribution"]
        assert math.isclose(rc["1"], 0.6 * mrc["1"], rel_tol=1e-12)
    assert result.l4_effective_count["status"] == "unavailable"
    assert result.correlation["status"] == "unavailable"
    assert result.style_exposure["status"] == "unavailable"


@pytest.mark.parametrize(
    "contract,metrics,accepted",
    [
        ("diag-publication-v2-universe", METRICS, True),
        ("diag-publication-v3", ENHANCED_METRICS, True),
        ("diag-publication-v2-universe", ENHANCED_METRICS, False),
        ("diag-publication-v3", METRICS, False),
    ],
)
def test_protocol_specific_metric_contract(contract, metrics, accepted):
    version = {
        "contract_version": contract,
        "as_of_date": "2026-11-05",
        "available_options": {
            "publication_scope": {
                "scope_type": "security_universe",
                "as_of": "2026-11-05",
                "model": "v2",
                "run_id": "run",
                "metrics": list(metrics),
            }
        },
    }
    if accepted:
        assert set(scope(version)["metrics"]) == metrics
    else:
        with pytest.raises(BadRequest):
            scope(version)
