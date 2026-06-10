"""stream 层基类与通用模型。

stream 职责：订阅供应商实时行情 → 归一化为 TickEvent → 写 realtime.tick_buffer（PG）。
与 ingest 一样受 OwnershipManager 约束（channel='stream'，单表单一 provider）。

实时 SDK 多以「后台线程回调」方式推送，CallbackBridge 把回调事件搬到主消费循环；
PgTickWriter 批量 upsert 进 PG。本层不依赖具体 SDK，provider 子类提供订阅与回调解析。
"""

from __future__ import annotations

import abc
import queue
import threading
from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from getrich_data.common.logging import get_logger
from getrich_data.common.ownership import OwnershipManager

REALTIME_TARGET = "realtime.tick_buffer"


@dataclass(slots=True)
class TickEvent:
    """归一化的实时行情事件，对齐 realtime.tick_buffer。"""

    instrument_id: int
    dt: datetime
    trading_day: date | None = None
    last: float | None = None
    volume: int | None = None
    amount: float | None = None
    bid1: float | None = None
    ask1: float | None = None
    bid_vol1: int | None = None
    ask_vol1: int | None = None
    open_interest: int | None = None
    source: str = ""


class CallbackBridge:
    """把 SDK 后台线程的回调事件搬运到主消费循环（线程安全队列）。"""

    def __init__(self, max_size: int = 50_000):
        self._q: queue.Queue[TickEvent | None] = queue.Queue(maxsize=max_size)
        self._stop = threading.Event()

    def put(self, event: TickEvent) -> None:
        try:
            self._q.put_nowait(event)
        except queue.Full:
            get_logger("stream.bridge").warning("事件队列已满，丢弃一条 tick（source=%s）", event.source)

    def drain(self, timeout: float = 1.0, max_batch: int = 1000) -> list[TickEvent]:
        out: list[TickEvent] = []
        try:
            first = self._q.get(timeout=timeout)
            if first is not None:
                out.append(first)
        except queue.Empty:
            return out
        while len(out) < max_batch:
            try:
                ev = self._q.get_nowait()
            except queue.Empty:
                break
            if ev is not None:
                out.append(ev)
        return out

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()


class BaseStreamHandler(abc.ABC):
    """provider 实时处理器基类。"""

    PROVIDER: str = ""

    def __init__(self, conn: psycopg.Connection, bridge: CallbackBridge | None = None):
        self.conn = conn
        self.bridge = bridge or CallbackBridge()
        self.log = get_logger(f"stream.{self.PROVIDER}")

    def claim_ownership(self, *, force: bool = False) -> None:
        """登记 realtime.tick_buffer 归属（channel='stream'）。"""
        OwnershipManager(self.conn).claim(
            REALTIME_TARGET, self.PROVIDER, channel="stream", force=force
        )
        self.conn.commit()

    @abc.abstractmethod
    def subscribe(self, symbols: list[str]) -> None:
        """向供应商订阅 symbols；回调中构造 TickEvent 投入 self.bridge。"""
        raise NotImplementedError
