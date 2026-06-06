# 数据库迁移

GetRich 使用**项目自带的迁移运行器**管理 PostgreSQL + ClickHouse 的 schema 变更。

**CLAUDE.md §6 铁律**：所有 PostgreSQL / ClickHouse schema 变更必须通过 `migrations/*.sql` 文件提交，并由 `python -m getrich.migrations.cli` 应用。**禁止**手动 `psql` 在生产 / 测试环境跑未走 runner 的 SQL。

---

## 1. 迁移运行器 CLI

### 1.1 命令

```bash
# 应用 PG migrations
python -m getrich.migrations.cli postgres

# 应用 CH migrations
python -m getrich.migrations.cli clickhouse

# 应用两个数据库（推荐部署流程）
python -m getrich.migrations.cli all

# 只打印发现 / 已应用状态
python -m getrich.migrations.cli status

# 试跑（dry-run）
python -m getrich.migrations.cli postgres --dry-run
python -m getrich.migrations.cli clickhouse --dry-run
```

### 1.2 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | Migration 错误（语法、断号、重复等） |
| 2 | 数据库连接失败 |

### 1.3 示例输出

```
[postgres] applied 3 migration(s): 023_idempotency.sql, 024_detail_html_length.sql, 025_signals_reason.sql
[clickhouse] no migrations to apply (already up to date)
```

---

## 2. 命名规范

**CLAUDE.md §6**：

- 文件名前缀为 **3+ 位数字**（`001_xxx.sql`），决定应用顺序
- **数字必须连续**（不允许 `001 → 003` 跳过 `002`），runner 会拒绝
- 不得有重复前缀，runner 会拒绝
- PostgreSQL migration 放 `migrations/`；ClickHouse migration 放 `migrations/clickhouse/`

### 2.1 文件名示例

```
migrations/
├── 001_sub_account_routing.sql
├── 002_strategy_trades.sql
├── 003_users.sql
├── ...
└── 025_signals_reason.sql

migrations/clickhouse/
├── 001_ohlcv_bars.sql
└── 002_factors_long.sql
```

---

## 3. 编写规范

### 3.1 幂等性

