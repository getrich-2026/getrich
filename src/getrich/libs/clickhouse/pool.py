"""
ClickHouse 连接池

提供连接池管理功能,支持连接复用、自动重连、负载均衡等特性。
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from threading import RLock
from typing import Any

from lntools.utils import Logger

from getrich.config.settings import settings

from .database import ClickHouseClient


class PooledConnection:
    """池化连接包装器"""

    def __init__(self, client: ClickHouseClient, pool: ClickHouseConnectionPool):
        """
        初始化池化连接。

        Args:
            client: ClickHouse 客户端实例
            pool: 所属的连接池
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
        """
        检查连接是否过期。

        Args:
            max_age: 最大生命周期(秒)

        Returns:
            已过期返回 True
        """
        return (time.time() - self.created_at) > max_age

    def is_idle_timeout(self, idle_timeout: float) -> bool:
        """
        检查连接是否空闲超时。

        Args:
            idle_timeout: 空闲超时时间(秒)

        Returns:
            空闲超时返回 True
        """
        return (time.time() - self.last_used) > idle_timeout

    def close(self) -> None:
        """关闭连接"""
        if self.client:
            self.client.close()


class ClickHouseConnectionPool:
    """
    ClickHouse 连接池。

    功能:
    - 连接复用:减少连接创建开销
    - 自动扩容:根据需求动态增加连接
    - 连接回收:自动清理空闲/过期连接
    - 健康检查:定期检查连接可用性
    - 线程安全:支持多线程环境

    使用方式:
        # 创建连接池
        pool = ClickHouseConnectionPool(
            min_size=2,
            max_size=10,
            host='192.168.1.232'
        )

        # 方式1:手动获取/释放
        client = pool.get_connection()
        try:
            df = client.query(sql)
        finally:
            pool.release_connection(client)

        # 方式2:使用上下文管理器(推荐)
        with pool.connection() as client:
            df = client.query(sql)
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
        max_idle_time: float = 300.0,  # 5分钟
        max_lifetime: float = 3600.0,  # 1小时
        connect_timeout: float = 10.0,
        health_check_interval: float = 60.0,  # 1分钟
    ):
        """
        初始化连接池。

        Args:
            min_size: 最小连接数
            max_size: 最大连接数
            host: ClickHouse 主机地址
            port: ClickHouse 端口
            user: 用户名
            password: 密码
            database: 数据库名
            max_idle_time: 连接最大空闲时间(秒)
            max_lifetime: 连接最大生命周期(秒)
            connect_timeout: 获取连接超时时间(秒)
            health_check_interval: 健康检查间隔(秒)
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

        # 连接配置：优先使用传入参数，否则回退到 DEFAULT_DB_CONFIG
        self._config: dict[str, Any] = {
            "host": host or settings.clickhouse.host,
            "port": port or settings.clickhouse.port,
            "user": user or settings.clickhouse.user,
            "password": password or settings.clickhouse.password,
            "database": database or settings.clickhouse.database,
        }
        # 过滤 None 值 (虽然有了默认值通常不会是None，但为了健壮性保留)
        self._config = {k: v for k, v in self._config.items() if v is not None}

        # 连接池
        self._pool: list[PooledConnection] = []
        self._lock = RLock()  # 可重入锁

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
        self.logger = Logger(module_name="ClickHouseConnectionPool")

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
        """
        创建新连接。

        Returns:
            创建成功返回 PooledConnection,否则返回 None
        """
        try:
            client = ClickHouseClient(**self._config)
            if not client.is_connected():
                self.logger.error("Failed to create connection")
                return None

            pooled_conn = PooledConnection(client, self)

            self._stats["total_connections"] += 1
            self._stats["connections_created"] += 1

            self.logger.debug(f"Created new connection (total: {self._stats['total_connections']})")

            return pooled_conn
        except Exception as e:
            self.logger.error(f"Error creating connection: {e}")
            return None

    def get_connection(self, timeout: float | None = None) -> ClickHouseClient:
        """
        从池中获取连接。

        Args:
            timeout: 获取超时时间(秒),None 使用默认值

        Returns:
            ClickHouse 客户端实例

        Raises:
            TimeoutError: 获取连接超时
            RuntimeError: 无法创建连接
        """
        timeout = timeout or self.connect_timeout
        start_time = time.time()

        self._stats["get_requests"] += 1

        while True:
            with self._lock:
                # 1. 尝试获取空闲连接
                for conn in self._pool:
                    if not conn.in_use:
                        # 检查连接健康
                        if self._is_connection_healthy(conn):
                            conn.mark_in_use()
                            self._stats["active_connections"] += 1
                            self.logger.debug(
                                f"Reused connection (active: {self._stats['active_connections']})"
                            )
                            return conn.client
                        else:
                            # 移除不健康的连接
                            self._remove_connection(conn)

                # 2. 如果没有空闲连接,尝试创建新连接
                if len(self._pool) < self.max_size:
                    new_conn = self._create_connection()
                    if new_conn:
                        self._pool.append(new_conn)
                        new_conn.mark_in_use()
                        self._stats["active_connections"] += 1
                        self.logger.debug(f"Created new connection (total: {len(self._pool)})")
                        return new_conn.client

            # 3. 达到最大连接数,等待连接释放
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                self._stats["get_timeouts"] += 1
                raise TimeoutError(
                    f"Could not get connection within {timeout}s "
                    f"(pool size: {len(self._pool)}/{self.max_size})"
                )

            # 短暂等待后重试
            time.sleep(0.01)

    def release_connection(self, client: ClickHouseClient) -> None:
        """
        释放连接回池中。

        Args:
            client: 要释放的客户端
        """
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
    def connection(self, timeout: float | None = None) -> Generator[ClickHouseClient, None, None]:
        """
        获取连接的上下文管理器。

        Args:
            timeout: 获取超时时间(秒)

        Yields:
            ClickHouse 客户端实例

        Example:
            with pool.connection() as client:
                df = client.query(sql)
        """
        client = self.get_connection(timeout)
        try:
            yield client
        finally:
            self.release_connection(client)

    def _is_connection_healthy(self, conn: PooledConnection) -> bool:
        """
        检查连接是否健康。

        Args:
            conn: 池化连接

        Returns:
            健康返回 True
        """
        # 检查是否过期
        if conn.is_expired(self.max_lifetime):
            self.logger.debug("Connection expired (max lifetime)")
            return False

        # 检查是否空闲超时
        if conn.is_idle_timeout(self.max_idle_time):
            self.logger.debug("Connection idle timeout")
            return False

        # 检查连接是否有效
        if not conn.client.is_connected():
            self.logger.debug("Connection not connected")
            return False

        return True

    def _remove_connection(self, conn: PooledConnection) -> None:
        """
        从池中移除连接。

        Args:
            conn: 要移除的连接
        """
        try:
            conn.close()
            self._pool.remove(conn)
            self._stats["total_connections"] -= 1
            self._stats["connections_closed"] += 1
            self.logger.debug(f"Removed connection (total: {self._stats['total_connections']})")
        except Exception as e:
            self.logger.error(f"Error removing connection: {e}")

    def shrink(self) -> None:
        """
        收缩连接池到最小连接数。

        关闭超过最小数量的空闲连接。
        """
        with self._lock:
            idle_connections = [c for c in self._pool if not c.in_use]

            # 计算需要关闭的连接数
            current_size = len(self._pool)
            target_size = max(self.min_size, self._stats["active_connections"])
            to_close = current_size - target_size

            if to_close > 0:
                # 关闭最老的空闲连接
                idle_connections.sort(key=lambda c: c.last_used)
                for conn in idle_connections[:to_close]:
                    self._remove_connection(conn)

                self.logger.info(
                    f"Shrank pool from {current_size} to {len(self._pool)} connections"
                )

    def cleanup(self) -> None:
        """
        清理过期和空闲超时的连接。
        """
        with self._lock:
            to_remove = []

            for conn in self._pool:
                if conn.in_use:
                    continue

                if not self._is_connection_healthy(conn):
                    to_remove.append(conn)

            for conn in to_remove:
                self._remove_connection(conn)

            # 确保至少有最小数量的连接
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
        """
        执行健康检查。

        检查所有连接的健康状态,移除不健康的连接。
        """
        with self._lock:
            self._stats["health_checks"] += 1

            for conn in self._pool[:]:  # 复制列表以安全删除
                if conn.in_use:
                    continue

                try:
                    # 执行简单查询测试连接
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
        """
        获取连接池统计信息。

        Returns:
            统计信息字典
        """
        with self._lock:
            stats = self._stats.copy()
            stats["pool_size"] = len(self._pool)
            stats["idle_connections"] = len([c for c in self._pool if not c.in_use])
            return stats

    def __enter__(self) -> ClickHouseConnectionPool:
        """支持上下文管理器"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """退出上下文管理器时关闭所有连接"""
        self.close_all()

    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"ClickHouseConnectionPool("
            f"size={len(self._pool)}/{self.max_size}, "
            f"active={self._stats['active_connections']}, "
            f"config={self._get_config_display()}"
            ")"
        )
