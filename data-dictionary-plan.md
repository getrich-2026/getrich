# 实施计划：数据字典生成器（`gr-db docs`）+ DDL 注释门禁

> 本文档是给**执行 agent** 的自包含实施计划。开工前请先读 `AGENTS.md`（项目约束唯一真源）
> 与 `.agent/brain/DECISIONS.md`。文中所有路径均相对仓库根目录。

## 1. 背景与目标

GetRich 的数据分散在三处，目前**没有任何一个地方能一次看全**：

| 层 | 规模 | 位置 |
|---|---|---|
| PostgreSQL | 85 张表 / 11 个 schema | `packages/gr-db/src/gr_db/ddl/postgres/*.sql`（3205 行） |
| ClickHouse | 1 张 `factors_long` | `packages/gr-db/src/gr_db/ddl/clickhouse/001_factors_long.sql` |
| raw parquet | 5 个 provider 的若干 dataset | `$RAW_PARQUET_ROOT`（仓库外） |

PG 各 schema 表数：market 22、app 22、backtest 10、ops 8、factor 8、meta 5、classify 4、
pick 2、fundamental 2、staging 1、realtime 1。

要知道某张表是什么、谁写的、字段什么含义，只能翻 SQL 原文。**目标**：一条 `gr-db docs` 命令
产出一个自包含 HTML，覆盖 PG + CH + raw 三层，标注每张表的写入方与字段含义，并列出契约/归属漂移；
同时给 DDL 加一道注释门禁，让字典成为 DDL 的副产物而非会腐烂的副本。

**为什么放在 getrich 仓库内而不是新开仓库**：字典的唯一输入是 DDL 与活库 catalog，两者都在
本仓库。分仓即刻违反 `AGENTS.md` §2「全部 DDL 的唯一真源是 `gr_db/ddl/`」——DDL 一改，
外仓字典就烂且无人知晓。

## 2. 探索已确认的事实（不必重新验证）

1. **ingest 层有统一注册表**。5 个 provider（`tushare` / `datayes` / `insight` / `ricequant` /
   `yinhe`）的 `packages/gr-data/src/gr_data/ingest/<provider>/__init__.py` 一律导出
   `REGISTRY: dict[dataset, ImporterClass]` 与 `GROUPS`。每个 importer 类携带 `PROVIDER` /
   `DATASET` / `CONTRACT: TableContract | None`（基类见
   `packages/gr-data/src/gr_data/ingest/base.py::BaseImporter`）。
   → `provider → dataset → 目标表 → canonical 列` **可全自动推导，不要手写清单**。

2. **`TableContract` 的形状**（`packages/gr-data/src/gr_data/common/contracts/base.py`）：
   frozen dataclass，字段 `schema` / `table` / `columns` / `conflict_keys` / `column_types`，
   属性 `qualified` 返回 `"schema.table"`。

3. **契约漂移目前无人守**。`AGENTS.md` §3.4 要求 `common/contracts` 的 canonical 列定义与
   gr-db 的 DDL「严格对齐，改一边必须同步另一边」，但仓库里**没有任何代码或测试在校验**。
   本计划顺带关闭这个缺口。

4. **归属登记表**：`ops.table_ownership(target, provider, channel, updated_at)`，DDL 见
   `packages/gr-db/src/gr_db/ddl/postgres/008_ownership.sql`，管理器见
   `packages/gr-data/src/gr_data/common/ownership.py`。它是**运行时**登记，可与第 1 条的
   **静态**推导交叉比对。

5. **现有 CLI 与连接方式**（`packages/gr-db/src/gr_db/cli.py`）：argparse，`command` 是
   positional，`choices=("migrate", "status")`。PG 走同步 `psycopg.connect(dsn)`，DSN 由
   `gr_data.config.settings.postgres` 拼；CH 走 `clickhouse_connect.get_client(...)`，
   注意 `_run_clickhouse` 里的注释——传 `protocol=` 会 TypeError，必须用 `secure=` 布尔。

6. **注释存量**：85 张 `CREATE TABLE` 对应 97 条 `COMMENT ON`，覆盖不全，且大量语义写在
   `--` 行注释里（典型如 `037_factor.sql` 顶部「model_run 一旦写入不可 UPDATE」——对下游最要紧，
   但 DB 里查不到）。

