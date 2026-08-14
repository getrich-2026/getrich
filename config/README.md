# 数据库配置定义

本目录是 `docker-compose.yml` 三个基础设施服务的**配置定义**，随仓库版本控制。
实际运行实例（真实 `.env`、数据卷、运维脚本）在仓库外的本机部署目录 —— 改完这里需要手动同步过去再重启。见 `.agent/brain/DECISIONS.md` D-012。

```
config/
├── postgres/
│   └── postgresql.conf     # PostgreSQL 完整配置（接管 timescaledb-tune）
├── clickhouse/
│   └── logger.xml          # ClickHouse 时区、日志轮转、system.*_log TTL
└── redis/
    └── redis.conf          # Redis 持久化、日志、淘汰策略
```

## PostgreSQL

通过 `postgres -c config_file=/etc/postgresql/postgresql.conf` **完整接管**配置，绕过镜像内 timescaledb-tune 写入 `$PGDATA/postgresql.conf` 的调优结果。

- **必须显式声明**：`shared_preload_libraries = 'timescaledb'`（否则扩展不加载）、`data_directory` / `hba_file` / `ident_file`（config_file 在 `$PGDATA` 之外时 PostgreSQL 无法推断）、`listen_addresses`。
- **时区**：`timezone` 与 `log_timezone` 均为 `Asia/Shanghai`，不依赖容器 `TZ` 环境变量隐式传递。
- **内存**：`shared_buffers` 512MB / `effective_cache_size` 1536MB 是本地开发默认值，部署实例按机器规格调整。
- **日志**：每天或满 100MB 轮转，`log_truncate_on_rotation=on` 自动覆盖旧文件；慢查询阈值 1s；`log_temp_files=0` 记录所有落盘临时文件，便于发现 `work_mem` 不足。
- **悬挂事务**：`idle_in_transaction_session_timeout = 10min`，避免长期持锁阻塞 vacuum。

## ClickHouse

- **时区**：显式 `<timezone>Asia/Shanghai</timezone>`。夜盘跨日数据依赖这一项，不要删。
- **服务器日志**：单文件 100MB、保留 10 个、JSON 格式。
- **`system.*_log` TTL**：`query_log`、`metric_log`、`asynchronous_metric_log`、`trace_log`、`part_log` 统一 7 天。其余表用 ClickHouse 自带默认值（多数 30 天），无需额外配置。
- **注意**：TTL 只在建表时生效。给已有实例改这个配置时，ClickHouse 会把旧表重命名后重建，**旧表仍占磁盘，需要手动 DROP**。

## Redis

- **淘汰策略 `noeviction`**：内存写满时写入直接报错，绝不静默淘汰 key。本实例混放 tick 缓存、跨进程状态、分布式锁和限流计数器，LRU 类策略会连锁一起淘汰，导致两个进程同时进临界区。详见 `DECISIONS.md` D-013。
- **容量**：`maxmemory` 由 compose 从 `REDIS_MAXMEMORY` 传入（默认 `2gb`），不写死在 conf 里。
- **持久化**：只开 AOF（`appendfsync everysec`），`save ""` 关闭 RDB 快照避免双写。
- **日志**：Redis 自身不支持轮转，依赖宿主机 logrotate 或部署目录的清理脚本。
- **密码**：由 compose 通过 `--requirepass` 命令行传入 —— 会出现在 `docker inspect` / `ps` 输出中。

## 常用操作

```bash
# 校验编排文件
docker compose config --quiet

# 改配置后重启单个服务
docker compose restart postgres
docker compose restart clickhouse
docker compose restart redis
```

`postgresql.conf` 中部分参数（`shared_buffers`、`max_connections`、`shared_preload_libraries`）需要**完整重启**才生效，`restart` 即可；`reload` 类参数改完可用 `SELECT pg_reload_conf();`。

## 运维提醒

1. 监控日志目录大小，避免磁盘占满。
2. 宿主机配置 logrotate 作为兜底，尤其是 Redis。
3. 定期检查 ClickHouse `system.*_log` 各表大小 —— 尤其是改过 TTL 后被重命名遗留的旧表。
4. 设置磁盘告警（建议剩余空间低于 20% 时触发）。
5. Linux 服务器上注意 bind-mount 目录属主：容器内进程写不了宿主机日志目录会导致启动失败或日志静默丢失。
