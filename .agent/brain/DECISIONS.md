# GetRich 技术决策与踩坑记录

只增不改。每条记录**决策本身 + 理由 + 对后续开发的约束**，不写施工流水账（那是 `git log` 的事）。
当前状态和未决 TODO 在 `NOTES.md`。2026-08-11／12 那轮 monorepo 重构的完整施工日志归档在 `archive/`。
被后续决策推翻或修复的条目**不删除**，在标题下方标注「已被 D-0xx 推翻／已修复」，保留原文以便理解当时的判断。

---

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

## D-024 选股信号（`pick` schema）落地：三处偏离设计文档的取舍

**时间**：2026-08-17

选股展示模块（`getrich-design/strategy-signal/`）的 P0 存储层落地为 `pick.batch` +
`pick.item` 两张表（迁移 `034_pick.sql`）。设计文档写于 introspect 实际库之前，
落地时有三处必须偏离，理由记在这里，免得后来者当成实现错误去「修正」：

1. **`strategy_id` 用 UUID 而不是 `VARCHAR(32)`。** 文档 §3 把这条列为阻塞项，
   要求落地前 introspect 确认 —— 实际 `app.strategies.id` 是 UUID（见
   `021_strategies.sql`），对外展示与路由用 `strategy_code`。这与 D-020 踩过的坑
   同源：引用别人主键时类型必须与被引用列一致，否则全新库上恒 500。
2. **`import_job_id` 保留列但不建外键，`chk_batch_job` 不建。** 文档假设复用
   `/v1/admin/imports` 的 `import_jobs` 表 —— 但**本仓根本没有那张表的 DDL**
   （`services/admin_import.py` 引用它，`gr-db/ddl/` 里一行都没有，全新库上那套接口
   必然报错）。P0 走函数 / CLI 导入，没有 job 可挂，硬建外键会让迁移直接失败。
3. **`uploaded_by` 可空。** 文档写 `NOT NULL VARCHAR(32)`，但 CLI 导入没有登录用户。
   改成可空 UUID 并外键到 `app.users(id)`。

**策略类型判别选了「加列」而不是「用分类」**（文档 §3.3 的方案 B）：
`app.strategies.strategy_kind`（`pick`/`timing`/`combo`，可空）。方案 A（用一个专门的
`strategy_categories` 分类）零改动，但会把「策略类型」和「业务分类」焊死，将来选股
再分子类（预增 / 双击）就打架。可空 + 选股接口只认 `strategy_kind='pick'`，
所以没回填的存量策略不会误入选股列表。

**两套交易所码是这块最容易静默出错的地方**：`pick.item.exchange` 存 `SSE/SZSE/BSE`
（前端接口契约 `PickItem.exchange` 枚举定死），数据层 `meta.*` 用 canonical 码
`XSHG/XSHE/XBSE`，且 `meta.instruments.symbol` 存的是**带后缀全码**（`600000.SH`）。
拿 `SSE` + 不带后缀的 `600000` 去查 `meta.instruments`，SQL 不报错、只是查不到，
表现为 `instrument_id` 整批 NULL、`holding_trading_days` 全部走自然日兜底。
转换集中在 `gr_api/services/pick_symbols.py`，别在别处再写一份。

**入池日推算的保守方向不可反转**：上一交易日没有 active 批次（漏传）或交易日历尚未
ingest 时，`entry_date` **沿用不重置**。反过来（重置成今天）会静默破坏历史且不可恢复；
沿用导致的偏差是「入池时间偏早」，可见、可解释、事后可修正。
`product_entry_date` 的兜底值取 `entry_date` 而非 `trading_day` —— 取后者会在
「首次入池 + 上传方给了更早的 entry_date」这个**每个基金经理首次接入的必经场景**下
违反 `chk_item_prod_entry`，整批插入失败（文档附录 A.6 第 1 条）。

## D-025 `gr-tools`：依赖图最底层的叶子包

**时间**：2026-08-17

从外部仓库 `lntools` 移植文件系统、多格式表格读取与人性化格式化三块能力，
落成 `packages/gr-tools`。**它不许依赖任何一方包** ——
`packages/gr-tools/tests/test_package_boundaries.py` 用 AST 静态扫描守这条线。
一旦为了复用 `gr_data.logging` 而 import `gr_data`，依赖图就成环（gr-data 想用它的
读文件能力时会互相 import），所以 gr-tools 内部一律用 stdlib `logging`。

移植时刻意改掉的两处：默认引擎写死 `polars`（不再读 `~/.config` 里的全局配置文件，
库不该依赖用户目录状态）；新增 `read_frame(..., all_string=True)`。

**`all_string` 不是可选项，是导入路径的硬要求**：CSV 类型推断会把 `000001` 读成整数
`1`，前导零丢掉后代码再也对不上，而且**全程不报错**，错误一路带进数据库。
凡是读用户提供的证券代码 / 日期文件，一律 `all_string=True` 后由业务层显式解析。

## D-026 选股读写路径的两处性能取舍

**时间**：2026-08-17（在 10 策略 × 250 交易日 × 30 只 ≈ 7.9 万条 `pick.item` 上实测）

**一、入池日推算不扫全量历史。** 原实现对每个分组键做
`DISTINCT ON ... WHERE trading_day < 本期`，代价是 O(该策略全部历史)，而且
symbol 与 product 各扫一遍 —— 每天导入一次，成本随年份线性上涨。

现在分两条路：连续上传（上一交易日有 active 批次）时**只读上一期那一批**，
一次索引扫描同时给出 symbol 与 product 两套索引；只有漏传 / 日历缺失才回退到
扫历史找「最近一条」。两者结论完全等价 —— 正常路径下入池日只可能继承自上一
交易日那期，更早的记录按规则本来就要重置为当天。

实测：0.071 ms（扫 20 行）对 39.774 ms（扫 435 行），且前者不随历史增长。

**二、个股反查的 `latest` CTE 必须按命中的策略收窄。** 原写法
`SELECT strategy_id, MAX(trading_day) FROM pick.batch WHERE status='active' GROUP BY 1`
会对整张 batch 表做聚合，代价随平台上**所有**策略的历史增长，而一次反查只需要
命中的那几个策略。加 `AND b.strategy_id IN (SELECT strategy_id FROM runs)` 即可。

**顺带记一笔量级**：这套接口的 SQL 执行时间在年度数据量下是 1–15 ms，
**查询计划的生成时间反而更贵**（10–45 ms）。psycopg3 默认 `prepare_threshold=5`，
同一条 SQL 在同一连接上跑够 5 次就会转成 prepared statement，规划开销随之摊掉 ——
所以**不要为了「少拼几个 WHERE」把 SQL 拼成千变万化的字符串**，那会让每个变体
都重新规划，反而比多写几个固定分支慢。

