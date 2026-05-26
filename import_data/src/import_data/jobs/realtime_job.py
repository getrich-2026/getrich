from __future__ import annotations

import asyncio

from import_data.core.config import settings
from import_data.core.logger import Logger
from import_data.realtime.service import RealtimeService

log = Logger("realtime_job")


def run_realtime(symbols: list[str] | None = None) -> None:
    """实时 1 分钟 K 线订阅落地服务入口。

    symbols 默认从 settings.insight.default_symbols 读取。
    """
    target_symbols = symbols or getattr(settings.insight, "default_symbols", [])
    if not target_symbols:
        log.warning(
            "No symbols configured. Set INSIGHT_DEFAULT_SYMBOLS in .env or pass symbols list."
        )

    async def _main() -> None:
        svc = RealtimeService()
        await svc.start(target_symbols)

    asyncio.run(_main())


if __name__ == "__main__":
    run_realtime()
