"""D-012：郑商所年度期权文件解析、哈希校验及有界字段覆盖。"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import polars as pl

from gr_data.common.paths import RawPaths


DATASET = "option_official_annual"
RULE = "tushare_czce_official_option_override_v1"
NOTICE = "CZCE official option verification "
FIRST = "20170419"
LAST = "20251231"
PRICE_EXCEPTION = "20170821"
ASSERT_FIELDS = ("open", "high", "low", "close", "pre_settle")
OVERLAY_FIELDS = ("settle", "vol", "oi", "amount")
VALUE_FIELDS = (*ASSERT_FIELDS, *OVERLAY_FIELDS)
NUMERIC = pl.Decimal(30, 10)
_HEADERS = {
    "交易日期": "trade_date",
    "品种代码": "ts_code",
    "合约代码": "ts_code",
    "昨结算": "pre_settle",
    "今开盘": "open",
    "最高价": "high",
    "最低价": "low",
    "今收盘": "close",
    "今结算": "settle",
    "成交量(手)": "vol",
    "持仓量": "oi",
    "空盘量": "oi",
    "成交额(万元)": "amount",
}


def digest(path: Path) -> str:
    """SHA256只校验文件内容，不修改输入。"""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    """原子写审计清单，拒绝非JSON数值。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_parquet(path: Path, frame: pl.DataFrame) -> None:
    """按分区原子写zstd；内存为调用者当前分区。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        frame.write_parquet(tmp, compression="zstd")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def parse_option_txt(path: Path) -> pl.DataFrame:
    """解析一个官方文件，价格／金额保持十进制源单位，量仓不换算。

    兼容UTF8和GB18030、两种代码表头及空盘量旧名。千分位移除；空白、
    --、—按NULL保留，非法数值／日期／重复键失败。单文件分批，峰值约为
    解码文本加当前文件的列式数据，不同时加载全部年度文本。
    """
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("gb18030")
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if "交易日期" in line and "|" in line), None)
    if header is None:
        raise ValueError(f"Missing CZCE option header file={path.name}")
    raw = pl.read_csv(io.StringIO("\n".join(lines[header:])), separator="|", infer_schema=False)
    names = {name: _HEADERS[name.strip()] for name in raw.columns if name.strip() in _HEADERS}
    if len(set(names.values())) != len(names):
        raise ValueError("Duplicate CZCE official column aliases")
    raw = raw.select(*names).rename(names)
    required = {"trade_date", "ts_code", *VALUE_FIELDS}
    if set(raw.columns) != required:
        raise ValueError(
            f"Missing CZCE official columns file={path.name} "
            f"missing={sorted(required - set(raw.columns))}"
        )
    raw = raw.with_columns(pl.all().str.strip_chars())
    if raw.is_empty():
        raise ValueError("Empty CZCE official file")
    dates = (
        pl.col("trade_date").str.strptime(pl.Date, "%Y-%m-%d", strict=True).dt.strftime("%Y%m%d")
    )
    out = raw.with_columns(dates, pl.col("ts_code").str.to_uppercase())
    # 2025年文件另含SR507MSC5300等原生代码；保留完整字符串，不猜期限。
    if out.filter(
        ~pl.col("ts_code").str.contains(r"^[A-Z]+[0-9]{3}[A-Z]*[CP][0-9]+(?:\.[0-9]+)?$")
    ).height:
        raise ValueError("Invalid CZCE official option code")
    out = out.with_columns(
        (pl.col("ts_code") + ".ZCE").alias("ts_code"), pl.lit("CZCE").alias("exchange")
    )
    for name in VALUE_FIELDS:
        cleaned = pl.col(name).str.replace_all(",", "").replace(["", "--", "—", "-"], None)
        out = out.with_columns(cleaned.cast(NUMERIC, strict=True).alias(name))
        if out.filter(pl.col(name) < 0).height:
            raise ValueError(f"Negative CZCE official value field={name}")
    for name in ("vol", "oi"):
        if out.filter(pl.col(name).is_not_null() & (pl.col(name) != pl.col(name).floor())).height:
            raise ValueError(f"Noninteger CZCE official value field={name}")
        out = out.with_columns(pl.col(name).cast(pl.Int64))
    if out.select(pl.struct("trade_date", "ts_code").is_duplicated().any()).item():
        raise ValueError("Duplicate CZCE official keys")
    return out.select("ts_code", "trade_date", "exchange", *VALUE_FIELDS).sort(
        ["trade_date", "ts_code"]
    )


class OfficialOptionHistory:
    """读取显式批准清单；年度文件缺失、哈希变化或键／价格差异立即停止。"""

    def __init__(self, paths: RawPaths, manifest_sha256: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
            raise ValueError("Invalid approved CZCE official manifest SHA256")
        self.root = paths.dataset_dir("czce", DATASET)
        path = self.root / "manifest.json"
        if not path.exists() or digest(path) != manifest_sha256:
            raise ValueError("Missing or changed approved CZCE official manifest")
        self.manifest = json.loads(path.read_text())
        if self.manifest.get("rule") != RULE or self.manifest.get("coverage") != [FIRST, LAST]:
            raise ValueError("Invalid CZCE official manifest scope")
        self.manifest_sha256 = manifest_sha256
        self._years: dict[str, pl.DataFrame] = {}

    def year(self, year: str) -> pl.DataFrame:
        """只缓存当前调用涉及的年度列式表；加载前核对清单中全部原件SHA。"""
        if year not in self._years:
            item = self.manifest["years"].get(year)
            if not isinstance(item, dict):
                raise ValueError(f"Missing CZCE official year={year}")
            for info in [*item["sources"], item["parquet"]]:
                path = self.root / info["path"]
                if (
                    not path.resolve().is_relative_to(self.root.resolve())
                    or digest(path) != info["sha256"]
                ):
                    raise ValueError(f"Changed CZCE official file year={year}")
            frame = pl.read_parquet(self.root / item["parquet"]["path"])
            if (
                frame.height != item["rows"]
                or frame.select(pl.struct("trade_date", "ts_code").is_duplicated().any()).item()
            ):
                raise ValueError(f"Invalid CZCE official year keys={year}")
            self._years[year] = frame
        return self._years[year]

    def reconcile(
        self, raw: pd.DataFrame, expected_days: set[str] | None = None
    ) -> tuple[pd.DataFrame, list[dict[str, Any]], pl.DataFrame]:
        """逐交易所日断言后覆盖授权字段，原DataFrame不变。

        输入是源单位opt_daily；不调用OHLC校验也不放宽它。先断言集合和五个
        价格字段，再输出供原校验链检查的副本。2017-08-21仅OHL例外，close
        和pre_settle仍严格相等；2026仅记未核对，不覆盖。不接受2027等未授权年。
        """
        if raw.empty:
            raise ValueError("Empty CZCE comparison input")
        out = raw.copy()
        selected = out.loc[out["exchange"].eq("CZCE")]
        if selected.empty:
            return out, [], pl.DataFrame()
        t = pl.from_pandas(selected.reset_index(names="_source_index"), nan_to_null=True)
        if t.schema["trade_date"] != pl.String:
            t = t.with_columns(pl.col("trade_date").cast(pl.String))
        if t.filter(~pl.col("trade_date").str.contains(r"^[0-9]{8}$")).height:
            raise ValueError("Invalid CZCE Tushare trade_date")
        if t.select(pl.struct("trade_date", "ts_code").is_duplicated().any()).item():
            raise ValueError("Duplicate CZCE Tushare keys")
        if t.filter((pl.col("trade_date") < FIRST) | (pl.col("trade_date") > "20261231")).height:
            raise ValueError("CZCE official comparison outside authorized scope")
        present = set(t["trade_date"].to_list())
        if expected_days is not None and present != expected_days:
            raise ValueError(
                "CZCE response missing/unexpected trading days "
                f"missing={sorted(expected_days - present)} extra={sorted(present - expected_days)}"
            )
        days = sorted(expected_days if expected_days is not None else present)
        reports: list[dict[str, Any]] = []
        diffs: list[pl.DataFrame] = []
        for day in days:
            original = t.filter(pl.col("trade_date") == day)
            if day > LAST:
                sums = {}
                for name in ("vol", "oi", "amount"):
                    total = str(original[name].cast(pl.String).cast(NUMERIC).sum())
                    sums[name] = {"before": total, "after": total}
                reports.append(
                    {
                        "rule": RULE,
                        "dataset": "opt_daily",
                        "exchange": "CZCE",
                        "trade_date": day,
                        "status": "未经官方年度文件核对",
                        "rows": original.height,
                        "overridden_rows": 0,
                        "changes": dict.fromkeys(OVERLAY_FIELDS, 0),
                        "daily_totals": sums,
                        "manifest_sha256": self.manifest_sha256,
                    }
                )
                continue
            official = self.year(day[:4]).filter(pl.col("trade_date") == day)
            if official.is_empty():
                raise ValueError(f"Missing CZCE official trading day={day}")
            keys = set(original["ts_code"].to_list())
            expected = set(official["ts_code"].to_list())
            if keys != expected:
                raise ValueError(
                    f"CZCE contract sets differ day={day} missing={sorted(expected - keys)[:5]} "
                    f"extra={sorted(keys - expected)[:5]}"
                )
            left = original.with_columns(
                [pl.col(c).cast(pl.String).cast(NUMERIC, strict=True) for c in VALUE_FIELDS]
            )
            joined = left.join(
                official.select("ts_code", *VALUE_FIELDS),
                on="ts_code",
                how="inner",
                suffix="_official",
            )
            changes = {}
            fields = (*OVERLAY_FIELDS, *(("open", "high", "low") if day == PRICE_EXCEPTION else ()))
            for name in VALUE_FIELDS:
                changed = ~pl.col(name).eq_missing(pl.col(name + "_official"))
                count = joined.filter(changed).height
                if (
                    name in ASSERT_FIELDS
                    and not (day == PRICE_EXCEPTION and name in ("open", "high", "low"))
                    and count
                ):
                    samples = (
                        joined.filter(changed)
                        .select("ts_code", name, name + "_official")
                        .head(3)
                        .to_dicts()
                    )
                    raise ValueError(
                        f"CZCE price assertion failed day={day} field={name} "
                        f"rows={count} samples={samples}"
                    )
                if name in fields:
                    changes[name] = count
                    if count:
                        diffs.append(
                            joined.filter(changed).select(
                                pl.lit(day).alias("trade_date"),
                                "ts_code",
                                pl.lit(name).alias("field"),
                                pl.col(name).alias("before"),
                                pl.col(name + "_official").cast(NUMERIC).alias("after"),
                            )
                        )
            for name in fields:
                out[name] = out[name].astype(object)
                out.loc[joined["_source_index"].to_list(), name] = joined[
                    name + "_official"
                ].to_list()
            sums = {
                name: {
                    "before": str(joined[name].sum()),
                    "after": str(joined[name + "_official"].sum()),
                }
                for name in ("vol", "oi", "amount")
            }
            reports.append(
                {
                    "rule": RULE,
                    "dataset": "opt_daily",
                    "exchange": "CZCE",
                    "trade_date": day,
                    "status": "官方年度文件已核对",
                    "rows": original.height,
                    "overridden_rows": original.height,
                    "changes": changes,
                    "daily_totals": sums,
                    "manifest_sha256": self.manifest_sha256,
                    "official_year_sha256": self.manifest["years"][day[:4]]["parquet"]["sha256"],
                }
            )
        diff = (
            pl.concat(diffs)
            if diffs
            else pl.DataFrame(
                schema={
                    "trade_date": pl.String,
                    "ts_code": pl.String,
                    "field": pl.String,
                    "before": NUMERIC,
                    "after": NUMERIC,
                }
            )
        )
        return out, reports, diff.sort(["trade_date", "ts_code", "field"])


def parse_official_notice(warning: str, manifest_sha256: str) -> dict[str, Any] | None:
    """运行器只认可固定清单、固定字段和授权日期范围的结构化核对告警。"""
    if not warning.startswith(NOTICE):
        return None
    try:
        d = json.loads(warning[len(NOTICE) :])
        if (
            not isinstance(d, dict)
            or d.get("rule") != RULE
            or d.get("dataset") != "opt_daily"
            or d.get("exchange") != "CZCE"
            or d.get("manifest_sha256") != manifest_sha256
        ):
            return None
        day = d["trade_date"]
        if not isinstance(day, str) or not re.fullmatch(r"[0-9]{8}", day):
            return None
        date.fromisoformat(day[:4] + "-" + day[4:6] + "-" + day[6:])
        if not FIRST <= day <= "20261231" or type(d.get("rows")) is not int or d["rows"] <= 0:
            return None
        fields = set(OVERLAY_FIELDS) | (
            {"open", "high", "low"} if day == PRICE_EXCEPTION else set()
        )
        if (
            not isinstance(d.get("changes"), dict)
            or set(d["changes"]) != fields
            or any(type(v) is not int or not 0 <= v <= d["rows"] for v in d["changes"].values())
        ):
            return None
        if day <= LAST:
            if (
                d.get("status") != "官方年度文件已核对"
                or d.get("overridden_rows") != d["rows"]
                or not re.fullmatch(r"[a-f0-9]{64}", d.get("official_year_sha256", ""))
            ):
                return None
        elif (
            d.get("status") != "未经官方年度文件核对"
            or d.get("overridden_rows") != 0
            or any(d["changes"].values())
        ):
            return None
        totals = d.get("daily_totals")
        if not isinstance(totals, dict) or set(totals) != {"vol", "oi", "amount"}:
            return None
        from decimal import Decimal

        for item in totals.values():
            if not isinstance(item, dict) or set(item) != {"before", "after"}:
                return None
            if any(not isinstance(v, str) or not Decimal(v).is_finite() for v in item.values()):
                return None
        return d
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return None