## D-027 Black-Litterman：去掉不自洽的归一化，并记下两个待定的建模口径

**时间**：2026-08-17

`BlackLitterman._compute_posterior` 原来对先验和观点**分别**做归一化：

```python
pi_prior = pi_prior / pi_norm          # → L1 = 1，量级 O(1)
q_vec = mu_scores / q_norm * pi_norm   # → L1 = pi_norm，量级 O(1e-5)
```

两次归一化互不自洽 —— Π 被拉到 O(1)，Q 却被压回原始 `pi_norm`（日收益量级）。
后验里 `ts_inv @ Π` 因此恒定压过 `omega_inv @ Q` 约五个数量级，**观点的符号被
完全抹掉**：`score=-1` 的标的照样拿到正的后验收益，长短仓完全反向。

现在两者都保持各自的自然量纲，不做任何归一化。修完后验从 `[0.167, 0.167]`
（观点消失）变成 `[+1.00, -0.99]`（观点符号保留）。

**同时修掉的第二个缺陷**：`np.linalg.inv` 只在矩阵**恰好**奇异时抛
`LinAlgError`。两只标的行情完全同步时协方差的行列式是 1e-26 这种量级，不触发
异常，却让求逆结果变成纯数值噪声。伪逆也救不了 —— `pinv` 的输出恒落在协方差的
行空间里（秩 1 时是 `span{[1,1]}`），和观点完全无关，归一化后得到 `[0.5, 0.5]`，
两个方向相反的标的同号。所以判据改成**条件数**（`_MAX_COND = 1e12`，依据是
float64 的相对精度 2.2e-16），退化时直接退回「按方向等权」，不拿噪声冒充最优解。

**遗留两个待决口径，等定了方案再动**：

1. **`tau` 目前是无效参数**。后验里 `(τΣ)⁻¹` 和 `Ω⁻¹ = 1/(diag(Σ)·τ)` 同时以
   `1/τ` 缩放，τ 在 `(Σ⁻¹/τ + D/τ)⁻¹ (Σ⁻¹Π/τ + DQ/τ)` 里精确约掉，改两个数量级
   得到的后验逐位相同。要让 τ 重新起作用必须换 Ω 的取法（Idzorek 置信度是常见
   做法）。用例 `test_tau_currently_cancels_out` 钉住现状，改了 Ω 它会先失败。
2. **score 被直接当预期收益用**（Q = score）。量纲上 `score=1` 等于「预期日收益
   100%」，和 Π 的 O(1e-5) 差五个数量级，等于把观点的置信度隐式拉满。要不要在
   Q 前面加一个标定系数（比如按截面波动率缩放），属于策略口径，需要先定。

**测试层面的教训**：BL 原有 6 条用例**全部**用同一条价格序列喂两个标的，协方差
秩为 1，走的都是退化分支 —— 真正的后验路径一条都没覆盖，符号错了三个月没人发现。
新增 `test_view_sign_survives_posterior`（cond(Σ)≈1.7 的非退化数据）补上这条路径。
**造测试数据时，「两个标的」必须真的不一样**，否则测的是 fallback 不是算法。

## D-028 ClickHouse 迁移记账一直是空的：`command()` 拼 INSERT 绑不上参数

**时间**：2026-08-17

`ClickHouseMigrationExecutor.apply_one` 原来这样记账：

```python
self._client.command(
    "INSERT INTO schema_migrations (file_name, checksum) VALUES",
    parameters={"file_name": ..., "checksum": ...},
)
```

这条 SQL 里**没有任何占位符**，`parameters` 无处可绑，ClickHouse 把它当成插入
0 行并静默成功。结果 `getrich.schema_migrations` 恒为空，每次
`gr-db migrate --target ch` 都把全部迁移重放一遍 —— 因为 DDL 都是
`CREATE TABLE IF NOT EXISTS`，重放看起来完全正常，报的还是
"applied 1 migration(s) successfully"。**幂等的 DDL 把记账失效这件事盖住了。**

改成 `client.insert("schema_migrations", [[name, checksum]], column_names=[...])`。

**这个 bug 被一条测试钉死过**：`test_clickhouse_apply_one_runs_sql_then_books`
用 `MagicMock` 断言的正是那条坏 SQL 的字面量和 `parameters` 的内容 —— mock 不会
告诉你 ClickHouse 收到之后插了 0 行。**断言「调了哪个 API、带了什么值」，
不要断言 SQL 字符串的字面量**，后者只能证明代码没变，不能证明代码是对的。

判断迁移是否幂等，**必须看第二次运行是不是 "already applied"**，
不能只看第二次没报错。

## D-029 数据库容器的数据目录改用 named volume，禁止 bind mount

**时间**：2026-08-17

`deploy/docker-compose.yml` 里 PostgreSQL / ClickHouse / Redis 的数据目录原来都 bind
到宿主机（`./.docker/<svc>/data`）。在 macOS + Docker Desktop 上，bind mount 走的是
虚拟机的文件共享层（VirtioFS / gRPC-FUSE），**它不保证 POSIX 语义**。写入压力上来后：

```
ERROR: could not create directory "base/16384": File exists
ERROR: could not open file "base/16384/27783": No such file or directory
   CONTEXT: while vacuuming index "uq_batch_active" of relation "pick.batch"
```

容器内对刚创建的 relfilenode `open()` 返回 ENOENT、`mkdir()` 返回 EEXIST，而**宿主机上
文件都在**（`base/16384` 807 个文件俱全）。报错出现在 autovacuum 内部，与任何应用 SQL
无关；宿主是 APFS，文件系统本身正常。当天复现两次，`docker restart` 后 WAL 自动恢复、
数据无损，但会反复发生。

改成 named volume（`getrich_pg_data` / `getrich_ch_data` / `getrich_redis_data`）。
卷仍然物理落在同一块外置盘上（Docker 的 disk image 就在那儿），但数据库看到的是
**虚拟机内的块设备 + ext4**，不经过文件共享层，POSIX 语义完整。

**换来的代价，必须记住**：数据不能再从宿主机翻目录直接看，备份只能走 `pg_dump` /
`clickhouse-client` / `BGSAVE` 这类逻辑导出，**不要再拷贝数据目录文件**。
日志目录仍是 bind mount —— 日志文件一天才创建一次，撞上共享层问题的概率极低，
且丢日志不毁数据，换来宿主机直接 `tail` 的便利。

推论：**任何「打真库的测试失败」，先排除挂载问题再怀疑代码。** 判据是看
`docker exec <c> ls <数据目录里报错的文件>` 与宿主机 `ls` 是否一致。

## D-030 两条「声明了但从未生效」的配置与门禁

