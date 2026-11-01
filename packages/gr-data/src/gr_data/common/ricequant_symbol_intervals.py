"""冻结已核实的代码区间；新探测规则不改写旧 raw 所用规则。"""

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


HISTORY_SYMBOL_RULES_VERSION = "cn_stock_code_intervals_v2"
_HISTORY_RULES = {
    "version": HISTORY_SYMBOL_RULES_VERSION,
    "rules": [
        *_RULES["rules"],
        {
            "source": "tushare",
            "old_source_symbol": "600849.SH",
            "new_source_symbol": "601607.SH",
            "effective_date": "2010-03-05",
            "old_valid_to_exclusive": "2010-03-05",
            "new_valid_from_inclusive": "2010-03-05",
            "evidence_url": "https://static.sse.com.cn/cs/zhs/scfw/gg/ssgs/2011-03-09/601607_2010_n.pdf",
            "evidence_date": "2011-03-09",
            "identity_basis": "same_legal_listed_entity",
            "identity_evidence_url": "https://static.cninfo.com.cn/finalpage/2011-08-15/59816208.PDF",
            "identity_evidence_sha256": (
                "2163601ea876bcc39bec159baa230ed587fc211d78748df7e625349df65ccafe"
            ),
            "absorbed_symbols_not_aliases": ["600607.SH", "600842.SH"],
        },
        {
            "source": "tushare",
            "old_source_symbol": "601313.SH",
            "new_source_symbol": "601360.SH",
            "effective_date": "2018-02-28",
            "old_valid_to_exclusive": "2018-02-28",
            "new_valid_from_inclusive": "2018-02-28",
            "evidence_url": "https://static.cninfo.com.cn/finalpage/2018-02-28/1204434951.PDF",
            "evidence_sha256": "31101753d3032ed4f10961465e9a0c27487d43da8e11b65c073989e27aeed053",
            "evidence_date": "2018-02-28",
            "identity_basis": "same_legal_listed_entity",
        },
        {
            "source": "tushare",
            "old_source_symbol": "000022.SZ",
            "new_source_symbol": "001872.SZ",
            "effective_date": "2018-12-26",
            "old_valid_to_exclusive": "2018-12-26",
            "new_valid_from_inclusive": "2018-12-26",
            "evidence_url": "https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF",
            "evidence_date": "2018-12-26",
            "identity_basis": "same_legal_listed_entity",
        },
        {
            "source": "tushare",
            "old_source_symbol": "000043.SZ",
            "new_source_symbol": "001914.SZ",
            "effective_date": "2019-12-16",
            "old_valid_to_exclusive": "2019-12-16",
            "new_valid_from_inclusive": "2019-12-16",
            "evidence_url": "https://static.cninfo.com.cn/finalpage/2019-12-16/1207164397.PDF",
            "evidence_date": "2019-12-16",
            "identity_basis": "same_legal_listed_entity",
        },
    ],
}


def _rules(version: str) -> dict[str, Any]:
    if version == SYMBOL_RULES_VERSION:
        return _RULES
    if version == HISTORY_SYMBOL_RULES_VERSION:
        return _HISTORY_RULES
    raise ContractViolationError("Unknown historical symbol interval rules")


def symbol_rule_evidence(version: str = SYMBOL_RULES_VERSION) -> dict[str, Any]:
    """返回可冻结的版本化规则副本，调用者不能修改全局规则。"""
    return copy.deepcopy(_rules(version))


def symbol_rule_hash(version: str = SYMBOL_RULES_VERSION) -> str:
    """规则正文的稳定语义哈希，作为新 raw 身份的一部分。"""
    return semantic_hash(_rules(version))


def resolve_symbol_intervals(
    snapshot: dict[str, Any], version: str = SYMBOL_RULES_VERSION
) -> dict[int, dict[str, Any]]:
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
    for rule in _rules(version)["rules"]:
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
