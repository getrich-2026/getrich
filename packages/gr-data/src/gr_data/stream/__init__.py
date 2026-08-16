"""stream 层：供应商实时行情 → realtime.tick_buffer（PG）。"""

from gr_data.stream.base import BaseStreamHandler, CallbackBridge, TickEvent
from gr_data.stream.writer import PgTickWriter


PROVIDERS = ("yinhe", "insight")


def get_handler(provider: str):
    if provider == "yinhe":
        from gr_data.stream.yinhe import YinheStreamHandler

        return YinheStreamHandler
    if provider == "insight":
        from gr_data.stream.insight import InsightStreamHandler

        return InsightStreamHandler
    raise ValueError(f"未知 stream provider: {provider}")


__all__ = [
    "BaseStreamHandler",
    "CallbackBridge",
    "TickEvent",
    "PgTickWriter",
    "PROVIDERS",
    "get_handler",
]
