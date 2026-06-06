# 安装

本节介绍如何在本地开发环境安装 GetRich 平台的所有依赖。

---

## 1. Python 环境

### 1.1 安装 uv

[uv](https://github.com/astral-sh/uv) 是 Astral 出品的 Python 包管理器，比 pip 快 10-100 倍。

=== "macOS / Linux"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Windows (PowerShell)"

    ```powershell
    powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

=== "Homebrew"

    ```bash
    brew install uv
    ```

### 1.2 同步项目依赖

```bash
git clone <repository-url> getrich
cd getrich
uv python install 3.12
uv sync --extra dev
```

> **关键命令**：
> - `uv python install 3.12` —— 安装 Python 3.12（项目已 CI 验证）
> - `uv sync --extra dev` —— 安装所有生产 + 开发依赖（`pyproject.toml` 中定义的）

### 1.3 验证 Python 安装

```bash
uv run python -c "import getrich_backtest; print(getrich_backtest.__version__)"
```

预期输出：`0.1.2`（或当前版本号）。

---

## 2. PostgreSQL

### 2.1 安装

=== "macOS (Homebrew)"

    ```bash
    brew install postgresql@16
    brew services start postgresql@16
    ```

=== "Ubuntu / Debian"

    ```bash
    sudo apt install postgresql-16
    sudo systemctl start postgresql
    ```

=== "Windows"

    下载安装包：<https://www.postgresql.org/download/windows/>

### 2.2 创建数据库与 schema

```bash
# 用 postgres 用户连接
sudo -u postgres psql

# 创建数据库
CREATE DATABASE getrich OWNER your_user;

# 启用需要的扩展
\c getrich
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

# 创建 frontend schema（所有业务表都放在这个 schema 下）
CREATE SCHEMA IF NOT EXISTS frontend;
GRANT ALL ON SCHEMA frontend TO your_user;
```

> **为什么用 `frontend` schema？**
> 隔离业务表与可能的公共表；所有 migration 都自动以 `frontend.` 为前缀。详见 [CLAUDE.md §2 数据库职责划分](https://github.com/getrich/getrich/blob/main/CLAUDE.md)。

### 2.3 应用 migrations

使用项目自带的迁移运行器（**禁止**手动跑 `psql`）：

```bash
uv run python -m getrich.migrations.cli postgres
```

预期输出：

```
[postgres] applied 25 migration(s): 001_sub_account_routing.sql, 002_strategy_trades.sql, ...
[postgres] no migrations to apply (already up to date)
```

> 详细用法：见 [运维指南 / 数据库迁移](../operations/migration-runner.md)。

---

## 3. ClickHouse

### 3.1 安装

=== "macOS (Homebrew)"

    ```bash
    brew install clickhouse
    brew services start clickhouse
    ```

=== "Ubuntu / Debian"

    ```bash
    sudo apt-get install -y apt-transport-https ca-certificates curl gnupg
    curl -fsSL 'https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key' | sudo gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] https://packages.clickhouse.com/deb stable main" | sudo tee /etc/apt/sources.list.d/clickhouse.list
    sudo apt update
    sudo apt install -y clickhouse-server clickhouse-client
    sudo systemctl start clickhouse-server
    ```

### 3.2 应用 CH 迁移

```bash
uv run python -m getrich.migrations.cli clickhouse
```

预期输出：

```
[clickhouse] applied 2 migration(s): 001_ohlcv_bars.sql, 002_factors_long.sql
```

> **CH 迁移与 PG 不同**：CH 没有跨语句事务，所以所有 migration 文件**必须幂等**（用 `IF NOT EXISTS`），详见 [CLAUDE.md §6 迁移约定](https://github.com/getrich/getrich/blob/main/CLAUDE.md)。

### 3.3 验证 CH 状态

```bash
uv run python -m getrich.migrations.cli status
```

---

## 4. Redis

=== "macOS (Homebrew)"

    ```bash
    brew install redis
    brew services start redis
    ```

=== "Ubuntu / Debian"

    ```bash
    sudo apt install redis-server
    sudo systemctl start redis
    ```

验证：

```bash
redis-cli ping
# 预期：PONG
```

> **Redis 的两个用途**：
> 1. Celery broker + result backend（`GETRICH_BROKER_URL=redis://localhost:6379/0`）
> 2. 缓存层（如 `/strategies/categories` 1h TTL）

---

## 5. Node.js（仅前端开发需要）

```bash
# 推荐 nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
nvm install 22
nvm use 22

# 验证
node --version   # v22.x
npm --version
```

安装前端依赖：

```bash
cd frontend
npm install
```

---

## 6. 验证完整安装

运行一次性 smoke test：

```bash
# 后端
uv run python -c "
import getrich_backtest
import getrich.config.settings as s
import getrich.apps.web.main as w
import getrich.apps.worker.celery_app as c
print('Engine:', getrich_backtest.__version__)
print('Settings OK')
print('Web app:', w.app)
print('Celery:', c.celery)
print('ALL GOOD')
"

# 前端
cd frontend
npm run build
# 预期：dist/ 目录生成，无 error
```

---

## 7. 常见安装问题

### 7.1 `uv sync` 报 `Resolution too deep`

降低 Python 版本要求，或删除 `uv.lock` 后重试。

### 7.2 PostgreSQL `permission denied for schema frontend`

```sql
GRANT ALL ON SCHEMA frontend TO your_user;
GRANT ALL ON ALL TABLES IN SCHEMA frontend TO your_user;
```

### 7.3 ClickHouse `Connection refused`

确认 CH 服务已启动（`systemctl status clickhouse-server`），端口 8123 可达。

### 7.4 前端 `Cannot find module 'vite'`

```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

---

下一步：[第一个回测](first-backtest.md)