**时间**：2026-08-17

同一天撞到两个同类问题：配置项和测试门禁都写在文档里，看起来生效，实际从来没起作用。
它们和 D-028（CH 记账 INSERT 绑不上参数）是同一个失败模式 —— **没有任何报错，
只是静默地不干活**。

**其一：`RAW_PARQUET_ROOT` 是死配置。** `AGENTS.md` §3.4 和 `.env.example` 都把它写成
raw 层落地根目录的真源，但 `Config.raw_root` 只读 `config.yaml` 的 `paths.raw_root`，
从没读过这个环境变量；而随包发布的 `config.example.yaml` 里该键恒等于
`/opt/raw_parquet`。于是环境变量配了也没用，新机器一律撞 `/opt` 的权限错。
已改成 **环境变量优先 > config.yaml > 默认值**，方向同 D-023。

**其二：`_docker_available()` 被自己的探测命令挡住。** `packages/gr-data/tests/conftest.py`
用 `docker info` + `timeout=10` 判断 docker 是否可用。`docker info` 要把镜像、容器、
存储、插件全查一遍，在 Docker Desktop for Mac 上首次调用实测 **9.75 s**，正好卡在
超时边界 —— 于是 5 个集成用例在 docker 完全健康的机器上被判成「docker 不可用」，
长期静默跳过。换成 `docker version --format '{{.Server.Version}}'`（同样要求守护进程
应答，实测稳定 0.2 s，快 50 倍），超时放宽到 20 s。改完 5 个用例全部真跑起来并通过。

**通用教训**：
1. **健康探测要用最轻的那条命令**，只需证明「服务在应答」，不要顺带拉全量状态。
2. **skip 数量的变化和失败一样值得看**。本轮把「2323 passed / 25 skipped」推到
   「2350 passed / 1 skipped」，多出来的 27 个用例不是新写的，是**本来就该跑但从没跑过的**
   （5 个 docker 集成 + 11 个 tushare 真实接口 + 5 个 job 持久化 + 选股集成）。
   CI 里只盯 failed 会让这类问题永远藏着。

## D-031 前端工具链升到 Vite 8（Rolldown）/ TS 6.0，以及它顺手暴露的三类存量问题

**时间**：2026-08-19

`apps/web` 从 Vite 7.2 + TS 5.9 + React 19.2.0 升到 **Vite 8.2.1 + TS 6.0.3 +
React 19.2.8**，分批提交（React → TS → Vite），每批都单独验证过。

**升级本身要记住的三条硬约束**：

1. **Vite 8 = Rolldown + lightningcss，esbuild 从依赖树里彻底消失。**
   `@vitejs/plugin-react` 必须 ≥6（peer 写死 `vite ^8.0.0`），5.x 装不上。
   构建耗时 22.9s → 4.6s，产物略小（js gzip 419.8 → 407.3 kB）。
2. **`build.rollupOptions` 在 Vite 8 里改名 `build.rolldownOptions`**，分包选项也从
   `manualChunks` 变成 `output.codeSplitting`。当前 config 没用到这些，但下次要做
   代码分割时别照抄 Vite 7 的写法。
3. **native config loader 不支持 `__dirname`**，要用 `import.meta.dirname`。
   现在只是告警，未来大版本会变成默认值。

**真正的教训：换构建器会把「一直存在但被静默放过」的问题一次性抖出来。** 这轮
抖出三类，都不是升级引入的：

- **无效 CSS 被 esbuild 放过、被 lightningcss 拒绝。** `src/components/ui/` 里
  calendar / sidebar / toggle-group 用了 **Tailwind v4 的 `--spacing()` 函数，
  而本项目是 Tailwind v3** —— v3 不认识它，原样输出成 `var(--spacing(4))` 这种非法
  CSS。也就是说这 4 条规则**升级前就是死规则，页面上根本没生效**，只是没人报错。
  推论：**shadcn/ui 组件是按 Tailwind v4 生成的，粘进 v3 项目时必须逐个查
  `--spacing()` / `@theme` / oklch 这类 v4-only 语法**，不能假定能用。
  （**后续**：项目已于同日升到 Tailwind v4，根因消失，这 4 处已恢复成 shadcn
  原始的 v4 写法。此条只作为「跨大版本粘贴生成代码」的教训保留，见 D-033。）
- **`"ignoreDeprecations": "6.0"` 在 TS 5.9 下是非法值（TS5103），`tsc -b` 第一步
  就挂。** 这个值只有 TS ≥6.0 才接受。有人提前写进 tsconfig，导致 `npm run build`
  在 dev 分支上长期失败 —— 而 CI 的 web workflow 只在 `apps/web/**` 变更时触发，
  没人动前端就一直没人看见。
- **lock 文件里的实际版本和 `package.json` 的范围不是一回事。** `typescript-eslint`
  写的是 `^8.46.4`，lock 锁的是 8.52.0，其 peer 为 `typescript <6.0.0`。升 TS 6 后
  lint 碰巧还能跑，但下一次 `npm install` 重新解析依赖就 ERESOLVE 直接失败。
  **查兼容性要查 `npm ls` 的实际版本，不要查 `package.json` 的范围上界。**

**当时的遗留（已在同日解决，见 D-032）**：`npm run lint` 有 44 个存量错误
（36 个 `no-explicit-any` + 7 个 `react-refresh/only-export-components` +
1 个 `react-hooks/purity`），与本次升级无关，升级前后数量一字不差。
清理过程本身挖出了三处真实的前后端契约错位 —— 那才是重点，见 D-032。

## D-032 用 `any` 兜住的接口层，藏了三处真实的前后端契约错位

**时间**：2026-08-19

清理 `apps/web` 的 44 个存量 lint 错误（其中 36 个 `no-explicit-any`）时，把
`src/lib/api.ts` 的 `request<any>` 换成 `src/types/` 里已有的真实类型，**一换就炸出
83 个类型错误**。逐条对着 `gr_api/services/` 的源码和真库实测响应核过，结论是：
类型没写错的地方，是**页面**在读后端从来不返回的字段。

**错位一：`TradeRecord` 的粒度整个搞反了。** `src/types/strategy.ts` 按「开平配对
后的回合」写（`entry_price` / `exit_price` / `holding_days` / `direction`），而
`list_trades` 返回的是**单笔成交**（`action` / `price` / `quantity` / `realized_pnl` /
`executed_at`）。页面读的 `open_price` / `close_price` / `open_time` 两边都不沾。
已按后端订正类型，并把成交表格的列头从「开仓价 / 平仓价」改成「成交价 / 数量」。

**错位二：列表项没有 `category`。** `list_strategies` 的返回项里没有 category
（只有详情接口 join 了 `strategy_categories`），但 `MyStrategyCard` 在读
`strategy.category?.name`。顺带发现类型漏了后端确实会返的 `description` 与
`cover_image`。

