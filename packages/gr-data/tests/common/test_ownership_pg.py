"""OwnershipManager 真 PostgreSQL 18 集成测试。

覆盖 PG 18 ``RETURNING OLD.provider`` 审计日志、冲突快速路径零锁泄漏、
并发竞态兜底保存点回滚，以及 IDLE / INTRANS / autocommit 三种事务形态。
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from gr_data.common.ownership import OwnershipError, OwnershipManager
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb


_DIAG_BARRIER_LOCK_KEY = 7342061105


@contextmanager
def _clean_diag_head(
    conn: psycopg.Connection,
    *,
    dataset_key: str = "market.stock_bar_1d",
) -> Generator[tuple[str, str], None, None]:
    """插入一条独立的 dirty=false diag_input_head 并在退出时清除，避免污染同容器其他用例。"""
    receipt_id = uuid4()
    partition_key = f"ownership-test-{uuid4().hex[:12]}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.diag_input_receipt (
                receipt_id, dataset_key, partition_key, provider, manifest_hash,
                importer_version, coverage_start, coverage_end, quality, evidence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                receipt_id,
                dataset_key,
                partition_key,
                "tushare",
                uuid4().hex + uuid4().hex,
                "ownership-pg-test",
                date(2024, 1, 2),
                date(2024, 1, 2),
                Jsonb({"status": "ok"}),
                Jsonb({"source": "test"}),
            ),
        )
        cur.execute(
            """
            INSERT INTO ops.diag_input_head (
                dataset_key, partition_key, basic_receipt_id, revision, dirty
            )
            VALUES (%s, %s, %s, 1, false)
            """,
            (dataset_key, partition_key, receipt_id),
        )
    conn.commit()
    try:
        yield dataset_key, partition_key
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET LOCAL session_replication_role = replica")
            cur.execute(
                "DELETE FROM ops.diag_input_head WHERE dataset_key = %s AND partition_key = %s",
                (dataset_key, partition_key),
            )
            cur.execute("DELETE FROM ops.diag_input_receipt WHERE receipt_id = %s", (receipt_id,))
        conn.commit()


def _is_head_dirty(conn: psycopg.Connection, dataset_key: str, partition_key: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT dirty FROM ops.diag_input_head WHERE dataset_key = %s AND partition_key = %s",
            (dataset_key, partition_key),
        )
        row = cur.fetchone()
    assert row is not None
    return bool(row[0])


def test_pg18_returning_old_provider_logs_only_on_transfer(
    pg_conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    """真库验证首次登记、同源重复登记不记转移日志；仅跨源 force=True 记一条结构化日志。"""
    target = "market.stock_bar_1d"
    mgr = OwnershipManager(pg_conn)
    caplog.set_level(logging.INFO, logger="gr_data.common.ownership")

    # 1) 首次登记：OLD.provider 为 NULL，不产生转移日志
    mgr.claim(target, "tushare", channel="ingest")
    pg_conn.commit()
    assert not caplog.records
    owner = mgr.owner(target)
    assert owner is not None and (owner.provider, owner.channel) == ("tushare", "ingest")

    # 2) 同 provider 重复 claim（即使 force=True 且切换 channel）：不产生转移日志
    mgr.claim(target, "tushare", channel="stream", force=True)
    pg_conn.commit()
    assert not caplog.records
    owner = mgr.owner(target)
    assert owner is not None and (owner.provider, owner.channel) == ("tushare", "stream")

    # 3) 跨 provider 强制转移：PG 18 RETURNING OLD.provider 返回真实旧 provider 并记日志
    mgr.claim(target, "ricequant", channel="ingest", force=True)
    pg_conn.commit()
    assert len(caplog.records) == 1
    record = caplog.records[0]
    fields = {
        "target": target,
        "previous_provider": "tushare",
        "new_provider": "ricequant",
        "channel": "ingest",
    }
    assert {k: record.__dict__[k] for k in fields} == fields
    assert all(f"{k}={v}" in record.getMessage() for k, v in fields.items())
    owner = mgr.owner(target)
    assert owner is not None and (owner.provider, owner.channel) == ("ricequant", "ingest")


def test_force_false_conflict_avoids_diag_lock_and_dirty_side_effect(
    pg_conn: psycopg.Connection, pg_dsn: dict[str, object]
) -> None:
    """force=False 归属冲突走只读快速路径：不抢占全局诊断排他锁，也不标脏 diag_input_head。"""
    target = "market.stock_bar_1d"
    mgr = OwnershipManager(pg_conn)
    mgr.claim(target, "tushare", channel="ingest")
    with _clean_diag_head(pg_conn) as (dataset_key, partition_key):
        assert pg_conn.info.transaction_status == TransactionStatus.IDLE

        with pytest.raises(OwnershipError, match="tushare"):
            mgr.claim(target, "ricequant", channel="ingest", force=False)

        # 调用方能看到本事务尚未提交的标脏写入；另一连接探测排他锁是否仍被持有。
        assert _is_head_dirty(pg_conn, dataset_key, partition_key) is False
        with psycopg.connect(**pg_dsn) as other:  # type: ignore[arg-type]
            with other.cursor() as cur:
                cur.execute(
                    "SELECT pg_try_advisory_xact_lock_shared(%s)", (_DIAG_BARRIER_LOCK_KEY,)
                )
                lock_row = cur.fetchone()
            assert lock_row == (True,), "force=False 冲突拒绝不应持有全局诊断排他锁"
            other.rollback()


def test_concurrent_conflict_race_rolls_back_dirty_side_effect(
    pg_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发竞态落入 UPSERT WHERE false 兜底路径时，保存点回滚语句级触发器的标脏副作用。"""
    target = "market.stock_bar_1d"
    mgr = OwnershipManager(pg_conn)
    mgr.claim(target, "tushare", channel="ingest")
    with _clean_diag_head(pg_conn) as (dataset_key, partition_key):
        # 模拟快速路径读到 None 后、另一会话抢先提交了 tushare 归属的 TOCTOU 竞态。
        real_owner = mgr.owner
        calls = {"n": 0}

        def stale_first_owner(name: str):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return real_owner(name)

        monkeypatch.setattr(mgr, "owner", stale_first_owner)

        with pytest.raises(OwnershipError, match="tushare"):
            mgr.claim(target, "ricequant", channel="ingest", force=False)

        # 在同一外层事务内即可观察到保存点已回滚标脏副作用。
        assert _is_head_dirty(pg_conn, dataset_key, partition_key) is False


