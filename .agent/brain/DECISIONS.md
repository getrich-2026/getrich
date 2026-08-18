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
