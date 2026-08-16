# GetRich 技术决策与踩坑记录

只增不改。每条记录**决策本身 + 理由 + 对后续开发的约束**，不写施工流水账（那是 `git log` 的事）。
当前状态和未决 TODO 在 `NOTES.md`。2026-08-11／12 那轮 monorepo 重构的完整施工日志归档在 `archive/`。

---

## D-001 monorepo 采用 uv workspace + PEP 420 namespace package

**时间**：2026-08-11

根项目为 uv workspace，成员是 `packages/gr-{agent,api,backtest,data,factor,signal}`，每个成员有独立 `pyproject.toml` / `src` / `tests`。`getrich` 与 `getrich.apps` 是 PEP 420 namespace package，没有顶层 `__init__.py`。

**约束**：不要给 `getrich` 或 `getrich.apps` 加 `__init__.py`，会阻断跨 package 的模块发现。

## D-002 2026-06-06 按时间切分包 —— 这次切分有问题，将被重构

**时间**：2026-08-12 决策，2026-08-14 标记为待推翻

当时的规则：以文件在 Git 中首次引入的时间为准，2026-06-06 00:00（Asia/Shanghai）之前的代码留在原包，当天及之后首次引入的代码全部归入 `gr-backtest`。结果是 `gr-backtest` 承接了 `getrich.apps.strategy`／`web`／`worker`、`getrich.libs`、`getrich.migrations` 等大量目录，`gr-signal` 变成无源码的占位包，`gr-agent` 只剩 gateway 空命名空间。

**现在的判断**：这次合并是有问题的 —— 按引入时间而非职责边界切分，导致 `gr-backtest` 成了大杂烩，包依赖边界并没有真正建立。**后续计划全部重构，逐步降低这次提交的影响。**

**对当前开发的约束**：
- 不要在 `gr-backtest` 里继续堆积新的跨领域模块，会加大将来拆分的成本。
- 涉及 `getrich.apps.*`、`getrich.libs`、`getrich.migrations` 的改动，优先考虑它「应该属于哪个包」，而不是「现在在哪个包」。
- migration 目录（`packages/gr-backtest/migrations/`）的位置属于这次切分的产物，将随重构变动，暂不写入固定规范。

## D-003 配置根目录推导会命中错误的 pyproject.toml

**时间**：2026-08-12

monorepo 迁移后，`find_project_root()` 会先命中 `packages/gr-data/pyproject.toml`，而不是 workspace 根，导致应用自动加载配置时读不到根 `.env`，回测 artifact 默认路径也变成 `packages/gr-data/tmp/artifacts`。

**约束**：代码修复前，启动任何 Python 服务都必须显式传 `--env-file`：

```bash
uv run --env-file .env uvicorn getrich.apps.web.main:app --reload
```

## D-004 `gr-data` 对 `gr-backtest` 存在隐式反向依赖

**时间**：2026-08-12

`gr-data` 的旧 ClickHouse 类导入 `getrich.libs.logging`，而该模块现在由 `gr-backtest` 承接。workspace 整体安装能跑，但**单独安装 `gr-data` 会失败**。

**约束**：正式拆包阶段必须先设计共享日志边界。同类问题还有 `gr-signal` 反向 import `getrich.apps.web.metrics`。

## D-005 部署编排移出仓库

**时间**：2026-08-12 · **已由 D-012 部分修订（2026-08-14）：compose 定义收回仓库，只有运行实例留在外面**

`docker-compose.yml`、数据库配置、日志清理脚本、`db.sh` 全部迁到仓库外的 `/Volumes/myssd/getrich-docker/`，仓库内不再维护 Dockerfile 或 systemd unit。

**约束**：
- 仓库根 `.env` 里的 `POSTGRES_DATA_DIR`、`CLICKHOUSE_LOG_DIR` 等变量对 compose 已无意义，应用侧不使用，保留无害。
- 需要起数据库时去 `/Volumes/myssd/getrich-docker/` 执行 `docker compose up -d`，连接数据库用该目录的 `./scripts/db.sh pg|ch|redis`。
- 待部署方案确定后，在仓库内独立 `deploy/` 目录重新设计。

## D-006 旧测试是行为基线，先替换后删除

**时间**：2026-08-12

六个 package 内的既有业务测试是从旧单体测试原样迁移的。

**约束**：新测试按 package 逐步替换，**替换完成后**才删对应旧测试，避免结构重构期间完全失去回归保护。

## D-007 文档体系已整体删除

**时间**：2026-08-12

`mkdocs.yml`、`docs/`、Docs／Pages workflow、文档 CI 校验脚本、根开发依赖里的 MkDocs 工具链全部删除。回测设计契约及策略／信号前期方案迁到独立仓库 `../getrich-design`。

**约束**：不要再引用 `mkdocs build`、`docs/` 路径或 GitHub Pages 相关配置 —— 这些命令现在必然失败。未来重建文档时再恢复独立 workflow。