7. **raw 路径约定**：`packages/gr-data/src/gr_data/common/paths.py::RawPaths`，布局
   `<root>/<provider>/<dataset>/...`，根目录取 `gr_data.config.pipeline` 的 `raw_root`
   （优先级：`RAW_PARQUET_ROOT` 环境变量 > `config.yaml` 的 `paths.raw_root` > `/opt/raw_parquet`）。

8. **CI 结构**（`.github/workflows/ci.yml`）：`python-quality` job 已在跑
   `scripts/lint_migrations.py --db all`；`python-tests` job 自带 PG + CH + Redis 服务，
   并已执行 `gr-db migrate --target pg|ch`——生成器可在那里免费做冒烟验证。

## 3. 已确认的范围与决策

| 项 | 决定 |
|---|---|
| 本轮范围 | 生成器 + 注释门禁 |
| 存量 `COMMENT ON` 补齐 | **不在本轮**（后续按 schema 推进，market / meta / factor 优先） |
| OpenAPI 导出 / Apifox 改造 | **不在本轮**，另开一轮 |
| HTML 产物去向 | 仓库外，默认 `<raw_root>/_docs/data-dictionary.html` |
| 注释门禁强度 | **只管新增/修改的迁移文件**，存量欠账不阻塞 CI |

**硬约束：**

- **不新增第三方依赖**。`packages/gr-db/pyproject.toml` 现有依赖仅 `clickhouse-connect` /
  `gr-data` / `psycopg[binary,pool]`。HTML 用 `string.Template` + `html.escape` 渲染，
  **不要引 Jinja2**——依赖变更属 `AGENTS.md` §8 必须先说的类别。
- **反射活库 catalog，不解析 SQL 文本**。`006_ops.sql` 里的 `DO $$ ... $$` 块和
  `ALTER TABLE ADD COLUMN IF NOT EXISTS` 让静态解析既易错又拿不到真实类型与索引。
  （例外：第 6 节的注释门禁**必须**是文本检查，因为它要在 CI 里离线跑。）
- 首行 `from __future__ import annotations`；注释与文档用中文，标识符用英文。

---

## 4. 新建 `packages/gr-db/src/gr_db/docs/` 模块

```
gr_db/docs/
    __init__.py       # 对外只暴露 build_dictionary() / render_html()
    model.py          # 纯 dataclass，无 IO
    introspect.py     # PG / CH catalog → model
    provenance.py     # gr-data REGISTRY + ops.table_ownership → 归属与漂移
    ddl_lint.py       # DDL 文本的 COMMENT ON 覆盖率检查（供 scripts/ 复用）
    render.py         # model → 单文件 HTML
    template.html     # 内嵌 CSS/JS 的骨架，随包安装
```

### 4.1 `model.py`

`ColumnDoc` / `TableDoc` / `SchemaDoc` / `DatasetDoc` / `DriftFinding` / `Dictionary`，
全部 frozen dataclass。`DriftFinding` 带 `severity: Literal["error", "warn"]`。

### 4.2 `introspect.py`

PostgreSQL 侧（连接方式照抄 `cli.py::_run_postgres`）：

- 表与注释：`pg_class` + `pg_namespace` + `obj_description(c.oid, 'pg_class')`
- 列：`pg_attribute` + `format_type()` + `col_description()`。**用 `pg_attribute` 而非
  `information_schema.columns`**——后者会把数组与自定义类型退化成 `ARRAY`，而 `factor.*`
  的数组列正是重点
- 约束：`pg_constraint` + `pg_get_constraintdef()`，区分 PK / UNIQUE / FK / CHECK
- 索引：`pg_index` + `pg_get_indexdef()`，排除已被约束覆盖的
- 行数与体积：`pg_class.reltuples`、`pg_total_relation_size()`。**页面必须标注是估算值**——
  在 `market.*_bar_1m` 上跑 `count(*)` 不可接受
- 超表：`timescaledb_information.hypertables` / `.dimensions` / `.compression_settings`。
  **整段用 try/except 包住**，扩展不存在时跳过（CI 的 timescaledb 镜像有，本地 pg 可能没有）

