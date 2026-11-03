"""期货连续合约上市前空占位行：四项证据齐备才允许已跳过行通过审核。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

import pandas as pd
import polars as pl

from gr_data.common.paths import RawPaths
from gr_data.ingest.tushare.adapter import TushareAdapter


FUTURE_PLACEHOLDER_RULE = "tushare_future_pre_listing_placeholder_v1"
FUTURE_PLACEHOLDER_NOTICE = "Future pre-listing placeholder "
PRICE_FIELDS = ("open", "high", "low", "close", "settle", "pre_close", "pre_settle")
ACTIVITY_FIELDS = ("vol", "amount", "oi")
_CONTINUOUS = re.compile(r"([A-Za-z]+)L[0-9]*\.(CFX|DCE|ZCE|SHF|INE|GFE)")
_DATED = re.compile(r"[A-Za-z]+[0-9]{1,2}(?:0[1-9]|1[0-2])\.(CFX|DCE|ZCE|SHF|INE|GFE)")


def _dated_pattern(product: str, suffix: str) -> str:
    return rf"{re.escape(product)}[0-9]{{1,2}}(?:0[1-9]|1[0-2])\.{suffix}"


def classify_pre_listing_placeholders(rows: pd.DataFrame, paths: RawPaths) -> list[dict[str, Any]]:
    """只分类源价格全缺失、量额仓均精确零的连续合约。

    日期为源trade_date事件日。上市日仅由当前raw中同品种、同交易所的带
    到期月份合约首次出现日推导，不使用连续合约或主数据日期代替。
    扫描只投影代码／日期并按品种过滤，峰值内存限于一个候选品种的匹配行；
    未找到到期合约就不产生可放行告警。坏分区／日期直接失败，raw从不改写。
    """
    candidates = rows.loc[
        rows[list(PRICE_FIELDS)].isna().all(axis=1) & rows[list(ACTIVITY_FIELDS)].eq(0).all(axis=1)
    ]
    groups: dict[tuple[str, str], list[tuple[str, date]]] = {}
    for code, day in candidates[["ts_code", "trade_date"]].itertuples(index=False, name=None):
        if not isinstance(code, str) or not isinstance(day, date):
            raise ValueError("Placeholder classification requires normalized code and trade_date")
        # TL2306属于TL到期合约，不能按T + L2306误认成连续合约。
        if _DATED.fullmatch(code):
            continue
        match = _CONTINUOUS.fullmatch(code)
        if match:
            groups.setdefault((match.group(1), match.group(2)), []).append((code, day))
    if not groups:
        return []
    # 必须查看已采集的全部月份，不能只看本次入库月或假设下一月已有数据。
    adapter = TushareAdapter(paths)
    partitions = [
        paths.dataset_file("tushare", "fut_daily", ym) for ym in adapter.list_months("fut_daily")
    ]
    if not partitions:
        return []
    scan = pl.scan_parquet(partitions).select("ts_code", "trade_date")
    notices = []
    hashes: dict[str, str] = {}
    for (product, suffix), items in sorted(groups.items()):
        pattern = _dated_pattern(product, suffix)
        first = (
            scan.filter(pl.col("ts_code").str.contains("^" + pattern + "$"))
            .select(
                "ts_code",
                pl.col("trade_date")
                .cast(pl.String)
                .str.strptime(pl.Date, "%Y%m%d", strict=True)
                .alias("date"),
            )
            .sort(["date", "ts_code"])
            .head(1)
            .collect()
        )
        if first.is_empty():
            continue
        contract_code, listing = first.row(0)
        if listing is None:
            raise ValueError("Missing dated future contract trade_date")
        partition = listing.strftime("%Y-%m")
        source = paths.dataset_file("tushare", "fut_daily", partition)
        if partition not in hashes:
            hashes[partition] = hashlib.sha256(source.read_bytes()).hexdigest()
        for code, day in sorted(items):
            if day >= listing:
                continue
            detail = {
                "rule": FUTURE_PLACEHOLDER_RULE,
                "dataset": "fut_daily",
                "ts_code": code,
                "date": day.isoformat(),
                "product": product,
                "listing_date": listing.isoformat(),
                "rows": 1,
                "raw_values": {**dict.fromkeys(PRICE_FIELDS), **dict.fromkeys(ACTIVITY_FIELDS, 0)},
                "evidence": {
                    "continuous_contract": True,
                    "all_prices_null": True,
                    "zero_activity": True,
                    "dated_contract_first_seen_after_row": True,
                    "first_dated_contract": {
                        "ts_code": contract_code,
                        "date": listing.isoformat(),
                        "raw_partition": partition,
                        "raw_sha256": hashes[partition],
                    },
                },
            }
            notices.append(detail)
    return notices


def parse_pre_listing_placeholder_notice(warning: str) -> dict[str, Any] | None:
    """runner共用的严格告警结构校验；普通无效价格告警永远不放行。"""
    if not warning.startswith(FUTURE_PLACEHOLDER_NOTICE):
        return None
    try:
        d = json.loads(warning[len(FUTURE_PLACEHOLDER_NOTICE) :])
        if not isinstance(d, dict) or set(d) != {
            "rule",
            "dataset",
            "ts_code",
            "date",
            "product",
            "listing_date",
            "rows",
            "raw_values",
            "evidence",
        }:
            return None
        match = _CONTINUOUS.fullmatch(d["ts_code"])
        if not match or _DATED.fullmatch(d["ts_code"]) or match.group(1) != d["product"]:
            return None
        day, listing = date.fromisoformat(d["date"]), date.fromisoformat(d["listing_date"])
        if (
            day.isoformat() != d["date"]
            or listing.isoformat() != d["listing_date"]
            or day >= listing
        ):
            return None
        if (
            d["rule"] != FUTURE_PLACEHOLDER_RULE
            or d["dataset"] != "fut_daily"
            or type(d["rows"]) is not int
            or d["rows"] != 1
        ):
            return None
        values = d["raw_values"]
        if not isinstance(values, dict) or set(values) != set(PRICE_FIELDS + ACTIVITY_FIELDS):
            return None
        if any(values[k] is not None for k in PRICE_FIELDS) or any(
            type(values[k]) not in (int, float) or values[k] != 0 for k in ACTIVITY_FIELDS
        ):
            return None
        evidence = d["evidence"]
        flags = {
            "continuous_contract",
            "all_prices_null",
            "zero_activity",
            "dated_contract_first_seen_after_row",
        }
        if (
            not isinstance(evidence, dict)
            or set(evidence) != flags | {"first_dated_contract"}
            or any(evidence[k] is not True for k in flags)
        ):
            return None
        first = evidence["first_dated_contract"]
        if not isinstance(first, dict) or set(first) != {
            "ts_code",
            "date",
            "raw_partition",
            "raw_sha256",
        }:
            return None
        if (
            not re.fullmatch(_dated_pattern(*match.groups()), first["ts_code"])
            or first["date"] != d["listing_date"]
            or first["raw_partition"] != listing.strftime("%Y-%m")
            or not re.fullmatch(r"[0-9a-f]{64}", first["raw_sha256"])
        ):
            return None
        return d
    except (ValueError, TypeError, KeyError):
        return None
