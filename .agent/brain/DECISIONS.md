# GetRich 技术决策与踩坑记录

只增不改。每条记录**决策本身 + 理由 + 对后续开发的约束**，不写施工流水账（那是 `git log` 的事）。
当前状态和未决 TODO 在 `NOTES.md`。2026-08-11／12 那轮 monorepo 重构的完整施工日志归档在 `archive/`。
被后续决策推翻或修复的条目**不删除**，在标题下方标注「已被 D-0xx 推翻／已修复」，保留原文以便理解当时的判断。

---

## D-001 monorepo 采用 uv workspace + PEP 420 namespace package

**时间**：2026-08-11 · **已被 D-018 推翻（2026-08-16）：命名空间包已废除，改为每包独立顶层 import 名**

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

**时间**：2026-08-12 · **已修复（2026-08-16）：`find_project_root()` 改为查找含 `[tool.uv.workspace]` 的 pyproject.toml，不再需要显式 `--env-file`**

monorepo 迁移后，`find_project_root()` 会先命中 `packages/gr-data/pyproject.toml`，而不是 workspace 根，导致应用自动加载配置时读不到根 `.env`，回测 artifact 默认路径也变成 `packages/gr-data/tmp/artifacts`。

**约束**：代码修复前，启动任何 Python 服务都必须显式传 `--env-file`：

```bash
uv run --env-file .env uvicorn getrich.apps.web.main:app --reload
```

## D-004 `gr-data` 对 `gr-backtest` 存在隐式反向依赖

**时间**：2026-08-12 · **已解除（2026-08-16，见 D-018）：日志实现收归 `gr_data.logging`，`LIVE_*` 指标收归 `gr_signal.metrics`**

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

**时间**：2026-08-12 · **部分过期（2026-08-16）：`gr-signal` 现在承载实盘信号与交易执行源码，不再是占位包；`gr-agent` 仍是空占位。下划线 import 名的约定被 D-018 推广到全部包**

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

## D-018 废除 `getrich.*` 命名空间包，每个包独立顶层 import 名

**时间**：2026-08-16 · **推翻 D-001**

D-001 让 `getrich` / `getrich.apps` 做 PEP 420 命名空间包，结果 `gr-api` 和 `gr-backtest`
同时往 `getrich/apps/web/` 里装文件（前者出 `main.py` 和一半路由，后者出另一半路由和
`middleware.py`）。表现是：workspace 整体装能跑，**单独装任何一个包都跑不起来**，
包边界名存实亡。`gr-data` 反向 import `getrich.libs.logging`（D-004）是同一个病。

**现在的规则**：发行名 = 目录名 = `gr-x`，import 名 = `gr_x`，连字符与下划线一一对应。

| 目录 | import |
|---|---|
| `packages/gr-data` | `gr_data` |
| `packages/gr-db` | `gr_db` |
| `packages/gr-backtest` | `gr_backtest` |
| `packages/gr-signal` | `gr_signal` |
| `packages/gr-api` | `gr_api` |
| `packages/gr-factor` | `gr_factor` |

依赖方向单向：`gr-data ← gr-db`，`gr-data ← gr-backtest ← gr-signal ← gr-api`；
`gr-factor` 独立。

**约束**：
- 不要再创建 `getrich.*` 或任何跨包共享的命名空间包。
- 新增跨包 import 前先确认方向；`packages/gr-backtest/tests/gr_backtest/test_package_boundaries.py`
  会用 AST 静态扫描拦截反向依赖（比 `import` 后查属性更严，能发现藏在函数体里的延迟 import）。
- 判断某个模块该放哪，看它**被谁调用**：`LIVE_*` 指标只被实盘用，就该在 `gr-signal`；
  `StrategyRegistryError` 由引擎的注册表抛出，就该在 `gr_backtest.exceptions`。

**踩坑**：改完代码后 `uv run --isolated --with ./packages/gr-signal` 仍报旧的
`ModuleNotFoundError`。原因是 `packages/*/build/lib/` 和 `src/*.egg-info/` 里有
setuptools 的旧产物，构建时会优先用 `build/lib/` 的内容，`uv cache clean` 也清不掉。
**改包结构后必须删掉 `build/` 与 `*.egg-info/` 再验证**，否则测的是上一版代码。