@pytest.mark.parametrize("force", [False, True], ids=["ordinary", "forced"])
def test_idle_claim_can_be_rolled_back(
    pg_conn: psycopg.Connection, pg_dsn: dict[str, object], force: bool
) -> None:
    """普通登记由归属预读开启事务，强制登记也须保留调用方的回滚权。"""
    target = "market.stock_bar_1d"
    mgr = OwnershipManager(pg_conn)
    assert pg_conn.autocommit is False
    assert pg_conn.info.transaction_status == TransactionStatus.IDLE
    mgr.claim(target, "tushare", force=force)
    assert pg_conn.info.transaction_status == TransactionStatus.INTRANS
    assert mgr.owner(target) is not None
    with psycopg.connect(**pg_dsn) as observer:  # type: ignore[arg-type]
        assert OwnershipManager(observer).owner(target) is None
    pg_conn.rollback()
    assert mgr.owner(target) is None


def test_claim_in_transaction_and_autocommit(
    pg_conn: psycopg.Connection, pg_dsn: dict[str, object]
) -> None:
    """验证已有事务和自动提交连接的登记行为。"""
    mgr = OwnershipManager(pg_conn)
    with _clean_diag_head(pg_conn) as (dataset_key, partition_key):
        # INTRANS：随外层事务一起提交生效
        with pg_conn.cursor() as cur:
            cur.execute("SELECT 1")
        assert pg_conn.info.transaction_status == TransactionStatus.INTRANS
        mgr.claim("market.stock_bar_1d", "tushare", channel="ingest")
        pg_conn.commit()
        assert mgr.owner("market.stock_bar_1d") is not None

        # autocommit=True：独立提交生效；冲突拒绝不标脏
        with psycopg.connect(**pg_dsn, autocommit=True) as auto_conn:  # type: ignore[arg-type]
            auto_mgr = OwnershipManager(auto_conn)
            auto_mgr.claim("market.index_bar_1d", "tushare", channel="ingest")
            assert auto_mgr.owner("market.index_bar_1d") is not None

            # 按 054 validate_head 契约递增 revision 复位 dirty，再测 autocommit 冲突拒绝
            with auto_conn.cursor() as cur:
                cur.execute(
                    "UPDATE ops.diag_input_head SET dirty = false, revision = revision + 1 "
                    "WHERE dataset_key = %s AND partition_key = %s",
                    (dataset_key, partition_key),
                )
            with pytest.raises(OwnershipError, match="tushare"):
                auto_mgr.claim("market.stock_bar_1d", "ricequant", channel="ingest", force=False)
            assert _is_head_dirty(auto_conn, dataset_key, partition_key) is False
