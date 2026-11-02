"""D-026：仅登记用户核实的 159908 转型前范围，不推断其他基金身份。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from gr_data.raw.tushare.asset_rules import source_dates


ETF_TRANSITION_CODE = "159908.SZ"
ETF_CURRENT_PRODUCT_START = date(2018, 12, 10)
ETF_TRANSITION_RULE = "tushare_etf_pre_transition_out_of_scope"
ETF_TRANSITION_NOTICE = "ETF pre-transition out of scope "
ETF_TRANSITION_EVIDENCE = (
    "https://paper.cnstock.com/html/2011-07/08/content_122133.htm",
    "https://static.cninfo.com.cn/finalpage/2025-09-30/1224688307.PDF",
)


def exclude_etf_pre_transition(
    frame: pd.DataFrame, dataset: str
) -> tuple[pd.DataFrame, dict[str, object] | None]:
    """排除 159908 新合同生效日前的源记录，返回副本与运行账本明细。

    只接受 fund_daily／fund_adj，日期为源交易日；2018-12-10 当天保留。
    不改 raw、list_date 或跟踪指数，其他代码仍由原上市日期门禁检查。
    """
    if dataset not in {"fund_daily", "fund_adj"}:
        raise ValueError("Unsupported ETF transition dataset")
    days = source_dates(frame["trade_date"])
    mask = frame["ts_code"].eq(ETF_TRANSITION_CODE) & days.lt(ETF_CURRENT_PRODUCT_START)
    if not mask.any():
        return frame, None
    excluded_days = days.loc[mask]
    detail: dict[str, object] = {
        "rule": ETF_TRANSITION_RULE,
        "reason": "基金转型前，不在范围内",
        "ts_code": ETF_TRANSITION_CODE,
        "dataset": dataset,
        "start_date": str(excluded_days.min()),
        "end_date": str(excluded_days.max()),
        "rows": int(mask.sum()),
        "current_product_start": str(ETF_CURRENT_PRODUCT_START),
        "evidence": list(ETF_TRANSITION_EVIDENCE),
    }
    return frame.loc[~mask].reset_index(drop=True), detail
