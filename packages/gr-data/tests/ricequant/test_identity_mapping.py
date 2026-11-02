"""跨库 ID 重排、旧 ID 碰撞和严格映射门禁回归。"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from typing import cast

import psycopg
import pytest
from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash
from gr_data.ingest.ricequant.identity_mapping import IdentityMapping, build_mapping


def fixtures():
    coverage = [
        {"instrument_id": 1, "canonical_symbol": "600000.SH", "status": "included"},
        {"instrument_id": 2, "canonical_symbol": "000001.SZ", "status": "included"},
    ]
    old = [
        {
            "instrument_id": r["instrument_id"],
            "symbol": r["canonical_symbol"],
            "exchange": "XSHG" if r["canonical_symbol"].endswith(".SH") else "XSHE",
            "list_date": "2000-01-01",
            "delist_date": None,
        }
        for r in coverage
    ]
    manifest = {"coverage": coverage, "universe": {"reference": {"metadata": {"instruments": old}}}}
    # 旧 ID=1 在新库明确指向另一只证券，不能按相同整数串联。
    target = {
        "stocks": [
            {
                "id": 2,
                "symbol": "600000.SH",
                "exchange": "XSHG",
                "list_date": "1999-01-01",
                "delist_date": None,
            },
            {
                "id": 1,
                "symbol": "000001.SZ",
                "exchange": "XSHE",
                "list_date": "2000-01-01",
                "delist_date": None,
            },
        ],
        "aliases": [],
    }
    return manifest, target


class Connection:
    def __init__(self, target):
        self.target = target

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params):
        pass

    def fetchall(self):
        return [(r["id"], r["symbol"], r["exchange"]) for r in self.target["stocks"]]


def test_reordered_ids_and_collision_preserve_raw_and_dates(tmp_path):
    manifest, target = fixtures()
    original = copy.deepcopy(manifest)
    payload = build_mapping([manifest], target, source_check={"performed": False})
    path = tmp_path / "map.json"
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False))
    mapping = IdentityMapping(path, semantic_hash(payload))
    translated = mapping.translate(
        cast(psycopg.Connection, Connection(target)), manifest, manifest["coverage"]
    )
    assert [r["instrument_id"] for r in translated] == [2, 1]
    assert manifest == original
    assert len(payload["date_differences"]) == 1
    assert translated[0]["canonical_symbol"] == "600000.SH"
    assert translated[0]["status"] == manifest["coverage"][0]["status"]
    changed = copy.deepcopy(target)
    changed["stocks"][0]["symbol"] = "600999.SH"
    with pytest.raises(ContractViolationError, match="target identity"):
        mapping.translate(
            cast(psycopg.Connection, Connection(changed)), manifest, manifest["coverage"]
        )
    with pytest.raises(ContractViolationError, match="hash"):
        IdentityMapping(path, "0" * 64)


@pytest.mark.parametrize("defect", ["missing", "ambiguous", "merge", "exchange", "unmapped"])
def test_mapping_rejects_untrusted_identity(defect):
    manifest, target = fixtures()
    if defect == "missing":
        target["stocks"].pop()
    elif defect == "ambiguous":
        target["aliases"].append(["tushare", "600000.SH", 1])
    elif defect == "merge":
        target["stocks"].pop()
        target["aliases"].append(["tushare", "000001.SZ", 2])
    elif defect == "exchange":
        target["stocks"][0]["exchange"] = "XSHE"
    else:
        manifest["coverage"][0]["status"] = "unmapped_symbol"
        target["stocks"][0]["symbol"] = "600001.SH"
        target["aliases"].append(["tushare", "600000.SH", 2])
    with pytest.raises(ContractViolationError):
        build_mapping([manifest], target, source_check={"performed": False})
