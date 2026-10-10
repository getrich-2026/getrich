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
- 仓库外的部署目录负责真实 `.env`、日志、备份和运维脚本；数据在 Docker named volume 里，不在部署目录。
- 不要把真实密码、主机绝对路径或运行数据写回本目录。
- 修改本目录后，需要把目录中的文件同步到实际部署目录根，并在部署目录中完成校验和重启。外部目录不再嵌套一层 `deploy/`。
- 默认只启动 PostgreSQL。ClickHouse、Redis 分别在 `clickhouse`、`redis` profile 里，需要时用 `--profile` 或 `.env` 的 `COMPOSE_PROFILES` 启用。

## 建立外部部署目录

部署目录放在仓库外任意位置。下面用 `$DEPLOY_DIR` 指代，macOS 上须位于 Docker Desktop 的文件共享路径内（见下文）。`rsync` 源路径末尾的 `/` 表示复制 `deploy/` 中的内容，而不是复制 `deploy/` 目录本身：

```bash
DEPLOY_DIR="$HOME/getrich-docker"   # 按本机规划替换
mkdir -p "$DEPLOY_DIR"
rsync -av --exclude '.env' --exclude '.docker/' deploy/ "$DEPLOY_DIR/"
cd "$DEPLOY_DIR"
cp .env.example .env
```

编辑部署目录中的 `.env`：

- 替换全部 `change-me-deployment-only` 密码（可用 `openssl rand -hex 24`）。未启用的 CH／Redis 也要填非空值，Compose 会校验整个文件。
- 应用根目录 `.env` 的 `PG_USER`／`PG_PASSWORD`／`PG_DB`／`PG_PORT` 必须与这里一致。
- Docker Desktop 上与其他服务共用虚拟机时，设置 `PG_TUNE_MEMORY`／`PG_TUNE_NUM_CPUS`（见下文）；按应用进程数设置 `PG_TUNE_MAX_CONNS`。

