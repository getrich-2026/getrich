"""申万一级行业目标截面；保留来源区间，不宣称历史 PIT 可得。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

import polars as pl


if TYPE_CHECKING:
    from gr_data.db import DictConnection


@dataclass(frozen=True)
class IndustrySnapshot:
    """通过校验的目标日分类；available_at 使用真实观察时间。"""

    nodes: pl.DataFrame
    members: pl.DataFrame
    missing_ids: tuple[int, ...]
    closed_members: pl.DataFrame | None = None
    as_of: date | None = None


def normalize_industry(
    nodes: pl.DataFrame,
    members: pl.DataFrame,
    *,
    symbol_ids: Mapping[str, int],
    as_of: date,
    observed_at: datetime,
) -> IndustrySnapshot:
    """生成目标日期有效的 SW2021 一级归属。

    原件保留全部历史；本次仅准入覆盖 as_of 的来源区间。out_date 按剔除日
    作为排他上界，与现有 DDL 一致；边界源证据冲突时拒绝，不推算替代日期。
    缺分类保留 missing_ids；同股多行业或不一致区间拒绝。最多处理供应商分片规模。
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Industry observation timestamp must be timezone aware")
    required_nodes = {"index_code", "industry_name", "level"}
    required_members = {"ts_code", "l1_code", "in_date", "out_date"}
    if not required_nodes <= set(nodes.columns) or not required_members <= set(members.columns):
        raise ValueError("Industry source columns are incomplete")
    selected = nodes.filter(pl.col("level") == "L1").select(
        pl.lit("sw2021").alias("scheme_code"),
        pl.lit(1).cast(pl.Int16).alias("level"),
        pl.col("index_code").alias("industry_code"),
        "industry_name",
        pl.col("index_code").alias("external_code"),
    )
    if selected.is_empty() or selected["industry_code"].n_unique() != selected.height:
        raise ValueError("Industry nodes must be nonempty and unique")
    if selected.select(pl.any_horizontal(pl.all().is_null()).any()).item():
        raise ValueError("Industry nodes contain null fields")
    frame = members.filter(pl.col("ts_code").is_in(list(symbol_ids))).with_columns(
        pl.col("in_date").cast(pl.String).str.strptime(pl.Date, "%Y%m%d", strict=True),
        pl.col("out_date")
        .cast(pl.String)
        .replace("", None)
        .str.strptime(pl.Date, "%Y%m%d", strict=True),
    )
    if frame.filter(pl.col("in_date").is_null() | (pl.col("out_date") <= pl.col("in_date"))).height:
        raise ValueError("Industry membership has invalid source dates")
    history = frame.select("ts_code", "l1_code", "in_date", "out_date").unique()
    history = history.filter(pl.col("in_date") <= as_of).sort("ts_code", "in_date")
    previous: dict[str, date | None] = {}
    for row in history.iter_rows(named=True):
        symbol = row["ts_code"]
        if symbol in previous and (previous[symbol] is None or row["in_date"] < previous[symbol]):
            raise ValueError("Overlapping source industry intervals")
        previous[symbol] = row["out_date"]
    closed = history.filter(pl.col("out_date").is_not_null() & (pl.col("out_date") <= as_of))
    frame = history.filter(pl.col("out_date").is_null() | (pl.col("out_date") > as_of))
    if not set(frame["l1_code"]) <= set(selected["industry_code"]):
        raise ValueError("Membership references an unverified SW2021 node")
    frame = (
        frame.with_columns(
            pl.col("ts_code")
            .replace_strict(symbol_ids, return_dtype=pl.Int64)
            .alias("instrument_id"),
            pl.lit("sw2021").alias("scheme_code"),
            pl.lit(1).cast(pl.Int16).alias("level"),
            pl.col("l1_code").alias("industry_code"),
            pl.lit(observed_at).alias("available_at"),
            pl.lit("tushare").alias("source"),
        )
        .select(
            "instrument_id",
            "scheme_code",
            "level",
            "industry_code",
            "in_date",
            "out_date",
            "available_at",
            "source",
        )
        .sort("instrument_id")
    )
    if frame["instrument_id"].n_unique() != frame.height:
        raise ValueError("Source aliases produce duplicate industry memberships")
    missing = tuple(sorted(set(symbol_ids.values()) - set(frame["instrument_id"])))
    closed = closed.with_columns(
        pl.col("ts_code").replace_strict(symbol_ids, return_dtype=pl.Int64).alias("instrument_id"),
        pl.col("l1_code").alias("industry_code"),
        pl.lit("sw2021").alias("scheme_code"),
        pl.lit(1).cast(pl.Int16).alias("level"),
        pl.lit(observed_at).alias("available_at"),
        pl.lit("tushare").alias("source"),
    ).select(frame.columns)
    return IndustrySnapshot(selected.sort("industry_code"), frame, missing, closed, as_of)


