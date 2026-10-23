"""仅维护已核实的中航电测换码区间，不推断其他证券或北交所规则。"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash


SYMBOL_RULES_VERSION = "cn_stock_code_intervals_v1"
_RULES = {
    "version": SYMBOL_RULES_VERSION,
    "rules": [
        {
            "source": "tushare",
            "old_source_symbol": "300114.SZ",
            "new_source_symbol": "302132.SZ",
            "effective_date": "2025-02-17",
            "old_valid_to_exclusive": "2025-02-17",
            "new_valid_from_inclusive": "2025-02-17",
            "evidence_url": "https://static.cninfo.com.cn/finalpage/2025-02-15/1222544408.PDF",
            "evidence_date": "2025-02-15",
            "identity_basis": "same_legal_listed_entity",
        }
    ],
}


def symbol_rule_evidence() -> dict[str, Any]:
    """返回可冻结的版本化规则副本，调用者不能修改全局规则。"""
    return copy.deepcopy(_RULES)


def symbol_rule_hash() -> str:
    """规则正文的稳定语义哈希，作为新 raw 身份的一部分。"""
    return semantic_hash(_RULES)


def resolve_symbol_intervals(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """通过已有验证别名解析换码身份，不硬编码 instrument_id。

    没有涉及本规则的证券可返回空；出现新旧代码时，旧 Tushare 别名与新 canonical
    必须同一身份。其他历史别名不能沿用本条日期或凭 SDK 转换猜测有效期。
    """
    stocks = {int(row["instrument_id"]): row for row in snapshot["instruments"]}
    canonical = {row["symbol"]: iid for iid, row in stocks.items()}
    aliases: dict[str, int] = {}
    for row in snapshot["aliases"]:
        if row["source"] != "tushare":
            continue
        code, iid = row["source_symbol"], int(row["instrument_id"])
        if code in aliases and aliases[code] != iid:
            raise ContractViolationError("Conflicting stock identity aliases")
        aliases[code] = iid
    resolved = {}
    for rule in _RULES["rules"]:
        old, new = rule["old_source_symbol"], rule["new_source_symbol"]
        if not ({old, new} & (set(canonical) | set(aliases))):
            continue
        iid = canonical.get(new)
        if (
            iid is None
            or aliases.get(old) != iid
            or aliases.get(new, iid) != iid
            or canonical.get(old, iid) != iid
        ):
            raise ContractViolationError(
                "Verified stock code interval identity is missing or conflicting"
            )
        resolved[iid] = copy.deepcopy(rule)
    return resolved


def interval_source_symbol(
    instrument_id: int, canonical_symbol: str, day: str, rules: dict[int, dict[str, Any]]
) -> tuple[str, dict[str, Any] | None]:
    """返回当日唯一有效源代码；上市日不替代代码的生效日期。"""
    rule = rules.get(instrument_id)
    if rule is None:
        return canonical_symbol, None
    current = date.fromisoformat(day)
    effective = date.fromisoformat(rule["effective_date"])
    symbol = rule["old_source_symbol"] if current < effective else rule["new_source_symbol"]
    return symbol, copy.deepcopy(rule)
