"""D-012：封闭的郑商所 2026-05-29 四十合约主数据补充及来源核验。"""

from __future__ import annotations

import io
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl

from gr_data.common.parquet import read_parquet_strict
from gr_data.common.paths import RawPaths
from gr_data.raw.czce.options import atomic_json, digest


DATASET = "option_metadata_supplement_v1"
RULE = "tushare_czce_metadata_20260529_v1"
NOTICE = "CZCE official metadata supplement "
FIRST = "20260529"
PREVIOUS = "20260528"
CALIBRATION_DAYS = (PREVIOUS, "20260605", "20260610")
STANDARD = r"^([A-Z]+[0-9]{3})([CP])([0-9]+(?:\.[0-9]+)?)\.ZCE$"
COPY_FIELDS = (
    "opt_code",
    "s_month",
    "maturity_date",
    "delist_date",
    "per_unit",
    "opt_multiplier",
    "opt_type",
    "exercise_type",
    "quote_unit",
    "min_price_chg",
    "last_edate",
    "last_ddate",
)
FIELDS = (
    "ts_code",
    "symbol",
    "exchange",
    "name",
    "per_unit",
    "opt_code",
    "opt_type",
    "call_put",
    "exercise_type",
    "exercise_price",
    "opt_multiplier",
    "s_month",
    "maturity_date",
    "list_price",
    "list_date",
    "delist_date",
    "last_edate",
    "last_ddate",
    "quote_unit",
    "min_price_chg",
)
PRICE_FIELDS = ("open", "high", "low", "close", "settle", "pre_settle", "vol", "oi", "amount")
NUMERIC_FIELDS = frozenset(("per_unit", "opt_multiplier", "exercise_price", "list_price"))
_DAILY_COLUMNS = {
    "合约代码": "ts_code",
    "品种代码": "ts_code",
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


def policy() -> dict[str, Any]:
    """读取随批准源码封存的精确清单及证据清单哈希，不推导额外代码。"""
    p = Path(__file__).with_name("evidence") / "option_metadata_20260529.v1.json"
    value = json.loads(p.read_text())
    if value.get("rule") != RULE or len(value.get("codes", [])) != 40:
        raise ValueError("Invalid approved CZCE metadata code registry")
    codes = value["codes"]
    if len(set(codes)) != 40 or any(re.fullmatch(STANDARD, c) is None for c in codes):
        raise ValueError("Invalid approved CZCE metadata code registry")
    return value


def approved_codes() -> frozenset[str]:
    """只返回登记的四十个完整源代码。"""
    return frozenset(policy()["codes"])


def parse_daily(path: Path, day: str) -> pd.DataFrame:
    """解析官方单日 TXT，保留价格／万元为 Decimal；仅排除显式统计行。

    原件不改。表头日期必须与请求日一致，月度 MS 合约保留原名供证据核对。
    非法代码、数值、重复主键、空文件均失败。
    """
    payload = path.read_bytes()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("gb18030")
    lines = text.splitlines()
    expected = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    if not lines or f"({expected})" not in lines[0]:
        raise ValueError(f"CZCE daily date mismatch day={day}")
    header = next((i for i, s in enumerate(lines) if "|" in s and "昨结算" in s), None)
    if header is None:
        raise ValueError("Missing CZCE daily header")
    frame = pl.read_csv(io.StringIO("\n".join(lines[header:])), separator="|", infer_schema=False)
    names = {c: _DAILY_COLUMNS[c.strip()] for c in frame.columns if c.strip() in _DAILY_COLUMNS}
    if set(names.values()) != {"ts_code", *PRICE_FIELDS} or len(names) != len(set(names.values())):
        raise ValueError("Invalid CZCE daily columns")
    frame = frame.select(list(names)).rename(names).with_columns(pl.all().str.strip_chars())
    frame = frame.filter(~pl.col("ts_code").str.contains(r"^(?:小计|总计|[A-Z]+合计)$"))
    if (
        frame.is_empty()
        or frame.filter(
            ~pl.col("ts_code").str.contains(r"^[A-Z]+[0-9]{3}(?:MS)?[CP][0-9]+(?:\.[0-9]+)?$")
        ).height
    ):
        raise ValueError("Invalid CZCE daily contract code")
    for field in PRICE_FIELDS:
        frame = frame.with_columns(
            pl.col(field)
            .str.replace_all(",", "")
            .replace(["", "--", "—", "-"], None)
            .cast(pl.Decimal(30, 10), strict=True)
            .alias(field)
        )
        if frame.filter(pl.col(field) < 0).height:
            raise ValueError(f"Invalid CZCE daily numeric field={field}")
    frame = frame.with_columns((pl.col("ts_code") + ".ZCE"), pl.lit(day).alias("trade_date"))
    if frame["ts_code"].is_duplicated().any():
        raise ValueError("Duplicate CZCE daily code")
    return frame.to_pandas()


def missing(value: object) -> bool:
    """标量缺失判断；仅在四十条补充及少量回测记录的边界使用。"""
    return bool(pd.Series([value], dtype=object).isna().iat[0])


def number(value: object) -> Decimal | None:
    """比较源数值，不舍入；缺失返回 None，非有限数值失败。"""
    if missing(value):
        return None
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError("Nonfinite CZCE metadata numeric")
    return parsed


def same(left: object, right: object) -> bool:
    """仅双方都缺失视为相等；其他值保持源字段逐值相等。"""
    if missing(left) or missing(right):
        return missing(left) and missing(right)
    return bool(left == right)


def calibrate_codes(reference: pd.DataFrame) -> int:
    """对全部 CZCE 标准格式主数据回测 C/P 与行权价，不套用于 MS 或其他格式。"""
    selected = reference.loc[
        reference["exchange"].eq("CZCE") & reference["ts_code"].str.fullmatch(STANDARD)
    ]
    if selected.empty:
        raise ValueError("No standard CZCE contracts for code calibration")
    frame = pl.from_pandas(selected[["ts_code", "call_put", "exercise_price"]])
    bad = frame.filter(
        (pl.col("ts_code").str.extract(STANDARD, 2) != pl.col("call_put"))
        | (
            pl.col("ts_code").str.extract(STANDARD, 3).cast(pl.Decimal(30, 10))
            != pl.col("exercise_price").cast(pl.String).cast(pl.Decimal(30, 10))
        )
        | pl.col("exercise_price").is_null()
        | pl.col("call_put").is_null()
    )
    if bad.height:
        raise ValueError(
            f"CZCE code calibration mismatch samples={bad['ts_code'].head(5).to_list()}"
        )
    return frame.height


def group_values(
    reference: pd.DataFrame, prefix: str, first: str, last: str
) -> tuple[dict[str, object], list[str]]:
    """仅选择标准格式且生命周期与已观察行情期间重叠的同前缀合约。

    所有复制字段逐值一致才返回；缺组、缺生命周期或任何冲突都失败，不猜年份。
    """
    selected = reference.loc[
        reference["exchange"].eq("CZCE")
        & reference["ts_code"].str.fullmatch(re.escape(prefix) + r"[CP][0-9]+(?:\.[0-9]+)?\.ZCE")
    ].copy()
    if not selected.empty:
        if selected[["list_date", "delist_date"]].isna().any().any():
            raise ValueError(f"Missing CZCE sibling lifecycle prefix={prefix}")
        listed = pd.to_datetime(selected["list_date"], format="%Y%m%d", errors="raise")
        expired = pd.to_datetime(selected["delist_date"], format="%Y%m%d", errors="raise")
        if expired.lt(listed).any():
            raise ValueError(f"Reversed CZCE sibling lifecycle prefix={prefix}")
        selected = selected.loc[listed.le(pd.Timestamp(last)) & expired.ge(pd.Timestamp(first))]
    if selected.empty:
        raise ValueError(f"Missing CZCE sibling contracts prefix={prefix}")
    values = {}
    for field in COPY_FIELDS:
        column = selected[field]
        value = column.iloc[0]
        if not (column.eq(value).fillna(False) | (column.isna() & pd.isna(value))).all():
            raise ValueError(f"Inconsistent CZCE sibling field prefix={prefix} field={field}")
        values[field] = None if pd.isna(value) else value
    return values, sorted(selected["ts_code"].tolist())


def derive(
    reference: pd.DataFrame,
    daily: dict[str, pd.DataFrame],
    observed: pd.DataFrame,
    codes: frozenset[str],
    evidence: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """从批准证据独立复算补充行和逐字段来源；任何前提不成立即失败。

    daily 包含挂牌前日、首日及三个基准价回测日。observed 是原始 Tushare
    行情证据，仅用实际首末行情确定同组生命周期，并逐值比对首日九字段。
    """
    checked = calibrate_codes(reference)
    price_checked = 0
    for day in CALIBRATION_DAYS:
        selected = reference.loc[reference["exchange"].eq("CZCE") & reference["list_date"].eq(day)]
        if selected.empty:
            raise ValueError(f"Missing CZCE list price calibration day={day}")
        official = daily[day].set_index("ts_code")
        for row in selected[["ts_code", "list_price"]].itertuples(index=False):
            if (
                row.ts_code not in official.index
                or number(row.list_price) is None
                or number(row.list_price) != number(official.at[row.ts_code, "pre_settle"])
            ):
                raise ValueError(
                    f"CZCE list price calibration mismatch code={row.ts_code} day={day}"
                )
            price_checked += 1
    previous = set(daily[PREVIOUS]["ts_code"])
    if previous & codes:
        raise ValueError(
            f"CZCE contract present before listing samples={sorted(previous & codes)[:5]}"
        )
    first_day = daily[FIRST].set_index("ts_code")
    if not codes <= set(first_day.index):
        raise ValueError("Missing approved CZCE first-day official contracts")
    rows = []
    group_counts = {}
    for code in sorted(codes):
        parsed = re.fullmatch(STANDARD, code)
        if parsed is None:
            raise ValueError(f"Nonstandard CZCE supplemental code={code}")
        prefix, call_put, strike = parsed.groups()
        trades = observed.loc[observed["ts_code"].eq(code)]
        if trades.empty or not trades["exchange"].eq("CZCE").all():
            raise ValueError(f"Missing approved CZCE observed prices code={code}")
        first, last = min(trades["trade_date"].astype(str)), max(trades["trade_date"].astype(str))
        if first != FIRST:
            raise ValueError(f"Invalid CZCE first observation code={code} first={first}")
        first_rows = trades.loc[trades["trade_date"].astype(str).eq(FIRST)]
        if len(first_rows) != 1:
            raise ValueError(f"Duplicate CZCE first-day observed prices code={code}")
        if number(first_day.at[code, "pre_settle"]) is None:
            raise ValueError(f"Missing CZCE first-day list price code={code}")
        for field in PRICE_FIELDS:
            if number(first_rows.iloc[0][field]) != number(first_day.at[code, field]):
                raise ValueError(f"CZCE first-day prices mismatch code={code} field={field}")
        copied, siblings = group_values(reference, prefix, first, last)
        group_counts[prefix] = len(siblings)
        sources: dict[str, object] = {
            field: {
                "kind": "tushare_sibling_consensus",
                "codes": siblings,
                "observed_range": [first, last],
                "sha256": evidence["reference"],
                "observed_evidence_sha256": evidence["observed"],
            }
            for field in COPY_FIELDS
        }
        for field in ("ts_code", "symbol", "exchange"):
            sources[field] = {"kind": "official_contract_code", "sha256": evidence[FIRST]}
        for field in ("call_put", "exercise_price"):
            sources[field] = {
                "kind": "calibrated_standard_code",
                "checked": checked,
                "reference_sha256": evidence["reference"],
            }
        sources["list_date"] = {
            "kind": "official_first_appearance",
            "previous_sha256": evidence[PREVIOUS],
            "sha256": evidence[FIRST],
        }
        sources["list_price"] = {
            "kind": "official_first_pre_settle",
            "sha256": evidence[FIRST],
            "calibration_rows": price_checked,
        }
        sources["name"] = {"kind": "user_authorized_null"}
        rows.append(
            {
                **copied,
                "ts_code": code,
                "symbol": code.removesuffix(".ZCE"),
                "exchange": "CZCE",
                "name": None,
                "call_put": call_put,
                "exercise_price": Decimal(strike),
                "list_date": FIRST,
                "list_price": first_day.at[code, "pre_settle"],
                "field_sources": json.dumps(sources, ensure_ascii=False, sort_keys=True),
            }
        )
    return pd.DataFrame(rows)[[*FIELDS, "field_sources"]], {
        "code_calibration_rows": checked,
        "list_price_calibration_rows": price_checked,
        "sibling_counts": group_counts,
        "supplement_rows": len(rows),
    }


class MetadataSupplement:
    """只读校验批准清单、原件及补充 Parquet，不改 Tushare 兼容文件。"""

    def __init__(self, paths: RawPaths) -> None:
        self.root = paths.dataset_dir("czce", DATASET)
        approved = policy()
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists() or digest(manifest_path) != approved["manifest_sha256"]:
            raise ValueError("Missing or changed approved CZCE metadata evidence manifest")
        self.manifest = json.loads(manifest_path.read_text())
        if self.manifest.get("rule") != RULE or set(self.manifest.get("codes", [])) != set(
            approved["codes"]
        ):
            raise ValueError("CZCE supplemental manifest code scope mismatch")
        for info in self.manifest["files"]:
            path = self.root / info["path"]
            if (
                not path.resolve().is_relative_to(self.root.resolve())
                or digest(path) != info["sha256"]
            ):
                raise ValueError("Changed CZCE supplemental evidence file")
        frame = read_parquet_strict(self.root / "metadata.parquet")
        if (
            frame is None
            or set(frame["ts_code"]) != set(approved["codes"])
            or frame["ts_code"].duplicated().any()
        ):
            raise ValueError("Invalid CZCE supplemental metadata rows")
        self.frame = frame
        reference = pd.read_parquet(self.root / "sources/tushare-basic-czce-all.parquet")
        daily = {
            day: parse_daily(self.root / f"sources/{day}/OptionDataDaily.txt", day)
            for day in {*CALIBRATION_DAYS, FIRST}
        }
        observed = pd.concat(
            [pd.read_parquet(self.root / name) for name in self.manifest["observed_files"]],
            ignore_index=True,
        )
        rebuilt, checks = derive(
            reference,
            daily,
            observed,
            frozenset(approved["codes"]),
            self.manifest["evidence_sha256"],
        )
        pd.testing.assert_frame_equal(self.frame, rebuilt, check_dtype=False, check_exact=True)
        if checks != self.manifest["validation"]:
            raise ValueError("CZCE supplemental calibration receipt mismatch")
        self.manifest_sha256 = digest(manifest_path)
        self.by_code = self.frame.set_index("ts_code", drop=False)

    def compare_tushare(self, frame: pd.DataFrame) -> None:
        """清单内供应商恢复行除 name/list_date 外须全部相等，采用供应商原行。"""
        for row in frame.loc[frame["ts_code"].isin(self.by_code.index)].to_dict("records"):
            code = row["ts_code"]
            for field in FIELDS:
                equal = (
                    number(row[field]) == number(self.by_code.at[code, field])
                    if field in NUMERIC_FIELDS and field in row
                    else field in row and same(row[field], self.by_code.at[code, field])
                )
                if field not in ("name", "list_date") and not equal:
                    raise ValueError(f"Restored CZCE metadata differs code={code} field={field}")

    def assert_siblings(self, frame: pd.DataFrame, code: str) -> None:
        """当前标的完整响应必须仍有同组证据，不能靠冻结补充值绕过缺组或冲突。"""
        sources = json.loads(str(self.by_code.at[code, "field_sources"]))
        first, last = sources["delist_date"]["observed_range"]
        prefix = re.fullmatch(STANDARD, code)
        assert prefix is not None
        values, _ = group_values(frame, prefix.group(1), first, last)
        for field in COPY_FIELDS:
            if not same(values[field], self.by_code.at[code, field]):
                raise ValueError(f"Current CZCE sibling differs code={code} field={field}")

    def merge(self, raw: pd.DataFrame) -> pd.DataFrame:
        """仅在 ingest 内合并缺失的补充行，已恢复行用原 Tushare 值。"""
        self.compare_tushare(raw)
        missing = self.frame.loc[~self.frame["ts_code"].isin(raw["ts_code"]), list(FIELDS)]
        return pd.concat([raw, missing], ignore_index=True) if not missing.empty else raw

    def reports(
        self, daily: pd.DataFrame, raw_metadata: pd.DataFrame, month: str
    ) -> list[dict[str, Any]]:
        """按实际行情月份、交易所和标的统计补齐身份，不把无行情的代码计入。"""
        codes = set(daily.loc[daily["exchange"].eq("CZCE"), "ts_code"]) & set(self.by_code.index)
        if not codes:
            return []
        real = set(raw_metadata["ts_code"])
        groups: dict[str, list[str]] = {}
        for code in sorted(codes):
            groups.setdefault(str(self.by_code.at[code, "opt_code"]), []).append(code)
        return [
            {
                "rule": RULE,
                "month": month,
                "exchange": "CZCE",
                "opt_code": underlying,
                "codes": [c for c in members if c not in real],
                "code_count": sum(c not in real for c in members),
                "samples": [c for c in members if c not in real][:5],
                "tushare_code_count": sum(c in real for c in members),
                "evidence_sha256": self.manifest["evidence_sha256"],
                "manifest_sha256": self.manifest_sha256,
            }
            for underlying, members in sorted(groups.items())
        ]

    def write_receipt(self, month: str, reports: list[dict[str, Any]]) -> None:
        """补充证据收据与 Tushare 原始观察分目录保存。"""
        atomic_json(
            self.root / "receipts" / f"{month}.json",
            {"rule": RULE, "month": month, "reports": reports},
        )


def parse_notice(value: str) -> dict[str, Any] | None:
    """后台队列只认可批准清单中、计数／样本／证据哈希均自洽的月度告警。"""
    if not value.startswith(NOTICE):
        return None
    try:
        report = json.loads(value[len(NOTICE) :])
        approved = policy()
        required = {
            "rule",
            "month",
            "exchange",
            "opt_code",
            "codes",
            "code_count",
            "samples",
            "tushare_code_count",
            "evidence_sha256",
            "manifest_sha256",
        }
        if not isinstance(report, dict) or set(report) != required:
            return None
        if (
            report["rule"] != RULE
            or report["exchange"] != "CZCE"
            or report["manifest_sha256"] != approved["manifest_sha256"]
            or report["evidence_sha256"] != approved["evidence_sha256"]
        ):
            return None
        if (
            not isinstance(report["month"], str)
            or re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", report["month"]) is None
        ):
            return None
        allowed = approved["groups"].get(report["opt_code"])
        codes = report["codes"]
        if (
            not allowed
            or not isinstance(codes, list)
            or any(not isinstance(c, str) for c in codes)
            or len(set(codes)) != len(codes)
            or codes != sorted(codes)
            or not set(codes) <= set(allowed)
        ):
            return None
        if (
            type(report["code_count"]) is not int
            or report["code_count"] != len(codes)
            or report["samples"] != codes[:5]
        ):
            return None
        restored = report["tushare_code_count"]
        if type(restored) is not int or not 0 <= restored <= len(allowed) - len(codes):
            return None
        return report
    except (ValueError, TypeError, KeyError):
        return None
