"""Tushare 代码归一化。

Tushare ``ts_code`` 形如 ``600000.SH`` / ``000001.SZ`` / ``CU2401.SHF``。
canonical：symbol 保留完整原始代码串，exchange 由后缀映射。
见 docs/conventions/symbol-mapping.md。

注意 Tushare 的交易所后缀与通行简称并不一致（``SHF`` 而非 ``SHFE``、
``ZCE`` 而非 ``CZCE``、``CFX`` 而非 ``CFFEX``），必须显式映射，
不能靠字符串截断猜测。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

import pandas as pd


SUFFIX_TO_EXCHANGE = {
    # 股票 / ETF / 指数
    "SH": "XSHG",
    "SZ": "XSHE",
    "BJ": "XBSE",
    # 指数发布机构（非交易所，但 Tushare 用同一后缀位表达）
    "CSI": "CSI",
    "SI": "SW",
    # 期货
    "CFX": "CFFEX",
    "SHF": "SHFE",
    "DCE": "DCE",
    "ZCE": "CZCE",
    "INE": "INE",
    "GFE": "GFEX",
}


def split_ts_code(code: str) -> tuple[str, str]:
    """``600000.SH`` → (symbol='600000.SH', exchange='XSHG')。

    symbol 维持完整带后缀代码（与 source_symbol 一致，避免跨市场重号）。
    未知后缀原样大写返回，不静默改写，便于在质量校验中暴露。
    """
    code = str(code).strip()
    if "." in code:
        _, suffix = code.rsplit(".", 1)
        exchange = SUFFIX_TO_EXCHANGE.get(suffix.upper(), suffix.upper())
    else:
        exchange = "UNKNOWN"
    return code, exchange


# 公司实施公告：2025-02-17 起换码，法人及上市主体延续。
# https://static.cninfo.com.cn/finalpage/2025-02-15/1222544408.PDF
# 这里只表达证券身份别名，不表达历史简称、生效期或历史可得性。
VERIFIED_STOCK_ALIASES = {"300114.SZ": "302132.SZ"}


def stock_alias_ids(
    stock_ids: Mapping[str, int], bse_mapping: pd.DataFrame | None
) -> dict[str, int]:
    """按有证据的换码关系解析旧代码；冲突、缺目标、非法代码拒绝。

    Args:
        stock_ids: canonical 股票代码到标的 ID；不包含指数或期货。
        bse_mapping: 供应商 bse_mapping 原始对照，可为 None（旧 raw）。

    Returns:
        旧 source_symbol 到现有股票标的 ID 的映射，不新建第二个标的。
    """
    aliases = {old: new for old, new in VERIFIED_STOCK_ALIASES.items() if new in stock_ids}
    if bse_mapping is not None:
        if bse_mapping.empty or not {"o_code", "n_code"} <= set(bse_mapping.columns):
            raise ValueError("Invalid BSE mapping schema or empty snapshot")
        for old, new in bse_mapping[["o_code", "n_code"]].itertuples(index=False, name=None):
            if not all(
                isinstance(code, str) and re.fullmatch(r"\d{6}\.BJ", code) for code in (old, new)
            ):
                raise ValueError("Invalid BSE mapping code")
            if old == new or (old in aliases and aliases[old] != new):
                raise ValueError(f"Conflicting stock alias: {old}")
            aliases[old] = new
    result = {}
    for old, new in aliases.items():
        if new not in stock_ids:
            raise ValueError(f"Stock alias target missing: {old} -> {new}")
        if old in stock_ids and stock_ids[old] != stock_ids[new]:
            raise ValueError(f"Stock alias conflicts with canonical instrument: {old}")
        result[old] = int(stock_ids[new])
    return result


def collapse_alias_rows(df: pd.DataFrame, canonical: Mapping[int, str]) -> pd.DataFrame:
    """合并同一标的同日的新旧代码重复观察；数值冲突拒绝，raw 保持原样。

    仅处理跨 source_symbol 的重复。所有字段须相同（含 NULL）；唯一例外是
    daily_basic.limit_status，已核实旧 300114 历史固定为 0，新代码反映实际涨跌。
    该字段按 canonical 代码优先保留，差异计数明确记录；其他元数据冲突仍拒绝。
    """
    day = "trading_day" if "trading_day" in df else "dt"
    keys = ["instrument_id", day]
    repeated = df[df.duplicated(keys, keep=False)]
    if repeated.empty:
        return df
    drop = []
    metadata_conflicts = 0
    for key, group in repeated.groupby(keys, sort=False):
        if group.ts_code.nunique() == 1:
            continue  # 同代码重复留给原有质量门禁，不借换码规则吞掉。
        preferred = group[group.ts_code.eq(canonical.get(int(key[0])))]
        if len(preferred) != 1 or group.ts_code.duplicated().any():
            raise ValueError(f"Ambiguous alias observations: {key}")
        differing = group.drop(columns=["ts_code"]).nunique(dropna=False)
        differences = set(differing[differing > 1].index)
        # 仅此已逐日核对的换码对允许供应商涨跌状态差异，不泛化到其他证券。
        permitted = {"limit_status"} if set(group.ts_code) == {"300114.SZ", "302132.SZ"} else set()
        if differences - permitted:
            raise ValueError(f"Conflicting alias observations: {key}, fields={sorted(differences)}")
        metadata_conflicts += int(bool(differences))
        drop.extend(group.index.difference(preferred.index))
    if drop:
        logging.getLogger(__name__).info(
            "Alias observations consolidated rows_removed=%d metadata_conflicts=%d "
            "preference=canonical",
            len(drop),
            metadata_conflicts,
        )
    return df.drop(index=drop).reset_index(drop=True)