**错位三：`SignalDetail.tsx` 有 4 块 UI 读的是不存在的字段** ——
`reason_detail.spread_std`、`market_snapshot.basis`、
`historical_performance.best_return` / `worst_return`、顶层 `related_signals`。
另有 `is_executed` 实际在 `user_state` 下、技术指标实际在 `market_snapshot.indicators`
下（且是 `rsi_14` 不是 `rsi14`）。前两类是**页面按设计稿写、后端没实现**，
已改成占位符 + `TODO(后端)` 注释保留布局；后两类是纯路径写错，已修正。

**教训**：
1. **`any` 不是「还没来得及写类型」，是「关掉了前后端契约的唯一一道检查」。**
   这三处错位全都不会报错，只会在页面上渲染成空值、`undefined` 或 0，
   看起来像「数据还没灌」。真正暴露它们的不是测试，是把 `any` 换成真类型。
2. **写前端类型要对着后端 service 的 return 语句抄，不要对着设计稿或 openapi 草案抄。**
   本仓库 `src/types/` 里带「tips: 文档未给出枚举值，根据 response 示例推断」这类
   注释的字段，基本都是错的重灾区。
3. **同一份类型收紧后要拿真库响应再验一遍**：本轮 `TradeRecord` / `Strategy` 改完，
   是打真接口逐字段比对确认的，不是只靠 `tsc` 过了就算。

**顺带的两条**：
- `useQuery` 的 `isLoading` **不能收窄 `data` 的类型**，`{isLoading ? <Skeleton/> : <X/>}`
  这种写法在 `data` 有真类型后会满屏 TS18048。改判 `!data` 即可，语义完全一致。
- **shadcn/ui 生成的 `src/components/ui/` 不该手改**（`AGENTS.md` §5），
  它天然会触发 `react-refresh/only-export-components`（组件文件同时导出 cva 常量）
  和 `react-hooks/purity`（骨架屏用 `Math.random()`）。这两条规则已在
  `eslint.config.js` 里**按目录**关闭，不是全局关 —— 自己写的组件仍受完整约束。

## D-033 Tailwind 升到 v4：配置从 JS 搬进 CSS，构建从 PostCSS 换到 Vite 插件

**时间**：2026-08-19

`apps/web` 从 Tailwind 3.4.19 升到 **4.3.3**，用官方 codemod
`npx @tailwindcss/upgrade` 迁移后逐条复核。

**形态上的四点变化，新写代码要按新的来**：

1. **没有 `tailwind.config.js` 了。** v4 是 CSS-first，主题定义写在
   `src/index.css` 的 `@theme { --color-*: …; --radius-*: …; }` 里，
   content 路径自动探测，不再需要声明。要加自定义色/圆角/动画，改 CSS 不改 JS。
2. **没有 `postcss.config.js` 了。** 改用官方 `@tailwindcss/vite` 插件挂在
   `vite.config.ts` 的 `plugins` 里。实测两条路径产出的 CSS 字节完全一致
   （同一个内容哈希），但 Vite 插件是官方在 Vite 项目下的推荐路径。
3. **`autoprefixer` 和 `postcss` 两个直接依赖删掉了。** v4 内置 lightningcss，
   自带前缀处理。别再往回加。
4. **动画插件换成 `tw-animate-css`**（v4 原生，`@import` 引入），
   替掉 v3 的 `tailwindcss-animate`（`@plugin` 引入）。

**类名重命名**（codemod 已全量改过，手写新代码注意）：
`flex-shrink-0`→`shrink-0`、`outline-none`→`outline-hidden`、
`shadow-sm`→`shadow-xs`、`shadow`→`shadow-sm`、`rounded-sm`→`rounded-xs`、
`bg-[var(--x)]`→`bg-(--x)`、`[&_[data-x]]:…`→`in-data-[x]:…`。

**踩坑一：codemod 会误伤「长得像类名的字符串」。** 它把 `pagination.tsx` 里
shadcn 的 button variant 取值 `"outline"` 也改成了 `"outline-solid"`（那是组件
prop，不是工具类），`tsc` 直接报 union 不匹配。**跑完 codemod 必须过一遍
类型检查 + 通读 diff**，别看见「build 过了」就提交 —— 这次恰好类型能拦住，
换成一个没有类型约束的 prop 就静默错了。

**踩坑二：怎么验证「样式没丢」而不靠肉眼。** 环境里没有浏览器，用的办法是
**比对「源码里用到的工具类」与「产物 CSS 里生成的选择器」两个集合**：
1015 个候选 token 无一在产物中缺失（报出的 30 个都是 `data-slot` 取值、
ECharts 内联样式串、`space-between` 这类 flex 关键字，本就不是工具类）。
再单独验证颜色链路（`.border-border` → `var(--color-border)` →
`hsl(var(--border))` → 实际值）和透明度修饰符（`color-mix`，含 srgb 回退）。
**这套方法比截图更可靠，以后做 CSS 框架大版本升级可以复用。**

**顺带的收获**：D-031 里记的那 4 处「Tailwind v4 `--spacing()` 语法在 v3 项目里
输出成非法 CSS」，升到 v4 后**已恢复成 shadcn 原始写法**，产物确认编译成
`calc(var(--spacing) * 8)` 这类合法 CSS。当初的 v3 折算是权宜之计，现在根因消失了。
**推论：`src/components/ui/` 是按 Tailwind v4 生成的，本项目现在终于和它对齐了**，
以后用 shadcn CLI 加组件不必再逐个排查 v4-only 语法。

## D-034 两套 API 层合并：重复的那一份，和留下的那一份，都是错的

**时间**：2026-08-19

`apps/web` 长期并存两套接口层，本次合并到 `src/api/`，删除 `src/lib/api.ts`。

**先说事实：9 个函数一个不落地完全重复**（`getStrategies`↔`getStrategyList`、
`getStrategy`↔`getStrategyDetail`、`getTrades`↔`getStrategyTrades`、
`getSignal`↔`getSignalDetail` …）。但重点不是重复，是**两边各自都有错**：

- **`src/lib/api.ts`（5 个页面在用的那份）用裸 `fetch`，不发任何请求头。**
  开发期 mock 认证靠 `X-User-Id`，缺了它后端认不出用户。实测同一接口
  带头返回 `is_subscribed = [F,F,T]`、不带头 `[F,F,F]` ——
  **首页「我的策略」板块因此恒为空**。这个 bug 存在了很久，没人发现，
  因为它的表现是「暂未订阅任何策略」，和真的没订阅长得一模一样。
