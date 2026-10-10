"""登录／刷新令牌打真实 PostgreSQL 的回归用例。

默认跳过，需要真库时::

    GETRICH_TEST_PG=1 uv run pytest packages/gr-api/tests/test_auth_pg_integration.py -v

mock 用例看不到 SQL 与 schema 不一致：auth.py 读取 ``app.users.display_name``，
而该列直到 043 才进 DDL，全新库上登录与刷新都报 UndefinedColumn。本文件在已迁移的
真库上执行完整的登录 → 刷新链路，并确认 011 的公开演示口令已被 043 停用。
测试数据都带 ``auth-pg-test-`` 前缀，teardown 会清理。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

import bcrypt
import pytest
from gr_api.config import load_api_settings
from gr_api.errors import Unauthorized
from gr_api.routers.auth import LoginRequest, RefreshRequest, login, refresh
from gr_data.config import load_postgres
from gr_tools.config import load_environment


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from psycopg import AsyncConnection


pytestmark = [
    pytest.mark.anyio,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GETRICH_TEST_PG") is None,
        reason="requires real PostgreSQL; set GETRICH_TEST_PG=1 to enable",
    ),
]

_EMAIL_PREFIX = "auth-pg-test-"
_PASSWORD = "auth-pg-test-password"


def _dsn() -> str:
    cfg = load_postgres(load_environment())
    return f"postgresql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}"


async def _connect() -> AsyncConnection:
    """按连接池的 search_path 连接测试库；失败时不打印含密码的 DSN。"""
    import psycopg
    from psycopg.rows import dict_row

    try:
        return await psycopg.AsyncConnection.connect(
            _dsn(),
            row_factory=dict_row,
            options="-c timezone=Asia/Shanghai -c search_path=app,market,meta,public",
        )
    except psycopg.OperationalError:
        pytest.fail("unable to connect to PostgreSQL for auth integration tests", pytrace=False)


async def _cleanup(conn: AsyncConnection) -> None:
    """只删除本文件创建的用户及其凭证、刷新令牌。"""
    pattern = f"{_EMAIL_PREFIX}%"
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM app.refresh_tokens WHERE user_id IN "
            "(SELECT id FROM app.users WHERE email LIKE %s)",
            (pattern,),
        )
        await cur.execute("DELETE FROM app.user_auth WHERE identifier LIKE %s", (pattern,))
        await cur.execute("DELETE FROM app.users WHERE email LIKE %s", (pattern,))
    await conn.commit()


@pytest.fixture
async def auth_db() -> AsyncIterator[tuple[AsyncConnection, str]]:
    """准备一名经 user_auth 邮箱登录的用户，display_name 留空。"""
    conn = await _connect()
    user_id = uuid4()
    email = f"{_EMAIL_PREFIX}{user_id.hex}@example.invalid"
    # 测试口令只需能校验，rounds=4 让 bcrypt 不拖慢用例
    credential = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    try:
        await _cleanup(conn)
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO app.users (id, email, password, name) VALUES (%s, %s, 'x', %s)",
                (user_id, email, "认证 PG 测试用户"),
            )
            await cur.execute(
                "INSERT INTO app.user_auth (user_id, auth_type, identifier, credential, verified)"
                " VALUES (%s, 'email', %s, %s, TRUE)",
                (user_id, email, credential),
            )
        await conn.commit()
        yield conn, email
    finally:
        await conn.rollback()
        await _cleanup(conn)
        await conn.close()


async def test_login_and_refresh_fall_back_to_name(
    auth_db: tuple[AsyncConnection, str],
) -> None:
    conn, email = auth_db
    settings = load_api_settings()

    logged_in = await login(
        body=LoginRequest(email=email, password=_PASSWORD), db=conn, rid="rid", settings=settings
    )
    assert logged_in["data"]["user"]["name"] == "认证 PG 测试用户"

    refreshed = await refresh(
        body=RefreshRequest(refresh_token=logged_in["data"]["refresh_token"]),
        db=conn,
        rid="rid",
        settings=settings,
    )
    assert refreshed["data"]["user"]["name"] == "认证 PG 测试用户"


async def test_login_and_refresh_prefer_display_name(
    auth_db: tuple[AsyncConnection, str],
) -> None:
    conn, email = auth_db
    settings = load_api_settings()
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE app.users SET display_name = %s WHERE email = %s", ("展示名", email)
        )
    await conn.commit()

    logged_in = await login(
        body=LoginRequest(email=email, password=_PASSWORD), db=conn, rid="rid", settings=settings
    )
    assert logged_in["data"]["user"]["name"] == "展示名"

    refreshed = await refresh(
        body=RefreshRequest(refresh_token=logged_in["data"]["refresh_token"]),
        db=conn,
        rid="rid",
        settings=settings,
    )
    assert refreshed["data"]["user"]["name"] == "展示名"


async def test_public_demo_password_cannot_log_in() -> None:
    """011 写入的 demo@getrich.io / password 必须无法登录（043 停用）。"""
    conn = await _connect()
    try:
        with pytest.raises(Unauthorized):
            await login(
                body=LoginRequest(email="demo@getrich.io", password="password"),
                db=conn,
                rid="rid",
                settings=load_api_settings(),
            )
    finally:
        await conn.rollback()
        await conn.close()
