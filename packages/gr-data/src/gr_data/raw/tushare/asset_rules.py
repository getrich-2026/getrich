"""ETF / 期权的源键、市场与数值门禁；不改变源报价或单位。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from gr_data.common.parquet import read_parquet_strict


OPTION_SUFFIXES = {
    "SSE": "SH",
    "SZSE": "SZ",
    "CFFEX": "CFX",
    "DCE": "DCE",
    "CZCE": "ZCE",
    "SHFE": "SHF",
    "INE": "INE",
    "GFEX": "GFE",
}
PRICE_COLUMNS = ("open", "high", "low", "close", "pre_close")
BAR_COLUMNS = ("ts_code", "trade_date", *PRICE_COLUMNS, "vol", "amount")
OPTION_BAR_COLUMNS = (*BAR_COLUMNS, "exchange", "settle", "pre_settle", "oi")


def standard_fund_codes(codes: pd.Series) -> pd.Series:
    """识别可用于沪深市场检查的六位交易代码；不改写或过滤源代码。"""
    return codes.str.fullmatch(r"\d{6}\.(SH|SZ)")


def quarantined_etf_mask(frame: pd.DataFrame) -> pd.Series:
    """隔离用户确认的源身份冲突及 L 缺上市日，不改码或改状态。

    2026-10-30：etf_basic 将 158008.OF 列为深圳 L，fund_basic 却标 market=O。
    原响应及对账位置见 imac-collector-migration.md 第二节；待源端更正再复验。
    """
    return conflicting_etf_code_mask(frame) | missing_etf_listing_mask(frame)


def conflicting_etf_code_mask(frame: pd.DataFrame) -> pd.Series:
    """只识别已有原响应佐证的 OF 身份冲突，不能为其他坏代码豁免校验。"""
    return (
        frame["ts_code"].eq("158008.OF") & frame["exchange"].eq("SZ") & frame["list_status"].eq("L")
    )


def missing_etf_listing_mask(frame: pd.DataFrame) -> pd.Series:
    """L 名单上市日缺失时只保留 raw；非法日期不当作缺失隔离。"""
    return frame["list_status"].eq("L") & (frame["list_date"].isna() | frame["list_date"].eq(""))


def czce_settlement_only_mask(frame: pd.DataFrame) -> pd.Series:
    """识别郑商所结算价正、OHLC 全零的缺失报价，不按量额推断成交价。

    仅接受 CZCE／.ZCE、OHLC 全零且 settle>0；价格 NULL 不匹配。
    2026-10-30 用户确认有成交量额时同样映射 NULL，量额／持仓仍独立严格校验。
    https://www.czce.com.cn/cn/DFSStaticFiles/Option/2024/20240102/OptionDataDaily.txt
    """
    return (
        frame["exchange"].eq("CZCE")
        & frame["ts_code"].str.endswith(".ZCE")
        & pd.concat(
            [numeric_values(frame[c], c).eq(0) for c in ("open", "high", "low", "close")],
            axis=1,
        ).all(axis=1)
        & numeric_values(frame["settle"], "settle").gt(0)
    )


def czce_settlement_only_counts(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """按市场登记缺失报价行、非零量额行及至多五个源键样本。"""
    selected = frame.loc[czce_settlement_only_mask(frame)]
    return {
        str(exchange): {
            "rows": len(rows),
            "nonzero_activity_rows": int(
                (
                    numeric_values(rows["vol"], "vol", integer=True).gt(0)
                    | numeric_values(rows["amount"], "amount", precision=30, scale=10).gt(0)
                ).sum()
            ),
            "samples": rows[["ts_code", "trade_date"]].head(5).to_dict("records"),
        }
        for exchange, rows in selected.groupby("exchange", sort=True)
    }


def zero_settlement_candidate_mask(frame: pd.DataFrame) -> pd.Series:
    """识别 CZCE／GFEX 的 OHLC／settle 全零候选；形态本身不证明到期。"""
    return (
        frame["exchange"].isin(["CZCE", "GFEX"])
        & frame["ts_code"].str.rsplit(".", n=1).str[-1].eq(frame["exchange"].map(OPTION_SUFFIXES))
        & pd.concat(
            [numeric_values(frame[c], c).eq(0) for c in ("open", "high", "low", "close", "settle")],
            axis=1,
        ).all(axis=1)
    )


def zero_settlement_candidate_counts(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """记录尚需元数据核对到期日的源候选，不把 raw 捕获当作入库验收。"""
    selected = frame.loc[zero_settlement_candidate_mask(frame)]
    return {
        str(exchange): {
            "rows": len(rows),
            "nonzero_volume_rows": int(
                numeric_values(rows["vol"], "vol", integer=True).gt(0).sum()
            ),
            "samples": rows[["ts_code", "trade_date"]].head(5).to_dict("records"),
        }
        for exchange, rows in selected.groupby("exchange", sort=True)
    }


def ohl_zero_placeholder_mask(frame: pd.DataFrame) -> pd.Series:
    """精确识别 OHL 全零、close>0 的源占位，不依据交易所或成交量猜测。"""
    prices = {c: numeric_values(frame[c], c) for c in ("open", "high", "low", "close")}
    return prices["open"].eq(0) & prices["high"].eq(0) & prices["low"].eq(0) & prices["close"].gt(0)


def ohl_zero_placeholder_counts(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """按市场记录占位行、非零成交量行及各至多五个源键样本。"""
    selected = frame.loc[ohl_zero_placeholder_mask(frame)]
    result = {}
    for exchange, rows in selected.groupby("exchange", sort=True):
        nonzero = rows.loc[numeric_values(rows["vol"], "vol").gt(0)]
        result[str(exchange)] = {
            "rows": len(rows),
            "nonzero_volume_rows": len(nonzero),
            "samples": rows[["ts_code", "trade_date"]].head(5).to_dict("records"),
            "nonzero_volume_samples": nonzero[["ts_code", "trade_date"]].head(5).to_dict("records"),
        }
    return result


def nonstandard_code_counts(frame: pd.DataFrame) -> dict[str, Any]:
    """统计保留在 raw 的非标准基金代码，样本不超过五个。"""
    codes = frame.loc[~standard_fund_codes(frame["ts_code"]), "ts_code"]
    return {"rows": len(codes), "samples": codes.drop_duplicates().head(5).tolist()}


def require_columns(frame: pd.DataFrame, columns: tuple[str, ...], source: str) -> None:
    """逐响应 / 分区检查必需列，拒绝 concat 后掩盖源缺列。"""
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns source={source} columns={sorted(missing)}")


def source_codes(frame: pd.DataFrame) -> pd.Series:
    """源代码必须是非空、无首尾空白的字符串，保留原格式。"""
    codes = frame["ts_code"]
    valid = codes.map(lambda v: isinstance(v, str) and bool(v) and v == v.strip())
    if not valid.all():
        raise ValueError("Invalid source ts_code")
    return codes


def unique_rows(frame: pd.DataFrame, keys: tuple[str, ...]) -> pd.DataFrame:
    """完全相同记录可去重；同键不同值拒绝，不用 UPSERT 掩盖冲突。"""
    out = frame.drop_duplicates().reset_index(drop=True)
    if out.duplicated(list(keys)).any():
        raise ValueError(f"Conflicting source keys keys={keys}")
    return out


def read_asset_observation(path: Path) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """核验本轮新资产文件的发布收据；崩溃或文件被改动不能伪装为已完成。

    老股票 / 指数 / 期货文件不走此协议；缺文件返回 None，存在而缺收据即拒绝。
    """
    frame = read_parquet_strict(path)
    if frame is None:
        return None, {}
    try:
        receipt = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Missing or invalid asset receipt file={path.name}") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()
    ):
        raise ValueError(f"Asset receipt hash mismatch file={path.name}")
    return frame, receipt


def source_dates(values: pd.Series) -> pd.Series:
    """校验 int8 / 字符串日期，返回 DATE；不接受时间戳或浮点日期。"""
    text = values.astype(str)
    if not text.str.fullmatch(r"\d{8}").all():
        raise ValueError("Invalid source date format")
    parsed = pd.to_datetime(text, format="%Y%m%d", errors="raise")
    if parsed.isna().any():
        raise ValueError("Missing source date")
    return parsed.dt.date


def numeric_values(
    values: pd.Series,
    column: str,
    *,
    scale: int = 6,
    precision: int = 20,
    multiplier: int = 1,
    integer: bool = False,
    positive: bool = False,
) -> pd.Series:
    """精确转换非负源数值；NULL 保留，非法值、非有限、溢出或舍入均拒绝。

    Args:
        values: 一列供应商数值，允许源 NULL。
        column: 错误定位字段，不包含完整 payload。
        scale: PG NUMERIC 小数位数。
        precision: PG NUMERIC 总位数。
        multiplier: ingest 的显式单位倍率；raw 检查使用 1。
        integer: 是否要求精确 BIGINT，不能先 round。
        positive: 是否必须严格大于零（复权因子、乘数等）。
    """

    def convert(value: Any) -> object:
        if value is None or value is pd.NA or pd.isna(value):
            return None
        try:
            number = Decimal(str(value)) * multiplier
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid numeric column={column}") from exc
        if not number.is_finite() or number < 0 or (positive and number == 0):
            raise ValueError(f"Invalid numeric column={column}")
        if integer:
            if number != number.to_integral_value() or number > 2**63 - 1:
                raise ValueError(f"Invalid integer column={column}")
            return int(number)
        if number >= Decimal(10) ** (precision - scale):
            raise ValueError(f"Numeric overflow column={column}")
        if number != number.quantize(Decimal(10) ** -scale):
            raise ValueError(f"Numeric precision loss column={column}")
        return number

    # map 会把 [int, None] 推断成 float，COPY BIGINT 因此变成 "1.0"；显式 object 保真。
    return pd.Series([convert(v) for v in values], index=values.index, dtype=object)


def validate_bars(
    frame: pd.DataFrame,
    *,
    option: bool = False,
    capture_unverified_expiry: bool = False,
    expiry_dates: Mapping[str, date | None] | None = None,
) -> pd.DataFrame:
    """检查源键、价格和活动值，返回源值不变的去重副本。

    价格缺失允许 NULL / NaN；Inf、坏字符串、负值及无 close / settle 的记录失败。
    raw 捕获可显式暂存 CZCE／GFEX 零结算候选；ingest 必须提供供应商到期日映射，
    逐行验证 trade_date 等于 delist_date，默认不接受无证据的候选。
    """
    require_columns(frame, OPTION_BAR_COLUMNS if option else BAR_COLUMNS, "bars")
    source_codes(frame)
    dates = source_dates(frame["trade_date"])
    out = frame.copy()
    out["trade_date"] = pd.to_datetime(dates).dt.strftime("%Y%m%d")
    out = unique_rows(out, ("ts_code", "trade_date"))
    if option:
        expected = out["exchange"].map(OPTION_SUFFIXES)
        if (
            expected.isna().any()
            or not out["ts_code"].str.rsplit(".", n=1).str[-1].eq(expected).all()
        ):
            raise ValueError("Option exchange and suffix mismatch")
    prices = [*PRICE_COLUMNS, *(("settle", "pre_settle") if option else ())]
    normalized = {c: numeric_values(out[c], c) for c in prices}
    close = normalized["close"]
    usable = close.notna()
    if option:
        usable |= normalized["settle"].notna()
    if not usable.all():
        raise ValueError("No usable close or settle")
    high, low = normalized["high"], normalized["low"]
    placeholder = pd.Series(False, index=out.index)
    if option:
        zero_ohl = normalized["open"].eq(0) & high.eq(0) & low.eq(0)
        placeholder = zero_ohl & close.gt(0)
        expiry_zero = zero_settlement_candidate_mask(out)
        if expiry_zero.any() and not capture_unverified_expiry:
            expiration = out["ts_code"].map(expiry_dates or {})
            verified = source_dates(out["trade_date"]).eq(expiration) & expiration.notna()
            if (expiry_zero & ~verified).any():
                raise ValueError("Unverified zero settlement expiry date")
        if (zero_ohl & ~placeholder & ~czce_settlement_only_mask(out) & ~expiry_zero).any():
            raise ValueError("Invalid OHLC zero placeholder without positive close")
    both = high.notna() & low.notna()
    if high.loc[both].lt(low.loc[both]).any():
        raise ValueError("Invalid OHLC high < low")
    for col in ("open", "close"):
        value = normalized[col]
        above = value.notna() & high.notna() & ~placeholder
        below = value.notna() & low.notna() & ~placeholder
        if value.loc[above].gt(high.loc[above]).any() or value.loc[below].lt(low.loc[below]).any():
            raise ValueError(f"Invalid OHLC bounds column={col}")
    numeric_values(out["vol"], "vol", integer=option, precision=30, scale=8)
    numeric_values(out["amount"], "amount", precision=30, scale=10)
    if option:
        numeric_values(out["oi"], "oi", integer=True)
    return out


def option_underlying(opt_code: object) -> str:
    """按官方 OP+标的 TS_CODE 约定读取；不从期权交易代码推测年份。"""
    if not isinstance(opt_code, str) or not re.fullmatch(r"OP[^\s.]+\.[A-Z]+", opt_code):
        raise ValueError("Invalid option opt_code")
    return opt_code[2:]
