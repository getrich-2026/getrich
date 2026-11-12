"""单次批处理桥接：复用异步发布函数，所有 SQL 仍在同一同步连接执行。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from gr_data.db import DictConnection


class _Cursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _Cursor:
        self._cursor.__enter__()
        return self

    async def __aexit__(self, *args: Any) -> Any:
        return self._cursor.__exit__(*args)

    async def execute(self, *args: Any, **kwargs: Any) -> _Cursor:
        self._cursor.execute(*args, **kwargs)
        return self

    async def executemany(self, *args: Any, **kwargs: Any) -> None:
        self._cursor.executemany(*args, **kwargs)

    async def fetchone(self) -> Any:
        return self._cursor.fetchone()

    async def fetchall(self) -> Any:
        return self._cursor.fetchall()


class _Connection:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self.info = conn.info

    def cursor(self, **kwargs: Any) -> _Cursor:
        return _Cursor(self._conn.cursor(**{"row_factory": dict_row, **kwargs}))

    async def execute(self, *args: Any, **kwargs: Any) -> _Cursor:
        return await self.cursor().execute(*args, **kwargs)

    @asynccontextmanager
    async def transaction(self):
        with self._conn.transaction():
            yield


def publication_connection(conn: psycopg.Connection) -> DictConnection:
    """仅供串行日更调用；不提供 commit/rollback，也不派生第二连接。"""
    return cast("DictConnection", cast("object", _Connection(conn)))
