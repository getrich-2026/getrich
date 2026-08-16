"""PgBarLoader 不提供因子加载 —— 因子时序在 ClickHouse，不在 PostgreSQL。

原先这里有一组 mock 测试，断言 ``load_factors()`` 会查 PostgreSQL 的
``factors_long`` 表。但 gr-data 的 PostgreSQL schema 里从来没有这张表：
因子时序表建在 ClickHouse（``gr_db/ddl/clickhouse/001_factors_long.sql``）。
那组测试用 mock 连接，因此永远是绿的，掩盖了「查一张不存在的表」这个事实。

现在的契约是**显式报错**：调用方要么改用 ClickHouse 客户端，要么用
``DataFrameBarLoader`` 直接传入因子数据。
"""

from unittest.mock import MagicMock

import pytest
from gr_backtest import PgBarLoader
from gr_backtest.exceptions import DataLoadError


class TestPgBarLoaderFactorsUnsupported:
    def test_factors_table_name_raises_with_actionable_message(self) -> None:
        with pytest.raises(DataLoadError) as exc_info:
            PgBarLoader._table_name_factors()

        message = str(exc_info.value)
        # 报错必须指出因子在哪、以及该怎么做，否则调用方只会看到一个空结果
        assert "ClickHouse" in message
        assert "factors_long" in message

    def test_load_factors_does_not_query_postgres(self) -> None:
        """报错发生在建 SQL 之前，不应该真的去 PostgreSQL 上查一张不存在的表。"""
        mock_conn = MagicMock()
        loader = PgBarLoader(conn=mock_conn)

        with pytest.raises(DataLoadError):
            loader.load_factors()

        mock_conn.cursor.assert_not_called()