async def write_industry_snapshot(
    conn: DictConnection,
    snapshot: IndustrySnapshot,
    *,
    expected_owners: Mapping[str, str | None],
) -> None:
    """在调用方发布事务中写分类；归属按前检值 CAS，禁止自动覆盖未知来源。

    本函数不提交。写入会使旧发布标脏，调用方必须在同一外层事务重签基础收据并发布。
    """
    from psycopg import sql
    from psycopg.pq import TransactionStatus

    from gr_data.common import contracts

    tables = ("classify.scheme", "classify.industry_node", "classify.instrument_industry")
    if (
        set(expected_owners) != set(tables)
        or conn.info.transaction_status != TransactionStatus.INTRANS
    ):
        raise ValueError(
            "Industry write requires an outer publication transaction and ownership CAS"
        )
    await conn.execute("SELECT pg_advisory_xact_lock(7342061105)")
    for table in tables:
        row = await (
            await conn.execute(
                "SELECT provider FROM ops.table_ownership WHERE target=%s FOR UPDATE", (table,)
            )
        ).fetchone()
        owner = row["provider"] if row else None
        if owner != expected_owners[table]:
            raise ValueError("Industry ownership changed since preflight")
        if owner not in (None, "datayes", "tushare"):
            raise ValueError("Unexpected industry table owner")
    for table in tables:
        if expected_owners[table] != "tushare":
            await conn.execute("DELETE FROM ops.table_ownership WHERE target=%s", (table,))
            await conn.execute(
                "INSERT INTO ops.table_ownership(target,provider,channel) "
                "VALUES (%s,'tushare','ingest')",
                (table,),
            )
    incoming = snapshot.members.to_dicts()
    if snapshot.closed_members is not None:
        incoming = snapshot.closed_members.to_dicts() + incoming
    ids = sorted({r["instrument_id"] for r in incoming} | set(snapshot.missing_ids))
    existing = await (
        await conn.execute(
            "SELECT instrument_id,scheme_code,level,industry_code,in_date,out_date,"
            "available_at,source "
            "FROM classify.instrument_industry WHERE scheme_code='sw2021' AND level=1 "
            "AND instrument_id=ANY(%s) FOR UPDATE",
            (ids,),
        )
    ).fetchall()
    changes = industry_changes(existing, snapshot)
    validate_missing_closures(existing, changes, snapshot)
    # 先收口，再插入；沿用源日期，不能自行猜一个新行业起点作为旧行业终点。
    closed_keys = set()
    if snapshot.closed_members is not None:
        closed_keys = {
            (r["instrument_id"], r["in_date"]) for r in snapshot.closed_members.to_dicts()
        }
    changes.sort(
        key=lambda r: (
            0 if (r["instrument_id"], r["in_date"]) in closed_keys else 1,
            r["instrument_id"],
            r["in_date"],
        )
    )
    frames = (
        (
            contracts.SCHEME,
            pl.DataFrame(
                {
                    "scheme_code": ["sw2021"],
                    "scheme_name": ["申万行业分类2021"],
                    "max_level": [3],
                    "available_level": [1],
                    "source": ["tushare"],
                }
            ),
        ),
        (
            contracts.INDUSTRY_NODE,
            snapshot.nodes.with_columns(pl.lit(None).cast(pl.String).alias("parent_code")),
        ),
    )
    for contract, frame in frames:
        table = f"{contract.schema}.{contract.table}"
        columns = contract.columns
        keys = contract.conflict_keys
        assignments = sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
            for c in columns
            if c not in keys
        )
        statement = sql.SQL(
            "INSERT INTO {} AS target ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {} "
            "WHERE ROW({}) IS DISTINCT FROM ROW({})"
        ).format(
            sql.Identifier(contract.schema, contract.table),
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(sql.Placeholder() for _ in columns),
            sql.SQL(",").join(map(sql.Identifier, keys)),
            assignments,
            sql.SQL(",").join(sql.Identifier("target", c) for c in columns if c not in keys),
            sql.SQL(",").join(sql.Identifier("excluded", c) for c in columns if c not in keys),
        )
        async with conn.cursor() as cur:
            await cur.executemany(statement, frame.select(columns).iter_rows())

    for row in changes:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO classify.instrument_industry "
                "(instrument_id,scheme_code,level,industry_code,in_date,out_date,"
                "available_at,source) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT "
                "(instrument_id,scheme_code,level,in_date) DO UPDATE SET "
                "industry_code=EXCLUDED.industry_code,out_date=EXCLUDED.out_date,"
                "available_at=EXCLUDED.available_at,source=EXCLUDED.source,updated_at=now()",
                tuple(row[c] for c in contracts.INSTRUMENT_INDUSTRY.columns),
            )


def industry_changes(existing: list[dict], snapshot: IndustrySnapshot) -> list[dict]:
    """仅产出实质变化；历史闭区间只收口已有行，不扩大当前节点的历史认证。"""
    by_key = {(r["instrument_id"], r["in_date"]): r for r in existing}
    changes = []
    closed = snapshot.closed_members.to_dicts() if snapshot.closed_members is not None else []
    for row, historical in [(r, True) for r in closed] + [
        (r, False) for r in snapshot.members.to_dicts()
    ]:
        old = by_key.get((row["instrument_id"], row["in_date"]))
        if old is None and historical:
            continue
        if old and (old["industry_code"], old["out_date"], old["source"]) == (
            row["industry_code"],
            row["out_date"],
            row["source"],
        ):
            continue
        if historical and old and old["industry_code"] != row["industry_code"]:
            raise ValueError("Source closure conflicts with stored industry identity")
        if old and row["available_at"] < old["available_at"]:
            raise ValueError("Stale industry observation would overwrite a newer interval")
        changes.append(row)
    return changes


def validate_missing_closures(
    existing: list[dict], changes: list[dict], snapshot: IndustrySnapshot
) -> None:
    """源端缺行不能代替区间收口证据。"""
    if not snapshot.missing_ids:
        return
    if snapshot.as_of is None:
        raise ValueError("Missing industry memberships require an explicit target date")
    projected = {(r["instrument_id"], r["in_date"]): r for r in existing}
    projected.update({(r["instrument_id"], r["in_date"]): r for r in changes})
    missing = set(snapshot.missing_ids)
    if any(
        r["instrument_id"] in missing
        and r["in_date"] <= snapshot.as_of
        and (r["out_date"] is None or r["out_date"] > snapshot.as_of)
        for r in projected.values()
    ):
        raise ValueError("Missing source industry row leaves a stored interval open")
