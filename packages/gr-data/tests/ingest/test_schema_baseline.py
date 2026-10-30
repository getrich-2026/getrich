"""新库基线的注释语义与完整 SQL 重放回归，仅连接一次性 PG。"""

from __future__ import annotations

from typing import LiteralString, cast

import psycopg
import pytest
from gr_db import POSTGRES_DDL_DIR, migrate_postgres
from psycopg.sql import SQL


# gr-db 管理的业务 schema；TimescaleDB 内部 catalog 不在此列。
_MANAGED_SCHEMAS = (
    "app",
    "backtest",
    "classify",
    "diag",
    "factor",
    "fundamental",
    "market",
    "meta",
    "ops",
    "pick",
    "realtime",
    "staging",
)


@pytest.mark.integration
def test_baseline_catalog_comments_and_direct_replay(pg_conn: psycopg.Connection) -> None:
    """重放全部 DDL 后，业务注释准确、公开演示账号仍停用，runner 不再应用。"""
    for path in sorted(POSTGRES_DDL_DIR.glob("*.sql")):
        # 仅执行仓库自带 DDL，不接受用户输入；显式标注受信 SQL 来源。
        pg_conn.execute(SQL(cast(LiteralString, path.read_text())))
        pg_conn.commit()

    for name in ("dataset_variant", "import_receipt", "import_checkpoint"):
        # 新库只建立 factor 下的专用表，避免两套对象并存后写错 schema。
        assert pg_conn.execute(
            "SELECT to_regclass(%s), to_regclass(%s)", (f"factor.{name}", f"ops.{name}")
        ).fetchone() == (f"factor.{name}", None)
    rows = pg_conn.execute(
        "SELECT DISTINCT n.nspname FROM pg_constraint c "
        "JOIN pg_class r ON r.oid = c.confrelid "
        "JOIN pg_namespace n ON n.oid = r.relnamespace "
        "WHERE c.conrelid = 'factor.import_checkpoint'::regclass AND c.contype = 'f'"
    ).fetchall()
    assert rows == [("factor",)]
    rows = pg_conn.execute(
        "SELECT DISTINCT n.nspname FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid = t.tgfoid "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE t.tgrelid = 'factor.import_checkpoint'::regclass AND NOT t.tgisinternal"
    ).fetchall()
    assert rows == [("factor",)]

    expected_fragments = {
        ("factor.model_run", "estimated_at"): "observed_at",
        ("factor.model_run", "model_version"): "run_id",
        ("factor.definition", "ordinal"): "ordinal + 1",
        ("pick.item", "symbol"): "不含交易所后缀",
        ("ops.users", "user_id"): "运维用户自身",
        ("ops.api_keys", "user_id"): "ops.users.user_id",
        ("ops.data_quality_check", "run_id"): "ops.etl_job_run.run_id",
    }
    for (table, column), fragment in expected_fragments.items():
        row = pg_conn.execute(
            "SELECT col_description(attrelid, attnum) FROM pg_attribute "
            "WHERE attrelid = %s::regclass AND attname = %s",
            (table, column),
        ).fetchone()
        assert row is not None and fragment in row[0]
    assert pg_conn.execute(
        "SELECT is_active FROM app.users WHERE email = 'demo@getrich.io'"
    ).fetchone() == (False,)

    # 042 已从动态兜底改为显式注释：新增表或列漏写注释时在此暴露，不再被自动补齐掩盖。
    missing = pg_conn.execute(
        "SELECT n.nspname || '.' || c.relname || '.' || a.attname "
        "FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a "
        "  ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
        "WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s) "
        "  AND col_description(c.oid, a.attnum) IS NULL "
        "UNION "
        "SELECT n.nspname || '.' || c.relname FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s) "
        "  AND obj_description(c.oid, 'pg_class') IS NULL "
        "ORDER BY 1",
        (list(_MANAGED_SCHEMAS), list(_MANAGED_SCHEMAS)),
    ).fetchall()
    assert missing == []
    pg_conn.commit()
    assert not migrate_postgres(pg_conn).migrations
