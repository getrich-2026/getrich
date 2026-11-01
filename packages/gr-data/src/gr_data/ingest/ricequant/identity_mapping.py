"""跨库证券身份映射：先独立生成并冻结，导入只消费显式校验的文件。"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import psycopg

from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash


def stock_snapshot(conn: psycopg.Connection) -> dict[str, Any]:
    """读取完整代码、交易所、上市日期和已有别名；不新增别名。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id,symbol,exchange,list_date,delist_date "
            "FROM meta.instruments WHERE asset='stock' ORDER BY instrument_id"
        )
        stocks = [
            dict(
                zip(
                    ("id", "symbol", "exchange", "list_date", "delist_date"),
                    (i, s, e, str(ld) if ld else None, str(dd) if dd else None),
                    strict=True,
                )
            )
            for i, s, e, ld, dd in cur.fetchall()
        ]
        cur.execute(
            "SELECT source,source_symbol,instrument_id FROM meta.symbol_map "
            "WHERE source IN ('tushare','ricequant') ORDER BY source,source_symbol"
        )
        aliases = [list(row) for row in cur.fetchall()]
    return {"stocks": stocks, "aliases": aliases}


def build_mapping(
    manifests: Iterable[dict[str, Any]], target: dict[str, Any], *, source_check: dict[str, Any]
) -> dict[str, Any]:
    """从冻结 manifest 和目标身份快照生成一一映射；日期差异仅审计。

    缺失、歧义、交易所冲突、源 ID 合并或拆分均拒绝。源库可用性核对由调用方
    独立完成并留证，不能把源 ID 当目标 ID 使用。
    """
    stocks = {r["id"]: r for r in target["stocks"]}
    lookup: dict[str, set[int]] = {}
    for r in stocks.values():
        lookup.setdefault(r["symbol"], set()).add(r["id"])
    for _source, symbol, identity in target["aliases"]:
        if identity in stocks:
            lookup.setdefault(symbol, set()).add(identity)
    entries: dict[tuple[int, str], dict[str, Any]] = {}
    forward: dict[int, int] = {}
    reverse: dict[int, int] = {}
    dates = []
    hashes = []
    for manifest in manifests:
        digest = semantic_hash(manifest)
        hashes.append(digest)
        seen: set[int] = set()
        metadata = {
            r["instrument_id"]: r
            for r in manifest["universe"]["reference"]["metadata"]["instruments"]
        }
        for row in manifest["coverage"]:
            source, symbol = row["instrument_id"], row["canonical_symbol"]
            candidates = lookup.get(symbol, set())
            if len(candidates) != 1:
                raise ContractViolationError(
                    f"Cross-database identity missing or ambiguous: {symbol}"
                )
            identity = next(iter(candidates))
            dest = stocks[identity]
            exchange = (
                "XSHG" if symbol.endswith(".SH") else "XSHE" if symbol.endswith(".SZ") else None
            )
            if exchange is None or dest["exchange"] != exchange:
                raise ContractViolationError("Cross-database identity exchange conflict")
            if row["status"] == "unmapped_symbol" and dest["symbol"] != symbol:
                raise ContractViolationError("Unmapped symbol requires exact canonical identity")
            if (
                source in forward
                and forward[source] != identity
                or identity in reverse
                and reverse[identity] != source
                or identity in seen
            ):
                raise ContractViolationError("Cross-database identity must be one-to-one")
            forward[source], reverse[identity] = identity, source
            seen.add(identity)
            entries[(source, symbol)] = {
                "source_id": source,
                "canonical_symbol": symbol,
                "target_id": identity,
                "target_symbol": dest["symbol"],
                "exchange": exchange,
            }
            old = metadata[source]
            if old["symbol"] != symbol or old["exchange"] != exchange:
                raise ContractViolationError("Source snapshot identity conflicts with coverage")
            if (old.get("list_date"), old.get("delist_date")) != (
                dest["list_date"],
                dest["delist_date"],
            ):
                dates.append(
                    {
                        "manifest_hash": digest,
                        "source_id": source,
                        "canonical_symbol": symbol,
                        "source_list_date": old.get("list_date"),
                        "source_delist_date": old.get("delist_date"),
                        "target_list_date": dest["list_date"],
                        "target_delist_date": dest["delist_date"],
                    }
                )
    return {
        "schema_version": 1,
        "source_check": source_check,
        "manifest_hashes": sorted(set(hashes)),
        "entries": [entries[k] for k in sorted(entries)],
        "date_differences": dates,
    }


class IdentityMapping:
    """带外 SHA-256 校验的映射；每个交易事务内再次核对目标身份。"""

    def __init__(self, path: Path, expected_hash: str):
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ContractViolationError("Cross-database identity mapping file hash mismatch")
        self.payload = json.loads(raw)
        self.digest = semantic_hash(self.payload)
        if self.digest != expected_hash or self.payload.get("schema_version") != 1:
            raise ContractViolationError("Cross-database identity mapping hash or version mismatch")
        forward: dict[int, int] = {}
        reverse: dict[int, int] = {}
        for row in self.payload["entries"]:
            source, target = row["source_id"], row["target_id"]
            if (
                type(source) is not int
                or type(target) is not int
                or min(source, target) <= 0
                or source in forward
                and forward[source] != target
                or target in reverse
                and reverse[target] != source
            ):
                raise ContractViolationError("Cross-database identity must be one-to-one")
            forward[source], reverse[target] = target, source
        self.path = str(path.resolve())

    @property
    def evidence(self) -> dict[str, Any]:
        return {
            "sha256": self.digest,
            "path": self.path,
            "source_check": self.payload["source_check"],
        }

    def translate(
        self, conn: psycopg.Connection, manifest: dict[str, Any], coverage: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """验证原始观察和一一映射后，仅转换写库 ID，不修改 raw 或名单。"""
        if semantic_hash(self.payload) != self.digest:
            raise ContractViolationError("Cross-database identity mapping mutated")
        if semantic_hash(manifest) not in self.payload["manifest_hashes"]:
            raise ContractViolationError("Cross-database mapping does not cover manifest")
        rows = self.payload["entries"]
        index = {(r["source_id"], r["canonical_symbol"]): r for r in rows}
        if len(index) != len(rows):
            raise ContractViolationError("Duplicate cross-database mapping entry")
        result = copy.deepcopy(coverage)
        targets, sources = set(), set()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT instrument_id, symbol, exchange FROM meta.instruments "
                "WHERE asset = 'stock' AND instrument_id = ANY(%s) FOR SHARE",
                ([r["target_id"] for r in rows],),
            )
            stored = {r[0]: r[1:] for r in cur.fetchall()}
        for row in result:
            source = row["instrument_id"]
            mapped = index.get((source, row["canonical_symbol"]))
            if mapped is None or stored.get(mapped["target_id"]) != (
                mapped["target_symbol"],
                mapped["exchange"],
            ):
                raise ContractViolationError("Cross-database target identity changed or missing")
            identity = mapped["target_id"]
            if identity in targets or source in sources:
                raise ContractViolationError("Cross-database identity must be one-to-one")
            if (
                row["status"] == "unmapped_symbol"
                and mapped["target_symbol"] != row["canonical_symbol"]
            ):
                raise ContractViolationError("Unmapped symbol requires exact canonical identity")
            targets.add(identity)
            sources.add(source)
            row["instrument_id"] = identity
        return result
