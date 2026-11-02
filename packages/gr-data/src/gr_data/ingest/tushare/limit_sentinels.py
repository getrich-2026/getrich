"""D-024 显式授权的精确哨兵对；不扩宽原有阈值或推断相近组合。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd


EXACT_NO_LIMIT_RULE = "tushare_stk_limit_exact_no_limit_sentinel"
EXACT_NO_LIMIT_PROCESSING_RULE = "exact_pair_10000_0001_no_limit"
EXACT_NO_LIMIT_EVIDENCE_URLS = (
    "https://static.cninfo.com.cn/finalpage/2020-08-11/1208149410.PDF",
    "https://static.cninfo.com.cn/finalpage/2020-08-17/1208182631.PDF",
)


def exact_no_limit_mask(up: pd.Series, down: pd.Series) -> np.ndarray:
    """仅数值精确等于 (10000.0, 0.001) 的有限双侧观察返回 True。

    数值转换只预筛候选，最终按源值的 Decimal 文本比较，不用浮点容差、
    量化或截断；即使预筛时近似文本被转成相同 float，也不会误判为哨兵。
    复杂度 O(n)，Decimal 仅处理候选，峰值 O(n) 布尔掩码。
    """
    result = np.zeros(len(up), dtype=bool)
    candidate = pd.to_numeric(up, errors="coerce").eq(10000.0) & pd.to_numeric(
        down, errors="coerce"
    ).eq(0.001)
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
            and lower == Decimal("0.001")
        )
    return result
