"""诊断发布读取屏障；连接、事务和发布上下文只属于当前请求。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any

from anyio import CancelScope
from gr_api.errors import BadRequest
from gr_data.db import DictConnection
from psycopg import IsolationLevel
from psycopg.pq import TransactionStatus


BARRIER_KEY = 7342061105


@dataclass(frozen=True)
class PublishedDiagnosticContext:
    """一次请求固定的发布身份；业务取数不再解析最新版本。"""

    version_id: str
    as_of_date: date
    published_at: datetime
    version: Mapping[str, Any]


current: ContextVar[PublishedDiagnosticContext | None] = ContextVar(
    "diagnosis_publication", default=None
)
enabled: ContextVar[bool] = ContextVar("diagnosis_publication_enabled", default=False)


async def _session_lock(db: DictConnection, key: int, *, shared: bool) -> None:
    """非阻塞锁探测加有界异步等待；取消不遗留服务器ACTIVE锁等待。"""
    sql = (
        "SELECT pg_try_advisory_lock_shared(%s) AS acquired"
        if shared
        else "SELECT pg_try_advisory_lock(%s) AS acquired"
    )
    try:
        async with asyncio.timeout(10):
            while True:
                async with db.cursor() as cur:
                    await cur.execute(sql, (key,))
                    row = await cur.fetchone()
                if row and row["acquired"]:
                    return
                await asyncio.sleep(0.05)
    except TimeoutError as exc:
        raise BadRequest("diagnostic input barrier timed out", http_status=503) from exc


@asynccontextmanager
async def consistent_read(
    db: DictConnection, *, mutation: bool = False
) -> AsyncGenerator[DictConnection]:
    """空闲独占连接先取 session 共享锁，再建立 RR 快照；失败时销毁连接。

    不提交调用方已有事务。取消发生在取锁响应之后也会尝试解锁；清理不能确认时关闭
    连接，让 PostgreSQL 释放所有 session 锁，连接池不再复用该连接。
    """
    if db.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError("diagnostic reader requires an idle dedicated connection")
    old_autocommit, old_isolation = db.autocommit, db.isolation_level
    acquired = False
    mutation_acquired = False
    old_timeout: str | None = None
    token = enabled.set(True)
    context_token = current.set(None)
    try:
        await db.set_autocommit(True)
        async with db.cursor() as cur:
            await cur.execute("SHOW statement_timeout")
            timeout_row = await cur.fetchone()
            assert timeout_row is not None
            old_timeout = timeout_row["statement_timeout"]
        await db.execute("SET statement_timeout='10s'")
        # RR快照建立前串行短写请求：避免等待幂等键/计算缓存锁之后仍读旧快照。
        # GET报告不取此锁；输入writer只用全局屏障，不与诊断写锁形成环。
        if mutation:
            await _session_lock(db, BARRIER_KEY + 1, shared=False)
            mutation_acquired = True
        await _session_lock(db, BARRIER_KEY, shared=True)
        acquired = True
        await db.set_isolation_level(IsolationLevel.REPEATABLE_READ)
        async with db.transaction():
            await db.execute("SET LOCAL statement_timeout='30s'")
            yield db
    finally:

        async def cleanup() -> None:
            try:
                await db.rollback()
                await db.set_autocommit(True)
                async with db.cursor() as cur:
                    await cur.execute(
                        "SELECT pg_advisory_unlock_shared(%s) AS unlocked", (BARRIER_KEY,)
                    )
                    result = await cur.fetchone()
                    if acquired and (result is None or not result["unlocked"]):
                        raise RuntimeError("diagnostic session lock release was not confirmed")
                if mutation:
                    async with db.cursor() as cur:
                        await cur.execute(
                            "SELECT pg_advisory_unlock(%s) AS unlocked", (BARRIER_KEY + 1,)
                        )
                        result = await cur.fetchone()
                        if mutation_acquired and (result is None or not result["unlocked"]):
                            raise RuntimeError("diagnostic mutation lock release was not confirmed")
                if old_timeout is not None:
                    await db.execute(
                        "SELECT set_config('statement_timeout',%s,false)", (old_timeout,)
                    )
                await db.set_isolation_level(old_isolation)
                await db.set_autocommit(old_autocommit)
            except BaseException:
                await db.close()
                raise

        # Starlette取消来自AnyIO cancel scope；只有asyncio.shield不足以抵抗重复注入。
        # 屏蔽外层取消期间仍保留自己的5秒清理上限，无法确认则销毁连接。
        with CancelScope(shield=True):
            cleanup_task = asyncio.create_task(cleanup())
            try:
                await asyncio.wait_for(asyncio.shield(cleanup_task), timeout=5)
            except BaseException:
                await db.close()
                cleanup_task.cancel()
                raise
            finally:
                current.reset(context_token)
                enabled.reset(token)


async def require_publication(db: DictConnection, version_id: str | None = None) -> dict[str, Any]:
    """核对一个正式发布及其失效状态；最新失效时不回退旧日期。"""
    pinned = current.get()
    if pinned is not None:
        if version_id is not None and version_id != pinned.version_id:
            raise BadRequest("request attempted to mix data versions", http_status=409)
        return deepcopy(dict(pinned.version))
    async with db.cursor() as cur:
        if version_id is None:
            await cur.execute(
                "SELECT data_version_id FROM diag.data_publication ORDER BY publication_seq DESC "
                "LIMIT 1"
            )
            row = await cur.fetchone()
            version_id = row["data_version_id"] if row else None
        if version_id is None:
            raise BadRequest("no usable diagnostic publication", http_status=503)
        await cur.execute("SELECT diag.publication_is_valid(%s) AS valid", (version_id,))
        validity = await cur.fetchone()
        if not validity or not validity["valid"]:
            raise BadRequest("diagnostic publication is unavailable", http_status=503)
        await cur.execute(
            "SELECT v.*,p.as_of_date,p.published_at,p.contract_version FROM diag.data_version v "
            "JOIN diag.data_publication p USING(data_version_id) WHERE data_version_id=%s",
            (version_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise BadRequest("no usable diagnostic publication", http_status=503)
    current.set(
        PublishedDiagnosticContext(
            version_id, row["as_of_date"], row["published_at"], MappingProxyType(deepcopy(row))
        )
    )
    return row


def cutoff() -> datetime:
    """已发布数据的实际可用截止；旧入口保持当前观察语义。"""
    from datetime import timezone

    context = current.get()
    return context.published_at if context else datetime.now(timezone.utc)


async def require_coverage(
    db: DictConnection, start: date, end: date, datasets: tuple[str, ...]
) -> None:
    """历史区间必须包含在发布组成的连续覆盖范围内，含前一开市日。"""
    from datetime import timedelta

    context = current.get()
    if context is None:
        raise RuntimeError("publication context is required")
    async with db.cursor() as cur:
        await cur.execute(
            """SELECT dataset_key,coverage_start,coverage_end
            FROM diag.data_version_component WHERE data_version_id=%s
              AND dataset_key=ANY(%s) ORDER BY dataset_key,coverage_start""",
            (context.version_id, list(datasets)),
        )
        rows = await cur.fetchall()
    for dataset in datasets:
        until = start
        for row in rows:
            if row["dataset_key"] != dataset or row["coverage_end"] < until:
                continue
            if row["coverage_start"] > until:
                break
            until = row["coverage_end"] + timedelta(days=1)
            if until > end:
                break
        if until <= end:
            raise BadRequest(
                "requested history window is outside published input coverage", http_status=503
            )
