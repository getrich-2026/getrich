"""日更两阶段发布的可选回放与全收益基准证据包处理（批次 B2）。

阶段 A（只读）：核验分红全历史原件、全市场退市名录原件与全收益基准原件，
冻结原件拷贝与内容哈希进 artifact；
阶段 B（单外层事务）：在签收之前完成归属校验、分红/退市/基准写入，
并在签收后按数据库事实构造当日 ``available_options.replay`` 与 ``benchmarks``。
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import polars as pl
import psycopg

from gr_data.common.benchmark import benchmark_version
from gr_data.common.replay_evidence import DIVIDEND_SIGNATURE_SQL
from gr_data.ingest.tushare.replay_actions import (
    import_actions,
    import_admitted_delistings,
    normalize_actions,
    read_delisting_coverage,
    read_dividend_coverage,
)
from gr_data.ingest.tushare.total_return import (
    TOTAL_RETURN_SYMBOLS,
    import_total_return,
    index_simple_returns,
)

from .evidence import file_hash


REPLAY_MANIFEST_VERSION = "pa12-local-v1"


def _copy_with_receipt(src: Path, dest_dir: Path) -> tuple[Path, str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    shutil.copy2(src, dst)
    receipt = src.with_suffix(".coverage.json")
    if receipt.exists():
        shutil.copy2(receipt, dst.with_suffix(".coverage.json"))
    return dst, file_hash(dst)


def prepare_replay_bundle(
    conn: psycopg.Connection,
    bundle_dir: Path,
    *,
    artifact: Path,
    day: date,
    symbol_ids: Mapping[str, int],
) -> dict[str, Any]:
    """阶段 A 只读核验回放证据包并将冻结副本写入 ``artifact/replay``。

    期望 ``bundle_dir`` 含：
    - 一份退市名录 ``stock_basic_delisted.parquet``（或 ``delisted*.parquet``）
      及其 ``.coverage.json``；
    - 一份或多份分红原件 ``dividend_*.parquet`` 及 ``.coverage.json``；
    - 可选全收益基准 ``index_daily_*.parquet`` 与 ``trade_cal_SSE.parquet``。
    """
    if not bundle_dir.is_dir():
        raise ValueError(f"Replay bundle directory does not exist: {bundle_dir}")

    delist_candidates = sorted(
        p
        for p in bundle_dir.glob("*.parquet")
        if p.name.startswith(("stock_basic_delisted", "delisted"))
    )
    if len(delist_candidates) != 1:
        raise ValueError(
            f"Replay bundle requires exactly 1 delisting parquet, found {len(delist_candidates)}"
        )
    delist_src = delist_candidates[0]
    delist_bytes = delist_src.read_bytes()
    delist_frame = pl.read_parquet(BytesIO(delist_bytes))
    delist_sha = sha256(delist_bytes).hexdigest()
    delist_observed = read_delisting_coverage(delist_src, delist_frame, delist_sha)
    delist_rows = normalize_actions(delist_frame, "stock_basic")
    raw_delist_by_symbol = {sym: str(dt) for sym, dt in delist_rows}

    div_sources = sorted(bundle_dir.glob("dividend_*.parquet"))
    if not div_sources:
        raise ValueError(f"Replay bundle contains no dividend_*.parquet files: {bundle_dir}")

    replay_dir = artifact / "replay"
    delist_dst, _ = _copy_with_receipt(delist_src, replay_dir)

    dividends_meta: list[dict[str, Any]] = []
    seen_div_ids: set[int] = set()
    through_dates: list[date] = []
    delist_dates_meta: dict[str, str | None] = {}

    for div_src in div_sources:
        content = div_src.read_bytes()
        frame = pl.read_parquet(BytesIO(content))
        digest = sha256(content).hexdigest()
        symbol, through, observed = read_dividend_coverage(div_src, frame, digest)
        if through < day:
            raise ValueError(
                f"Dividend coverage for {symbol} ends on {through}, before target day {day}"
            )
        normalize_actions(frame, "dividend")
        iid = symbol_ids.get(symbol)
        if iid is None:
            # 兜底查库内已存在映射（如研究/历史标的）
            row = conn.execute(
                "SELECT instrument_id FROM meta.symbol_map "
                "WHERE source='tushare' AND source_symbol=%s",
                (symbol,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Replay bundle dividend symbol not mapped in DB: {symbol}")
            iid = int(row[0])
        if iid in seen_div_ids:
            raise ValueError(f"Duplicate dividend file for instrument_id={iid} ({symbol})")
        seen_div_ids.add(iid)
        through_dates.append(through)
        div_dst, _ = _copy_with_receipt(div_src, replay_dir)
        dividends_meta.append(
            {
                "instrument_id": iid,
                "symbol": symbol,
                "file": div_dst.relative_to(artifact).as_posix(),
                "receipt_file": div_dst.with_suffix(".coverage.json")
                .relative_to(artifact)
                .as_posix(),
                "sha256": digest,
                "receipt_sha256": file_hash(div_dst.with_suffix(".coverage.json")),
                "through_date": str(through),
                "observed_at": observed.isoformat(),
            }
        )
        # 完整退市名录中查无该已核实代码才可记为 None
        delist_dates_meta[str(iid)] = raw_delist_by_symbol.get(symbol)

    benchmarks_meta: list[dict[str, Any]] = []
    bench_sources = sorted(bundle_dir.glob("index_daily_*.parquet"))
    if bench_sources:
        cal_src = bundle_dir / "trade_cal_SSE.parquet"
        if not cal_src.exists():
            raise ValueError("Replay bundle with benchmark files requires trade_cal_SSE.parquet")
        cal_dst, cal_sha = _copy_with_receipt(cal_src, replay_dir)
        cal_frame = pl.read_parquet(cal_src)
        for bench_src in bench_sources:
            bench_frame = pl.read_parquet(bench_src)
            symbol, returns = index_simple_returns(bench_frame, cal_frame)
            if symbol not in TOTAL_RETURN_SYMBOLS:
                raise ValueError(f"Unsupported benchmark symbol in replay bundle: {symbol}")
            if max(returns) < day:
                raise ValueError(
                    f"Benchmark {symbol} ends on {max(returns)}, before target day {day}"
                )
            version = benchmark_version(symbol, returns)
            row = conn.execute(
                """
                SELECT i.instrument_id FROM meta.symbol_map s
                JOIN meta.instruments i USING (instrument_id)
                WHERE s.source = 'tushare' AND s.source_symbol = %s
                  AND i.asset = 'index' AND i.exchange = 'CSI' AND i.symbol = %s
                """,
                (symbol, symbol),
            ).fetchone()
            if row is None:
                raise ValueError(f"Missing admitted Tushare index identity: {symbol}")
            bench_dst, bench_sha = _copy_with_receipt(bench_src, replay_dir)
            benchmarks_meta.append(
                {
                    "instrument_id": int(row[0]),
                    "symbol": symbol,
                    "version": version,
                    "file": bench_dst.relative_to(artifact).as_posix(),
                    "sha256": bench_sha,
                    "calendar_file": cal_dst.relative_to(artifact).as_posix(),
                    "calendar_sha256": cal_sha,
                    "max_date": str(max(returns)),
                    "return_count": len(returns),
                }
            )

    return {
        "version": REPLAY_MANIFEST_VERSION,
        "through_date": str(min(through_dates)),
        "delisting": {
            "file": delist_dst.relative_to(artifact).as_posix(),
            "receipt_file": delist_dst.with_suffix(".coverage.json")
            .relative_to(artifact)
            .as_posix(),
            "sha256": delist_sha,
            "receipt_sha256": file_hash(delist_dst.with_suffix(".coverage.json")),
            "observed_at": delist_observed.isoformat(),
        },
        "dividends": sorted(dividends_meta, key=lambda x: x["instrument_id"]),
        "delist_dates": dict(sorted(delist_dates_meta.items(), key=lambda kv: int(kv[0]))),
        "benchmarks": sorted(benchmarks_meta, key=lambda x: x["instrument_id"]),
    }


def verify_frozen_replay_files(artifact: Path, replay_meta: Mapping[str, Any]) -> None:
    """阶段 B 装载校验：确保 ``artifact/replay`` 内全部冻结文件与 ``prepared.json`` 哈希一致。"""
    root = artifact.resolve()

    def _check(rel: str, expected_sha: str) -> None:
        path = (artifact / rel).resolve()
        if not path.is_relative_to(root) or not path.exists() or file_hash(path) != expected_sha:
            raise ValueError(f"Replay artifact file checksum mismatch: {rel}")

    delist = replay_meta["delisting"]
    _check(delist["file"], delist["sha256"])
    _check(delist["receipt_file"], delist["receipt_sha256"])
    for item in replay_meta.get("dividends") or ():
        _check(item["file"], item["sha256"])
        _check(item["receipt_file"], item["receipt_sha256"])
    for item in replay_meta.get("benchmarks") or ():
        _check(item["file"], item["sha256"])
        _check(item["calendar_file"], item["calendar_sha256"])


def reverify_existing_benchmarks(
    conn: psycopg.Connection,
    previous_benchmarks: list[dict[str, Any]] | None,
    *,
    day: date,
) -> list[dict[str, Any]]:
    """沿用旧版基准前重新核对身份、整版内容哈希与当日覆盖；不满足者不沿用。"""
    verified: list[dict[str, Any]] = []
    for item in previous_benchmarks or ():
        iid = item.get("instrument_id")
        symbol = item.get("symbol")
        version = item.get("version")
        if not isinstance(iid, int) or not isinstance(symbol, str) or not isinstance(version, str):
            continue
        rows = conn.execute(
            """
            SELECT b.dt, b.simple_return FROM market.index_total_return_1d b
            JOIN meta.instruments i ON i.instrument_id = b.instrument_id
            WHERE b.instrument_id = %s AND b.version = %s AND b.source = 'tushare'
              AND i.symbol = %s
            ORDER BY b.dt
            """,
            (iid, version, symbol),
        ).fetchall()
        if not rows:
            continue
        values = {r[0]: float(r[1]) for r in rows}
        if max(values) < day:
            continue
        if benchmark_version(symbol, values) != version:
            continue
        verified.append({"instrument_id": iid, "symbol": symbol, "version": version})
    return verified


def apply_replay_bundle(
    conn: psycopg.Connection,
    artifact: Path,
    replay_meta: Mapping[str, Any],
    *,
    day: date,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """阶段 B 在外层事务内导入回放原件，并返回待写入 ``available_options`` 的回放与基准清单。"""
    verify_frozen_replay_files(artifact, replay_meta)

    delist_path = artifact / replay_meta["delisting"]["file"]
    delist_audit_path = artifact / "replay" / "delisting_audit.json"
    delist_result = import_admitted_delistings(conn, delist_path, audit_path=delist_audit_path)
    delist_sha = str(replay_meta["delisting"]["sha256"])
    if delist_result["raw_sha256"] != delist_sha:
        raise ValueError("Delisting observation SHA-256 mismatch during apply")

    dividend_sha256: dict[str, str] = {}
    dividend_signatures: dict[str, list[Any]] = {}
    delist_dates: dict[str, str | None] = {}

    for item in replay_meta["dividends"]:
        div_path = artifact / item["file"]
        symbol = str(item["symbol"])
        iid = int(item["instrument_id"])
        expected_sha = str(item["sha256"])
        import_actions(conn, div_path, "dividend", symbols={symbol})
        sig_row = conn.execute(DIVIDEND_SIGNATURE_SQL, (iid, expected_sha)).fetchone()
        if sig_row is None:
            raise ValueError(f"Failed to compute dividend signature for {symbol} ({iid})")
        dividend_sha256[str(iid)] = expected_sha
        dividend_signatures[str(iid)] = [int(sig_row[0]), str(sig_row[1])]
        expected_delist = replay_meta["delist_dates"].get(str(iid))
        actual_delist = delist_result["delisted_by_id"].get(str(iid))
        if expected_delist != actual_delist:
            raise ValueError(
                f"Delisting date mismatch for {symbol} ({iid}): "
                f"prepared={expected_delist}, persisted={actual_delist}"
            )
        delist_dates[str(iid)] = actual_delist

    benchmarks_manifest: list[dict[str, Any]] = []
    for item in replay_meta.get("benchmarks") or ():
        bench_path = artifact / item["file"]
        cal_path = artifact / item["calendar_file"]
        symbol, version, _count = import_total_return(conn, bench_path, cal_path)
        if symbol != item["symbol"] or version != item["version"]:
            raise ValueError(
                f"Benchmark mismatch during apply for {item['symbol']}: "
                f"expected={item['version']}, actual={version}"
            )
        benchmarks_manifest.append(
            {
                "instrument_id": int(item["instrument_id"]),
                "symbol": symbol,
                "version": version,
            }
        )

    through = date.fromisoformat(str(replay_meta["through_date"]))
    if through < day:
        raise ValueError(f"Replay bundle through_date {through} precedes publication day {day}")

    replay_manifest = {
        "version": str(replay_meta["version"]),
        "through_date": str(through),
        "delisting_sha256": delist_sha,
        "dividend_sha256": dividend_sha256,
        "dividend_signatures": dividend_signatures,
        "delist_dates": delist_dates,
    }
    return replay_manifest, benchmarks_manifest, delist_result
