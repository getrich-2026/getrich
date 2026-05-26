from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pandas as pd

from import_data.core.logger import Logger
from import_data.db.tables.bar import MinBarTable
from import_data.realtime.models import BarEvent

if TYPE_CHECKING:
    from import_data.db.clickhouse.pool import ClickHouseConnectionPool


class ClickHouseBarWriter:
    """ClickHouse 批量写入器，缓冲 BarEvent 后定期 flush 到 bars_1m 表。

    flush 策略：buffer 满 FLUSH_SIZE 条，或距上次 flush 超过 FLUSH_INTERVAL 秒。
    实际 insert 通过 run_in_executor 在线程池执行（同步 ClickHouseConnectionPool），
    不阻塞 asyncio 事件循环。
    """

    FLUSH_SIZE = 200
    FLUSH_INTERVAL = 60.0
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2.0

    def __init__(self, pool: "ClickHouseConnectionPool") -> None:
        self._table = MinBarTable(pool=pool)
        self._buffer: list[BarEvent] = []
        self._last_flush: float = time.monotonic()
        self._flush_lock = asyncio.Lock()
        self._logger = Logger("ClickHouseBarWriter")

    async def write(self, event: BarEvent) -> None:
        self._buffer.append(event)
        if self._should_flush():
            await self.flush()

    def _should_flush(self) -> bool:
        return (len(self._buffer) >= self.FLUSH_SIZE) or (
            (time.monotonic() - self._last_flush) >= self.FLUSH_INTERVAL
        )

    async def flush(self) -> int:
        async with self._flush_lock:
            if not self._buffer:
                return 0
            batch = self._buffer[:]
            self._buffer.clear()

        return await self._insert_with_retry(batch)

    async def _insert_with_retry(self, batch: list[BarEvent]) -> int:
        df = _events_to_dataframe(batch)
        loop = asyncio.get_running_loop()

        for attempt in range(self.MAX_RETRIES):
            try:
                success = await loop.run_in_executor(None, self._table.insert, df)
                if success:
                    self._last_flush = time.monotonic()
                    self._logger.info(f"Flushed {len(batch)} bars to ClickHouse")
                    return len(batch)
                raise RuntimeError("insert() returned False")
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    self._logger.warning(
                        f"ClickHouse insert failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}, "
                        f"retry in {delay}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    self._logger.error(
                        f"ClickHouse insert failed after {self.MAX_RETRIES} retries, "
                        f"dropping {len(batch)} bars: {e}"
                    )
        return 0


def _events_to_dataframe(events: list[BarEvent]) -> pd.DataFrame:
    rows = [
        {
            "symbol": e.symbol,
            "type": e.type,
            "dt": e.dt,
            "bar_time": e.bar_time,
            "pre_close": e.pre_close,
            "open": e.open,
            "high": e.high,
            "low": e.low,
            "close": e.close,
            "volume": e.volume,
            "amount": e.amount,
            "open_interest": e.open_interest,
            "settle": e.settle,
            "pre_settle": e.pre_settle,
            "local_time": e.local_time,
            "provider": e.provider,
        }
        for e in events
    ]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    from datetime import date, datetime
    from import_data.realtime.models import BarEvent

    events = [
        BarEvent(
            symbol="600000.SH",
            type="stock",
            dt=date.today(),
            bar_time=datetime.now(),
            open=10.0,
            close=10.5,
        )
    ]
    df = _events_to_dataframe(events)
    print(df)
    print(df.dtypes)