- **`src/api/`（零引用的那份）类型是假的。** 拦截器 `return response.data`
  已经剥掉了 Axios 外壳，调用方签名却还写着 `AxiosResponse<ApiResponse<T>>`，
  照签名写 `res.data.data` 运行时恒为 `undefined`。而且它**不校验后端的 `code`
  字段**，业务错误会被当成正常数据渲染成空白。

**教训：「没人用的代码」不等于「无害的代码」。** 它零引用所以永远不会报错，
于是错误的类型签名可以一直躺在那儿，等着某天有人照它写代码。
删掉或用起来，二选一，别让它半死不活地挂着。

**合并后的分层规矩（新增接口按这个写）**：

```
src/api/client.ts   axios 实例 + 拦截器：认证头、401 跳转、校验 code、剥信封
src/api/<domain>.ts 接口函数，返回 Promise<T>，T 就是后端的 data
src/types/<domain>.ts 与后端对齐的类型
组件            只通过 react-query 调 src/api/*
```

三条硬约束：

1. **`api` 层不做面向视图的形状转换。** 原来 `lib/api.ts` 的 `getEquityCurve`
   把三条曲线压成并列数组喂 ECharts、`getMonthlyReturns` 重命名字段——
   这类转换已下沉到 `EquityChart` / `MonthlyHeatmap` 组件内部。
   **同一个接口出现两份互不兼容的返回类型，正是这次要消灭的东西。**
2. **剥壳只在 `client.ts` 做一次。** 拦截器把 `response.data` 就地换成信封里的
   `data` 并**仍然返回 `AxiosResponse`**（这样不必对 Axios 的类型撒谎），
   再由 `http` 包装统一 `.then(r => r.data)`。全链路零 `as` 断言。
3. **`code !== 0` 必须抛错**，不能当正常数据往下传。

**代价要认**：产物 JS 1352 → 1390 kB（gzip 407 → 422）。axios 之前因为
`src/api/` 无人引用被 tree-shaking 掉了，现在真正进包。这是走 `AGENTS.md` §5
规定路径的成本，接受。

---

## D-035 `factor` schema 相对设计文档的四处刻意偏离

`getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md` §5.2 是 `factor`
schema 的 DDL 草案真源。`037_factor.sql` 有四处不照抄，**都是刻意的**，
看到差异不要当成实现错误去「订正」：

| 偏离 | 理由 |
|---|---|
| `covariance.cov_flat` 用 `DOUBLE PRECISION[]` 而非 `REAL[]` | 实测样本里最大值 723.695971 = 9 位有效数字，`REAL` 只有约 7 位，末两位会被**静默**截掉。矩阵求逆与半正定判定对精度敏感，而截断后的矩阵依然对称、依然正定，不会有任何报错 |
| `model_run` 加 `units JSONB NOT NULL DEFAULT '{}'` | `annualization_basis` 是单值 CHECK ∈ (daily, annual_252)，装不下「$F$/$D$ 年化 + $f$/$u$ 日频」这种**同一模型内部混着量纲**的事实。`annualization_basis` 保留填 `'annual_252'`，语义收窄为「风险类口径」 |
| `model_run` 加 `calibrated BOOLEAN NOT NULL DEFAULT false` | 量纲定标的依据是**单日**样例且属 SW14 期。全区间复核（P6）通过前，下游必须能读到「这批数是没复核过的」，否则会把 degraded 当成正常结果展示 |
| `model_run` 加 `factor_set_hash VARCHAR(32)` | 每日复核当日活跃因子集合，不符即中断。见 D-036 |

**下游必须知道的一条**：若 portfolio-analysis 按
`annualization_basis='annual_252'` 去读 `factor_return.ret_vector`，会差 √252 倍
——`f` 是**日频小数**。口径以 `model_run.units` 为准，不以 `annualization_basis` 为准。

另有一条 ownership 粒度的边界：`factor.*` 目前**按表级**登记归属
（`OwnershipManager` 只支持表级）。一旦要用自研估计与采购数据并存地写
`factor.*`，必须先把 ownership 下沉到表 + run_id，否则两套估计会混在一张表里
且事后分辨不出哪行是谁写的。

## D-036 datayes 三张宽表的因子列顺序互不相同（静默算错的头号风险）

实测样本 `dy1d_*_20260829.csv` 逐列核对，**不是推测**：

```
exposure  : … COMPUTERS, CONGLOMERATES, CONSTRDECOR, DEFENSE, ELECTRICALEQUIP, ELECTRONICS …
covariance: … COMPUTERS, ELECTRONICS,   CONSTRDECOR, DEFENSE, ELECTRICALEQUIP, NONBANKFINAN …
```

三表都是 58 个因子列（20 风格 + 37 行业 + COUNTRY），**集合相同、顺序不同**，
且 CSV 列名全大写而协方差的 `factorName` 行标签是原大小写。

**按源列序 `df[cols].to_numpy()` 展平 = 每个因子都对应错**，而结果依然是合法的
52 维向量 / 对称正定矩阵，没有任何报错。这是本次接入唯一的「形状正确但数值全错」
高危点。四层防护：

1. `factors.reindex_wide(df, order)` 是**唯一允许把宽表变成数组的函数**，
   源列名经大小写归一后匹配，缺列 / 重复列一律抛错，**不 fillna 不容忍**。
   全仓禁止再出现按源列序取值的写法。
2. `factor_set_hash` 每日复核：当日活跃因子集合的哈希与 `model_run` 不符即中断，
   人工确认后开新 `model_version`。与 `factor_order_hash`（校验我们自己的常量
   没被改）分两列存。
3. 协方差硬校验：行标签集合 == 列名集合、对称性、对角元 > 0，任一不满足即中断；
   半正定只做软校验（告警）。
4. 行业哑变量每行恰有一个 1、`COUNTRY ≡ 1` —— 这两条同时是「列没错位」的最强
   证据，因此**不做「取最大值」兜底**：兜底正好会把错位掩盖过去。

配套的一条：活跃因子集合**从数据派生**而不是写死 52。SW14 期是 49 个、SW21 期
是 52 个，写死一个数字就等于在体系切换时静默算错。写死的只有 58 个的超集与它
的规范顺序（那份是文档明确给出的）。

**踩过的坑**：手上的样本 CSV 是 2020-12-31，属 SW14 期，9 个 SW21 新行业整列为
NaN，只有 49 个因子有值。**它不能直接当 52 因子路径的测试 fixture。**

## D-037 `meta.symbol_map` 是「单表单一来源」铁律的唯一例外

AGENTS.md §3.4 规定同一张目标表只能由一个 provider 写入。接入 datayes 时
`DatayesSymbolMapImporter` 撞上 `OwnershipError：表 meta.symbol_map 已归属
provider='tushare'`。