## D-008 CI 用路径过滤，不要设为 required checks

**时间**：2026-08-11

CI 拆成 `ci.yml`（Python）、`web.yml`、`backtest-web.yml` 三个路径过滤工作流，让不同应用的历史失败不阻塞无关目录的 PR。

**约束**：路径过滤 workflow **不要**直接设为全仓 required checks，未触发的 workflow 会保持 Pending 卡住 PR。若需要强制状态检查，得先加一个每个 PR 都运行的汇总 gate workflow。

## D-009 `gr-signal` / `gr-agent` 是仅含元数据的占位包

**时间**：2026-08-12

两者用 `py-modules = []` 显式声明为只有元数据的可构建项目，不提供任何 `getrich.*` 兼容 import。

**约束**：保留连字符的发行项目名 `gr-agent`／`gr-signal`；将来加 Python 源码时，import 名必须用下划线形式 `gr_agent`／`gr_signal`。

## D-010 `archive/` 删除需要明确确认

`archive/root-web-scaffold/` 是根级不完整 Vite 脚手架的备份。

**约束**：删除前必须得到用户明确确认，不要自行清理。

## D-011 `.agent/` 进仓库，`.claude/settings.local.json` 不进

**时间**：2026-08-14

`.agent/brain/` 是 Claude Code、Codex、DeepSeek 三个 harness 共享的唯一跨会话状态，之前被 gitignore 且从未被 git 跟踪 —— 换机器就断档，历史也无法追溯。已从 `.gitignore` 移除。

`.claude/settings.json` 是团队共享的权限策略（含 `deny: git push / rm -rf`），需要提交；只有个人覆盖走 `.claude/settings.local.json`，那个才 gitignore。

**约束**：`.agent/` 下不得写入任何真实凭证、密码或 token —— 它现在是公开仓库内容。

## D-012 数据库 compose：仓库存「定义」，本机部署目录存「实例」

**时间**：2026-08-14 · 修订 D-005

D-005 把整套 docker 编排移出仓库后留下两个问题：根目录残留了一份坏掉的 `docker-compose.yml`（挂载 `./config/clickhouse/logger.xml` 和 `./config/redis/redis.conf`，但 `config/` 已被删，起不来），以及新克隆或换机器时仓库里没有任何能拉起开发数据库的依据 —— 这与「`.agent/` 进仓库保证跨机器接续」的目标矛盾。

**现在的划分**：

| 位置 | 内容 | 进 git |
|---|---|---|
| 仓库根 | `docker-compose.yml`、`config/clickhouse/logger.xml`、`config/redis/redis.conf`、`.env.example` | 是 |
| 本机部署目录 | 从仓库复制的 compose、真实 `.env`、`.docker/` 数据卷、`scripts/db.sh`、`scripts/cleanup-logs.sh` | 否 |

数据库依然是**单独部署**的基础设施，不随应用构建；仓库只负责让这份编排可复现。

**约束**：
- 改仓库里的 `docker-compose.yml` 或 `config/` 后，必须手动同步到部署目录再重启容器 —— 目前没有自动同步。
- `.docker/` 已加入 `.gitignore`（compose 的默认挂载点，`${*_DATA_DIR}` 未设置时会落在这里）。
- 部署目录的绝对路径是本机特定的，不写进仓库任何文件。

## D-013 Redis 用 noeviction，写满报错而非淘汰

**时间**：2026-08-14

原 `redis.conf` 设了 `maxmemory-policy allkeys-lru` 但**没有设 `maxmemory`** —— Redis 默认 `maxmemory 0`（无上限），淘汰策略在这种情况下完全不生效，内存会一直涨到 OOM。

补上容量上限后，`allkeys-lru` 的方向本身也是错的：本实例混放了 tick 缓存、跨进程状态、**分布式锁**和限流计数器。`allkeys-lru` 不区分 key 用途，内存压力下会把锁一起淘汰 —— 锁凭空消失会让两个进程同时进临界区，导致重复下单或重复写账户快照。

**现在的配置**：`maxmemory-policy noeviction`，容量由 compose 从 `REDIS_MAXMEMORY`（默认 `2gb`）传入。写满时写入返回 `OOM command not allowed when used memory > 'maxmemory'`，缓存类 key 靠自身 TTL 回收。金融路径上「写失败并报错」远好过「锁没了但没人知道」。

**待观察**：如果后续 tick 缓存增长导致频繁 OOM 报错，再评估是否改回 LRU。**前置条件是先把分布式锁和限流计数器隔离到独立 db 或独立 Redis 实例** —— 在混放的前提下不要直接切 LRU。

## D-014 PostgreSQL 配置分层：tune 管机器，配置文件管平台规范

**时间**：2026-08-14

