"""DataYes ingest importer 注册表。"""

from gr_data.ingest.datayes.importers.riskmodel import (
    CovarianceImporter,
    DatayesSymbolMapImporter,
    ExposureImporter,
    FactorReturnImporter,
    ModelRunImporter,
    SpecificReturnImporter,
    SpecificRiskImporter,
)


REGISTRY = {
    "symbol_map": DatayesSymbolMapImporter,
    "model_run": ModelRunImporter,
    "exposure": ExposureImporter,
    "factor_return": FactorReturnImporter,
    "covariance": CovarianceImporter,
    "specific_risk": SpecificRiskImporter,
    "specific_return": SpecificReturnImporter,
}

# 依赖有严格先后：symbol_map 建立 secID → instrument_id 的映射，
# model_run 钉住因子集合与顺序，其余五张表都要靠它俩。
GROUPS = {
    "meta": ["symbol_map", "model_run"],
    "wide": ["exposure", "factor_return", "covariance"],
    "cross": ["specific_risk", "specific_return"],
    "all": [
        "symbol_map",
        "model_run",
        "exposure",
        "factor_return",
        "covariance",
        "specific_risk",
        "specific_return",
    ],
}

__all__ = ["REGISTRY", "GROUPS"]