ClickHouse 侧：`system.tables`（engine / partition_key / sorting_key / comment / total_rows /
total_bytes）+ `system.columns`（name / type / comment）。

### 4.3 `provenance.py`

两个来源合并：

- **静态**：`importlib.import_module(f"gr_data.ingest.{p}")` 取 `REGISTRY`，读每个 importer 类的
  `PROVIDER` / `DATASET` / `CONTRACT`。`CONTRACT` 可能为 `None`，必须容忍
- **运行时**：`SELECT target, provider, channel, updated_at FROM ops.table_ownership`

产出 `DriftFinding`：

| 现象 | severity |
|---|---|
| `TableContract.columns` 里有列在活库中不存在 | error |
| `ops.table_ownership.provider` 与 REGISTRY 推导的 provider 冲突 | error |
| 同一目标表被多个 provider 的 importer 声明 | error |
| 活库有列不在契约里（`updated_at` 除外） | warn |
| 有 importer 写但 `ops.table_ownership` 未登记 | warn |
| 表或列缺 `COMMENT ON` | warn |

raw 层数据集清单同样从 REGISTRY 推导，路径布局取 `RawPaths` 的约定；若 `raw_root` 可访问则
顺带统计各 dataset 的文件数与总字节（**不可访问就只列约定路径，不报错**——生成器不能依赖
仓库外目录存在）。

### 4.4 `render.py` + `template.html`

单文件输出，**严格无外部请求**：

- 顶部统计条：schema 数 / 表数 / 列数 / 注释覆盖率 / error 与 warn 漂移计数
- 左侧 sticky 导航：PG 按 schema 分组 → ClickHouse → Raw datasets
- 每表一张卡片：全限定名、表注释、写入 provider + dataset、行数估算、体积、超表与压缩策略、
  列表格（列名 / 类型 / NULL / 默认 / 注释）、约束、索引
- 顶部搜索框即时过滤表名与列名，纯原生 JS
- 漂移单独一节，error 置顶
- 配色跟随 `prefers-color-scheme`，深浅两套都显式定义

**所有插值一律过 `html.escape`**——DDL 注释里有中文、引号和尖括号。

---

## 5. `gr-db docs` 子命令

改 `packages/gr-db/src/gr_db/cli.py`：`command` 的 `choices` 增加 `"docs"`，新增参数：

```
--out PATH            默认 $GETRICH_DOCS_OUT，未设则 <raw_root>/_docs/data-dictionary.html；
                      "-" 写 stdout
--format html|json    默认 html。json 供测试断言结构与后续做 diff，不必解析 HTML
--fail-on-drift       仅当存在 severity=error 的 finding 时退出码非 0
```

`main()` 里在 `status` 分支旁加 `docs` 分支。写文件走**原子写**（先 `*.tmp-<uuid>` 再
`os.replace()`），与 `AGENTS.md` §3.4 对 parquet 落地的要求同构。

`packages/gr-db/pyproject.toml` 的 `[tool.setuptools.package-data]` 增加 `"docs/*.html"`，
否则模板不随包安装（与现有 `ddl/*.sql` 同样的理由）。

---

## 6. DDL 注释门禁

逻辑放 `gr_db/docs/ddl_lint.py`（DDL 归 gr-db，且放这里才能被 `packages/gr-db/tests` 正常测到），
`scripts/lint_migrations.py` 只做薄封装调用。

- 现有 `scripts/lint_migrations.py` 的 `IGNORED_SQL` 是剥注释与字面量用的，注释检查需要
  **保留** `--` 行以外的内容，**单独写一遍正则，不要复用 `find_violations`**
- 从文件中抽 `CREATE TABLE IF NOT EXISTS <schema>.<name> (...)` 及其列名；
  从**整个 ddl 目录**收集 `COMMENT ON TABLE` / `COMMENT ON COLUMN` 的目标——后续迁移可能给
  早先的表补注释，只扫单文件会误报
- 判定：changed 文件中新建的每张表必须有表注释；每个列必须有列注释，豁免一份显式的自明列名
  集合（`updated_at` / `created_at` / `id`）