- **优先**用 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` 等幂等语句
- 一个文件一个逻辑主题（一张表、一个 index、一组相关 ALTER）
- 便于重跑

### 3.2 业务库与 schema

- **PG 业务库名是 `getrich`**（不是 `frontend` / `goldmine`），schema 名是 `frontend`
- **所有 SQL 内部**必须全限定引用 `frontend.users` 等
- 不依赖连接池的 `search_path`（runner 在 DSN 加 `options="-c search_path=frontend"`，但 SQL 显式引用是 best practice）

### 3.3 破坏性变更

- DROP / TRUNCATE 等破坏性操作**必须**先在 NOTES.md 风险评估
- 不可逆操作建议加保护（如 DROP 前的 `SELECT COUNT(*)` 断言）

### 3.4 新增列

- **必须**显式带 `DEFAULT`（避免大表 NOT NULL 失败）
- 大表 ALTER（如 `ALTER TABLE ADD COLUMN` 锁表）建议在低峰期跑

### 3.5 ClickHouse 特殊要求

- CH 没有跨语句事务，**所有 migration 必须幂等**
- 强制使用 `MergeTree` 系列引擎
- 强制 `PARTITION BY`、`ORDER BY`、`TTL` 配置
- 时间字段用 `DateTime64(3, 'Asia/Shanghai')`（防夜盘跨日丢失）

---

## 4. 一个完整的 migration 文件

### 4.1 PostgreSQL

```sql
-- migrations/026_add_user_preferences.sql
-- Add user notification preferences (Round #1070)

CREATE TABLE IF NOT EXISTS frontend.user_preferences (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES frontend.users(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent index
CREATE INDEX IF NOT EXISTS user_preferences_user_id_idx
    ON frontend.user_preferences (user_id);

-- Composite index for the hot query
CREATE INDEX IF NOT EXISTS user_preferences_user_category_idx
    ON frontend.user_preferences (user_id, category);
```

### 4.2 ClickHouse

```sql
-- migrations/clickhouse/003_signals_history.sql
-- Add signals history (long format) for backtest factor analysis

CREATE TABLE IF NOT EXISTS signals_long
(
    dt          DateTime64(3, 'Asia/Shanghai'),
    symbol      LowCardinality(String),
    action      Enum8('buy' = 1, 'sell' = -1),
    confidence  Float32,
    trigger_price  Float64,
    reason      String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(dt)
ORDER BY (symbol, dt)
TTL dt + INTERVAL 3 YEAR
COMMENT 'Signal production history for backtest factor analysis';
```

---

## 5. 内部机制

### 5.1 已应用追踪表

runner 在每个数据库建一张 `migrations_applied` 表，存已应用的 `(name, applied_at, checksum)`：

```sql
CREATE TABLE migrations_applied (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum    TEXT NOT NULL
);
```

启动时只查询该表，与磁盘上的 `.sql` 文件做差集，得到待应用列表。

### 5.2 校验

- 文件名前缀必须连续（`001`, `002`, `003`, ...，中间无缺）
- 不得有重复前缀
- 单文件 checksum 不变（防止运行中被人改文件）
- 数据库连接（psycopg3）必须能连

### 5.3 应用流程

对每个待应用 migration：

1. 在事务中执行（PG；CH 跳过事务）
2. 成功后插入 `migrations_applied` 行
3. COMMIT
4. 失败 → ROLLBACK + 立即退出（非零码）

### 5.4 并发保护

runner 用 `SELECT ... FOR UPDATE` 锁住 `migrations_applied` 表的待处理行；多个 runner 同时跑不会重复应用。

---

## 6. 常见错误

### 6.1 断号

```
Error: migration prefix 005 is missing (found 004, 006)
```

**修复**：补一个 `005_xxx.sql` 空迁移（内容是 `SELECT 1;`），或把后续文件前缀整体减 1。

### 6.2 重复前缀

```
Error: duplicate migration prefix 003
```

**修复**：合并两个文件或重新编号。

### 6.3 search_path 找不到表

```
Error: relation "users" does not exist
```

**修复**：所有 SQL 内部必须用 `frontend.users` 全限定。

### 6.4 CH 迁移不可逆

CH 没有事务。如果一半语句成功一半失败，会留下"半迁移"状态。**修复**：手动清理 + 改 SQL 让它完全幂等（每条都是 `IF NOT EXISTS`）。

---

## 7. CI 集成

`.github/workflows/ci.yml` 的 test job 在跑 pytest 之前自动应用所有 migrations：

```yaml
- name: Apply PG migrations
  run: uv run python -m getrich.migrations.cli postgres
- name: Apply CH migrations
  run: uv run python -m getrich.migrations.cli clickhouse
- name: Run tests
  run: uv run pytest tests/ -v
```

---

## 8. 部署流程

```bash
# 1. 拉代码
git pull

# 2. 查看待应用
python -m getrich.migrations.cli status

# 3. 试跑（不实际执行）
python -m getrich.migrations.cli all --dry-run

# 4. 实际应用
python -m getrich.migrations.cli all

# 5. 重启服务（如果 schema 变了）
systemctl restart getrich-api
systemctl restart getrich-worker.target
```

---

## 9. 进阶：自己写一个 migration runner

如果新数据库（比如 DuckDB）也需要迁移，可复用 `src/getrich/migrations/runner.py`：

```python
from getrich.migrations.runner import run_directory
from getrich.migrations.executors import DuckDBMigrationExecutor

# 假设已有 DuckDB 客户端
async def apply():
    executor = DuckDBMigrationExecutor(duckdb_client)
    plan = await run_directory(Path("migrations/duckdb/"), executor)
    print(f"Applied {len(plan.migrations)} migrations")
```

详见 [`src/getrich/migrations/`](https://github.com/getrich/getrich/tree/main/src/getrich/migrations/) 源码。
