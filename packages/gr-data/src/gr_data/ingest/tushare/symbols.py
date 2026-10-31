"""Tushare 代码归一化。

Tushare ``ts_code`` 形如 ``600000.SH`` / ``000001.SZ`` / ``CU2401.SHF``。
canonical：symbol 保留完整原始代码串，exchange 由后缀映射。
见 docs/conventions/symbol-mapping.md。

注意 Tushare 的交易所后缀与通行简称并不一致（``SHF`` 而非 ``SHFE``、
``ZCE`` 而非 ``CZCE``、``CFX`` 而非 ``CFFEX``），必须显式映射，
不能靠字符串截断猜测。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import NoReturn

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


# 公司实施公告确认法人及上市主体延续；这里只表达证券身份别名，
# 不表达历史简称、生效期或历史可得性。
# 深赤湾 A：2018-12-26 起换码。
# https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF
# 中航善达：2019-12-16 起换码。
# https://static.cninfo.com.cn/finalpage/2019-12-16/1207164397.PDF
# 中航电测（中航成飞）：2025-02-17 起换码。
# https://static.cninfo.com.cn/finalpage/2025-02-15/1222544408.PDF
VERIFIED_STOCK_ALIASES = {
    "000022.SZ": "001872.SZ",
    "000043.SZ": "001914.SZ",
    "300114.SZ": "302132.SZ",
}

# 2026-10-31 用户明确授权；其余换码对及字段继续严格一致。
_TOLERATED_METADATA_PAIRS = {
    frozenset(("000022.SZ", "001872.SZ")),
    frozenset(("000043.SZ", "001914.SZ")),
}
_TOLERATED_METADATA_FIELDS = {"dv_ratio", "dv_ttm", "limit_status"}


def _optional_decimal(value: object, field: str) -> Decimal | None:
    """已授权的元数据对账中，NULL／NaN／Inf 同属缺失；坏文本仍拒绝。"""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Non-comparable alias metadata field={field}") from exc
    return result if result.is_finite() else None


def _finite_decimal(value: object, field: str) -> Decimal:
    """价格证据必须有限，不以元数据缺失策略放宽行情。"""
    result = _optional_decimal(value, field)
    if result is None:
        raise ValueError(f"Non-comparable alias metadata field={field}")
    return result


def _reject_alias_metadata(detail: Mapping[str, object], rule: str) -> NoReturn:
    """拒绝事件留在运行日志；失败事务不会伪造已提交的覆盖审计。"""
    failure = {**detail, "processing_rule": rule}
    logging.getLogger(__name__).warning(
        "Alias metadata reconciliation rejected detail=%s",
        json.dumps(failure, ensure_ascii=False, allow_nan=False),
    )
    raise ValueError(f"Alias metadata reconciliation rejected: {failure}")


def _limit_status_from_prices(prices: Mapping[str, object]) -> int:
    """用实际 OHLC、前收与当日限价重判 0～6，不接受缺失的限价证据。"""
    values = {
        name: _finite_decimal(prices.get(name), name)
        for name in ("open", "high", "low", "close", "pre_close", "limit_up", "limit_down")
    }
    if any(values[name] <= 0 for name in ("open", "high", "low", "close", "pre_close")):
        raise ValueError("Invalid alias price evidence")
    close, up, down = values["close"], values["limit_up"], values["limit_down"]
    no_limit = up >= 99999 and 0 <= down <= Decimal("0.01")
    if not no_limit and (down <= 0 or up <= down or not down <= close <= up):
        raise ValueError("Invalid alias price limit evidence")
    if (
        not values["low"]
        <= min(values["open"], close)
        <= max(values["open"], close)
        <= values["high"]
    ):
        raise ValueError("Invalid alias OHLC evidence")
    one_price = all(values[name] == close for name in ("open", "high", "low"))
    if not no_limit and close == up:
        return 3 if one_price else 2
    if not no_limit and close == down:
        return 6 if one_price else 5
    previous = values["pre_close"]
    return 1 if close > previous else 4 if close < previous else 0


def expand_stock_auxiliary_aliases(frame: pd.DataFrame) -> pd.DataFrame:
    """为已核实换码对补齐辅助表的等价关联键，源文件与已有行均不修改。

    只复制缺失的 (ts_code, trade_date) 键；已有两条观察即使冲突也保留，
    由后续价格一致性校验拒绝，不借别名吞掉差异。
    """
    present = set(frame[["ts_code", "trade_date"]].itertuples(index=False, name=None))
    additions = []
    for old, new in VERIFIED_STOCK_ALIASES.items():
        for source, target in ((old, new), (new, old)):
            selected = frame.loc[frame["ts_code"].eq(source)].copy()
            missing = [(target, day) not in present for day in selected["trade_date"]]
            selected = selected.loc[missing]
            if not selected.empty:
                selected["ts_code"] = target
                additions.append(selected)
    return pd.concat([frame, *additions], ignore_index=True) if additions else frame


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


def collapse_alias_rows(
    df: pd.DataFrame,
    canonical: Mapping[int, str],
    *,
    price_evidence: Mapping[tuple[int, date], Mapping[str, object]] | None = None,
    audit: Callable[[Mapping[str, object]], None] | None = None,
) -> pd.DataFrame:
    """合并同一标的同日的新旧代码重复观察；数值冲突拒绝，raw 保持原样。

    仅处理跨 source_symbol 的重复。300114 的 limit_status 沿用已核实规则。
    000022／000043 两对按显式授权处理缺失、股息率容差和价格反证，
    并要求审计回调逐字段留痕；相对差以新代码绝对值为基准。其余冲突拒绝。

    Args:
        df: 已解析标的 ID、日期和源代码的观察；不就地改写。
        canonical: 股票标的 ID 到当前代码的映射。
        price_evidence: 同一标的、交易日的真实 OHLC、前收及涨跌停价。
        audit: 逐字段审计回调；调用方负责与业务写入同事务提交或回滚。

    Returns:
        按当前代码保留的唯一观察。

    Raises:
        ValueError: 身份不明确、容差／价格反证不通过或缺少审计设施。
    """
    day = "trading_day" if "trading_day" in df else "dt"
    keys = ["instrument_id", day]
    repeated = df[df.duplicated(keys, keep=False)]
    if repeated.empty:
        return df
    df = df.copy()
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
        # 中航成飞保留原已核实例外；另外两对必须满足下方新增的校验与审计。
        codes = frozenset(group.ts_code)
        permitted = {"limit_status"} if codes == {"300114.SZ", "302132.SZ"} else set()
        reviewed_metadata = codes in _TOLERATED_METADATA_PAIRS
        if reviewed_metadata:
            permitted = _TOLERATED_METADATA_FIELDS
        if differences - permitted:
            raise ValueError(f"Conflicting alias observations: {key}, fields={sorted(differences)}")
        if reviewed_metadata:
            current = preferred.iloc[0]
            previous = group.loc[~group.ts_code.eq(current.ts_code)].iloc[0]
            observed_day = pd.Timestamp(str(key[1])).date()
            reconciliations = []
            for field in sorted(permitted.intersection(group.columns)):
                old_value = _optional_decimal(previous[field], field)
                new_value = _optional_decimal(current[field], field)
                if field == "limit_status" and old_value is not None and old_value == new_value:
                    continue
                if audit is None:
                    raise ValueError("Alias metadata reconciliation requires audit")
                detail = {
                    "old_code": str(previous.ts_code),
                    "canonical_code": str(current.ts_code),
                    "trading_day": observed_day.isoformat(),
                    "field": field,
                    "old_value": str(old_value) if old_value is not None else None,
                    "new_value": str(new_value) if new_value is not None else None,
                    "old_raw_value": str(previous[field]),
                    "new_raw_value": str(current[field]),
                }

                if new_value is None:
                    if old_value is not None:
                        _reject_alias_metadata(detail, "new_missing_stop")
                    rule = "both_missing_keep_null"
                elif old_value is None:
                    rule = "old_missing_use_new"
                elif field in {"dv_ratio", "dv_ttm"}:
                    distance = abs(old_value - new_value)
                    if distance > max(Decimal("0.01"), abs(new_value) * Decimal("0.01")):
                        _reject_alias_metadata(detail, "dividend_tolerance_stop")
                    rule = "finite_within_tolerance"
                else:
                    rule = "limit_status_verified"
                if field == "limit_status" and new_value is not None:
                    prices = (price_evidence or {}).get((int(str(key[0])), observed_day))
                    if (
                        old_value is not None and old_value not in range(7)
                    ) or new_value not in range(7):
                        _reject_alias_metadata(detail, "invalid_limit_status_stop")
                    if (
                        prices is not None
                        and "close" in current
                        and _finite_decimal(current["close"], "close")
                        != _finite_decimal(prices.get("close"), "close")
                    ):
                        _reject_alias_metadata(detail, "price_evidence_mismatch_stop")
                    if prices is None or Decimal(_limit_status_from_prices(prices)) != new_value:
                        _reject_alias_metadata(detail, "limit_status_mismatch_stop")
                    detail["verified_limit_status"] = str(new_value)
                reconciliations.append(
                    {
                        **detail,
                        "processing_rule": rule,
                        "selected_value": str(new_value) if new_value is not None else None,
                    }
                )
            for detail in reconciliations:
                field = str(detail["field"])
                if detail["selected_value"] is None:
                    df.at[preferred.index[0], field] = None
                if audit is not None:
                    audit(detail)
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
