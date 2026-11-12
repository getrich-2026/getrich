"""米筐历史参数与固定口径 Greeks：逐观察校验、正式身份重解析、同事务审计。

本模块不采集网络数据、不迁移、不提交事务，也不开放历史回测或交易用途。
每批建议不超过一万合约日；内存与批大小线性增长。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from gr_data.common import contracts
from gr_data.common.ownership import OwnershipManager


GREEK_FIELDS = ("iv", "delta", "gamma", "vega", "theta", "rho")
GREEK_METHOD = {
    "model_family": "BS",
    "model": "implied_forward",
    "price_type": "close",
    "frequency": "1d",
}
GREEK_UNITS = {
    "iv": "decimal annualized volatility",
    "delta": "per underlying price unit",
    "gamma": "delta per underlying price unit",
    "vega": "per absolute volatility 1.0",
    "theta": "per calendar year",
    "rho": "per absolute rate 1.0",
}
TERMS_RULE = "ricequant_option_terms_observation_v1"
GREEKS_RULE = "ricequant_option_greeks_history_v1"
MAP_RULE = "ricequant_option_history_identity_v1"
OBSERVATION_RULE = "ricequant_option_history_observation_v1"
SEED_GREEKS_RULE = "ricequant_option_greeks_fixed_bs_v1"
SEED_POLICY_SHA256 = "45ccf7bed69df174e75c2740bf5210ab14d06a5223a1b99f7285d526447bc85a"


class HistoryError(ValueError):
    """来源、身份、精度或不可变观察冲突，调用方须回滚当前批次。"""


class ExistingHistoryConflictError(HistoryError):
    """已有值与新观察不同；逐键留差异，不能覆盖，其他键可独立重验。"""

    def __init__(self, differences: list[dict[str, Any]]) -> None:
        self.differences = differences
        super().__init__("Existing option history observation conflicts; no overwrite")


@dataclass(frozen=True)
class Observation:
    """原始观察身份和可证实的观察时间；不推断历史发布时间。"""

    observation_id: str
    raw_sha256: str
    observed_at: datetime
    time_kind: str

    def __post_init__(self) -> None:
        if (
            not self.observation_id
            or not re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
            or self.time_kind not in {"archived_at", "response_completed_at"}
        ):
            raise HistoryError("Invalid option observation identity or timestamp")


def decimal_value(value: object, scale: int, *, exact: bool = False) -> Decimal:
    """按 DDL 量化有限数；参数只接受原始十进制或至多两 ULP 的 IEEE 噪声。"""
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation
        stored = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise HistoryError("Missing or nonfinite option value") from None
    if exact and number != stored:
        noise = Decimal(str(2 * math.ulp(value))) if isinstance(value, float) else Decimal(0)
        if abs(number - stored) > noise:
            raise HistoryError("Option parameter precision exceeds DDL")
    return stored


def _frame(frame: pd.DataFrame, fields: Sequence[str]) -> pd.DataFrame:
    result = frame.reset_index() if "order_book_id" not in frame.columns else frame.copy()
    if not {"order_book_id", "trading_date", *fields} <= set(result.columns):
        raise HistoryError("Option response lacks declared columns")
    dates = pd.to_datetime(result["trading_date"], errors="raise")
    if dates.isna().any() or (dates != dates.dt.normalize()).any():
        raise HistoryError("Invalid option daily event time")
    result["trading_date"] = dates.dt.date
    if result["order_book_id"].isna().any():
        raise HistoryError("Missing option source identity")
    result["order_book_id"] = result["order_book_id"].astype(str)
    if result.duplicated(["order_book_id", "trading_date"]).any():
        raise HistoryError("Option response has duplicate contract-day")
    return result


def _term_row(row: Mapping[str, Any], observation: Observation) -> dict[str, Any]:
    strike = decimal_value(row["strike_price"], 4, exact=True)
    multiplier = decimal_value(row["contract_multiplier"], 4, exact=True)
    code = row["product_name"]
    if min(strike, multiplier) <= 0 or max(strike, multiplier) >= Decimal("1e14"):
        raise HistoryError("Option parameter outside NUMERIC(18,4) range")
    if not isinstance(code, str) or not code or len(code) > 64:
        raise HistoryError("Invalid historical option trading code")
    return {
        "rq_code": row["order_book_id"],
        "trading_day": row["trading_date"],
        "strike": strike,
        "multiplier": multiplier,
        "trading_code": code,
        "source": "ricequant",
        "observation_id": observation.observation_id,
        "observed_at": observation.observed_at,
        "available_at": None,
    }


def prepare_terms(frame: pd.DataFrame, observation: Observation) -> list[dict[str, Any]]:
    """只转换接口实际返回日期；strike 为元／份、multiplier 为份／张。"""
    source = _frame(frame, ("strike_price", "contract_multiplier", "product_name"))
    return [
        _term_row({str(k): v for k, v in row.items()}, observation)
        for row in source.to_dict("records")
    ]


def prepare_term_candidates(
    frame: pd.DataFrame, observation: Observation
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """扩大回补时分离独立不合格日期；不补值，不把源 schema 或重复键异常降格。"""
    source = _frame(frame, ("strike_price", "contract_multiplier", "product_name"))
    valid, pending = [], []
    for raw_row in source.to_dict("records"):
        row = {str(k): v for k, v in raw_row.items()}
        try:
            valid.append(_term_row(row, observation))
        except HistoryError as exc:
            pending.append(
                {
                    "rq_code": row["order_book_id"],
                    "trading_day": row["trading_date"],
                    "reason": str(exc),
                    "raw_strike": str(row["strike_price"]),
                    "raw_multiplier": str(row["contract_multiplier"]),
                    "raw_trading_code": str(row["product_name"]),
                }
            )
    return valid, pending


def prepare_greeks(
    frame: pd.DataFrame,
    *,
    precision: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """保留来源 BS/implied_forward/close/1d 单位；不除以100或365。

    缺失、非有限、超精度或越界记录留待核实；不会为一般溢出自动置 NULL。
    不同独立合约日可继续处理，重复业务键则整批拒绝。
    """
    precision = precision or dict.fromkeys(GREEK_FIELDS, (12, 8))
    result, pending = [], []
    for row in _frame(frame, GREEK_FIELDS).to_dict("records"):
        item = {"rq_code": row["order_book_id"], "trading_day": row["trading_date"]}
        problems = []
        for field in GREEK_FIELDS:
            try:
                digits, scale = precision[field]
                item[field] = decimal_value(row[field], scale)
                if abs(item[field]) >= Decimal(10) ** (digits - scale):
                    raise HistoryError(f"NUMERIC({digits},{scale}) overflow")
                if field in {"iv", "gamma", "vega"} and item[field] < 0:
                    raise HistoryError("Negative nonnegative Greek")
                if field == "delta" and abs(item[field]) > 1:
                    raise HistoryError("Delta outside [-1,1]")
            except HistoryError as exc:
                problems.append(
                    {
                        **{k: item[k] for k in ("rq_code", "trading_day")},
                        "field": field,
                        "raw_value": str(row[field]),
                        "reason": str(exc),
                    }
                )
        if problems:
            pending.extend(problems)
        else:
            result.append({**item, "underlying_px": None, "source": "ricequant"})
    return result, pending


IDENTITY_QUERY = """
SELECT i.symbol,i.asset,i.exchange,i.list_date,i.delist_date,
       o.option_type,o.exercise_style,o.strike,o.multiplier,
       o.list_date AS option_list_date,o.last_trade_date,o.maturity_date,o.trading_code,
       u.symbol AS underlying_symbol,u.exchange AS underlying_exchange,u.asset AS underlying_asset,
       i.instrument_id
