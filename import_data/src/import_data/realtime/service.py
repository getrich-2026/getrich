from __future__ import annotations

import asyncio
import signal

from import_data.core.config import settings
from import_data.core.logger import Logger
from import_data.db.clickhouse.pool import ClickHouseConnectionPool
from import_data.realtime.bridge import CallbackBridge
from import_data.realtime.clickhouse_writer import ClickHouseBarWriter
from import_data.realtime.insight_handler import InsightBarHandler
from import_data.realtime.redis_writer import RedisStreamWriter

try:
    import redis.asyncio as aioredis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class RealtimeService:
    """实时 1 分钟 K 线订阅落地服务。

    数据流：
      Insight SDK（后台线程）
        → CallbackBridge（asyncio.Queue）
        → _consume_loop（asyncio）
        → RedisStreamWriter（实时分发）
        → ClickHouseBarWriter（持久化）

    优雅关闭：
      SIGTERM → _shutdown_event.set() → drain queue → flush ClickHouse → exit
    """

    FLUSH_TIMER_INTERVAL = 30.0  # ClickHouse 定时 flush 间隔（秒）

    def __init__(self) -> None:
        self._logger = Logger("RealtimeService")
        self._shutdown_event = asyncio.Event()

    async def start(self, symbols: list[str]) -> None:
        loop = asyncio.get_running_loop()

        # 初始化 ClickHouse 连接池
        ch_cfg = settings.clickhouse
        self._pool = ClickHouseConnectionPool(
            min_size=2,
            max_size=4,
            host=ch_cfg.host,
            port=ch_cfg.port,
            user=ch_cfg.user,
            password=ch_cfg.password,
            database=ch_cfg.database,
        )

        # 初始化 Redis 客户端
        if HAS_REDIS:
            redis_cfg = settings.redis
            password = redis_cfg.password or None
            self._redis = aioredis.from_url(
                f"redis://{redis_cfg.host}:{redis_cfg.port}/{redis_cfg.db}",
                password=password,
                decode_responses=True,
            )
        else:
            self._redis = None
            self._logger.warning("redis[asyncio] not installed, Redis writes disabled")

        # 初始化组件
        self._bridge = CallbackBridge(loop)
        self._redis_writer = RedisStreamWriter(self._redis) if self._redis else None
        self._ch_writer = ClickHouseBarWriter(self._pool)
        self._handler = InsightBarHandler(self._bridge)

        # SIGTERM 优雅关闭
        loop.add_signal_handler(signal.SIGTERM, self._handle_sigterm)

        # 向 SDK 注册订阅
        self._handler.subscribe(symbols)

        self._logger.info(
            f"RealtimeService started, subscribed to {len(symbols)} symbols"
        )

        # 并发运行消费循环和定时 flush
        await asyncio.gather(
            self._consume_loop(),
            self._flush_timer(),
        )

    async def _consume_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                event = await asyncio.wait_for(self._bridge.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            writers = []
            if self._redis_writer:
                writers.append(self._redis_writer.write(event))
            writers.append(self._ch_writer.write(event))

            await asyncio.gather(*writers, return_exceptions=True)

        # 关闭前排空队列
        remaining = await self._bridge.drain()
        if remaining:
            self._logger.info(
                f"Draining {len(remaining)} remaining events before shutdown"
            )
            for e in remaining:
                self._ch_writer._buffer.append(e)

        flushed = await self._ch_writer.flush()
        self._logger.info(f"Graceful shutdown complete, final flush: {flushed} bars")

    async def _flush_timer(self) -> None:
        while not self._shutdown_event.is_set():
            await asyncio.sleep(self.FLUSH_TIMER_INTERVAL)
            flushed = await self._ch_writer.flush()
            if flushed:
                self._logger.debug(f"Timer flush: {flushed} bars to ClickHouse")

    def _handle_sigterm(self) -> None:
        self._logger.info("SIGTERM received, initiating graceful shutdown")
        self._shutdown_event.set()

    async def shutdown(self) -> None:
        self._shutdown_event.set()


if __name__ == "__main__":
    # 仅打印配置，不实际连接
    print("RealtimeService module loaded.")
    print(f"Redis config: {settings.redis.host}:{settings.redis.port}")
    print(f"Insight enabled: {settings.insight.enabled}")