- 变更集判定：`git diff --name-only <base-ref>...HEAD` 过滤到 ddl 目录。`--base-ref` 默认
  `origin/dev`。**git 不可用或 ref 不存在时打 WARN 并跳过（退出 0）**，避免本地无 remote 时误红

`scripts/lint_migrations.py` 新增 `--comments` 与 `--base-ref`，**默认关闭，保持现有调用行为不变**。

---

## 7. CI 接线（`.github/workflows/ci.yml`）

`python-quality` job：

- `actions/checkout@v7` 加 `fetch-depth: 0`——当前是默认浅克隆，`git diff origin/dev...HEAD`
  拿不到 base
- 在 `Migration topology lint` 之后新增：

```yaml
- name: Migration comment coverage
  run: >-
    uv run --frozen python scripts/lint_migrations.py --db pg --comments
    --base-ref origin/${{ github.base_ref || 'dev' }}
```

`python-tests` job（仅 `matrix.coverage` 那格，migrations 步骤之后）加一步生成器冒烟：

```yaml
- name: Data dictionary smoke
  if: matrix.coverage
  run: uv run --frozen gr-db docs --target all --out /tmp/dd.html --fail-on-drift
```

CI 是全新迁移出来的库，契约理应与 DDL 完全一致，`--fail-on-drift` 只看 error 级别，
`ops.table_ownership` 为空只产生 warn，不会误红。**这一步顺带把第 2 节第 3 条的缺口关上了。**

---

## 8. 测试（`packages/gr-db/tests/`）

- `test_docs_introspect.py`：喂 fake cursor 的 catalog 行，断言 model 组装、以及
  timescaledb 信息缺失时的降级路径
- `test_docs_provenance.py`：从**真实** REGISTRY 推导，断言每个目标表只被一个 provider 声明
  （这本身就是「单表单一来源」铁律的静态守卫），以及 `CONTRACT is None` 的 importer 不会让流程崩
- `test_docs_render.py`：model → HTML，断言产物不含 `http://` / `https://` 外链、表名出现、
  含尖括号与引号的注释被正确转义
- `test_ddl_lint.py`：构造带/不带 `COMMENT ON` 的临时 SQL，断言命中与豁免；断言 base-ref
  缺失时返回 0

---

## 9. 验证

```bash
# 依赖与静态检查
uv sync --frozen --all-packages
uv run ruff check packages scripts && uv run ruff format --check packages scripts

# 单元测试
uv run pytest packages/gr-db/tests -v

# 打真库：先迁移，再生成
uv run gr-db migrate --target all
uv run gr-db docs --target all --out /tmp/dd.html
uv run gr-db docs --target all --format json --out - | head -40
uv run gr-db docs --target all --format json --out - --fail-on-drift; echo "exit=$?"

# 门禁：现有行为不变 + 新增检查
uv run python scripts/lint_migrations.py --db all
uv run python scripts/lint_migrations.py --db pg --comments --base-ref origin/dev
```

**人工验收**：浏览器打开 `/tmp/dd.html`，确认

1. 离线打开无破图、无控制台报错
2. 搜索 `bar_1d` 能同时命中 5 张行情表
3. `market.stock_bar_1d` 卡片上写着写入方 provider 与超表/压缩信息
4. 漂移一节列出的 error 条目为空或可解释
5. 切换系统深色模式配色正常

---

## 10. 交付后

- 按 `AGENTS.md` §7 更新 `.agent/brain/NOTES.md`
- 在 `.agent/brain/DECISIONS.md` 追加一条：「`common/contracts` 与 gr-db DDL 的对齐此前无人守，
  现由 `gr-db docs --fail-on-drift` 在 CI 承担」

## 11. 后续（不在本轮）

1. 按 schema 补齐存量 `COMMENT ON`，market / meta / factor 优先，补完后可考虑把门禁从
   「只管新增」升级为全量强制
2. FastAPI 的 OpenAPI 导出进仓库 + CI 一致性校验，Apifox 改为从该 spec 单向导入
   （方向锁死为 代码 → Apifox）。动机与 `DECISIONS.md` D-032 同源：手维护的响应结构会与真实
   返回漂移，**而漂移不报错**
