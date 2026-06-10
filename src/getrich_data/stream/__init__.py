"""stream 层：供应商实时行情 → realtime.tick_buffer（PG）。"""

from getrich_data.stream.base import BaseStreamHandler, CallbackBridge, TickEvent
from getrich_data.stream.writer import PgTickWriter

PROVIDERS = ("yinhe", "insight")


def get_handler(provider: str):
    if provider == "yinhe":
        from getrich_data.stream.yinhe import YinheStreamHandler
        return YinheStreamHandler
    if provider == "insight":
        from getrich_data.stream.insight import InsightStreamHandler
        return InsightStreamHandler
    raise ValueError(f"未知 stream provider: {provider}")


__all__ = ["BaseStreamHandler", "CallbackBridge", "TickEvent", "PgTickWriter",
           "PROVIDERS", "get_handler"]
