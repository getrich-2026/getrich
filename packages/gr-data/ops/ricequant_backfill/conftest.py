from __future__ import annotations

import pytest
import yaml


@pytest.fixture(autouse=True)
def synthetic_seed_templates(tmp_path_factory, monkeypatch, request):
    """使用自包含模板，不依赖曾经存在的 /tmp 真实运行目录。"""
    module = getattr(request.module, "m", None)
    if module is None or not hasattr(module, "SEED"):
        return
    seed = tmp_path_factory.mktemp("synthetic-seed")
    for model in ("v1", "v2", "v2trd"):
        risk = {
            "selected": True,
            "permission_confirmed": True,
            "model": model,
            "industry_mapping": "sws_2021",
            "start_date": "2024-01-02",
            "end_date": "2024-01-29",
            "universe_policy": "listed_cn_a_v2",
            "purpose": "production",
            "source_units": {
                "factor_return": "dec_daily",
                "specific_return": "dec_daily",
                "covariance": "dec2_annual",
                "specific_risk": "dec_annual",
            },
            "units_evidence": "synthetic-test-only",
        }
        data = {
            "providers": {"ricequant": {"license_env": "RICEQUANT_API_KEY", "risk_model": risk}}
        }
        (seed / f"{model}.yaml").write_text(yaml.safe_dump(data))
    monkeypatch.setattr(module, "SEED", seed)
