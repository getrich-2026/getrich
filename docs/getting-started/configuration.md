# 配置

> **本节讲解 GetRich 平台的环境变量 + 配置文件体系**。所有配置走 `pydantic-settings` 12 因子模式：环境变量 > `.env` > 默认值。**单一真源**：[`src/getrich/config/settings.py`](https://github.com/getrich/getrich/blob/main/src/getrich/config/settings.py)。

---

## 1. 配置加载优先级

```mermaid
flowchart LR
    HardC[代码默认值] --> ENV[env var]
    ENV --> ENVFile[.env / .env.local]
    ENVFile --> ENVProd[.env.production]
    ENVProd --> Pydantic[pydantic-settings]
    Pydantic --> Validate[类型校验 + 启动期 fail-fast]
```

> **环境变量 > `.env` > 硬编码默认值**。同名变量后写的覆盖先写的；pydantic 自动做大小写不敏感解析。

---

## 2. `.env` 文件位置

| 文件 | 用途 | git 追踪 |
|---|---|---|
| `.env` | 默认配置（开发） | ❌ 建议 `.gitignore`（含密码） |
| `.env.example` | **所有变量名 + 默认值**（不含密码） | ✅ 入库 |
| `.env.local` | 本地覆盖（**不入库**） | ❌ `.gitignore` |
| `.env.production` | 生产环境 | ❌ 系统注入（如 systemd EnvironmentFile=） |

> 推荐：**commit `.env.example` 永远同步**；本地用 `.env.local`；生产用 systemd `EnvironmentFile=`。

### 2.1 `.env.example` 模板

```bash
# .env.example —— 完整变量清单（不含密码）
# 复制为 .env.local 填实际值

# ---------------- PostgreSQL ----------------
GETRICH_PG__HOST=localhost
GETRICH_PG__PORT=5432
GETRICH_PG__USER=quant
GETRICH_PG__PASSWORD=
GETRICH_PG__DATABASE=getrich
GETRICH_PG__POOL_MIN_SIZE=2
GETRICH_PG__POOL_MAX_SIZE=20

# ---------------- ClickHouse ----------------
GETRICH_CLICKHOUSE__HOST=localhost
GETRICH_CLICKHOUSE__PORT=8123
GETRICH_CLICKHOUSE__USER=default
GETRICH_CLICKHOUSE__PASSWORD=
GETRICH_CLICKHOUSE__DATABASE=getrich
GETRICH_CLICKHOUSE__PROTOCOL=http

# ---------------- DuckDB ----------------
GETRICH_DUCKDB__PATH=:memory:
GETRICH_DUCKDB__PARQUET_ROOT=

# ---------------- Redis (Celery broker) ----------------
GETRICH_REDIS__URL=redis://localhost:6379/0
GETRICH_REDIS__RESULT_BACKEND=redis://localhost:6379/1

# ---------------- Web API ----------------
GETRICH_WEB__HOST=0.0.0.0
GETRICH_WEB__PORT=8000
GETRICH_WEB__JWT_SECRET=
GETRICH_WEB__JWT_EXPIRES_MIN=15
GETRICH_WEB__CORS_ORIGINS=
GETRICH_WEB__CSP_POLICY="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
GETRICH_WEB__DOCS_URL=/docs
GETRICH_WEB__OPENAPI_URL=/openapi.json

# ---------------- Backtest 存储 ----------------
GETRICH_BACKTEST_STORAGE__ARTIFACT_DIR=/var/lib/getrich/artifacts
GETRICH_BACKTEST_STORAGE__PUBLIC_BASE_URL=https://getrich.example.com/content

# ---------------- Worker ----------------
GETRICH_WORKER_BACKEND=inproc
GETRICH_WORKER_BROKER_URL=redis://localhost:6379/0
GETRICH_WORKER_RESULT_BACKEND=redis://localhost:6379/1
GETRICH_WORKER_FLOWER_URL=http://localhost:5555

# ---------------- 日志 ----------------
GETRICH_LOGGING__LEVEL=INFO
GETRICH_LOGGING__FORMAT=%(asctime)s [%(levelname)s] %(name)s: %(message)s
GETRICH_LOGGING__FILE_PATH=

# ---------------- 行情源（可选） ----------------
# GETRICH_RICEQUANT__ENABLED=false
# GETRICH_RICEQUANT__API_KEY=
# GETRICH_HDB__ENABLED=false
# GETRICH_INSIGHT__ENABLED=false
# GETRICH_INSIGHT__USER=
# GETRICH_INSIGHT__PASSWORD=
```

> ⚠️ **`__` 双下划线 = 嵌套**（pydantic-settings 约定）：`GETRICH_WEB__PORT` → `Settings.web.port`。

---

## 3. 12 个 Config 类

> 源码：`src/getrich/config/settings.py`

| 类 | 字段 | 默认 |
|---|---|---|
| `PostgresConfig` | host / port / user / password / database / pool min/max | localhost:5432 |
| `ClickHouseConfig` | host / port / user / password / database / protocol | localhost:8123 / http |
| `DuckDBConfig` | path / parquet_root | `:memory:` |
| `BacktestStorageConfig` | artifact_dir / public_base_url | `/var/lib/getrich/artifacts` |
| `LoggingConfig` | level / format / file_path | `INFO` / stdout |
| `RiceQuantConfig` | enabled / api_key | `false` |
| `HdbConfig` | enabled | `false` |
| `InsightConfig` | enabled / user / password | `false` |
| `WebConfig` | host / port / jwt_secret / cors_origins / csp_policy / docs_url | 0.0.0.0:8000 |
| `WorkerConfig` | backend / broker_url / result_backend / flower_url | inproc |

`Settings` 是根类：

```python
class Settings(BaseSettings):
    pg: PostgresConfig = PostgresConfig()
    ch: ClickHouseConfig = ClickHouseConfig()
    duckdb: DuckDBConfig = DuckDBConfig()
    backtest_storage: BacktestStorageConfig = BacktestStorageConfig()
    logging: LoggingConfig = LoggingConfig()
    web: WebConfig = WebConfig()
    worker: WorkerConfig = WorkerConfig()
    ricequant: RiceQuantConfig | None = None
    hdb: HdbConfig | None = None
    insight: InsightConfig | None = None

    model_config = SettingsConfigDict(
        env_prefix="GETRICH_",
        env_nested_delimiter="__",
        env_file=(".env", ".env.local"),
        case_sensitive=False,
        extra="ignore",
    )
```

---

## 4. 在代码中读取

```python
from getrich.config import settings

# 方式 1：直接读
db_host = settings.pg.host
broker = settings.worker.broker_url

# 方式 2：在 FastAPI dependency 中
from getrich.apps.web.deps import get_db

# 方式 3：注入到 Celery task
@celery_app.task
def my_task():
    broker = settings.worker.broker_url
```

> `settings` 是 `lru_cache` 的单例 —— 启动时加载一次，运行期改环境变量**不生效**。

---

## 5. 校验与启动 fail-fast

`pydantic-settings` 在启动时**强制类型校验**。下面这些会立刻 fail：

| 错误 | 触发 | 修法 |
|---|---|---|
| `port=abc` | 整数字段给字符串 | 类型修正 |
| `host=` 空 | 必填字段空 | 设值 |
| `pool_max_size < pool_min_size` | 自定义 validator | 调整 |
| `csp_policy="..."` 含非法字符 | CSP 解析失败 | 重新写 |
| `worker_backend=celery` 但没设 `broker_url` | 启动检查 | 配 Redis |
| `jwt_secret=""` 长度 < 32 | 安全检查 | 用长随机串 |

> **生产 fail-fast 比运行时崩溃好** —— 启动时立刻报"配置错"，运维能在 5 秒内看到。

---

## 6. 三个环境模板

### 6.1 本地开发

```bash
# .env.local
GETRICH_PG__PASSWORD=devpass
GETRICH_WEB__JWT_SECRET=dev-only-not-for-prod-32bytes-min
GETRICH_LOGGING__LEVEL=DEBUG
GETRICH_WEB__CORS_ORIGINS=["http://localhost:5173"]
```

### 6.2 CI（GitHub Actions）

```yaml
# .github/workflows/ci.yml 注入
env:
  PG_HOST: localhost
  PG_PORT: "5432"
  PG_USER: quant
  PG_PASSWORD: testpass
  PG_DB: getrich
  CLICKHOUSE_HOST: localhost
  CLICKHOUSE_PORT: "8123"
  GETRICH_WORKER_BACKEND: celery
  GETRICH_BROKER_URL: redis://localhost:6379/0
```

> CI 用 service 容器（PG/CH/Redis）而不是 .env 文件。

### 6.3 生产（systemd）

```ini
# /etc/getrich/api.env
GETRICH_PG__PASSWORD=<from-secret-manager>
GETRICH_WEB__JWT_SECRET=<from-secret-manager>
GETRICH_WEB__CORS_ORIGINS=["https://app.getrich.example.com"]
GETRICH_WEB__CSP_POLICY="default-src 'self'; ..."
```

```ini
# /etc/systemd/system/getrich-api.service.d/override.conf
[Service]
EnvironmentFile=/etc/getrich/api.env
```

> **不要**把 `.env` 文件 commit 到 git。密码用 secret manager（HashiCorp Vault / AWS Secrets Manager / 1Password CLI）。

---

## 7. 热重载（开发用）

`uvicorn --reload` 在代码改动时自动重启 API；环境变量改动**不会触发**重启。

```bash
# 改 .env.local 后手动重启
pkill -f "uvicorn getrich"
uvicorn getrich.apps.web.main:app --reload
```

---

## 8. Secret 管理

| Secret | 存储 | 注入方式 |
|---|---|---|
| `GETRICH_PG__PASSWORD` | Vault / SM / 1Password | 环境变量 |
| `GETRICH_WEB__JWT_SECRET` | Vault | 环境变量 |
| `GETRICH_CLICKHOUSE__PASSWORD` | Vault | 环境变量 |
| `GETRICH_RICEQUANT__API_KEY` | Vault | 环境变量 |
| broker TLS 证书 | 文件 | mount 进容器 |

> **永远不要**把 secret 写到 `.env.example` 或 commit 到 git。

---

## 9. 常见配置错误

| 症状 | 真正原因 | 修法 |
|---|---|---|
| `ValidationError: pool_max_size` | 字符串/负数 | 改 int > 0 |
| `Connection refused` on startup | `.env` 没加载 | 检查路径 / `env_file=` |
| 生产有 dev `JWT_SECRET` | `.env.production` 没覆盖 | systemd `EnvironmentFile=` |
| `CSP` 拒了内联 script | policy 太严 | 加 `script-src 'self' 'unsafe-inline'`（不推荐） |
| `cors_origins` 解析成字符串而不是 list | JSON 格式错 | `["http://..."]` 加双引号 |
| 启动后 5 秒 OOM | `pool_max_size=10000` | 调小到 ≤ PG `max_connections / 5` |

---

## 10. 进一步阅读

- 完整变量清单：[`src/getrich/config/settings.py`](https://github.com/getrich/getrich/blob/main/src/getrich/config/settings.py)
- 环境变量参考（每项详细）：[reference/env-vars](../reference/env-vars.md)
- 部署：[systemd 部署](../operations/systemd.md)
- 工具：
    - [pydantic-settings 文档](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
    - [12 因子应用](https://12factor.net/config)
