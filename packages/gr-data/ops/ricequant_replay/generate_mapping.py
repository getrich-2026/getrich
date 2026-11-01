"""按已验收账本独立生成跨库映射；只读目标库与 raw，不采集、不入库。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
from gr_data.common.ricequant_specs import ContractViolationError, semantic_hash
from gr_data.config.settings import load_postgres, make_pg_dsn
from gr_data.ingest.ricequant.identity_mapping import build_mapping, stock_snapshot
from gr_tools.config import load_environment


def selected_manifests(
    ledger_root: Path,
    raw: Path,
    source: dict[int, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """逐观察核对原始账本哈希，修复日只选择已验收的替代观察。"""
    ledger = json.loads((ledger_root / "ledger.json").read_text())
    baseline = json.loads((ledger_root / "baseline.json").read_text())
    for job in [*baseline["jobs"], *ledger["jobs"].values()]:
        evidence = job["import_evidence"]
        partition = evidence["capture_checkpoint"]["partition_key"]
        path = raw / "ricequant/rq_risk_model/v2" / partition / "manifest.json"
        manifest = json.loads(path.read_text())
        if semantic_hash(manifest) != evidence["manifest_hash"]:
            raise ValueError("Ledger manifest hash mismatch")
        if source is not None:
            for row in manifest["coverage"]:
                if source.get(row["instrument_id"]) != row["canonical_symbol"]:
                    raise ContractViolationError("Source database ID/code differs from manifest")
        yield manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-env-file", type=Path)
    args = parser.parse_args()
    env = load_environment(env_file=args.env_file)
    target = load_postgres(env)
    source = None
    source_check = {"performed": False, "reason": "No independent source endpoint configured"}
    if args.source_env_file is not None:
        old = load_postgres(load_environment(env_file=args.source_env_file, environ={}))
        if (old.host, old.port, old.database) == (target.host, target.port, target.database):
            source_check["reason"] = (
                "Source-disk configuration resolves to current working database endpoint; "
                "original source database not independently reachable"
            )
        else:
            try:
                with psycopg.connect(make_pg_dsn(old), connect_timeout=5) as source_conn:
                    source_conn.execute("SET TRANSACTION READ ONLY")
                    source = {r["id"]: r["symbol"] for r in stock_snapshot(source_conn)["stocks"]}
                source_check = {"performed": True, "reason": "Source ID/code checked"}
            except psycopg.Error as exc:
                source_check["reason"] = "Source connection failed: " + type(exc).__name__
    source_check["manifest_metadata_checked"] = True
    with psycopg.connect(make_pg_dsn(target)) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        snapshot = stock_snapshot(conn)
        mapping = build_mapping(
            selected_manifests(args.ledger_root, args.raw_root, source),
            snapshot,
            source_check=source_check,
        )
    exclusion = args.ledger_root / "acceptance/old-run-publication-exclusion.json"
    mapping["publication_exclusion"] = {
        "record": json.loads(exclusion.read_text()),
        "source_file_sha256": hashlib.sha256(exclusion.read_bytes()).hexdigest(),
    }
    with args.output.open("x") as out:
        json.dump(mapping, out, sort_keys=True, separators=(",", ":"), allow_nan=False)
    print(
        json.dumps(
            {
                "sha256": semantic_hash(mapping),
                "entries": len(mapping["entries"]),
                "observations": len(mapping["manifest_hashes"]),
                "date_differences": len(mapping["date_differences"]),
            }
        )
    )


if __name__ == "__main__":
    main()
