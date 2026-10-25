"""Tushare 原油 TAS 价差与普通期货价格的 raw 校验；不改写源数据。"""

from __future__ import annotations

import numpy as np
import pandas as pd


TAS_OFFSET_COLUMNS = ("open", "high", "low", "close", "pre_close")
_SETTLEMENT_COLUMNS = ("settle", "pre_settle")
_ACTIVITY_COLUMNS = ("vol", "amount", "oi")
_TAS_RANGE_START = pd.Timestamp("2023-04-11")
_TAS_MAX_OFFSET = 2.0
# 能源中心 2023-03-29 通知：2023-04-10 夜盘起，TAS 申报价差为结算价 ±2 元/桶。
# https://www.ine.com.cn/eng/circularnews/circular/202303/t20230329_822378.html
# Tushare SCTAS 的 OHLC 为该价差，settle/pre_settle 仍为绝对结算价；不可混同。
TAS_CODE_PATTERN = r"SCTAS(?:[0-9]{4}|L)?\.INE"


def tas_code_mask(codes: pd.Series) -> pd.Series:
    """按代码形态识别 SCTAS 月合约及主力／连续代码；不读基础信息，不改输入。"""
    return codes.astype(str).str.strip().str.fullmatch(TAS_CODE_PATTERN)


def tas_spread_mask(raw: pd.DataFrame, instruments: pd.DataFrame) -> pd.Series:
    """识别有基础信息佐证的 SCTAS 月合约及主力／连续代码。

    Args:
        raw: 至少有 ts_code 的源行情；不修改任何值。
        instruments: 原始期货清单，TAS 行须具有 exchange=INE、fut_code=SCTAS。

    Returns:
        与 raw 索引对齐的布尔掩码。空行情返回空掩码。

    Raises:
        ValueError: 行情代码缺失，或 SCTAS 代码缺少匹配的源基础信息。
    """
    if "ts_code" not in raw or raw["ts_code"].isna().any():
        raise ValueError("Missing future quote code")
    codes = raw["ts_code"].astype(str).str.strip()
    mask = tas_code_mask(codes)
    if not mask.any():
        return mask
    required = {"ts_code", "exchange", "fut_code"}
    if not required <= set(instruments.columns):
        raise ValueError("TAS quote requires future reference metadata")
    reference = instruments.copy()
    reference["ts_code"] = reference["ts_code"].astype(str).str.strip()
    selected = reference[reference["ts_code"].isin(codes[mask])]
    if selected["ts_code"].duplicated().any():
        raise ValueError("Ambiguous TAS future reference metadata")
    confirmed = selected.loc[
        selected["exchange"].eq("INE") & selected["fut_code"].eq("SCTAS"), "ts_code"
    ]
    if not codes[mask].isin(confirmed).all():
        raise ValueError("Unverified TAS future reference metadata")
    return mask


def validate_future_quote_values(raw: pd.DataFrame, instruments: pd.DataFrame) -> dict[str, int]:
    """校验有限数值及 SCTAS 价差边界，返回统计，不转换或填补源值。

    SCTAS 的 OHLC/前收按元/桶的结算价偏移量校验：2023-04-11 起允许 [-2, 2]；
    更早记录仅接受 0。普通合约价格、所有 settle/pre_settle、成交量、成交额及持仓量
    保持非负，vol/oi 保持整数手。源 NULL 允许保留，已有非数值或无穷值拒绝。
    空行情返回零统计；高低价关系、日期覆盖与业务键由调用方检查。

    Raises:
        ValueError: 缺少字段、TAS 参照无法核实、日期或数值违反上述规则。
    """
    columns = (*TAS_OFFSET_COLUMNS, *_SETTLEMENT_COLUMNS, *_ACTIVITY_COLUMNS)
    required = {"ts_code", "trade_date", *columns}
    if not required <= set(raw.columns):
        raise ValueError("Missing future quote fields")
    tas = tas_spread_mask(raw, instruments)
    dates = pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d", errors="raise")
    if dates.isna().any():
        raise ValueError("Invalid future quote date")
    negative_tas = pd.Series(False, index=raw.index)
    for column in columns:
        values = pd.to_numeric(raw[column], errors="coerce")
        present = raw[column].notna()
        if (present & (values.isna() | ~np.isfinite(values))).any():
            raise ValueError(f"Nonfinite or nonnumeric future quote column={column}")
        if column in TAS_OFFSET_COLUMNS:
            if (values.lt(0) & ~tas).any():
                raise ValueError(f"Negative ordinary future price column={column}")
            limit = pd.Series(0.0, index=raw.index).where(dates < _TAS_RANGE_START, _TAS_MAX_OFFSET)
            if (tas & values.abs().gt(limit)).any():
                raise ValueError(f"TAS settlement offset out of range column={column}")
            negative_tas |= tas & values.lt(0)
        elif values.lt(0).any():
            raise ValueError(f"Negative future value column={column}")
        if column in ("vol", "oi") and (values.dropna() % 1 != 0).any():
            raise ValueError(f"Noninteger future contract count column={column}")
    return {"tas_rows": int(tas.sum()), "tas_negative_quote_rows": int(negative_tas.sum())}