之后只在部署目录执行：

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
```

首次启动后，在库内启用慢查询统计视图（运维扩展，不属于 gr-db 业务 DDL），再从仓库执行业务迁移：

```bash
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"'
```

更新模板时再次同步，但不要覆盖部署目录中的真实 `.env` 和 `.docker/` 日志目录。`config/` 会被整体覆盖，部署侧的个性化参数不要写在这里（见下文）。

停机时如果用 `--profile` 临时启动过 CH／Redis，停止也要带上 profile，或用 `docker compose --profile '*' stop` 停掉全部服务。长期启用的服务建议写进 `.env` 的 `COMPOSE_PROFILES`。

### 已有 PG17 数据卷的部署

2026-10-10 之前的模板使用 PG17，数据卷根目录就是数据目录。新模板把卷挂到 `/var/lib/postgresql`，旧卷会被 PG18 入口脚本识别为旧版本数据并拒绝启动，容器反复重启，但数据不会丢。升级步骤：

1. 用旧模板（PG17）仍在运行时 `pg_dump -Fc` 导出各库；
2. 同步新模板，把 `.env` 的 `POSTGRES_VOLUME_NAME` 改成新卷名，`POSTGRES_CONTAINER_NAME` 改为 `getrich-pg18`；
3. 启动新实例，执行 `SELECT timescaledb_pre_restore();` → `pg_restore` → `SELECT timescaledb_post_restore();`；
4. 校验数据后再删除旧卷。

## 首次初始化后不可更改的项

以下设置只在 named volume 为空、数据目录首次初始化时生效。之后修改 `.env` 或 Compose 不会改变已有实例；要改只能导出数据、删卷重建：

- `PG_USER`／`PG_PASSWORD`／`PG_DB`：改密码请在库内执行 `ALTER ROLE ... PASSWORD`，再同步两份 `.env`。
- `POSTGRES_INITDB_ARGS`：编码 UTF8、`builtin` C.UTF-8 排序规则、数据页校验和。
- `PG_TUNE_MEMORY`／`PG_TUNE_NUM_CPUS`／`PG_TUNE_MAX_CONNS`：`timescaledb-tune` 只在初始化时运行。更换机器规格后用 `ALTER SYSTEM SET shared_buffers = ...` 等调整（写入卷内 `postgresql.auto.conf`，不会被模板同步覆盖），不要改部署目录的 `config/postgresql.conf`。

## 配置说明

### PostgreSQL

使用 `timescale/timescaledb` 的非 `-oss` 镜像（Timescale License）。压缩、保留策略和后台作业只在该版本可用；`-oss` 版下 gr-db 的相关 DDL 会被 `EXCEPTION` 吞掉，迁移看似成功，但 1 分钟行情不压缩、`realtime.tick_buffer` 不按 7 天清理。Timescale License 允许自行部署和内部商用，禁止把 TimescaleDB 作为托管数据库服务对外提供。

PostgreSQL 18 镜像的数据目录是 `/var/lib/postgresql/18/docker`，named volume 挂在 `/var/lib/postgresql`。`config/postgres/postgresql.conf` 里的路径带大版本号，升级大版本时要和镜像一起改。

`config/postgres/postgresql.conf` 先加载数据目录内由 `timescaledb-tune` 生成的配置，再覆盖时区、日志、WAL、查询规划和事务设置。`timescaledb-tune` 默认按容器可见的全部内存和核数计算；Docker Desktop 上即整个虚拟机，与 CH／Redis 共用时会超卖内存，因此应设置 `PG_TUNE_MEMORY`／`PG_TUNE_NUM_CPUS`。

日志写入挂载的日志目录（`logging_collector` 开启），`docker compose logs postgres` 只能看到启动阶段输出。日志文件按星期命名，服务跨午夜运行时按天截断同名文件，长期运行下最多保留 7 天；若每天在午夜前停机，启动时只追加不截断，需要部署侧定期清理。

升级 TimescaleDB 镜像小版本后，需对每个库（包括 `template1`）用 `psql -X` 连接，并把 `ALTER EXTENSION timescaledb UPDATE;` 作为第一条命令执行。

容器停止宽限期为 2 分钟，避免大 `shared_buffers` 的关机 checkpoint 被 SIGKILL 打断。

Linux 宿主机上的 PostgreSQL 日志目录必须允许容器内 `postgres` 用户写入。当前 TimescaleDB 镜像中的 UID 为 `70`，目录属主错误会导致数据库启动失败。

### ClickHouse

`config/clickhouse/logger.xml` 固定使用 `Asia/Shanghai` 时区，限制服务器日志轮转，并将主要 `system.*_log` 表的 TTL 设为 7 天。修改已有实例的 TTL 后，需要检查被重命名的旧系统日志表是否仍占用磁盘。

### Redis

`config/redis/redis.conf` 使用 AOF、关闭 RDB，并采用 `noeviction`。内存达到 `REDIS_MAXMEMORY` 后写入会明确失败，不会静默淘汰分布式锁或限流计数器。缓存 key 必须自行设置 TTL。

## macOS Docker Desktop 注意事项

- 部署目录必须位于 Docker Desktop 的文件共享路径内（默认 `/Users`、`/Volumes`、`/private`、`/tmp`、`/var/folders`），否则挂载 `config/` 会报 `mounts denied`。`/opt` 默认不共享。
- CLI 选择 User 安装方式时，`docker` 位于 `$HOME/.docker/bin`，需要自行加入 `PATH`。
- named volume 存在 Docker Desktop 的磁盘镜像里（Settings → Resources → Disk image location）。磁盘镜像放在外置盘时，拔盘或休眠断开前先执行 `docker compose stop`；外置盘未挂载时不要启动 Docker Desktop。
- 重置 Docker Desktop 或删除磁盘镜像会丢失全部数据库数据，备份必须走 `pg_dump` 等逻辑导出，并存放到另一块盘。

## 安全提醒

- 数据库端口默认只绑定 `127.0.0.1`；不要在没有防火墙和访问控制的情况下暴露到公网。
- Redis 密码通过 Compose 命令参数传入，可能出现在 `docker inspect` 或宿主机进程信息中。
- 部署目录应配置备份、磁盘告警和日志轮转；这些运行态内容不属于 GetRich 仓库。
