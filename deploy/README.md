# 基础设施部署模板

本目录保存 GetRich 依赖的 PostgreSQL／TimescaleDB、ClickHouse 和 Redis 的可复现部署定义。它是**部署模板**，不是 GetRich 应用的一部分，也不应在 GetRich 仓库内直接创建或运行 Docker 实例。

```text
deploy/
├── docker-compose.yml
├── .env.example
└── config/
    ├── postgres/postgresql.conf
    ├── clickhouse/logger.xml
    └── redis/redis.conf
```

## 使用边界

- GetRich 仓库负责版本控制 Compose、镜像版本和数据库配置。
- 仓库外的部署目录负责真实 `.env`、数据卷、日志、备份和运维脚本。
- 不要把真实密码、主机绝对路径或运行数据写回本目录。
- 修改本目录后，需要把目录中的文件同步到实际部署目录根，并在部署目录中完成校验和重启。外部目录不再嵌套一层 `deploy/`。

## 建立外部部署目录

下面以 `/opt/getrich-docker` 为例；本机可以换成其他仓库外路径。`rsync` 源路径末尾的 `/` 表示复制 `deploy/` 中的内容，而不是复制 `deploy/` 目录本身：

```bash
mkdir -p /opt/getrich-docker
rsync -av --exclude '.env' --exclude '.docker/' deploy/ /opt/getrich-docker/
cd /opt/getrich-docker
cp .env.example .env
```

编辑部署目录中的 `.env`，至少替换三个 `change-me-deployment-only` 密码，并按服务器磁盘规划设置数据和日志目录。之后只在部署目录执行：

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
```

更新模板时再次同步，但不要覆盖部署目录中的真实 `.env` 和 `.docker/` 数据目录。

## 配置说明

### PostgreSQL

`config/postgres/postgresql.conf` 先加载数据目录内由 `timescaledb-tune` 生成的配置，再覆盖时区、日志、WAL、查询规划和事务设置。`timescaledb-tune` 只在数据目录首次初始化时运行；更换服务器规格后需要重新调优。

Linux 宿主机上的 PostgreSQL 日志目录必须允许容器内 `postgres` 用户写入。当前 TimescaleDB 镜像中的 UID 为 `70`，目录属主错误会导致数据库启动失败。

### ClickHouse

`config/clickhouse/logger.xml` 固定使用 `Asia/Shanghai` 时区，限制服务器日志轮转，并将主要 `system.*_log` 表的 TTL 设为 7 天。修改已有实例的 TTL 后，需要检查被重命名的旧系统日志表是否仍占用磁盘。

### Redis

`config/redis/redis.conf` 使用 AOF、关闭 RDB，并采用 `noeviction`。内存达到 `REDIS_MAXMEMORY` 后写入会明确失败，不会静默淘汰分布式锁或限流计数器。缓存 key 必须自行设置 TTL。

## 安全提醒

- 数据库端口默认只绑定 `127.0.0.1`；不要在没有防火墙和访问控制的情况下暴露到公网。
- Redis 密码通过 Compose 命令参数传入，可能出现在 `docker inspect` 或宿主机进程信息中。
- 部署目录应配置备份、磁盘告警和日志轮转；这些运行态内容不属于 GetRich 仓库。
