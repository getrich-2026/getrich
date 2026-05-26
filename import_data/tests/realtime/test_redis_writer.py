from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from import_data.realtime.models import BarEvent
from import_data.realtime.redis_writer import RedisStreamWriter, _bar_event_to_dict


def _make_event(symbol="600000.SH"):
    return BarEvent(
        symbol=symbol,
        type="stock",
        dt=date.today(),
        bar_time=datetime.now(),
        close=10.5,
    )


def test_bar_event_to_dict():
    e = _make_event()
    d = _bar_event_to_dict(e)
    assert d["symbol"] == "600000.SH"
    assert d["provider"] == "insight"
    assert "bar_time" in d
    assert isinstance(d["close"], str)  # 所有值必须是 str


@pytest.mark.asyncio
async def test_write_calls_xadd():
    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value="1234567890-0")

    writer = RedisStreamWriter(mock_redis)
    e = _make_event()
    await writer.write(e)

    mock_redis.xadd.assert_called_once()
    call_kwargs = mock_redis.xadd.call_args
    assert call_kwargs[0][0] == "stream:bars_1m:600000.SH"
    assert call_kwargs[1]["maxlen"] == RedisStreamWriter.MAXLEN
    assert call_kwargs[1]["approximate"] is True


@pytest.mark.asyncio
async def test_write_error_returns_none():
    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock(side_effect=Exception("connection refused"))

    writer = RedisStreamWriter(mock_redis)
    result = await writer.write(_make_event())
    assert result is None  # 失败时返回 None 而不是 raise


@pytest.mark.asyncio
async def test_write_batch_uses_pipeline():
    mock_pipeline = AsyncMock()
    mock_pipeline.xadd = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=["ok"] * 3)

    mock_redis = AsyncMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

    writer = RedisStreamWriter(mock_redis)
    events = [_make_event(f"6000{i:02d}.SH") for i in range(3)]
    count = await writer.write_batch(events)

    assert count == 3
    assert mock_pipeline.xadd.call_count == 3
    mock_pipeline.execute.assert_called_once()
