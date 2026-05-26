from __future__ import annotations

import asyncio
import threading
from datetime import date, datetime

from import_data.realtime.bridge import CallbackBridge
from import_data.realtime.models import BarEvent


def _make_event(symbol: str = "600000.SH") -> BarEvent:
    return BarEvent(
        symbol=symbol,
        type="stock",
        dt=date.today(),
        bar_time=datetime.now(),
        close=10.5,
        provider="insight",
    )


def test_put_and_get_same_thread():
    async def _run():
        loop = asyncio.get_running_loop()
        bridge = CallbackBridge(loop, maxsize=100)
        event = _make_event()
        bridge.put_nowait_threadsafe(event)
        await asyncio.sleep(0)  # 让 call_soon_threadsafe 执行
        received = await asyncio.wait_for(bridge.get(), timeout=1.0)
        assert received.symbol == event.symbol
        assert received.close == event.close

    asyncio.run(_run())


def test_threadsafe_from_another_thread():
    async def _run():
        loop = asyncio.get_running_loop()
        bridge = CallbackBridge(loop, maxsize=100)
        events = [_make_event(f"6000{i:02d}.SH") for i in range(5)]

        def _producer():
            for e in events:
                bridge.put_nowait_threadsafe(e)

        t = threading.Thread(target=_producer)
        t.start()
        t.join()
        await asyncio.sleep(0.05)

        received = await bridge.drain(max_items=10)
        assert len(received) == 5
        symbols = {e.symbol for e in received}
        assert symbols == {e.symbol for e in events}

    asyncio.run(_run())


def test_drain_empty():
    async def _run():
        loop = asyncio.get_running_loop()
        bridge = CallbackBridge(loop)
        result = await bridge.drain()
        assert result == []

    asyncio.run(_run())
