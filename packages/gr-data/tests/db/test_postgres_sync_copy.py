"""同步 PostgreSQL 连接和 COPY 的关键契约。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from gr_data.common.contracts import TableContract
from gr_data.db.postgres.copy import upsert_rows
from gr_data.db.postgres.sync import PgConfig, PgPool, connect
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import TransactionStatus


@pytest.fixture
def config() -> PgConfig:
    return PgConfig(password="synthetic %'\\ value", statement_timeout_ms=1234)


def test_sync_config_hides_password_and_sets_session_options(config: PgConfig) -> None:
    assert config.password not in repr(config)
    parsed = conninfo_to_dict(config.conninfo())
    assert parsed["password"] == config.password
    assert "timezone=Asia/Shanghai" in str(parsed["options"])
    assert "statement_timeout=1234" in str(parsed["options"])


def test_sync_connect_leaves_commit_to_caller(config: PgConfig) -> None:
    fake = MagicMock()
    with (
        patch("gr_data.db.postgres.sync.psycopg.connect", return_value=fake) as factory,
        connect(config) as borrowed,
    ):
        assert borrowed is fake
    factory.assert_called_once_with(config.conninfo(), autocommit=False)
    fake.commit.assert_not_called()
    fake.close.assert_called_once()


def test_sync_pool_inherits_session_options(config: PgConfig) -> None:
    with patch("psycopg_pool.ConnectionPool") as factory:
        PgPool(config)
    parsed = conninfo_to_dict(factory.call_args.args[0])
    assert "statement_timeout=1234" in str(parsed["options"])
    assert "timezone=Asia/Shanghai" in str(parsed["options"])


def _fake_connection(*, autocommit: bool, status: TransactionStatus):
    conn = MagicMock()
    conn.autocommit = autocommit
    conn.info.transaction_status = status
    cursor = MagicMock()
    cursor.rowcount = 2
    copy = MagicMock()
    cursor.copy.return_value.__enter__.return_value = copy
    conn.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def transaction():
        yield

    conn.transaction.side_effect = transaction
    return conn, cursor, copy


def test_copy_keeps_outer_commit_and_cleans_stage() -> None:
    conn, cur, copy = _fake_connection(autocommit=False, status=TransactionStatus.IDLE)
    contract = TableContract("meta", "sample", ("id", "value"), ("id",))
    assert upsert_rows(conn, contract, [(1, "a"), (2, "b")]) == 2
    conn.execute.assert_called_once_with("SELECT 1")
    conn.commit.assert_not_called()
    assert cur.execute.call_count == 3
    assert cur.execute.call_args.args[0].as_string().startswith("DROP TABLE")
    assert copy.write_row.call_count == 2
    assert 'ON CONFLICT ("id") DO UPDATE' in cur.execute.call_args_list[1].args[0].as_string()


def test_copy_autocommit_uses_transaction_and_rejects_invalid_rows() -> None:
    conn, cur, _ = _fake_connection(autocommit=True, status=TransactionStatus.IDLE)
    contract = TableContract("meta", "sample", ("id", "value"), ("id",))
    assert upsert_rows(conn, contract, [(1, "a")]) == 2
    conn.transaction.assert_called_once()
    conn.execute.assert_not_called()
    for columns, rows in [(["value"], [("a",)]), (["id", "id"], [(1, 1)]), (["id"], [(1, 2)])]:
        with pytest.raises(ValueError):
            upsert_rows(conn, contract, rows, columns=columns)
    assert cur.execute.call_count == 3