`config/postgres/postgresql.conf` 第一行 `include_if_exists = '/var/lib/postgresql/data/postgresql.conf'`，把镜像内 timescaledb-tune 的调优作为基线，其后的设置覆盖它。PostgreSQL 后读到的设置胜出，**include 必须放在最前面**。

分工：

- **不写在配置文件里的**（内存、并行度）→ tune 说了算，跟机器规格走
- **写在配置文件里的**（时区、日志、WAL、planner、事务）→ 配置文件说了算，跟平台规范走

最初版本把 `shared_buffers` 等手写成保守值，实测会把现有实例从 978MB 降到 512MB、`max_worker_processes` 从 27 降到 8 —— 手写值盖掉按机器算出的调优，属于负优化。已改为交给 tune。

**关键前提：timescaledb-tune 只在首次 initdb 时跑一次。** 实测证据：

```
timescaledb.last_tuned = '2026-08-12T22:05:58+08:00'   # 数据目录初始化时刻
容器创建时间            = 2026-08-14T15:22:03Z          # 重建后 tune 未再运行
```

**约束**：
- 换机器、扩内存、迁移数据目录后，tune **不会**重算，PG 仍按初始化那天的机器规格跑。需要手动进容器执行 `timescaledb-tune --yes` 再重启。
- 部署到新机器时，先核对 `$PGDATA/postgresql.conf` 里的 `last_tuned` 时间戳与当前机器规格是否匹配。
- 若需要跨机器可复现（CI、容量规划确定后），在配置文件 include **之后**追加内存参数即可钉死。

## D-015 Linux 宿主机 bind-mount 日志目录属主必须匹配容器内 uid

**时间**：2026-08-14

远端 `greencloud`（Linux）上 PG 处于崩溃重启循环：

```
FATAL: could not open log file "/var/log/postgresql/postgresql-....log": Permission denied
```

容器内 postgres 是 **uid 70**（Alpine 镜像），而手工 `mkdir` 创建的 `/opt/getrich-docker/.docker/postgres/logs` 属主是 uid 1000，权限 755 → 写不进去。`data` 目录没问题，因为 Docker 初始化时自动设成了 uid 70。

**约束**：
- 在 Linux 部署时，所有手工创建的 bind-mount 日志目录都要 `chown` 成容器内对应 uid（PG=70）。macOS Docker Desktop 会自动 remap 属主，**不会暴露这个问题**，本地测通不代表服务器能跑。
- 只要 `logging_collector = on`，日志目录写不了就是启动致命错误，不是降级警告。

## D-016 基础设施定义统一放入 deploy，仓库内不实例化 Docker

**时间**：2026-08-16 · 修订 D-012 的仓库路径和使用方式

根级 `docker-compose.yml` 和通用名称 `config/` 容易让人误以为 GetRich 应用会在仓库内创建数据库实例，也会与未来的应用配置目录混淆。因此，所有数据库基础设施定义统一收进 `deploy/`：

| 位置 | 内容 | 用途 |
|---|---|---|
| `deploy/docker-compose.yml` | 固定版本的 PostgreSQL／TimescaleDB、ClickHouse、Redis 编排 | 部署模板 |
| `deploy/config/` | 三个数据库的运行配置 | 部署模板 |
| `deploy/.env.example` | 容器、端口、数据卷和部署密码占位符 | 复制到外部部署目录后使用 |
| 根 `.env.example` | 应用连接和运行配置 | GetRich 应用使用 |
| 仓库外部署目录 | 真实 `.env`、数据卷、日志、备份和运维脚本 | 实际运行实例 |

**约束**：

- 不在 GetRich 仓库内执行 `docker compose up`、`down` 或 `restart`，也不在仓库内保存运行数据。
- `deploy/` 必须整体复制或同步到仓库外的部署目录，Compose 命令只从部署目录运行。
- 仓库内允许用 `deploy/.env.example` 执行 `docker compose config --quiet` 静态校验；这不会创建容器。
- 同步模板时不得覆盖部署目录中的真实 `.env`、数据卷或主机专属运维配置。
- 根 `.env` 只服务 GetRich 应用；容器名称、数据卷路径、端口发布和 Redis 内存上限属于部署侧配置。

## D-017 deploy 同步到外部部署目录时不保留外层目录

**时间**：2026-08-16 · 修订 D-016 的复制表述

外部部署目录本身就是 Compose 项目根，因此同步的是 `deploy/` **目录中的文件**，不是 `deploy/` 目录本身。以 `/opt/getrich-docker` 为例，同步后的结构是：

```text
/opt/getrich-docker/
├── docker-compose.yml
├── .env.example
└── config/
```

而不是 `/opt/getrich-docker/deploy/`。

**约束**：同步命令必须保持目录内容平铺到外部部署目录根。例如 `rsync` 源路径使用末尾 `/`：

```bash
rsync -av --exclude '.env' --exclude '.docker/' deploy/ /opt/getrich-docker/
```
