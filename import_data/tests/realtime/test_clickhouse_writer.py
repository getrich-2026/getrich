from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from import_data.realtime.clickhouse_writer import ClickHouseBarWriter, _events_to_dataframe
from import_data.realtime.models import BarEvent


def _make_event(symbol="600000.SH"):
    return BarEvent(
        symbol=symbol,
        type="stock",
        dt=date.today(),
        bar_time=datetime.now(),
        close=10.5,
    )


def _make_writer() -> ClickHouseBarWriter:
    """创建 writer，mock 掉 MinBarTable 避免真实 ClickHouse 连接。"""
    mock_pool = MagicMock()
    with patch(
        "import_data.realtime.clickhouse_writer.MinBarTable.__init__",
        return_value=None,
    ):
        writer = ClickHouseBarWriter(mock_pool)
    # 手动替换 _table 为 mock，绕过 MinBarTable 初始化
    writer._table = MagicMock()
    return writer


def test_events_to_dataframe_shape():
    events = [_make_event("600000.SH"), _make_event("000001.SZ")]
    df = _events_to_dataframe(events)
    assert len(df) == 2
    expected_cols = {"symbol", "type", "dt", "bar_time", "open", "close", "volume", "provider"}
    assert expected_cols.issubset(set(df.columns))


def test_events_to_dataframe_values():
    e = _make_event()
    df = _events_to_dataframe([e])
    assert df.iloc[0]["symbol"] == "600000.SH"
    assert df.iloc[0]["close"] == 10.5
    assert df.iloc[0]["provider"] == "insight"


@pytest.mark.asyncio
async def test_flush_calls_insert():
    writer = _make_writer()

    for _ in range(3):
        writer._buffer.append(_make_event())

    writer._table.insert = MagicMock(return_value=True)
    count = await writer.flush()

    assert count == 3
    writer._table.insert.assert_called_once()
    assert writer._buffer == []  # buffer 已清空


@pytest.mark.asyncio
async def test_flush_empty_buffer_returns_zero():
    writer = _make_writer()
    count = await writer.flush()
    assert count == 0


@pytest.mark.asyncio
async def test_write_triggers_flush_on_size():
    writer = _make_writer()
    writer.FLUSH_SIZE = 3
    writer._table.insert = MagicMock(return_value=True)

    for _ in range(3):
        await writer.write(_make_event())

    assert writer._buffer == []  # 第 3 条触发 flush 后清空


@pytest.mark.asyncio
async def test_flush_retry_on_failure():
    writer = _make_writer()
    writer.MAX_RETRIES = 2
    writer.RETRY_BASE_DELAY = 0.001  # 测试中缩短 delay
    writer._buffer.append(_make_event())
    writer._table.insert = MagicMock(side_effect=Exception("CH down"))

    count = await writer.flush()

    assert count == 0  # 全部重试失败后返回 0
