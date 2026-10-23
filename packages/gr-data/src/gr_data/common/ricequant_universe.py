"""冻结证券身份与供应商边界；动态名单不使用当前状态筛历史。"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from datetime import date
from typing import Any

import psycopg

from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash
from gr_data.common.ricequant_symbol_intervals import (
    SYMBOL_RULES_VERSION,
    interval_source_symbol,
    resolve_symbol_intervals,
    symbol_rule_evidence,
    symbol_rule_hash,
)
from gr_data.config.ricequant_risk import (
    DYNAMIC_UNIVERSE_POLICY,
    MAPPING_VERSION,
    TUSHARE_UNIVERSE_POLICY,
)


def _obid(symbol: str) -> str | None:
    match = re.fullmatch(r"([0-9]{6})\.(SH|SZ)", symbol)
    if match is None:
        return None
    return f"{match[1]}.{'XSHG' if match[2] == 'SH' else 'XSHE'}"


def _b_share(code: str) -> bool:
    """显式沪深 B 股号段；不以交易所或 CS 类型代替 A 股范围。"""
    return bool(re.fullmatch(r"(?:200[0-9]{3}\.(?:SZ|XSHE)|900[0-9]{3}\.(?:SH|XSHG))", code))


def _day(value: Any) -> date | None:
    if value in (None, "", "0000-00-00"):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def load_metadata_snapshot(conn: psycopg.Connection) -> dict[str, Any]:
    """在调用方只读一致性事务内冻结全部沪深股票与两个供应商身份映射。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id,symbol,exchange,list_date,delist_date,status "
            "FROM meta.instruments WHERE asset='stock' AND exchange IN ('XSHG','XSHE') "
            "ORDER BY instrument_id"
        )
        columns = ("instrument_id", "symbol", "exchange", "list_date", "delist_date", "status")
        stocks = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
        cur.execute(
            "SELECT sm.source,sm.source_symbol,sm.instrument_id FROM meta.symbol_map sm "
            "JOIN meta.instruments i USING(instrument_id) WHERE i.asset='stock' "
            "AND i.exchange IN ('XSHG','XSHE') AND sm.source IN ('tushare','ricequant') "
            "ORDER BY sm.source,sm.source_symbol"
        )
        aliases = [
            dict(zip(("source", "source_symbol", "instrument_id"), row, strict=True))
            for row in cur.fetchall()
        ]
    for stock in stocks:
        for key in ("list_date", "delist_date"):
            stock[key] = str(stock[key]) if stock[key] is not None else None
    return {"instruments": stocks, "aliases": aliases}


def reference_input_codes(snapshot: dict[str, Any]) -> list[str]:
    """返回 canonical 及已验证别名的显式后缀转换集合。"""
    requestable_ids = {
        int(row["instrument_id"])
        for row in snapshot["instruments"]
        if _obid(row["symbol"]) is not None
    }
    codes = {_obid(row["symbol"]) for row in snapshot["instruments"]}
    codes.update(
        row["source_symbol"] if row["source"] == "ricequant" else _obid(row["source_symbol"])
        for row in snapshot["aliases"]
        if int(row["instrument_id"]) in requestable_ids
    )
    return sorted(
        code
        for code in codes
        if code is not None and re.fullmatch(r"[0-9]{6}\.(XSHG|XSHE)", code) and not _b_share(code)
    )