## D-019 行情主存定为 PostgreSQL/TimescaleDB，ClickHouse 收窄为因子时序

**时间**：2026-08-16

此前两套行情存储并存且互相冲突：`getrich-database` 把 K 线建在 PG/TimescaleDB
（`market.*_bar_*`，`instrument_id` 外键），而 `AGENTS.md` §2 写的是 ClickHouse，
`gr-backtest` 也有 CH 的 `md_bars_1m`／`md_bars_1d`。更糟的是 `PgBarLoader` 读的
`md_bars_{asset}_{freq}` 表**在任何迁移文件里都不存在** —— 那条路径是死代码，
mock 测试却一直是绿的。

**决策**：以数据接入层为准，行情主存是 PostgreSQL/TimescaleDB。删除 CH 的 `md_bars_*`，
CH 只留 `factors_long`。

**引擎侧适配**（canonical 列名不变，映射发生在 loader 边界）：

| `market.*_bar_*` | 引擎 canonical |
|---|---|
| `instrument_id`（外键） | `symbol`（JOIN `meta.instruments`） |
| `dt`（日线 `DATE`／分钟线 `TIMESTAMPTZ`） | `dt`（统一 Asia/Shanghai aware） |
| `amount` ÷ `volume` | `vwap` |
| `b_xdy`／`f_xdy` | `pre_factor`／`post_factor` |

**约束**：
- 日线 `dt` 是 `DATE`，与 `timestamptz` 比较时按会话时区解释。读取必须显式写
  `dt::timestamp AT TIME ZONE 'Asia/Shanghai'`，否则边界日期会随连接配置整体错一天。
- `b_xdy` = 前复权、`f_xdy` = 后复权，取自厂商文档（getrich-design
  `dataapi/legacy/insight/architecture-overview.md` §3.2），**不是推断**。搞反方向会让
  整段历史价格系统性偏移，而且回测不会报错。
- `market` 表目前**没有** `oi`（持仓量），也没有公司行为表。`PgBarLoader` 请求这两者时
  显式抛 `DataLoadError`，**不要改成填默认值** —— 期货策略拿到全 0 的持仓量、
  或拿不到除权信息，都会算出看起来正常但完全错误的结果。

## D-020 `frontend` schema 拆成 `app` + `backtest`，并修正 id 类型不一致

**时间**：2026-08-16

`frontend` 这个 schema 名装的其实是后端业务表（用户、策略、信号、订单）和回测产物，
名不副实。现拆为 `app`（22 张业务表）+ `backtest`（10 张回测产物表），与
`meta`／`market`／`ops`／`realtime`／`staging` 并列。

拆分过程中发现一个**更严重的既有缺陷**：`app.strategies.id` 声明为 `VARCHAR(64)`
（注释却写着 `-- UUID`），而引用它的 9 张表全部用 `UUID`。于是
`/v1/strategies`、`/v1/signals` 在**全新建的库上恒 500**：

```
operator does not exist: uuid = character varying
```

`orders.id`／`orders.user_id`／`strategy_trades.*`／`strategy_sub_account_mapping.strategy_id`
有同样的问题。已统一改为 `UUID`（与被引用主键对齐，也与注释一致）。

**约束**：
- 连接池 `search_path = app,market,meta,public`；`backtest` **不在** search_path 里，
  回测 SQL 一律显式写 `backtest.` 前缀。
- 新增引用其它表的 id 列时，**类型必须与被引用主键一致**。这类不一致在 mock 测试下
  完全看不出来，只有在真库上跑真实查询才会暴露 —— 改 DDL 后要在真实 PG 上验证一次。
- 已有实例升级走 `packages/gr-db/src/gr_db/ddl/upgrade/001_frontend_to_app_backtest.sql`
  （已在模拟旧布局的库上验证过数据无损），新库直接跑主 DDL。

## D-021 `gr-db` 统一 DDL，迁移记账用 checksum 而非前缀

**时间**：2026-08-16