这不是实现 bug，是规则与这张表的用途本身冲突：**该表的主键就是
`(source, source_symbol)`，它存在的意义就是跨源对齐**。铁律要防的是「两家供应商
往同一批行里写不同口径的值」，而这里两个 source 写的是互不相交的行。

处理：`common/ownership.py` 加 `MULTI_SOURCE_TABLES = frozenset({"meta.symbol_map"})`，
`check()` 提前返回、`claim()` 不登记。

**往这个集合里加表的门槛（必须同时满足）**：主键里含 `source` 列，因此不同
provider 写的行物理上不可能相交。不满足就不能加 —— 加错了不会报错，只会让两家
供应商的数据互相覆盖。

## D-038 gr-data CLI 的 statement_timeout 放宽到 30 分钟

`PgConfig.statement_timeout_ms` 默认 60 s，那是给交互式短查询的。而一次 ingest
是「一个事务里 COPY 上百万行再 UPSERT」：实测 `daily_basic` 单次 1,433,283 行在
60 s 处被 `psycopg.errors.QueryCanceled` 打断，**已写入的部分整批回滚，重跑还是
同样的结果**，且报错信息（"canceling statement due to statement timeout"）看不出
是量太大还是库有问题。

`cli.py::_pg()` 显式传 `_INGEST_STATEMENT_TIMEOUT_MS`（默认 1800000，可用
`GR_DATA_STATEMENT_TIMEOUT_MS` 覆盖）。**只影响 gr-data CLI 这条批处理通路**，
服务侧的连接池与 `PgConfig` 的默认值都不变 —— 给 API 请求 30 分钟的超时是灾难。

## D-039 从 datayes 暴露表派生行业分类：五条必须显式披露的限制

G1（行业分类）的**正解**是 tushare 的 `index_classify` + `index_member_all`：
三级树、申万官方码、真实生效日期。但这两个接口在
`getrich-design/dataapi/tushare-api/tushare_api_design.md` 的 §2–§8（61 个小节，
已逐节核对）里**没有字段目录**，凭猜实现会写出一批看起来对、实际对不上申万发布
口径的数据。

折中：从通联 CNE6 exposure 的 31 个行业哑变量读出逐日归属，按变化点压成
`[in_date, out_date)` 区间。代价是五条限制，**全部写进 DDL 列注释 +
`ops.data_quality_check`，不假装不存在**：

1. 只覆盖 CNE6 收录的 A 股个股，不含 ETF / 指数 / 期货；
2. 只有一级，`scheme.available_level = 1`（**体系级声明，不得当逐标的判据**）；
3. `industry_code` 是通联的英文标识（`Banks` / `NonbankFinan`），不是申万官方码
   （`801780.SI` 那类）。`industry_node.external_code` **恒 NULL**，接到真源后
   回填 —— 猜一份映射会让下游误以为能直接对接申万发布的成分数据；
4. 没有真实 `in_date`，区间起点被导入窗口截短（记 `rule='classify_window_truncated'`）。
   方向是**保守**的：不会让历史看到未来的行业，只会看不到更早的历史；
5. 停牌日没有 exposure 行会打断区间，只对行业相同、间隔 ≤ 40 自然日的相邻段合并。
   停牌一年的票中间有没有被重分类，我们并不知道，接上就是替供应商编数据。

两个容易写错的实现细节：

- **`out_date` 取下一段的起点，不是本段最后一个交易日。** 后者会在两段之间漏掉
  一天，那一天查不到任何行业，而查询本身不报错，只是少了一只票。
- **资产类别（G5）只映射能确定的 stock / etf / fund。** future / option / index
  刻意不映射：CFFEX 同时挂股指期货（equity）与国债期货（fixed_income），交易所
  定不了类别。少一行只让下游标 degraded，写错一行让资产配置分解整块失真且不报错
  —— 两者代价不对称。

接到 tushare 真源后，`classify.instrument_industry` 走 `gr-data own release/set`
转移归属，**两个来源的分歧本身就是很强的质量信号**，值得保留交叉校验。

## D-040 `available_at` 只能有一个产地

新建 `ingest/pit.py`，三个函数按**可信度降序**：

| 函数 | 依据 | 可信度 |
|---|---|---|
| `from_vendor_timestamp(ts)` | 供应商的逐行时间戳（datayes `updateTime`） | 高：逐行精确，天然覆盖回算与重述 |
| `from_announce_date(ann, fallback)` | 公告日（财报的 `f_ann_date` / `ann_date`） | 中：日粒度 |
| `from_trading_day(day, publish_hour)` | 交易日 + 文档声明的发布小时 | 低：**文档值不是实测值** |

**绝对禁止用 `end_date` 兜底**：20241231 的年报次年 3–4 月才披露，按 `end_date`
对齐等于提前看到三四个月后的信息，且回测会「表现优异」——这类前视不会报错，
只会让结果好看。

时区一律 `Asia/Shanghai` 显式 localize。相关的测试写法坑：断言时区**不能断言
`utcoffset()`**，那只反映读取连接的会话时区，换个连接就变。要断言**瞬间**：
`SELECT available_at AT TIME ZONE 'UTC'`，17:00+08 必须等于 09:00 UTC。
漏了 `tz_localize` 时，CI 的 UTC 机器上会存成 17:00Z 而本地机器看着完全正常。

## D-041 `column_types` 声明的是**发送侧线格式**，不是目标列类型

`TableContract` 新增可选字段 `column_types`，`upsert_rows` 据它调
`cursor.copy().set_types(...)`，用来打通 JSONB 与数组列的 COPY 通路。

踩过的坑：`fundamental.valuation_1d.total_mv` 目标列是 `NUMERIC(24,4)`，
于是声明成 `("total_mv", "numeric")`，结果 psycopg 报
`TypeError: class NumericDumper cannot dump float` —— Python 侧给的是 `float`，
而 `numeric` 适配器不接受它。改声明 `float8` 后正常：float8 的文本表示能被
`NUMERIC` 原样解析。

规则：**填的是「我这边发的是什么 Python 类型」，不是「库里那列是什么类型」。**
另外 `set_types` 要么不填、要么填全，不能只填一部分。

顺带一条：`raw_payload` 这类 JSONB 列在 `to_dict("records")` 之前必须把 NaN 换成
None —— `json.dumps(float('nan'))` 产出 `NaN` 字面量，PG 的 jsonb 解析器**会拒绝**，
整批 COPY 失败（而不是那一行失败）。

## D-042 datayes 的区间查询必须用 `tradeDate` 多值，不是 `beginDate`/`endDate`

配好 token 后第一次跑 live 契约用例，10 条挂了 9 条，全部是 retCode=-2：

