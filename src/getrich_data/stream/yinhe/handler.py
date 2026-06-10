"""银河 AmazingData 实时行情处理器。

真实集成点：银河实时订阅以后台线程回调推送行情。subscribe() 注册回调，
回调中把 SDK bar 解析为 TickEvent 并投入 bridge。SDK 通过依赖注入传入（_sdk），
便于测试用 Fake 驱动整条链路。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from getrich_data.stream.base import BaseStreamHandler, CallbackBridge, TickEvent


class YinheStreamHandler(BaseStreamHandler):
    PROVIDER = "yinhe"

    def __init__(
        self,
        conn: psycopg.Connection,
        sdk: Any | None = None,
        bridge: CallbackBridge | None = None,
        symbol_to_id: dict[str, int] | None = None,
    ):
        super().__init__(conn, bridge)
        self._sdk = sdk
        # source_symbol(htsc_code) -> instrument_id
        self._symbol_to_id = symbol_to_id or {}

    def _on_tick(self, raw: Any) -> None:
        """SDK 回调：把原始行情解析为 TickEvent 投入 bridge。"""
        code = getattr(raw, "htsc_code", None) or getattr(raw, "symbol", None)
        iid = self._symbol_to_id.get(str(code))
        if iid is None:
            return
        ts = getattr(raw, "time", None)
        dt = ts if isinstance(ts, datetime) else datetime.now()
        self.bridge.put(
            TickEvent(
                instrument_id=iid,
                dt=dt,
                last=getattr(raw, "last", None) or getattr(raw, "close", None),
                volume=getattr(raw, "volume", None),
                amount=getattr(raw, "value", None) or getattr(raw, "amount", None),
                bid1=getattr(raw, "bid1", None),
                ask1=getattr(raw, "ask1", None),
                bid_vol1=getattr(raw, "bid_vol1", None),
                ask_vol1=getattr(raw, "ask_vol1", None),
                open_interest=getattr(raw, "open_interest", None),
                source=self.PROVIDER,
            )
        )

    def subscribe(self, symbols: list[str]) -> None:
        if self._sdk is None:
            raise RuntimeError(
                "未注入 银河实时 SDK。生产环境请传入已登录的 SDK 句柄。"
            )
        # 真实 SDK 形如：self._sdk.subscribe(symbols, callback=self._on_tick)
        self._sdk.subscribe(symbols, callback=self._on_tick)
        self.log.info("已订阅 %d 个标的的实时行情", len(symbols))
