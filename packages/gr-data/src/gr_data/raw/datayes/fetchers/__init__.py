"""DataYes raw fetcher 注册表。

每张表一个独立 fetcher：通联是**按表购买权限**的，未购买的表返回 403，
拆开之后能拉哪张算哪张，缺表只影响下游对应的指标，不会整批失败。
"""

from gr_data.raw.datayes.fetchers.riskmodel import (
    ExposureFetcher,
    FactorCovarianceFetcher,
    FactorReturnFetcher,
    SpecificReturnFetcher,
    SpecificRiskFetcher,
)


REGISTRY = {
    # 先拉最小的两张（每天几十行），能最快验证凭证与权限是否就绪
    "factor_ret_cne6_sw21": FactorReturnFetcher,
    "factor_cov_cne6_sw21": FactorCovarianceFetcher,
    "exposure_cne6_sw21": ExposureFetcher,
    "srisk_cne6_sw21": SpecificRiskFetcher,
    "specific_ret_cne6_sw21": SpecificReturnFetcher,
}

__all__ = ["REGISTRY"]
