"""D-024 沪市精确哨兵对；不扩宽原阈值，也不推断其他市场或近似值。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd


EXACT_NO_LIMIT_RULE = "tushare_stk_limit_exact_no_limit_sentinel"
EXACT_NO_LIMIT_PROCESSING_RULE = "sh_exact_pair_10000_down_0001_or_001_no_limit"
LEGACY_EXACT_NO_LIMIT_PROCESSING_RULE = "exact_pair_10000_0001_no_limit"
EXACT_NO_LIMIT_EVIDENCE_BY_OBSERVATION = {
    ("600610.SH", "2020-08-17"): (
        "https://static.cninfo.com.cn/finalpage/2020-08-11/1208149410.PDF",
        "https://static.cninfo.com.cn/finalpage/2020-08-17/1208182631.PDF",
    ),
    ("600145.SH", "2022-03-30"): (
        "https://static.cninfo.com.cn/finalpage/2022-03-23/1212644112.PDF",
        "https://static.cninfo.com.cn/finalpage/2022-03-30/1212725521.PDF",
    ),
}


def exact_no_limit_mask(up: pd.Series, down: pd.Series, codes: pd.Series) -> np.ndarray:
    """仅沪市、上限精确 10000、下限精确 0.001 或 0.01 返回 True。

    数值转换只预筛候选，最终按源值的 Decimal 文本比较，不用浮点容差、
    量化或截断；即使预筛时近似文本被转成相同 float，也不会误判为哨兵。
    复杂度 O(n)，Decimal 仅处理候选，峰值 O(n) 布尔掩码。
    """
    result = np.zeros(len(up), dtype=bool)
    candidate = (
        codes.astype("string").str.fullmatch(r"[0-9]{6}\.SH", na=False)
        & pd.to_numeric(up, errors="coerce").eq(10000.0)
        & pd.to_numeric(down, errors="coerce").isin([0.001, 0.01])
    )
    for position in np.flatnonzero(candidate.fillna(False).to_numpy(dtype=bool)):
        try:
            upper = Decimal(str(up.iloc[position]))
            lower = Decimal(str(down.iloc[position]))
        except InvalidOperation:
            continue  # 坏文本留给原有数值门禁，不认作哨兵。
        result[position] = (
            upper.is_finite()
            and lower.is_finite()
            and upper == Decimal("10000.0")
            and lower in {Decimal("0.001"), Decimal("0.01")}
        )
    return result
