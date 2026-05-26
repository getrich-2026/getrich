from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from threading import RLock
from typing import Any

from import_data.core.logger import Logger
from import_data.core.config import settings

from .database import ClickHouseClient


class PooledConnection:
    """池化连接包装器"""

    def __init__(self, client: ClickHouseClient, pool: ClickHouseConnectionPool):
        """
        初始化池化连接。
        """
        self.client = client
        self.pool = pool
        self.in_use = False
        self.created_at = time.time()
        self.last_used = time.time()
        self.use_count = 0

    def mark_in_use(self) -> None:
        """标记为使用中"""
        self.in_use = True
        self.last_used = time.time()
        self.use_count += 1

    def mark_available(self) -> None:
        """标记为可用"""
        self.in_use = False
        self.last_used = time.time()

    def is_expired(self, max_age: float) -> bool:
        """检查连接是否过期。"""
        return (time.time() - self.created_at) > max_age

    def is_idle_timeout(self, idle_timeout: float) -> bool:
        """检查连接是否空闲超时。"""
        return (time.time() - self.last_used) > idle_timeout

    def close(self) -> None:
        """关闭连接"""
        if self.client:
            self.client.close()


class ClickHouseConnectionPool:
    """
    ClickHouse 连接池。
    """

    def __init__(
        self,
        min_size: int = 2,
        max_size: int = 10,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        max_idle_time: float = 300.0,
        max_lifetime: float = 3600.0,
        connect_timeout: float = 10.0,
        health_check_interval: float = 60.0,
    ):
        """
        初始化连接池。
        """
        if min_size < 1:
            raise ValueError("min_size must be at least 1")
        if max_size < min_size:
            raise ValueError("max_size must be >= min_size")

        self.min_size = min_size
        self.max_size = max_size
        self.max_idle_time = max_idle_time
        self.max_lifetime = max_lifetime
        self.connect_timeout = connect_timeout
        self.health_check_interval = health_check_interval

        # 连接配置
        self._config: dict[str, Any] = {
            "host": host or settings.clickhouse.host,
            "port": port or settings.clickhouse.port,
            "user": user or settings.clickhouse.user,
            "password": password or settings.clickhouse.password,
            "database": database or settings.clickhouse.database,
        }
        self._config = {k: v for k, v in self._config.items() if v is not None}

        # 连接池
        self._pool: list[PooledConnection] = []
        self._lock = RLock()

        # 统计信息
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "get_requests": 0,
            "get_timeouts": 0,
            "connections_created": 0,
            "connections_closed": 0,
            "health_checks": 0,
            "failed_health_checks": 0,
        }

        # 日志
        self.logger = Logger("ClickHouseConnectionPool")

        # 初始化最小连接数
        self._initialize_pool()

        self.logger.info(
            f"Connection pool initialized: min={min_size}, max={max_size}, "
            f"config={self._get_config_display()}"
        )

    def _get_config_display(self) -> str:
        """获取配置显示字符串(隐藏密码)"""
        config = self._config.copy()
        if "password" in config:
            config["password"] = "***"
        return str(config)

    def _initialize_pool(self) -> None:
        """初始化连接池到最小连接数"""
        with self._lock:
            for _ in range(self.min_size):
                conn = self._create_connection()
                if conn:
                    self._pool.append(conn)

    def _create_connection(self) -> PooledConnection | None:
        """创建新连接。"""
        try:
            client = ClickHouseClient(**self._config)
            if not client.is_connected():
                self.logger.error("Failed to create connection")
                return None

            pooled_conn = PooledConnection(client, self)
            self._stats["total_connections"] += 1
            self._stats["connections_created"] += 1
            self.logger.debug(
                f"Created new connection (total: {self._stats['total_connections']})"
            )
            return pooled_conn
        except Exception as e:
            self.logger.error(f"Error creating connection: {e}")
            return None

    def get_connection(self, timeout: float | None = None) -> ClickHouseClient:
        """从池中获取连接。"""
        timeout = timeout or self.connect_timeout
        start_time = time.time()

        self._stats["get_requests"] += 1

        while True:
            with self._lock:
                for conn in self._pool:
                    if not conn.in_use:
                        if self._is_connection_healthy(conn):
                            conn.mark_in_use()
                            self._stats["active_connections"] += 1
                            self.logger.debug(
                                f"Reused connection (active: {self._stats['active_connections']})"
                            )
                            return conn.client
                        else:
                            self._remove_connection(conn)

                if len(self._pool) < self.max_size:
                    new_conn = self._create_connection()
                    if new_conn:
                        self._pool.append(new_conn)
                        new_conn.mark_in_use()
                        self._stats["active_connections"] += 1
                        self.logger.debug(
                            f"Created new connection (total: {len(self._pool)})"
                        )
                        return new_conn.client

            elapsed = time.time() - start_time
            if elapsed >= timeout:
                self._stats["get_timeouts"] += 1
                raise TimeoutError(
                    f"Could not get connection within {timeout}s "
                    f"(pool size: {len(self._pool)}/{self.max_size})"
                )

            time.sleep(0.01)

    def release_connection(self, client: ClickHouseClient) -> None:
        """释放连接回池中。"""
        with self._lock:
            for conn in self._pool:
                if conn.client is client:
                    if conn.in_use:
                        conn.mark_available()
                        self._stats["active_connections"] -= 1
                        self.logger.debug(
                            f"Released connection (active: {self._stats['active_connections']})"
                        )
                    return
            self.logger.warning("Attempted to release connection not in pool")

    @contextmanager
    def connection(
        self, timeout: float | None = None
    ) -> Generator[ClickHouseClient, None, None]:
        """获取连接的上下文管理器。"""
        client = self.get_connection(timeout)
        try:
            yield client
        finally:
            self.release_connection(client)

    def _is_connection_healthy(self, conn: PooledConnection) -> bool:
        """检查连接是否健康。"""
        if conn.is_expired(self.max_lifetime):
            self.logger.debug("Connection expired (max lifetime)")
            return False

        if conn.is_idle_timeout(self.max_idle_time):
            self.logger.debug("Connection idle timeout")
            return False

        if not conn.client.is_connected():
            self.logger.debug("Connection not connected")
            return False

        return True

    def _remove_connection(self, conn: PooledConnection) -> None:
        """从池中移除连接。"""
        try:
            conn.close()
            self._pool.remove(conn)
            self._stats["total_connections"] -= 1
            self._stats["connections_closed"] += 1
            self.logger.debug(
                f"Removed connection (total: {self._stats['total_connections']})"
            )
        except Exception as e:
            self.logger.error(f"Error removing connection: {e}")

    def shrink(self) -> None:
        """收缩连接池到最小连接数。"""
        with self._lock:
            idle_connections = [c for c in self._pool if not c.in_use]
            current_size = len(self._pool)
            target_size = max(self.min_size, self._stats["active_connections"])
            to_close = current_size - target_size

            if to_close > 0:
                idle_connections.sort(key=lambda c: c.last_used)
                for conn in idle_connections[:to_close]:
                    self._remove_connection(conn)

                self.logger.info(
                    f"Shrank pool from {current_size} to {len(self._pool)} connections"
                )

    def cleanup(self) -> None:
        """清理过期和空闲超时的连接。"""
        with self._lock:
            to_remove = []
            for conn in self._pool:
                if conn.in_use:
                    continue
                if not self._is_connection_healthy(conn):
                    to_remove.append(conn)

            for conn in to_remove:
                self._remove_connection(conn)

            while len(self._pool) < self.min_size:
                new_conn = self._create_connection()
                if new_conn:
                    self._pool.append(new_conn)
                else:
                    break

            if to_remove:
                self.logger.info(
                    f"Cleaned up {len(to_remove)} connections, pool size: {len(self._pool)}"
                )

    def health_check(self) -> None:
        """执行健康检查。"""
        with self._lock:
            self._stats["health_checks"] += 1
            for conn in self._pool[:]:
                if conn.in_use:
                    continue
                try:
                    result = conn.client.query("SELECT 1 as test")
                    if result.empty:
                        self._stats["failed_health_checks"] += 1
                        self._remove_connection(conn)
                except Exception as e:
                    self.logger.warning(f"Health check failed: {e}")
                    self._stats["failed_health_checks"] += 1
                    self._remove_connection(conn)

    def close_all(self) -> None:
        """关闭所有连接并清空连接池"""
        with self._lock:
            for conn in self._pool[:]:
                conn.close()

            closed_count = len(self._pool)
            self._pool.clear()
            self._stats["total_connections"] = 0
            self._stats["active_connections"] = 0
            self.logger.info(f"Closed all {closed_count} connections")

    def get_stats(self) -> dict[str, Any]:
        """获取连接池统计信息。"""
        with self._lock:
            stats = self._stats.copy()
            stats["pool_size"] = len(self._pool)
            stats["idle_connections"] = len([c for c in self._pool if not c.in_use])
            return stats

    def __enter__(self) -> ClickHouseConnectionPool:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        self.close_all()

    def __repr__(self) -> str:
        return (
            f"ClickHouseConnectionPool("
            f"size={len(self._pool)}/{self.max_size}, "
            f"active={self._stats['active_connections']}, "
            f"config={self._get_config_display()}"
            ")"
        )
