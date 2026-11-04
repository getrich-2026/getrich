"""``gr_data.db`` 导出的 PostgreSQL 接口必须与 ``gr_data.db.postgres`` 为同一对象。"""

from __future__ import annotations

from importlib import import_module

import pytest
from gr_data import db
from gr_data.db import postgres


def test_exports_share_pool_and_types():
    for name in postgres.__all__:
        assert getattr(db, name) is getattr(postgres, name)
    assert db.pg_pool is import_module("gr_data.db.postgres.pool").pg_pool


@pytest.mark.parametrize("name", ["pool", "sync", "copy", "trading_status", "risk_receipts"])
def test_legacy_module_paths_removed(name):
    with pytest.raises(ModuleNotFoundError):
        import_module(f"gr_data.db.{name}")
