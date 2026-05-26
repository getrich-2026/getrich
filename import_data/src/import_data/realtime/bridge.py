from __future__ import annotations

import asyncio

from import_data.core.logger import Logger
from import_data.realtime.models import BarEvent


class CallbackBridge:
    """将 SDK 后台线程的 on_bar 回调安全投递到 asyncio 事件循环。

    SDK 在其私有线程调用 put_nowait_threadsafe()，
    通过 loop.call_soon_threadsafe 把 queue.put_nowait 调度到事件循环线程执行，
    保证 asyncio.Queue 只被事件循环线程修改。
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, maxsize: int = 50_000) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[BarEvent] = asyncio.Queue(maxsize=maxsize)
        self._logger = Logger("CallbackBridge")

    def put_nowait_threadsafe(self, event: BarEvent) -> None:
        """从任意线程（SDK 回调线程）调用。队列满时丢弃并记录警告（背压保护）。"""
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except asyncio.QueueFull:
            self._logger.warning(
                f"Queue full, dropping bar: {event.symbol} {event.bar_time}"
            )

    async def get(self) -> BarEvent:
        return await self._queue.get()

    async def drain(self, max_items: int = 100_000) -> list[BarEvent]:
        """批量取出剩余事件，用于关闭前排空。"""
        items: list[BarEvent] = []
        for _ in range(max_items):
            try:
                items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return items

    @property
    def qsize(self) -> int:
        return self._queue.qsize()


if __name__ == "__main__":
    import asyncio
    from datetime import date, datetime
    from import_data.realtime.models import BarEvent

    async def _demo() -> None:
        loop = asyncio.get_running_loop()
        bridge = CallbackBridge(loop, maxsize=10)
        event = BarEvent(
            symbol="600000.SH",
            type="stock",
            dt=date.today(),
            bar_time=datetime.now(),
            close=10.5,
        )
        bridge.put_nowait_threadsafe(event)
        await asyncio.sleep(0)
        received = await bridge.get()
        print(f"received: {received.symbol} close={received.close}")

    asyncio.run(_demo())
