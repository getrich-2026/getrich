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


# 用户于 2026-11-02 批准；法律代码与供应商实际请求码分别记账。
APPROVED_HISTORY_SYMBOL_RULES_VERSION = "cn_stock_code_intervals_v3"
_PROVIDER_REQUEST_OVERRIDE = {
    "canonical_symbol": "601607.SH",
    "legal_old_source_symbol": "600849.SH",
    "legal_effective_date": "2010-03-05",
    "request_code": "601607.XSHG",
    "scope": "registered_same_identity_across_legal_code_periods",
    "announcement_url": "https://static.cninfo.com.cn/finalpage/2010-03-08/57663591.PDF",
    "announcement_sha256": "f51fea0d6a996ba4c8b9cae6e7551358460789933edf6278702cdf772d6be5ac",
    "probe_model": "v1",
    "probe_day": "2010-01-04",
    "probe_receipt_sha256": "2407bf19a5bb63ea705b2fb35ca088e04f3c70e50652af016edd7ce88f000f50",
    "suspension_does_not_remove_membership": True,
}
_DELIST_BOUNDARY_EXCEPTION = {
    "canonical_symbol": "600680.SH",
    "provider_symbol": "600680.XSHG",
    "list_date": "1993-10-18",
    "tushare_delist_date": "2019-05-23",
    "ricequant_delist_date": "2019-05-24",
    "boundary_day": "2019-05-23",
    "boundary_status": "universe_boundary_unknown",
    "boundary_request_code": None,
    "announcement_url": "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/2019-05-18/600680_20190518_2.pdf",
    "announcement_number": "临2019-036",
    "announcement_date": "2019-05-18",
    "evidence_basis": "official_cached_text_and_user_confirmed_dates",
    "original_pdf_downloaded": False,
    "approval_date": "2026-11-02",
}
_APPROVED_HISTORY_RULES = {
    "version": APPROVED_HISTORY_SYMBOL_RULES_VERSION,
    "rules": copy.deepcopy(_HISTORY_RULES["rules"]),
    "provider_request_overrides": [_PROVIDER_REQUEST_OVERRIDE],
    "delist_boundary_exceptions": [_DELIST_BOUNDARY_EXCEPTION],
}

# 2026-11-06 用户批准生产补数；只纳入原规则与两个已核实深圳换码。
# 不借此启用历史探测的上海请求码覆盖或退市边界例外。
PRODUCTION_SYMBOL_RULES_VERSION = "cn_stock_code_intervals_v4"
_PRODUCTION_RULES = {
    "version": PRODUCTION_SYMBOL_RULES_VERSION,
    "rules": copy.deepcopy(
        [
            *_RULES["rules"],
            *[
                rule
                for rule in _HISTORY_RULES["rules"]
                if rule["new_source_symbol"] in {"001872.SZ", "001914.SZ"}
            ],
        ]
    ),
}


def approved_provider_request_override() -> dict[str, Any]:
    """已批准的唯一请求码覆盖；不得推导其他代码或其他证券。"""
    return copy.deepcopy(_PROVIDER_REQUEST_OVERRIDE)


def approved_delist_boundary_exception() -> dict[str, Any]:
    """保留原公告下载失败事实，只适用于明确日期及完整证券身份。"""
    return copy.deepcopy(_DELIST_BOUNDARY_EXCEPTION)


def matches_approved_delist_sources(stock: dict[str, Any], refs: list[dict[str, Any]]) -> bool:
    """双源完整代码、上市日及两个结束日必须全部精确匹配。"""
    case = _DELIST_BOUNDARY_EXCEPTION
    return (
        stock.get("symbol") == case["canonical_symbol"]
        and stock.get("exchange") == "XSHG"
        and stock.get("list_date") == case["list_date"]
        and stock.get("delist_date") == case["tushare_delist_date"]
        and len(refs) == 1
        and refs[0]
        == {
            "order_book_id": case["provider_symbol"],
            "listed_date": case["list_date"],
            "de_listed_date": case["ricequant_delist_date"],
        }
    )


def approved_boundary_coverage(row: dict[str, Any], day: str, identity: dict[str, Any]) -> bool:
    """新 gate 唯一身份例外；旧 variant、错误日期或缺证据均不接受。"""
    evidence = row.get("evidence", {})
    return (
        identity.get("approved_history_raw") == "pre2024_v3"
        and identity.get("universe_policy") == "listed_cn_a_v2"
        and identity.get("mapping_version") == "alias_v2"
        and identity.get("symbol_rules_version") == APPROVED_HISTORY_SYMBOL_RULES_VERSION
        and identity.get("symbol_rules_hash")
        == symbol_rule_hash(APPROVED_HISTORY_SYMBOL_RULES_VERSION)
        and row.get("canonical_symbol") == "600680.SH"
        and day == _DELIST_BOUNDARY_EXCEPTION["boundary_day"]
        and row.get("status") == "universe_boundary_unknown"
        and row.get("request_code") is None
        and row.get("pieces")
        == dict.fromkeys(("exposure", "specific_return", "specific_risk"), False)
        and evidence.get("delist_boundary_exception") == _DELIST_BOUNDARY_EXCEPTION
        and matches_approved_delist_sources(
            evidence.get("canonical", {}), evidence.get("supplier", [])
        )
    )


def _rules(version: str) -> dict[str, Any]:
    if version == SYMBOL_RULES_VERSION:
        return _RULES
    if version == HISTORY_SYMBOL_RULES_VERSION:
        return _HISTORY_RULES
    if version == APPROVED_HISTORY_SYMBOL_RULES_VERSION:
        return _APPROVED_HISTORY_RULES
    if version == PRODUCTION_SYMBOL_RULES_VERSION:
        return _PRODUCTION_RULES
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