此前有两套互不相识的迁移系统：`getrich.migrations`（`NNN_*.sql`，按前缀记账，
PG+CH 双执行器）和 `getrich_data.common.migrate`（`db/ddl/*.sql`，按 checksum 记在
`ops.schema_migrations`）。现全部收进 `packages/gr-db`。

合并取两边各自的长处：保留前者的 `MigrationExecutor` Protocol 注入设计（import 时不依赖
`psycopg`／`clickhouse_connect`，无需真库即可测），记账语义取后者的 **file_name + checksum**。

**为什么必须是 checksum**：只记前缀检测不到「文件已应用、之后又被改过」，
库结构会和仓库里的 DDL 静默分叉，而且分叉之后没有任何信号。checksum 变了就重新应用，
因此**所有 DDL 必须幂等**（`CREATE ... IF NOT EXISTS`／`ADD COLUMN IF NOT EXISTS`）。

**约束**：
- DDL 全部 schema 全限定（写 `app.users`，不要靠 `search_path`）。迁移连接刻意把
  `search_path` 设成 `pg_catalog, public` —— 靠 search_path 隐式定位正是旧 `frontend`
  方案的坑，换个连接就把表建到别的 schema 去了。
- 文件前缀必须**连续**，runner 会拒绝跳号（防止漏文件）。
- CH 执行器的 `command()` 一次只吃一条语句，多表 DDL 必须先切分；不切分的话第二张表
  会被**静默忽略**，建库时看不出错，直到运行期报 "table doesn't exist"。
- DDL 是 package-data，路径基于 `gr_db.__file__` 定位，`pip install` 后也能建库，
  不依赖仓库布局。

## D-022 `getrich-database` 已合并进 `gr-data`，源仓库转只读

**时间**：2026-08-16

用 `git subtree add` 合并，51 个提交的历史与 blame 全部保留。设计文档按 getrich-design
仓 `CLAUDE.md` §2 的约定迁到该仓 `data-platform/`，重复文件已去重
（insight／ricequant 文档与设计仓逐字节相同；tushare 取了内容更新的一版）。

**约束**：
- 不要再往 `getrich-database` 提交任何东西，那边已是只读存档。
- 数据接入的口径约定压进了 `AGENTS.md` §3.4，运行手册在 `packages/gr-data/README.md`，
  设计文档在 getrich-design 仓。三者不要互相复制。

**踩到的坑（凭证泄漏）**：`reference/design/ricequant/config.md` 含明文 license key，
在源仓库里是被跟踪的，subtree 合并后**进了本仓 git 历史**。已从索引移除并加进
`.gitignore`，但历史里仍在，必须当作已泄漏处理并轮换。
**合并外部仓库前先扫一遍对方仓库里有没有凭证**，`.gitignore` 只挡未来的提交，挡不住历史。

## D-023 配置来源统一到根 `.env`，`.env` 不再覆盖真实环境变量

**时间**：2026-08-16

两个独立缺陷：

1. `settings.load_settings()` 原来用 `load_dotenv(..., override=True)`，`.env` 文件会
   **盖掉真实环境变量**。结果 `PG_PORT=55433 gr-db migrate` 这类一次性覆盖、CI 注入、
   容器环境变量全部失效 —— 命令看起来跑了，实际连的还是 `.env` 里那个库。已改为
   `override=False`（12-factor 的正常方向：环境变量优先）。
2. `config.yaml` 里另有一份 `postgres` 段，用的还是 `PGHOST`／`PGPASSWORD`，
   与应用侧的 `PG_HOST`／`PG_PASSWORD` 是**两套变量名**，同一个仓库里 CLI 和服务
   可能连到不同的库。已删除该段，`gr-data` CLI 改读 `settings`。

`config.yaml` 现在只放结构化的采集参数（抓取范围、限频、启用哪些 fetcher/importer）。

**另外修掉的默认值缺陷**：`PG_HOST` 默认值写死了某台机器的内网 IP（`100.80.19.6`）、
`PG_DB` 默认 `goldmine`，新克隆在没有 `.env` 时会去连别人的主机，报一个和真实原因
无关的连接错误。这与 Round #1143 修过的 ClickHouse 默认值是同一类问题。
**默认值必须是本机可用的中性值**（`localhost`），且与 `.env.example` 一致。