def build_universe_provider(
    snapshot: dict[str, Any],
    reference: dict[str, Any],
    *,
    universe_policy: str = DYNAMIC_UNIVERSE_POLICY,
    mapping_version: str | None = None,
    symbol_rules: dict[str, Any] | None = None,
) -> Callable[[str], dict[str, Any]]:
    """从冻结快照生成逐日名单，未知边界保留，冲突身份拒绝。

    listed_cn_a_v1 保留原米筐区间与双源对照算法，供旧 raw 原样重放。
    listed_cn_a_v2 先按 Tushare list_date <= day < delist_date 决定在市，
    再按唯一已验证换码规则选择代码；其余双源边界冲突保留为未知。
    无法安全生成请求代码的独立身份保留 unmapped_symbol，不剥前缀或猜换股。
    返回结构全部可 JSON 序列化，每次调用独立复制，避免跨日污染。
    """
    if universe_policy not in {DYNAMIC_UNIVERSE_POLICY, TUSHARE_UNIVERSE_POLICY}:
        raise ContractViolationError("Unknown historical universe policy")
    is_temporal = universe_policy == TUSHARE_UNIVERSE_POLICY
    expected_mapping = "alias_v2" if is_temporal else MAPPING_VERSION
    if mapping_version is not None and mapping_version != expected_mapping:
        raise ContractViolationError("Universe and mapping version mismatch")
    if is_temporal:
        if symbol_rules is not None and symbol_rules != symbol_rule_evidence():
            raise ContractViolationError("Unknown historical symbol interval rules")
    elif symbol_rules is not None:
        raise ContractViolationError("Legacy universe must not contain temporal symbol rules")
    snapshot, reference = copy.deepcopy(snapshot), copy.deepcopy(reference)
    temporal_rules = resolve_symbol_intervals(snapshot) if is_temporal else {}
    all_stocks = {int(row["instrument_id"]): row for row in snapshot["instruments"]}
    if len(all_stocks) != len(snapshot["instruments"]):
        raise ContractViolationError("Duplicate canonical universe")
    excluded = [row for row in all_stocks.values() if _b_share(row["symbol"])]
    stocks = {iid: row for iid, row in all_stocks.items() if not _b_share(row["symbol"])}
    if not stocks:
        raise ContractViolationError("Empty or duplicate canonical universe")
    lookup: dict[str, int] = {}
    inputs: dict[int, set[str]] = {iid: set() for iid in stocks}
    unrequestable: set[int] = set()
    source_ids: dict[tuple[str, str], int] = {}

    def remember_source(source: str, symbol: str, iid: int) -> None:
        key = (source, symbol)
        if key in source_ids and source_ids[key] != iid:
            raise ContractViolationError("Conflicting stock identity aliases")
        # canonical 股票采用 Tushare 完整代码。非六位历史代码也必须在两个命名空间
        # 中指向同一身份；逐日排除未来／退市证券之前检查，不剥前缀或缩成六位。
        peer = {"canonical": "tushare", "tushare": "canonical"}.get(source)
        if peer is not None and (peer, symbol) in source_ids and source_ids[peer, symbol] != iid:
            raise ContractViolationError("Conflicting stock identity aliases")
        source_ids[key] = iid

    def register(code: str | None, iid: int) -> None:
        if code is None or iid not in stocks:
            raise ContractViolationError("Invalid canonical stock mapping")
        if code in lookup and lookup[code] != iid:
            raise ContractViolationError("Conflicting stock identity aliases")
        lookup[code] = iid
        inputs[iid].add(code)

    for iid, stock in stocks.items():
        symbol, exchange = stock["symbol"], stock["exchange"]
        suffix = {"XSHG": ".SH", "XSHE": ".SZ"}.get(exchange)
        if suffix is None or not isinstance(symbol, str) or not symbol.endswith(suffix):
            raise ContractViolationError("Canonical stock exchange mismatch")
        remember_source("canonical", symbol, iid)
        code = _obid(symbol)
        if code is None:
            # 历史编码不是当前六位代码时，保留独立身份，不剥前缀、不猜换股关系。
            unrequestable.add(iid)
            inputs[iid].add(symbol)
        else:
            register(code, iid)
    for row in snapshot["aliases"]:
        iid = int(row["instrument_id"])
        if iid in all_stocks and iid not in stocks:
            continue
        if iid not in stocks or row["source"] not in {"ricequant", "tushare"}:
            raise ContractViolationError("Invalid canonical stock mapping")
        original = row["source_symbol"]
        remember_source(row["source"], original, iid)
        code = original if row["source"] == "ricequant" else _obid(original)
        if code in lookup and lookup[code] != iid:
            raise ContractViolationError("Conflicting stock identity aliases")
        if iid in unrequestable or code is None or not re.fullmatch(r"[0-9]{6}\.(XSHG|XSHE)", code):
            inputs[iid].add(original)
        else:
            register(code, iid)
    if is_temporal:
        for iid, codes in inputs.items():
            if iid in unrequestable:
                continue
            canonical_code = _obid(stocks[iid]["symbol"])
            rule = temporal_rules.get(iid)
            permitted = {canonical_code}
            if rule is not None:
                permitted.update(
                    {_obid(rule["old_source_symbol"]), _obid(rule["new_source_symbol"])}
                )
            if not codes <= permitted:
                raise ContractViolationError(
                    "Historical stock alias lacks a verified code interval"
                )
    mapped: dict[int, list[dict[str, Any]]] = {iid: [] for iid in stocks}
    unknown = []
    seen = set()
    excluded_reference = []
    for original in reference["instruments"]:
        row = {
            key: str(value) if value is not None else None
            for key, value in original.items()
            if key in {"order_book_id", "listed_date", "de_listed_date"}
        }
        code = row["order_book_id"]
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}\.(XSHG|XSHE)", code):
            continue  # 仅沪深范围；其他交易所不进入候选分母。
        if _b_share(code):
            excluded_reference.append(row)
            continue
        if code in seen:
            raise ContractViolationError("Duplicate reference stock code")
        seen.add(code)
        if code in lookup:
            mapped[lookup[code]].append(row)
        else:
            unknown.append(row)
    sdk_mapping = reference["sdk_mapping"]
    output_ids: dict[str, int] = {}
    for code, iid in lookup.items():
        output = sdk_mapping.get(code)
        if output is None:
            continue
        if not isinstance(output, str) or not re.fullmatch(r"[0-9]{6}\.(XSHG|XSHE)", output):
            raise ContractViolationError("Unsupported SDK stock mapping")
        if output in lookup and lookup[output] != iid:
            raise ContractViolationError("SDK stock mapping conflicts with canonical identity")
        if output in output_ids and output_ids[output] != iid:
            raise ContractViolationError("SDK stock mapping collapses distinct instruments")
        output_ids[output] = iid
    # 明确的 SDK 转换可以连接供应商当前代码与已验证 canonical 身份。
    remaining = []
    for row in unknown:
        iid = output_ids.get(row["order_book_id"])
        if iid is None:
            remaining.append(row)
        else:
            mapped[iid].append(row)
    metadata_hash = semantic_hash(snapshot)
    reference_info = {
        "snapshot_hash": semantic_hash(reference),
        "sdk_version": reference.get("sdk_version", "unknown"),
        "boundary_rule": "listed_date <= day < de_listed_date; 0000-00-00 means no delist",
        "alias_selection_rule": "canonical_preferred_if_multiple_accepted",
        "excluded_b_shares": {"canonical": excluded, "supplier": excluded_reference},
        "metadata": snapshot,
        "supplier_snapshot": reference,
    }

    if is_temporal:
        reference_info.update(
            boundary_rule=(
                "tushare.list_date <= day < tushare.delist_date; null means no recorded end"
            ),
            alias_selection_rule="verified_effective_date_unique_code",
            symbol_rules=symbol_rule_evidence(),
            symbol_rules_version=SYMBOL_RULES_VERSION,
            symbol_rules_hash=symbol_rule_hash(),
        )

    def provider(day: str) -> dict[str, Any]:
        current = date.fromisoformat(day)
        candidates = []
        unresolved = []
        for row in remaining:
            listed, delisted = _day(row.get("listed_date")), _day(row.get("de_listed_date"))
            if listed is not None and listed > current:
                continue
            if delisted is not None and current >= delisted:
                continue
            # 无 canonical 身份，与表内“身份已知但无请求代码”明确区分。
            unresolved.append({"status": "unresolved_identity", "evidence": row})
        for iid, stock in sorted(stocks.items()):
            refs = mapped[iid]
            ts_listed = _day(stock.get("list_date"))
            ts_delisted = _day(stock.get("delist_date"))
            intervals = {(row.get("listed_date"), row.get("de_listed_date")) for row in refs}
            status = None
            selected_symbol, interval_rule = (
                interval_source_symbol(iid, stock["symbol"], day, temporal_rules)
                if is_temporal
                else (stock["symbol"], None)
            )
            selected_code = _obid(selected_symbol)
            if is_temporal:
                valid_dates = ts_listed is not None and (
                    stock.get("delist_date") is None
                    or (ts_delisted is not None and ts_listed < ts_delisted)
                )
                if valid_dates and (
                    current < ts_listed or (ts_delisted is not None and current >= ts_delisted)
                ):
                    continue
                if iid in unrequestable:
                    status = "unmapped_symbol"
                elif not valid_dates or (stock.get("status") == "delisted" and ts_delisted is None):
                    status = "universe_boundary_unknown"
                else:
                    matching = [row for row in refs if row["order_book_id"] == selected_code]
                    if len(matching) != 1:
                        status = "universe_boundary_unknown"
                    else:
                        ref = matching[0]
                        rq_listed, rq_delisted = (
                            _day(ref.get("listed_date")),
                            _day(ref.get("de_listed_date")),
                        )
                        # 本条旧代码结束是换码边界，不是证券退市。其他差异仍显式留待检查。
                        old_code_end = (
                            interval_rule is not None
                            and selected_symbol == interval_rule["old_source_symbol"]
                        )
                        end_matches = rq_delisted == ts_delisted
                        if old_code_end:
                            end_matches = ref.get("de_listed_date") in (
                                "0000-00-00",
                                interval_rule["old_valid_to_exclusive"],
                            )
                        if (
                            rq_listed != ts_listed
                            or not end_matches
                            or (ref.get("de_listed_date") != "0000-00-00" and rq_delisted is None)
                        ):
                            status = "universe_boundary_unknown"
            elif iid in unrequestable:
                # 这里只排除确定在区间外的日子。退市当天保留，不猜退市日语义。
                valid_dates = ts_listed is not None and (
                    stock.get("delist_date") is None
                    or (ts_delisted is not None and ts_listed <= ts_delisted)
                )
                if valid_dates and (
                    current < ts_listed or (ts_delisted is not None and current > ts_delisted)
                ):
                    continue
                status = "unmapped_symbol"
            elif len(intervals) != 1:
                if not refs and ts_listed is not None and current < ts_listed:
                    continue
                status = "universe_boundary_unknown"
            else:
                listed_raw, delisted_raw = next(iter(intervals))
                listed, delisted = _day(listed_raw), _day(delisted_raw)
                valid = (
                    listed is not None
                    and (delisted_raw == "0000-00-00" or delisted is not None)
                    and (delisted is None or listed < delisted)
                )
                conflict = ts_listed is None or listed != ts_listed or delisted != ts_delisted
                if valid and ts_listed is not None and current < min(listed, ts_listed):
                    continue
                if (
                    valid
                    and delisted is not None
                    and ts_delisted is not None
                    and current > max(delisted, ts_delisted)
                ):
                    continue
                if valid and not conflict:
                    if current < listed or (delisted is not None and current >= delisted):
                        continue
                else:
                    status = "universe_boundary_unknown"
            accepted = {
                sdk_mapping.get(code) for code in inputs[iid] if lookup.get(code) == iid
            } - {None}
            if is_temporal:
                # SDK 接受另一时期的代码不是本日代码许可；不能静默跨过生效日期。
                request = (
                    selected_code
                    if selected_code is not None and sdk_mapping.get(selected_code) == selected_code
                    else None
                )
            elif len(accepted) > 1:
                # 已验证同一身份有多个有效源代码；显式优先 canonical，绝不双写。
                canonical = _obid(stock["symbol"])
                preferred = sdk_mapping.get(canonical)
                if preferred not in accepted:
                    raise ContractViolationError("Ambiguous SDK request alias")
                request = preferred
            else:
                request = next(iter(accepted), None)
            if status is None and request is None:
                status = "sdk_filtered"
            candidates.append(
                {
                    "instrument_id": iid,
                    "canonical_symbol": stock["symbol"],
                    "input_codes": sorted(inputs[iid]),
                    "request_code": request if status is None else None,
                    "status": status,
                    "evidence": {
                        **(
                            {
                                "symbol_interval": {
                                    **interval_rule,
                                    "selected_source_symbol": selected_symbol,
                                }
                            }
                            if is_temporal and interval_rule is not None
                            else {}
                        ),
                        "canonical": stock,
                        "supplier": refs,
                        "sdk_mapping": {
                            code: sdk_mapping.get(code) if lookup.get(code) == iid else None
                            for code in sorted(inputs[iid])
                        },
                    },
                }
            )
        return copy.deepcopy(
            {
                "day": day,
                "policy": universe_policy,
                "mapping_version": expected_mapping,
                "metadata_hash": metadata_hash,
                "candidates": candidates,
                "unresolved": unresolved,
                "reference": reference_info,
            }
        )

    return provider