```
At least one of [secID,ticker,tradeDate] parameters must be provided   (exposure / srisk / specific_ret)
At least one of [factorName,tradeDate] parameters must be provided     (covariance)
```

五张表里**只有 factor_ret 接受纯 `beginDate`+`endDate`**，另外四张必须在
`tradeDate` 那一组里至少给一个。接口文档看不出这一点：它的「是否必须」一栏填的
是「多选多」（文档作者也在注里标了这栏可疑），实测语义是「这一组至少给一个」。

实测确认的三条语义：

- `tradeDate` 支持**逗号分隔多值**（空格分隔返回 0 行，不报错 —— 又一个静默失败）；
- 给了 `tradeDate` 之后，`beginDate`/`endDate` **被忽略**；
- 单日 exposure 约 5551 行，因此一次最多塞约 17 天就会逼近 10 万行上限。

改法：`client._query_span()` 把区间展开成**工作日列表**发 `tradeDate`，
`query_range` 的切分与折半逻辑不动。周末不发（接口对非交易日只返回空，带上它
只让 URL 长 30%）；法定节假日仍然发 —— 查日历会让 raw 层依赖数据库，而
`meta.trading_calendar` 本身也是抓来的，那是循环依赖，代价只是几行空返回。

**这条是「live 契约用例挡住了设计错误」的实例**：Fake 永远测不出来，因为 Fake 是
照我们自己的理解写的。单测已把契约钉死在 `tests/raw/test_datayes_client.py`。

## D-043 通联的北交所后缀是 `XBEI`，不是 canonical 的 `XBSE`

`ingest/datayes/symbols.py` 原来假设「通联用的本来就是 canonical 码」，
把 `DATAYES_SUFFIX_TO_EXCHANGE` 写成恒等映射。**实测证明北交所不是。**

2026-08-28 单日 exposure 的后缀分布：`XSHE` 2897 / `XSHG` 2315 / **`XBEI` 339**，
一条 `XBSE` 都没有。XBEI 那 339 只全在 920xxx 代码段，与 `meta.instruments` 里
341 只 920xxx（exchange=XBSE）交叉核对一致 —— 是实测结论，不是按名字猜的。

不改的后果：339 只北交所标的的 `secID` 解析不出交易所 → `to_tushare_symbol()`
返回 None → symbol_map 建不起来 → 这批标的的因子数据整批入不了库。
未解析比例 339/5551 ≈ 6.1%，会撞上 0.5% 的容忍上限直接中断，所以**这次不会静默**；
但如果哪天北交所只剩十几只，就会掉到容忍线以下变成静默丢数。

`XBSE` 仍保留在映射表里兜底，万一供应商改用 canonical 码不至于整批解析不了。

**这条同样是探针用例抓出来的**（`test_sec_id_suffixes_are_all_known`）：
它枚举真实返回的后缀，出现未登记的就失败。当初写它时标的是「未决项 U21」，
现在证明这个未决项确实存在，而且答案与推测相反。

## D-044 datayes 五表的真实数据起点是 2021-08-02

探针方法（避免踩到自己挖的坑）：

1. **先别用 `meta.trading_calendar` 做二分。** 第一次这么做，五张表都「探到」
   最早是 2025-08-01 —— 那是**日历表在本库里的下界**，不是接口的下界
   （tushare calendar 当时只灌了 1520 行）。二分只能证明「在候选集合内最早」，
   候选集合本身错了就毫无意义。
2. **按年粗探时别取月初工作日。** 第二次用「每年 1/4/7/10 月的前 5 个工作日」，
   得出「最早 2022 年」。错的：2021 年那批候选日里，10 月 1–7 日整周是国庆、
   1 月 1 日元旦、4 月 5 日清明 —— 几乎全是节假日。改用**月中**（每月 12 日起的
   4 个工作日）后，2021 年立刻有数据。

最终结论：五张表**一致**在 2021-08-02（2021 年 8 月第一个交易日）起有数据，
2021-07 整月为空，2020 及更早全空。`config.yaml` 的
`providers.datayes.start_date` 因此定为 `20210802`，再往前抓只会拿到空返回。

顺带一条：手上那份 2020-12-31 的样本 CSV **不是本账号权限内的数据**，
它是供应商的演示样本。别拿它当「历史能取到 2020 年」的证据。

## D-051 数据契约与 DDL 的一致性由 `gr-db docs` 在 CI 守卫

`gr_data.common.contracts` 与 `gr-db` 的 DDL 原本分别维护，虽有「严格对齐」的约定，
但没有自动验证，新增列后很容易只改一侧。现在 `gr-db docs` 反射活库 catalog，读取
ingest 注册表和 `ops.table_ownership`，并在 `--fail-on-drift` 时将「契约列不存在」与
「运行时归属 provider 不在注册表中」作为 error；CI 的全新迁移库执行此检查。

多个 provider 可以声明同一张表作为可选接入能力，不能仅据此判定生产冲突；真正的单表
写入方由运行时 `ops.table_ownership` 锁定。将未启用的 importer 当作 error 会让 CI 对
合法的切换能力误报。

DDL 注释门禁只检查相对 PR 基线新增或修改的建表迁移，并从整个迁移目录收集 `COMMENT ON`，
这样后续迁移补的注释也有效；存量欠账不阻塞当前开发。新表除 `id`、`created_at`、
`updated_at` 外的每个列都必须有明确注释。

## D-052 zsh 的 `status` 是只读保留变量

执行验证包装命令时不能将退出码写入 `status`；zsh 会报 `read-only variable: status`，
即使前一条业务命令已经成功也会让整个 shell 返回失败。后续脚本统一使用任务专属名称，
如 `dictionary_exit_code`，或直接以最后一条验证命令的退出码结束。

## D-053 gr-db 只管理显式声明的业务 schema，不改 TimescaleDB 内部 catalog

活库的 `pg_class` 同时会列出 `_timescaledb_catalog`、`_timescaledb_internal` 等扩展内部对象，
以及可能由其它仓库迁移维护的 schema（当前为 `diag`）。这些对象不在
`packages/gr-db/src/gr_db/ddl/` 的唯一真源中；给它们写 `COMMENT ON` 会把扩展实现细节或
外部 schema 误纳入本仓迁移责任。

数据字典与全量注释迁移只覆盖 gr-db 明确拥有的 11 个 schema：`app`、`backtest`、
`classify`、`factor`、`fundamental`、`market`、`meta`、`ops`、`pick`、`realtime`、`staging`。
当前 85 张表、1,048 个字段均有 catalog 注释；以后新字段仍由 DDL 注释门禁负责阻止遗漏。

## D-054 DDL 注释门禁同时覆盖建表与后续新增列

