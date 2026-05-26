from __future__ import annotations

from import_data.core.logger import Logger
from import_data.realtime.models import BarEvent

try:
    import redis.asyncio as aioredis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class RedisStreamWriter:
    """写入 Redis Streams，作为实时分发缓冲层。

    Key: stream:bars_1m:{symbol}
    MAXLEN ~ 2880（约 2 个交易日的 1 分钟 K 线，支持中断恢复窗口）
    """

    MAXLEN = 2880

    def __init__(self, redis_client: "aioredis.Redis") -> None:
        self._redis = redis_client
        self._logger = Logger("RedisStreamWriter")

    async def write(self, event: BarEvent) -> str | None:
        """XADD 单条 bar，返回 entry ID。"""
        key = f"stream:bars_1m:{event.symbol}"
        fields = _bar_event_to_dict(event)
        try:
            entry_id = await self._redis.xadd(
                key, fields, maxlen=self.MAXLEN, approximate=True
            )
            return entry_id
        except Exception as e:
            self._logger.error(f"Redis xadd failed for {event.symbol}: {e}")
            return None

    async def write_batch(self, events: list[BarEvent]) -> int:
        """pipeline 批量写，减少 RTT。"""
        if not events:
            return 0
        try:
            pipe = self._redis.pipeline(transaction=False)
            for event in events:
                key = f"stream:bars_1m:{event.symbol}"
                pipe.xadd(
                    key,
                    _bar_event_to_dict(event),
                    maxlen=self.MAXLEN,
                    approximate=True,
                )
            await pipe.execute()
            return len(events)
        except Exception as e:
            self._logger.error(f"Redis pipeline write_batch failed: {e}")
            return 0


def _bar_event_to_dict(event: BarEvent) -> dict[str, str]:
    return {
        "symbol": event.symbol,
        "type": event.type,
        "dt": event.dt.isoformat(),
        "bar_time": event.bar_time.isoformat(),
        "pre_close": str(event.pre_close),
        "open": str(event.open),
        "high": str(event.high),
        "low": str(event.low),
        "close": str(event.close),
        "volume": str(event.volume),
        "amount": str(event.amount),
        "open_interest": str(event.open_interest),
        "settle": str(event.settle),
        "pre_settle": str(event.pre_settle),
        "local_time": event.local_time.isoformat(),
        "provider": event.provider,
    }


if __name__ == "__main__":
    import asyncio
    from datetime import date, datetime
    from unittest.mock import AsyncMock

    from import_data.realtime.models import BarEvent

    async def _demo() -> None:
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        writer = RedisStreamWriter(mock_redis)
        e = BarEvent(
            symbol="600000.SH",
            type="stock",
            dt=date.today(),
            bar_time=datetime.now(),
            close=10.5,
        )
        entry_id = await writer.write(e)
        print(f"entry_id: {entry_id}")

    asyncio.run(_demo())
