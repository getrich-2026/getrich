"""从 Tushare 原始 Parquet 导入实施分红与退市截断依据。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import polars as pl
import psycopg
from psycopg import sql

from gr_data.common.dates import int_to_date, to_int_date
from gr_data.common.ownership import OwnershipManager
from gr_data.ingest.tushare.stock_scope import B_SHARE_EXCEPTIONS, B_SHARE_PATTERN


_B_SHARE_RE = re.compile(B_SHARE_PATTERN)
# Tushare dividend.div_proc 已核实的非实施进度（均未产生除权除息或派息执行）。
_NON_IMPLEMENTED_DIV_PROCS = frozenset(
    {"预案", "预披露", "股东大会通过", "股东提议", "停止实施", "股东大会未通过"}
)


def _is_b_share_code(code: str) -> bool:
    return bool(_B_SHARE_RE.fullmatch(code)) or code in B_SHARE_EXCEPTIONS


def _day(value: object) -> date | None:
    if value is None:
        return None
    raw = str(value)
    if len(raw) != 8 or not raw.isascii() or not raw.isdigit():
        raise ValueError(f"Invalid Tushare date: {raw}")
    return int_to_date(to_int_date(raw))


def _ratio(value: object) -> Decimal | None:
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("Invalid distribution amount")
    return number


def normalize_actions(
    frame: pl.DataFrame, dataset: Literal["dividend", "stock_basic"]
) -> list[tuple]:
    """保留已实施方案或退市记录，合并经济条款完全一致的重复公告。"""
    events: dict[tuple, tuple] = {}
    announced: dict[tuple, date | None] = {}
    for raw in frame.iter_rows(named=True):
        symbol = raw["ts_code"]
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("Missing source symbol")
        if dataset == "dividend":
            if raw["div_proc"] != "实施":
                if raw["div_proc"] not in _NON_IMPLEMENTED_DIV_PROCS:
                    raise ValueError(f"Unknown dividend progress: {raw['div_proc']}")
                continue
            key = (symbol, _day(raw["end_date"]), _day(raw["imp_ann_date"]))
            values = tuple(
                _day(raw[col]) for col in ("record_date", "ex_date", "pay_date", "div_listdate")
            ) + (_ratio(raw["cash_div_tax"]), _ratio(raw["stk_div"]))
            # 同一报告期、同一除息日却有两个实施公告，可能是修订稿；
            # 单凭当前快照无法区分两次分配与公告更正，不能相加。
            ex_date = values[1]
            if ex_date is not None:
                payment = (symbol, key[1], ex_date)
                if payment in announced and announced[payment] != key[2]:
                    raise ValueError(f"Conflicting implementation announcements: {payment}")
                announced[payment] = key[2]
        elif dataset == "stock_basic":
            if raw["list_status"] != "D":
                raise ValueError("Expected a delisted stock_basic observation")
            key = (symbol, _day(raw["delist_date"]))
            values = ()
        else:
            raise ValueError("Unknown replay dataset")
        if None in key or (key in events and events[key] != values):
            raise ValueError(f"Ambiguous replay action: {key}")
        events[key] = values
    return [key + values for key, values in events.items()]


def _coverage_receipt(
    path: Path, frame: pl.DataFrame, digest: str, dataset: str, scope: str
) -> tuple[dict, datetime]:
    proof = json.loads(path.with_suffix(".coverage.json").read_bytes())
    observed = datetime.fromisoformat(proof["observed_at"])
    if (
        proof["version"] != 1
        or proof["source"] != "tushare"
        or proof["dataset"] != dataset
        or proof["scope"] != scope
        or proof["rows"] != frame.height
        or proof["empty_page_offset"] != frame.height
        or proof["sha256"] != digest
        or observed.utcoffset() is None
        or observed > datetime.now(timezone.utc)
    ):
        raise ValueError(f"Invalid full-history observation for {dataset}")
    return proof, observed


def read_dividend_coverage(
    path: Path, frame: pl.DataFrame, digest: str
) -> tuple[str, date, datetime]:
    """核对整股查询直到空页的收据；当日未结束，覆盖只到上海的前一日。"""
    proof, observed = _coverage_receipt(path, frame, digest, "dividend", "symbol_full_history")
    symbol = proof["symbol"]
    if (
        not isinstance(symbol, str)
        or not symbol
        or (frame.height and set(frame["ts_code"]) != {symbol})
    ):
        raise ValueError("Invalid full-history dividend symbol")
    through = observed.astimezone(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    return symbol, through, observed


def read_delisting_coverage(path: Path, frame: pl.DataFrame, digest: str) -> datetime:
    """核对 stock_basic(D) 全集；只有完整查询才能作为代码不在退市名录的依据。"""
    proof, observed = _coverage_receipt(path, frame, digest, "stock_basic", "all_delisted")
    if (
        proof["list_status"] != "D"
        or frame.is_empty()
        or set(frame["list_status"]) != {"D"}
        or frame["ts_code"].null_count()
        or frame["ts_code"].n_unique() != frame.height
        or frame["delist_date"].null_count()
    ):
        raise ValueError("Invalid full-history delisted universe")
    return observed


def import_actions(
    conn: psycopg.Connection,
    path: Path,
    dataset: Literal["dividend", "stock_basic"],
    *,
    symbols: set[str] | None = None,
) -> int:
    """事务内校验来源归属及完整映射，再写入所选标的的原始观察。"""
    content = path.read_bytes()
    frame = pl.read_parquet(BytesIO(content))
    digest = sha256(content).hexdigest()
    coverage = read_dividend_coverage(path, frame, digest) if dataset == "dividend" else None
    if dataset == "stock_basic":
        read_delisting_coverage(path, frame, digest)
    if symbols is not None and coverage is not None and symbols != {coverage[0]}:
        raise ValueError("Requested symbols differ from full-history observation")
    if symbols is not None and coverage is None:
        frame = frame.filter(pl.col("ts_code").is_in(sorted(symbols)))
        if set(frame["ts_code"].to_list()) != symbols:
            raise ValueError("Requested symbols missing from raw observation")
    rows = normalize_actions(frame, dataset)
    if dataset == "dividend":
        schema, table = "finance", "dividend"
        keys = ("instrument_id", "period_end", "implementation_date")
        data = (
            "record_date",
            "ex_date",
            "pay_date",
            "share_listing_date",
            "cash_per_share",
            "shares_per_share",
        )
    else:
        schema, table = "market", "stock_delisting"
        keys = ("instrument_id", "delist_date")
        data = ()
    cols = (*keys, *data, "source", "raw_sha256")
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO NOTHING").format(
        sql.Identifier(schema, table),
        sql.SQL(",").join(map(sql.Identifier, cols)),
        sql.SQL(",").join(sql.Placeholder() for _ in cols),
        sql.SQL(",").join(map(sql.Identifier, (*keys, "raw_sha256"))),
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("LOCK TABLE ops.table_ownership IN SHARE ROW EXCLUSIVE MODE")
        ownership = OwnershipManager(conn)
        targets = [f"{schema}.{table}"]
        if coverage:
            targets.append("finance.dividend_coverage")
        for target in targets:
            if ownership.owner(target) is None:
                ownership.claim(target, "tushare")
            else:
                ownership.check(target, "tushare")
        names = {r[0] for r in rows}
        if coverage:
            names.add(coverage[0])
        cur.execute(
            "SELECT source_symbol,instrument_id FROM meta.symbol_map "
            "WHERE source='tushare' AND source_symbol=ANY(%s)",
            (sorted(names),),
        )
        ids = dict(cur.fetchall())
        if names - ids.keys():
            raise ValueError(f"Unmapped Tushare symbols: {sorted(names - ids.keys())}")
        if coverage:
            symbol, through, observed = coverage
            cur.execute(
                """INSERT INTO finance.dividend_coverage
                (instrument_id, through_date, observed_at, source, raw_sha256)
                VALUES (%s, %s, %s, 'tushare', %s)
                ON CONFLICT (instrument_id,raw_sha256) DO UPDATE SET
                  through_date=EXCLUDED.through_date, observed_at=EXCLUDED.observed_at
                WHERE finance.dividend_coverage.observed_at < EXCLUDED.observed_at""",
                (ids[symbol], through, observed, digest),
            )
        cur.executemany(stmt, [(ids[r[0]], *r[1:], "tushare", digest) for r in rows])
    return len(rows)


def import_admitted_delistings(
    conn: psycopg.Connection,
    path: Path,
    *,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """核验完整退市全集并仅将已映射沪深 A 股退市记录写入 ``market.stock_delisting``。

    保留原件整份 SHA-256 与分页完整性证明；按 ``meta.symbol_map`` + ``meta.instruments``
    与 B 股排除规则分流范围外与未映射项并留证。若可写行数为 0 则拒绝开放回放。
    """
    content = path.read_bytes()
    frame = pl.read_parquet(BytesIO(content))
    digest = sha256(content).hexdigest()
    observed = read_delisting_coverage(path, frame, digest)
    rows = normalize_actions(frame, "stock_basic")

    admitted_rows: list[tuple[int, date]] = []
    delisted_by_id: dict[int, str] = {}
    out_of_scope: list[dict[str, str]] = []
    unmapped: list[dict[str, str]] = []

    with conn.transaction(), conn.cursor() as cur:
        cur.execute("LOCK TABLE ops.table_ownership IN SHARE ROW EXCLUSIVE MODE")
        ownership = OwnershipManager(conn)
        target = "market.stock_delisting"
        if ownership.owner(target) is None:
            ownership.claim(target, "tushare")
        else:
            ownership.check(target, "tushare")

        source_symbols = sorted({r[0] for r in rows})
        cur.execute(
            """
            SELECT s.source_symbol, i.instrument_id, i.asset, i.exchange, i.delist_date
            FROM meta.symbol_map s
            JOIN meta.instruments i ON i.instrument_id = s.instrument_id
            WHERE s.source = 'tushare' AND s.source_symbol = ANY(%s)
            """,
            (source_symbols,),
        )
        mapped: dict[str, list[tuple[int, str, str, date | None]]] = {}
        for src_sym, iid, asset, exchange, meta_delist in cur.fetchall():
            mapped.setdefault(str(src_sym), []).append(
                (int(iid), str(asset), str(exchange), meta_delist)
            )

        for src_sym, delist_dt in rows:
            if _is_b_share_code(src_sym):
                out_of_scope.append(
                    {"symbol": src_sym, "delist_date": str(delist_dt), "reason": "b_share"}
                )
                continue
            if not src_sym.endswith((".SH", ".SZ")):
                out_of_scope.append(
                    {
                        "symbol": src_sym,
                        "delist_date": str(delist_dt),
                        "reason": "unsupported_exchange",
                    }
                )
                continue
            matches = mapped.get(src_sym) or []
            if not matches:
                unmapped.append(
                    {"symbol": src_sym, "delist_date": str(delist_dt), "reason": "unmapped_symbol"}
                )
                continue
            if len(matches) > 1:
                raise ValueError(f"Ambiguous Tushare symbol mapping for delisting: {src_sym}")
            iid, asset, exchange, meta_delist = matches[0]
            if asset != "stock" or exchange not in {"XSHG", "XSHE"}:
                out_of_scope.append(
                    {
                        "symbol": src_sym,
                        "delist_date": str(delist_dt),
                        "reason": f"non_cn_a_stock:{asset}:{exchange}",
                    }
                )
                continue
            if meta_delist is not None and meta_delist != delist_dt:
                raise ValueError(
                    f"Conflicting delisting date for {src_sym}: meta={meta_delist}, raw={delist_dt}"
                )
            if iid in delisted_by_id and delisted_by_id[iid] != str(delist_dt):
                raise ValueError(f"Conflicting delisting dates mapped to instrument_id={iid}")
            delisted_by_id[iid] = str(delist_dt)
            admitted_rows.append((iid, delist_dt))

        if not admitted_rows:
            raise ValueError(
                "No admitted CN-A delisted stocks can be written from delisting observation"
            )

        cur.executemany(
            """
            INSERT INTO market.stock_delisting (instrument_id, delist_date, source, raw_sha256)
            VALUES (%s, %s, 'tushare', %s)
            ON CONFLICT (instrument_id, delist_date, raw_sha256) DO NOTHING
            """,
            [(iid, delist_dt, digest) for iid, delist_dt in admitted_rows],
        )
        cur.execute(
            "SELECT count(*) FROM market.stock_delisting WHERE raw_sha256 = %s",
            (digest,),
        )
        verified_row = cur.fetchone()
        verified_count = int(verified_row[0]) if verified_row else 0
        if verified_count < 1:
            raise ValueError("Failed to verify persisted delisting row for observation SHA-256")

    summary: dict[str, Any] = {
        "raw_sha256": digest,
        "observed_at": observed.isoformat(),
        "total_rows": len(rows),
        "admitted_count": len(delisted_by_id),
        "verified_db_rows": verified_count,
        "out_of_scope_count": len(out_of_scope),
        "unmapped_count": len(unmapped),
        "delisted_by_id": {str(k): v for k, v in sorted(delisted_by_id.items())},
    }
    if audit_path is not None:
        audit_payload = {
            **{k: v for k, v in summary.items() if k != "delisted_by_id"},
            "out_of_scope": out_of_scope,
            "unmapped": unmapped,
        }
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit_payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return summary


def main() -> None:
    """从一个明确指定的原始观察导入，可重复传 --symbol 限定测试标的。"""
    import argparse

    from gr_tools.config import load_environment

    from gr_data.config import load_postgres, make_pg_dsn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=("dividend", "stock_basic"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--symbol", action="append")
    args = parser.parse_args()
    with psycopg.connect(make_pg_dsn(load_postgres(load_environment()))) as conn:
        count = import_actions(
            conn, args.path, args.dataset, symbols=set(args.symbol) if args.symbol else None
        )
    print(f"Imported {count} actions")


if __name__ == "__main__":
    main()