仅检查 `CREATE TABLE` 会留下一个直接绕过路径：迁移可先创建带完整注释的表，再通过
`ALTER TABLE ... ADD COLUMN` 增加未经说明的业务字段。注释门禁现在会解析同一条 ALTER 的
多个 `ADD COLUMN [IF NOT EXISTS]` 动作，并要求每个非豁免字段在整个迁移目录中存在
`COMMENT ON COLUMN`；`id`、`created_at`、`updated_at` 保持自明字段豁免。

数据字典的 PG 契约／归属校验只能在实际传入 PostgreSQL 连接时执行。ClickHouse-only 模式
仍会列出 raw 数据集，但没有 PG catalog 作为比较基准时不能把它们判成漂移；否则
`gr-db docs --target ch --fail-on-drift` 会产生错误的失败。

## D-045 通联 CNE6 的行业体系在 2021-11 切换，`cne6-sw21` 的窗口只能从 2021-12 起

抓完全量后，`ModelRunImporter` 的逐月因子集校验当场报出：

```
2021-11 的活跃因子集合与 2021-08 不一致：
  多出 [BasicChemicals, BeautyCare, Coal, EnvironProtect, Petroleum,
        PowerEquip, RetailTrade, SocialServices, TextileApparel]
  缺少 [Chemicals, Commerce, ElectricalEquip, Leisure, Mining, TextileGarment]
```

逐月统计（61 个月）：**2021-08/09/10 是申万 2014（49 因子），2021-11 起是申万
2021（52 因子）**，只切换一次。注意接口路径叫 `...CNE6SW21`，但它对切换前的日期
返回的仍是旧体系 —— **端点名不能当作口径保证**。

更细的一层：切换在五张表之间**不是同一天发生的**。逐日核对 2021-11：

| 表 | 2021-11-01 |
|---|---|
| exposure | 已是申万 2021（4527 行全部落在新行业列） |
| factor_ret / covariance | **仍是申万 2014**（协方差当月 1141 行 = 49 + 21×52） |
| srisk / specific_ret | 无因子列，不受影响 |

所以 2021-11 是个混合月。五张表必须在同一个 `model_run` 内**逐日一致**（同一天
要能同时取到 X、F、D、f），因此 `cne6-sw21` 的窗口起点定为 **2021-12-01**，
实际入库 57 个月（2021-12 → 2026-08）。

**为什么不给申万 2014 那段单独开一个 run**：`factor.definition` 的主键是
`(model_id, factor_code)`、并且有 `UNIQUE (model_id, ordinal)`，是**按 model_id**
而不是按 model_version 建的。两套体系里同名因子的 ordinal 不同，塞进同一个
`model_id` 会直接撞唯一约束。要支持双体系，得先决定是拆 `model_id`
（`barra_cne6_sw14` / `barra_cne6_sw21`）还是把 `definition` 下沉到 model_version
—— 那是 `持仓诊断_表与接口设计.md` §5.2 的设计范围，**不在数据接入层单方面改**。
代价是 2021-08~11 共 4 个月（约 5% 的可取区间）暂时进不了库。

顺带一条**方法论**：这个错误是「逐月比对」抓出来的。原实现是先把 61 个月
`concat` 成一个大 DataFrame 再算 `active_factors`，那样得到的是两套体系的**并集
58 个**，既不等于 49 也不等于 52，会被当成「超集全都活跃」而静默混用两套下标。
改成逐月比对不只是为了省内存，它本身就是更强的校验。

## D-046 全量入库必须按月分批，否则会被 OOM killer 静默杀掉

第一次跑 `gr-data ingest datayes --only symbol_map,model_run` 的现象是：
**没有任何输出、退出码 0、一行数据都没落库**。不是异常被吞了，是进程被
OOM killer 杀掉 —— 这种失败模式比报错危险得多，看日志会以为「跑完了但没数据」。

本机 5 GB 内存（可用约 2 GB），而 importer 的形态是「读全部月份 → 拼一个大
DataFrame → 一次 upsert」：

| 数据集 | 规模 | pandas 占用 |
|---|---|---|
| datayes exposure | 61 个月 × 11 万行 × 58 列 | 约 3.5 GB |
| tushare daily_basic | 164 个月 × 11 万行 | 加上 merge 的中间结果同样量级 |

三处改动（都向后兼容，默认行为不变）：

1. `IngestContext.months` + 两个 adapter 的 `list_months` 过滤，
   `gr-data ingest --months 2021-12..2026-08` 暴露到 CLI。按月调用把峰值压到单月
   量级，代价是每月一条 `ops.etl_job_run` —— 这反而让「哪个月入过库」可追溯。
2. `DatayesSymbolMapImporter` / `ModelRunImporter` 改成**逐月读、当场归约**
   （前者累积 secID 集合，后者只比对列集合），它们本来就不需要行数据。
3. `InstrumentIndustryImporter` **不能按月分批**（区间压缩需要全历史，分批会把每个月
   压成独立区间、`out_date` 全错，而且 EXCLUDE 约束拦不住 —— 它们并不重叠）。
   改成逐月读入后立刻降到 4 列，全历史中间结果约 200 MB。

顺带一条 `statement_timeout`：分批之后单批只有 10 万行左右，30 分钟的超时绰绰有余；
但**不分批时曾在 60s 处被 `QueryCanceled` 打断并整批回滚**（见 D-038）。

## D-047 通联接口在大响应上会中途断连，而读超时拦不住它

抓 exposure 时（按 10 个自然日切，单次响应约 4 MB）反复出现：

```
peer closed connection without sending complete message body
  (received 2724243 bytes, expected 3900172)
```

重试能接住，但随后会转成**持续的读超时**，而且**拖不死也退不出**：
httpx 的 `timeout` 是「两次收到字节之间的最长间隔」，服务端慢速涓流会不断重置它。
实测单个 chunk 卡了 33 分钟仍未触发超时，`retry_call` 重试 5 次耗尽后整批抓取中断
（`fetch()` 只捕获配额与未授权两类异常）。

处理：`ExposureFetcher.CHUNK_DAYS` 10 → 4，把响应压到约 1.5 MB，之后不再触发。
**但要知道代价**：服务端耗时几乎与返回行数无关（每次约 60–100 秒），切得越碎总耗时
越长 —— 实测 4 天切分反而比 10 天慢（14 min/月 vs 7 min/月）。

真正的杠杆是**并发**：瓶颈是服务端响应时间，不是我们的调用频率（实测约 0.03 req/s，
远低于配置的 1 req/s）。用 4 并发的一次性脚本回补 43 个月，零失败，
把 10 小时压到 1.5 小时。这条没有写进仓库代码 —— 并发抓取要不要成为常规能力，
涉及限流策略与配额，是需要先讨论的架构决定。