FROM meta.instruments i JOIN meta.option_contracts o USING(instrument_id)
JOIN meta.instruments u ON u.instrument_id=o.underlying_id
WHERE i.asset='option'
"""


def read_identities(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """读取目标库身份，不把数值 ID 带入跨库匹配键。"""
    cur = conn.execute(IDENTITY_QUERY)
    if cur.description is None:
        raise HistoryError("Missing option identity result description")
    return [
        dict(zip((d.name for d in cur.description), row, strict=True)) for row in cur.fetchall()
    ]


def _text_code(value: object) -> str:
    return str(value).upper().replace("-", "")


def reference_matches(canonical: Mapping[str, Any], reference: Mapping[str, Any]) -> bool:
    """核实当前快照中的生命周期、标的、方向、行权价和乘数；不推断别名。"""
    try:
        exchange = canonical["exchange"]
        equity = exchange in {"XSHG", "XSHE"}
        source_code = reference["order_book_id"] if equity else reference["trading_code"]
        target_code = canonical["symbol"].split(".")[0] if equity else canonical["trading_code"]
        underlying = canonical["underlying_symbol"]
        if canonical["underlying_exchange"] in {"XSHG", "XSHE"}:
            suffix = ".XSHG" if canonical["underlying_exchange"] == "XSHG" else ".XSHE"
            expected_underlying = underlying.rsplit(".", 1)[0] + suffix
        else:
            expected_underlying = underlying.rsplit(".", 1)[0]
        return all(
            (
                reference["type"] == "Option",
                reference["exchange"] == exchange,
                _text_code(source_code) == _text_code(target_code),
                reference["underlying_order_book_id"] == expected_underlying,
                reference["option_type"] == canonical["option_type"],
                {"A": "american", "E": "european"}.get(reference["exercise_type"])
                == canonical["exercise_style"],
                pd.Timestamp(reference["listed_date"]).date()
                == canonical["list_date"]
                == canonical["option_list_date"],
                pd.Timestamp(reference["de_listed_date"]).date()
                == canonical["delist_date"]
                == canonical["last_trade_date"],
                pd.Timestamp(reference["maturity_date"]).date() == canonical["maturity_date"],
                decimal_value(reference["strike_price"], 4, exact=True) == canonical["strike"],
                decimal_value(reference["contract_multiplier"], 4, exact=True)
                == canonical["multiplier"],
            )
        )
    except (KeyError, TypeError, ValueError):
        return False


def match_reference(
    identities: Sequence[dict[str, Any]], reference: pd.DataFrame
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """先用来源交易代码缩小候选，再逐字段核验；缺失或歧义只登记，不猜映射。"""
    lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for identity in identities:
        code = (
            identity["symbol"].split(".")[0]
            if identity["exchange"] in {"XSHG", "XSHE"}
            else identity["trading_code"]
        )
        lookup.setdefault((identity["exchange"], _text_code(code)), []).append(identity)
    matched, pending, blocked = {}, [], set()
    for raw_ref in reference.to_dict("records"):
        ref = {str(k): v for k, v in raw_ref.items()}
        rq_code = str(ref.get("order_book_id", ""))
        exchange = str(ref.get("exchange", ""))
        code = rq_code if exchange in {"XSHG", "XSHE"} else ref.get("trading_code")
        candidates = [
            v for v in lookup.get((exchange, _text_code(code)), []) if reference_matches(v, ref)
        ]
        if len(candidates) != 1 or rq_code in matched or rq_code in blocked:
            pending.append(
                {"rq_code": rq_code, "reason": "missing or ambiguous verified canonical identity"}
            )
            matched.pop(rq_code, None)
            blocked.add(rq_code)
        else:
            matched[rq_code] = {**candidates[0], "rq_code": rq_code, "reference": ref}
    reverse: dict[str, list[str]] = {}
    for code, item in matched.items():
        reverse.setdefault(item["symbol"], []).append(code)
    for codes in reverse.values():
        if len(codes) > 1:
            for code in codes:
                matched.pop(code)
                pending.append(
                    {"rq_code": code, "reason": "multiple source codes share canonical identity"}
                )
    return matched, pending


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


def verify_existing_greek_methods(
    conn: psycopg.Connection, existing: Sequence[tuple], month: str
) -> None:
    """已有键必须有同口径审计；数值相同不证明方法相同。"""
    if not existing:
        return
    wanted = {(row[0], row[1]) for row in existing}
    covered: set[tuple] = set()
    audits = conn.execute(
        "SELECT rule,detail FROM ops.data_quality_check WHERE rule=%s "
        "OR (rule=%s AND detail->>'month'=%s)",
        (SEED_GREEKS_RULE, GREEKS_RULE, month),
    ).fetchall()
    by_key = {(row[0], row[1]): row for row in existing}
    for rule, detail in audits:
        if rule == SEED_GREEKS_RULE:
            key = (detail.get("instrument_id"), pd.Timestamp(detail.get("trading_day")).date())
            if key not in wanted:
                continue
            if (
                {k: detail.get(k) for k in GREEK_METHOD} != GREEK_METHOD
                or detail.get("policy_sha256") != SEED_POLICY_SHA256
                or detail.get("units") != GREEK_UNITS
            ):
                raise HistoryError("Existing Greek seed method differs")
            actual = by_key[key]
            if actual[2] != "ricequant" or any(
                detail.get("stored_values", {}).get(field) is None
                or Decimal(str(detail["stored_values"][field])) != value
                for field, value in zip(GREEK_FIELDS, actual[3:], strict=True)
            ):
                raise HistoryError("Existing Greek seed stored-value evidence differs")
            covered.add(key)
        else:
            keys = {
                key
                for key in wanted
                if int(detail.get("key_masks", {}).get(str(key[0]), 0)) & (1 << (key[1].day - 1))
            }
            if keys and (
                detail.get("evidence", {}).get("method") != GREEK_METHOD
                or detail.get("units") != GREEK_UNITS
            ):
                raise HistoryError("Existing Greek batch method differs")
            covered.update(keys)
    if covered != wanted:
        raise HistoryError("Existing Greek lacks approved method provenance")


def write_batch(
    conn: psycopg.Connection,
    dataset: str,
    rows: Sequence[dict[str, Any]],
    observation: Observation,
    identities: Mapping[str, dict[str, Any]],
    *,
    evidence: Mapping[str, Any],
) -> dict[str, int]:
    """在调用方当前事务中写一批不可变记录、映射及审计；从不 commit。

    Args:
        conn: 当前目标库连接；由调用方提交或回滚。
        dataset: option_terms_1d 或 option_greeks_1d。
        rows: 已校验、单月、至多一万条的来源记录。
        observation: 与 raw 哈希绑定的真实观察。
        identities: 经米筐自身元数据核实的 canonical 身份，ID 将重新解析。
        evidence: 原始响应及方法证据；Greek 方法必须等于固定契约。

    Returns:
        实际新增记录、已有正确记录及新增映射数。

    Raises:
        HistoryError: 身份变化、精度、日期、重复键或已有值冲突。
    """
    if dataset not in {"option_terms_1d", "option_greeks_1d"} or not 0 < len(rows) <= 10000:
        raise HistoryError("Invalid option history batch")
    if len({r["trading_day"].strftime("%Y-%m") for r in rows}) != 1:
        raise HistoryError("Option history batch crosses month boundary")
    if dataset == "option_greeks_1d" and evidence.get("method") != GREEK_METHOD:
        raise HistoryError("Unapproved Greek method")
    for row in rows:
        if row.get("source") != "ricequant":
            raise HistoryError("Option history provider differs")
        if dataset == "option_terms_1d" and (
            row.get("observation_id") != observation.observation_id
            or row.get("observed_at") != observation.observed_at
            or row.get("available_at") is not None
        ):
            raise HistoryError("Option terms observation evidence differs")
        if dataset == "option_greeks_1d" and (
            row.get("underlying_px") is not None
            or any(
                not isinstance(row.get(field), Decimal)
                or not row[field].is_finite()
                or row[field] != row[field].quantize(Decimal("0.00000001"))
                for field in GREEK_FIELDS
            )
        ):
            raise HistoryError("Greek batch requires prepared finite values and source-only inputs")
    target = "meta.option_terms_1d" if dataset == "option_terms_1d" else "market.option_greeks_1d"
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("ricequant:" + target,))
    binding = {
        "dataset": dataset,
        "observation_id": observation.observation_id,
        "raw_sha256": observation.raw_sha256,
        "observed_at": observation.observed_at.isoformat(),
        "observation_time_kind": observation.time_kind,
        "evidence": dict(evidence),
    }
    observation_key = {"dataset": dataset, "observation_id": observation.observation_id}
    previous = conn.execute(
        "SELECT detail FROM ops.data_quality_check WHERE rule=%s AND detail @> %s",
        (OBSERVATION_RULE, Jsonb(observation_key)),
    ).fetchall()
    if previous and (len(previous) != 1 or previous[0][0] != binding):
        raise HistoryError("Immutable option observation evidence changed")
    if not previous:
        conn.execute(
            "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES(%s,'info',%s)",
            (OBSERVATION_RULE, Jsonb(binding)),
        )
    owner = OwnershipManager(conn)
    owner.check(target, "ricequant")
    if owner.owner(target) is None:
        conn.execute(
            "INSERT INTO ops.table_ownership(target,provider,channel) "
            "VALUES(%s,'ricequant','ingest') ON CONFLICT(target) DO NOTHING",
            (target,),
        )
        owner.check(target, "ricequant")
    codes = sorted({r["rq_code"] for r in rows})
    symbols = [identities[code]["symbol"] for code in codes]
    cur = conn.execute(IDENTITY_QUERY + " AND i.symbol=ANY(%s) FOR SHARE OF i,o,u", (symbols,))
    if cur.description is None:
        raise HistoryError("Missing current option identity result description")
    current = {
        r[0]: dict(zip((d.name for d in cur.description), r, strict=True)) for r in cur.fetchall()
    }
    resolved = {}
    for code in codes:
        identity = identities[code]
        actual = current.get(identity["symbol"])
        if actual is None or any(
            actual[k] != v
            for k, v in identity.items()
            if k not in {"instrument_id", "rq_code", "reference"}
        ):
            raise HistoryError(f"Canonical option identity changed code={code}")
        if not reference_matches(actual, identity["reference"]):
            raise HistoryError(f"Unverified own-source option identity code={code}")
        resolved[code] = actual["instrument_id"]
    mapped = dict(
        conn.execute(
            "SELECT source_symbol,instrument_id FROM meta.symbol_map WHERE source='ricequant' "
            "AND source_symbol=ANY(%s) FOR UPDATE",
            (codes,),
        ).fetchall()
    )
    inserted_maps = []
    for code, identity in resolved.items():
        if code in mapped and mapped[code] != identity:
            raise HistoryError(f"Conflicting existing option source map code={code}")
        inserted = conn.execute(
            "INSERT INTO meta.symbol_map(source,source_symbol,instrument_id) "
            "VALUES('ricequant',%s,%s) ON CONFLICT(source,source_symbol) DO NOTHING "
            "RETURNING instrument_id",
            (code, identity),
        ).fetchone()
        if inserted is not None:
            inserted_maps.append([code, identity])
        if conn.execute(
            "SELECT instrument_id FROM meta.symbol_map WHERE source='ricequant' "
            "AND source_symbol=%s",
            (code,),
        ).fetchone() != (identity,):
            raise HistoryError("Concurrent source mapping conflict")
    if dataset == "option_terms_1d":
        contract = contracts.OPTION_TERMS_1D
        keys = contract.conflict_keys
        columns = contract.columns
        rule = TERMS_RULE
    else:
        columns = ("instrument_id", "trading_day", *GREEK_FIELDS, "underlying_px", "source")
        keys = ("instrument_id", "trading_day")
        contract = contracts.TableContract("market", dataset, columns, keys)
        rule = GREEKS_RULE
    prepared = []
    for row in rows:
        identity = identities[row["rq_code"]]
        if not identity["list_date"] <= row["trading_day"] <= identity["last_trade_date"]:
            raise HistoryError("Option history outside contract lifecycle")
        prepared.append(
            tuple(resolved[row["rq_code"]] if k == "instrument_id" else row[k] for k in columns)
        )
    if len({tuple(r[columns.index(k)] for k in keys) for r in prepared}) != len(prepared):
        raise HistoryError("Duplicate canonical option history key")
    stage = "_rq_option_history"
    conn.execute(
        sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP").format(
            sql.Identifier(stage), sql.Identifier(*target.split("."))
        )
    )
    names = sql.SQL(",").join(map(sql.Identifier, columns))
    with (
        conn.cursor() as cursor,
        cursor.copy(sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(stage), names)) as cp,
    ):
        cp.set_types(
            [
                "int8"
                if k == "instrument_id"
                else "date"
                if k == "trading_day"
                else "timestamptz"
                if k in {"observed_at", "available_at"}
                else "text"
                if k in {"source", "trading_code", "observation_id"}
                else "numeric"
                for k in columns
            ]
        )
        for row in prepared:
            cp.write_row(row)
    join = sql.SQL(" AND ").join(
        sql.SQL("t.{}=s.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in keys
    )
    different = sql.SQL("ROW({}) IS DISTINCT FROM ROW({})").format(
        sql.SQL(",").join(sql.SQL("t.{}").format(sql.Identifier(k)) for k in columns),
        sql.SQL(",").join(sql.SQL("s.{}").format(sql.Identifier(k)) for k in columns),
    )
    conflict_query = sql.SQL("SELECT count(*) FROM {} t JOIN {} s ON {} WHERE {}").format(
        sql.Identifier(*target.split(".")), sql.Identifier(stage), join, different
    )
    if dataset == "option_greeks_1d":
        old = conn.execute(
            sql.SQL(
                "SELECT t.instrument_id,t.trading_day,t.source,{} FROM {} t JOIN {} s ON {}"
            ).format(
                sql.SQL(",").join(sql.SQL("t.{}").format(sql.Identifier(k)) for k in GREEK_FIELDS),
                sql.Identifier(*target.split(".")),
                sql.Identifier(stage),
                join,
            )
        ).fetchall()
        verify_existing_greek_methods(conn, old, rows[0]["trading_day"].strftime("%Y-%m"))
    conflicts = conn.execute(conflict_query).fetchone()
    if conflicts is None or conflicts[0]:
        if conflicts is None:
            raise HistoryError("Missing option conflict query result")
        pairs = conn.execute(
            sql.SQL("SELECT {},{} FROM {} t JOIN {} s ON {} WHERE {}").format(
                sql.SQL(",").join(sql.SQL("t.{}").format(sql.Identifier(k)) for k in columns),
                sql.SQL(",").join(sql.SQL("s.{}").format(sql.Identifier(k)) for k in columns),
                sql.Identifier(*target.split(".")),
                sql.Identifier(stage),
                join,
                different,
            )
        ).fetchall()
        reverse = {value: key for key, value in resolved.items()}
        differences = []
        for pair in pairs:
            old, new = (
                dict(zip(columns, pair[: len(columns)], strict=True)),
                dict(zip(columns, pair[len(columns) :], strict=True)),
            )
            differences.append(
                {
                    "rq_code": reverse[new["instrument_id"]],
                    "trading_day": new["trading_day"],
                    "old_values": {k: str(v) if v is not None else None for k, v in old.items()},
                    "new_values": {k: str(v) if v is not None else None for k, v in new.items()},
                }
            )
        raise ExistingHistoryConflictError(differences)
    added = conn.execute(
        sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT ({}) DO NOTHING").format(
            sql.Identifier(*target.split(".")),
            names,
            names,
            sql.Identifier(stage),
            sql.SQL(",").join(map(sql.Identifier, keys)),
        )
    ).rowcount
    conflicts = conn.execute(conflict_query).fetchone()
    if conflicts is None or conflicts[0]:
        raise HistoryError("Concurrent option history value conflict")
    actual = conn.execute(
        sql.SQL("SELECT {} FROM {} t JOIN {} s ON {}").format(
            sql.SQL(",").join(sql.SQL("t.{}").format(sql.Identifier(k)) for k in columns),
            sql.Identifier(*target.split(".")),
            sql.Identifier(stage),
            join,
        )
    ).fetchall()
    if sorted(actual, key=str) != sorted(prepared, key=str):
        raise HistoryError("Option history full field readback differs")
    detail = {
        "dataset": dataset,
        "observation_id": observation.observation_id,
        "raw_sha256": observation.raw_sha256,
        "observed_at": observation.observed_at.isoformat(),
        "observation_time_kind": observation.time_kind,
        "rows": len(rows),
        "month": rows[0]["trading_day"].strftime("%Y-%m"),
        "codes": codes[:5],
        "code_count": len(codes),
        "values_sha256": _digest(sorted(prepared, key=str)),
        "historical_available_at_unknown": True,
        "evidence": dict(evidence),
    }
    key_masks: dict[str, int] = {}
    for row in rows:
        key = str(resolved[row["rq_code"]])
        key_masks[key] = key_masks.get(key, 0) | (1 << (row["trading_day"].day - 1))
    detail["key_masks"] = key_masks
    if dataset == "option_greeks_1d":
        detail["units"] = GREEK_UNITS
        detail["underlying_px_reason"] = "Source API does not return the underlying price used"
    key = {
        "observation_id": observation.observation_id,
        "month": detail["month"],
        "values_sha256": detail["values_sha256"],
    }
    previous = conn.execute(
        "SELECT detail FROM ops.data_quality_check WHERE rule=%s AND detail @> %s",
        (rule, Jsonb(key)),
    ).fetchall()
    if previous and (len(previous) != 1 or previous[0][0] != detail):
        raise HistoryError("Immutable option batch audit changed")
    conn.execute(
        "INSERT INTO ops.data_quality_check(rule,severity,detail) SELECT %s,'info',%s "
        "WHERE NOT EXISTS(SELECT 1 FROM ops.data_quality_check WHERE rule=%s AND detail @> %s)",
        (rule, Jsonb(detail), rule, Jsonb(key)),
    )
    if inserted_maps:
        map_detail = {
            "dataset": dataset,
            "observation_id": observation.observation_id,
            "raw_sha256": observation.raw_sha256,
            "mappings": inserted_maps,
            "reference_sha256": evidence.get("reference_sha256"),
        }
        conn.execute(
            "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES(%s,'info',%s)",
            (MAP_RULE, Jsonb(map_detail)),
        )
    conn.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(stage)))
    return {"inserted": added, "unchanged": len(rows) - added, "maps_inserted": len(inserted_maps)}
