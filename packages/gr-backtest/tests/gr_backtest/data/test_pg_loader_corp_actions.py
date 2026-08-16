"""PgBarLoader 暂不提供公司行为加载 —— gr-data schema 里还没有这张表。

原先这里有一组 mock 测试，断言 ``load_corp_actions()`` 会查 ``corp_actions`` 表。
gr-data 的 PostgreSQL schema（``gr_db/ddl/postgres/``）里没有这张表，
mock 连接让这组测试一直是绿的，掩盖了「查一张不存在的表」这个事实。

分红送转直接影响回测收益率，静默返回空结果比报错危险得多 —— 拿不到除权信息
的回测会把除权日的价格跳空当成真实亏损。所以现在的契约是**显式报错**，
并提示用 ``DataFrameBarLoader`` 显式传入。

补上 ``market`` 侧的公司行为表和 importer 之后，把这里换回真实的查询测试。
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from gr_backtest import PgBarLoader, get_shanghai_tz
from gr_backtest.exceptions import DataLoadError


TZ = get_shanghai_tz()


class TestPgBarLoaderCorpActionsUnsupported:
    def test_corp_actions_table_name_raises_with_actionable_message(self) -> None:
        with pytest.raises(DataLoadError) as exc_info:
            PgBarLoader._table_name_corp_actions()

        message = str(exc_info.value)
        assert "DataFrameBarLoader" in message

    def test_load_corp_actions_does_not_query_postgres(self) -> None:
        """报错发生在建 SQL 之前，不会去查不存在的表。"""
        mock_conn = MagicMock()
        loader = PgBarLoader(conn=mock_conn)

        with pytest.raises(DataLoadError):
            loader.load_corp_actions(
                symbols=["000001.SZ"],
                start=datetime(2026, 1, 1, tzinfo=TZ),
                end=datetime(2026, 2, 1, tzinfo=TZ),
            )

        mock_conn.cursor.assert_not_called()
