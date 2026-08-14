# GetRich 开发进度

## 2026-08-11：monorepo 结构迁移

### 已完成

- 根项目改为 uv workspace，成员为 `packages/gr-{data,factor,signal,backtest,api,agent}`。
- 每个 Python 模块已有独立 `pyproject.toml`、`src/` 和 `tests/`；暂时保留原 import 名，避免本轮批量修改业务代码。
- `getrich` 与 `getrich.apps` 改为 PEP 420 namespace package；原两个顶层 `__init__.py` 已移除。
- 主产品 React 前端从原 `web/` 迁到 `apps/web/`。
- 回测 React 前端从原 `frontend/` 迁到 `apps/backtest-web/`。
- 根级不完整 Vite 脚手架保存在 `archive/root-web-scaffold/`，未删除。
- 回测设计契约及策略／信号前期方案迁入独立仓库 `../getrich-design`。
- 新增 `.github/CODEOWNERS`。

### 验证

- `uv lock` 与 `uv sync --frozen --all-packages` 成功，六个成员均能构建安装。
- namespace 模块位置检查通过。
- `uv run pytest packages/gr-data/tests/getrich/migrations -q`：68 passed，1 个既有未 await coroutine warning。
- `python -m getrich.migrations.cli status`：发现 25 个 PostgreSQL 和 2 个 ClickHouse migration。
- `uv run mkdocs build --strict --clean`：通过。
- 迁移源码、测试、前端文件的内容哈希无缺失；外迁的 38 个设计文件哈希逐字一致。

### P0：下一阶段逐项修复

- 更新 `.github/workflows/`、`.pre-commit-config.yaml`、Docker、安装脚本及根 `scripts/` 中的旧路径。
- 修复配置根目录推导：当前 artifact 默认路径变成 `packages/gr-data/tmp/artifacts`。
- 解除 `gr-signal` 对 `getrich.apps.web.metrics` 的反向 import，再收紧 package 依赖边界。
- 评估是否恢复 `getrich.__version__` 兼容入口；当前 namespace package 不再提供根级快捷导出。
- 修复 `apps/backtest-web` 缺失的 `src/lib/utils` 与 `src/lib/sanitize`；当前 `npm run build` 有 8 个 TS2307。
- 更新主仓用户文档中的旧 `src/getrich*`、`frontend/`、`tests/getrich*` 路径。

### P1

- 将 `getrich_backtest.data` 的 PIT 契约逐步抽入 `gr-data`，将因子评估与归因逐步抽入 `gr-factor`。
- 为 `gr-factor` 建立首批独立测试。
- 评估 `archive/root-web-scaffold/` 的保留期限，删除前必须得到明确确认。

### 已知副作用

- 首次导入配置模块时，原有逻辑在 `~/.config/getrich/.env` 创建了默认配置文件；本轮未删除或改写。

## 2026-08-11：GitHub 协作与 monorepo CI

### 已完成

- 保留 `.github/`，将 `CODEOWNERS` 按六个 Python package、两个前端、文档和 workspace 根文件分路径配置；当前 owner 仍为 `@neolin0629`，后续可逐行替换为可见且有 write 权限的 `@getrich-2026/<team-slug>`。
- Dependabot 改为原生 uv workspace，并为 `apps/web`、`apps/backtest-web` 和 GitHub Actions 分别配置更新计划；minor／patch 分组，major 人工评估，冷却期 7 天，不再依赖未创建的自定义 label。
- CI 拆分为四个路径过滤工作流：`ci.yml`（Python）、`web.yml`、`backtest-web.yml`、`docs.yml`。不同应用的历史失败不会再阻塞无关目录的 PR。
- Python CI 使用 `uv sync --frozen --all-packages`，覆盖 Python 3.10–3.12，并启动 PostgreSQL、ClickHouse 与 Redis；根级前端构建断言由应用工作流负责，不进入 Python pytest。
- 文档工作流使用 GitHub Pages 官方 artifact／deploy 流程，在 `dev` 分支发布到 `https://getrich-2026.github.io/getrich/`。
- 更新 CI 文档、Dependabot／coverage 配置测试、迁移扫描路径和静默失败扫描范围，使其适配 monorepo。

### 验证

- `.github/workflows/*.yml` 与 `.github/dependabot.yml` 均可由 PyYAML 解析。
- 仓库级结构测试：191 passed，1 skipped。
- 完整 Python 测试收集：2,361 tests collected；本轮未运行全部业务测试。
- 直接相关配置测试：108 passed。
- PostgreSQL 25 个迁移、ClickHouse 2 个迁移的拓扑检查通过。
- `uv run --frozen mkdocs build --strict --clean` 通过；仍有多条既有文档锚点提示。
- `git diff --check` 通过。

### P0：合并前需关注

- GitHub 仓库需要在 `Settings → Pages` 将 Source 设为 `GitHub Actions`，再手动运行一次 `Docs` 或推送文档改动到 `dev`。
- `apps/web` 当前有 45 个既有 ESLint 错误，构建因 `tsconfig.app.json` 的 `ignoreDeprecations` 值不兼容而失败。
- `apps/backtest-web` 当前缺少 ESLint 插件文件，并缺少 `src/lib/utils`、`src/lib/sanitize`，导致 lint 与构建失败。
- Ruff 当前有 362 个既有问题；静默失败扫描新增发现 4 个 `gr-backtest` P0 review。重构期间这两个步骤暂时为非阻塞，清理后移除 `continue-on-error`。
- 当前路径过滤工作流不要直接设为全仓 required checks，否则未触发的 workflow 可能保持 Pending；后续若需要强制状态检查，应增加每个 PR 都运行的汇总 gate workflow。

## 2026-08-12：旧测试第一轮清理

### 已移除

- 删除 `tests/docs/test_phase3_polish.py` 与 `tests/scripts/test_verify_docs_ci.py`；其目标 `docs/` 已不存在。
- 删除 `tests/frontend/test_vite_echarts_split.py`；回测前端当前暂缓，后续重设计时重新建立前端测试。
- 删除 `tests/scripts/test_audit_responsive.py`；它只验证旧前端响应式审计工具。
- Python CI 恢复直接运行完整 pytest testpaths，不再对已删除的 `tests/frontend` 做例外过滤。

### 保留原则

- 六个 package 内的既有业务测试目前仍是从旧单体测试原样迁移的行为基线。新测试应按 package 逐步替换，替换完成后再删除对应旧测试，避免结构重构期间完全失去回归保护。

## 2026-08-12：根目录配置与部署遗留清理

### 已完成

- 保留 `.python-version`、`LICENSE`、`AGENTS.md`、`CLAUDE.md` 和 `.github/`；将开发命令及路径更新为 uv workspace 和 `apps/web`。
- 删除无法适配当前 monorepo 的根 `Dockerfile`、六个硬编码旧服务器路径的 systemd unit、冗余的 `GEMINI.md`、失效的 `MANIFEST.in`。
- 根 `docker-compose.yml` 收敛为 PostgreSQL、ClickHouse、Redis 三个本地基础设施服务，不再尝试构建或运行应用。
- 删除已失去文档源的 `mkdocs.yml`、Docs/Pages workflow、文档 CI 校验脚本和旧前端响应式审计脚本；同步移除根开发依赖中的 MkDocs 工具链并更新 `uv.lock`。
- `.pre-commit-config.yaml` 改为轻量仓库门禁：基础文件检查、迁移拓扑、Conventional Commit 和 Gitleaks；Ruff、前端 lint 与静默失败扫描待基线清理后再启用。
- 清理 README、备份脚本和 Python 注释中的旧 Docker、systemd 与已删除 docs 引用。

### 验证

- `docker compose config --quiet` 通过。
- `.pre-commit-config.yaml`、Dependabot 及三个现存 GitHub Actions workflow 均可由 PyYAML 解析。
- `uv lock --check` 通过；25 个 PostgreSQL 和 2 个 ClickHouse migration 拓扑检查通过。
- 完整 Python 测试：2,162 passed，6 skipped，1 failed。失败为既有 `TestBlackLitterman.test_mixed_scores_long_short`，单独复跑仍失败；本轮按结构优先原则未修改算法代码。
- `git diff --check` 通过。

### 后续关注

- 上一节记录的 GitHub Pages 启用事项已失效：文档源已删除，当前不发布 Pages；未来重建文档时再恢复独立 workflow。
- README 仍包含较多 2025 年的旧架构与数据表设计，后续应单独重写；`.env.example` 也需要按本地 Compose 与 workspace 重新核对。
- 当前仓库不再提供应用 Docker 镜像或 systemd 部署单元；待部署方案确定后，在独立 `deploy/` 目录重新设计。
- 后续代码修复阶段处理 Black-Litterman 权重方向失败及 pytest 报告的未 await coroutine warnings。

## 2026-08-12：scripts 第二轮清理

### 已完成

- 删除 `find_silent_fails.py`，并从 Python CI 移除静默失败扫描；现有静默错误留到代码修复阶段处理。
- 删除旧兼容入口 `lint_clickhouse_migrations.py`、失效的本地覆盖率包装脚本 `measure_coverage.sh` 和整套未接入当前部署的 `scripts/backup/`。
- 保留 `lint_migrations.py`：migration 已是 `gr-data` 的正式能力，该检查可防止 ClickHouse 行级改写和 PostgreSQL 事务内并发建索引等高风险操作。
- 将 `lint_migrations.py` 从 329 行精简为约 100 行，只保留危险操作规则、SQL 注释／字符串清理及 CLI；CI 与 pre-commit 继续调用它。
- `scripts/` 现在只包含 `lint_migrations.py`。

### 验证

- 精简检查器通过 Ruff lint 和 format 检查。
- 25 个 PostgreSQL 与 2 个 ClickHouse migration 全部通过。
- 使用内存样例验证 4 类危险 SQL 能被拒绝，注释、字符串和安全 DDL 不会误报。
- CI 与 pre-commit YAML 均可正常解析；仓库中没有已删除脚本的有效引用。

## 2026-08-12：按 2026-06-06 切分后端代码

### 切分规则

- 以文件在 Git 中首次引入的时间为准，严格保留 2026-06-06 00:00（Asia/Shanghai）之前的代码；当天及之后首次引入的代码归入 `gr-backtest`。
- 不回退截止日前文件后续收到的修复；本轮以移动目录、测试和依赖声明为主，不重写业务逻辑。

### 已完成

- `gr-data` 保留 11 个截止日前源文件；日志模块、migration runner、25 个 PostgreSQL migration、2 个 ClickHouse migration 及相应测试迁入 `gr-backtest`。
- `gr-factor` 的 7 个期权分析源文件均早于截止日，保持不动。
- `gr-api` 保留 20 个 2026-04-27 引入的 API 源文件；21 个 2026-06-06 及之后引入的认证、回测、middleware 和 service 文件及全部 API 测试迁入 `gr-backtest`。
- `gr-signal` 的策略／信号实现及测试全部归入 `gr-backtest`，当前为无业务源码的 workspace 占位包。
- `gr-agent` 只保留 2026-01-05 引入的 `gateway` 占位；worker 实现及测试全部归入 `gr-backtest`。
- `gr-backtest` 继续使用原有 `getrich_backtest`，并新增承接目录 `getrich.apps.strategy`、`getrich.apps.web`、`getrich.apps.worker`、`getrich.libs` 与 `getrich.migrations`，暂时保留旧 import 路径。
- 删除会阻断拆分模块发现的空 `__init__.py`，用 PEP 420 namespace 合并 `gr-api` 与 `gr-backtest` 的 Web 子模块。
- migration CLI 入口、migration lint、pre-commit 路径、README、`CLAUDE.md` 和 `uv.lock` 已改到 `gr-backtest`。

### 验证

- 对 `gr-data`、`gr-factor`、`gr-signal`、`gr-api`、`gr-agent` 剩余的 39 个 Python／SQL 文件复核 Git 首次引入日期，截止日当天或之后的文件为 0。
- `uv sync --frozen --all-packages` 通过；新旧 Web 子模块、worker、日志和 migration CLI 的跨 package 导入路径均通过。
- migration lint 通过：25 个 PostgreSQL migration、2 个 ClickHouse migration。
- `python -m getrich.migrations.cli status` 能从 `packages/gr-backtest/migrations` 发现全部 27 个 migration。
- 迁入 `gr-backtest` 的 1,261 项测试首轮为 1,258 passed、1 skipped、2 failed；失败来自临时替换旧 Logger 后的接口差异。该实现改动已撤回，原失败文件复跑为 44 passed。
- `git diff --check` 通过。

### 后续关注

- `gr-data` 的旧 ClickHouse 类仍导入现在由 `gr-backtest` 承接的 `getrich.libs.logging`。workspace 整体安装可正常运行，但单独安装 `gr-data` 时该隐式反向依赖尚未解决；后续应在正式拆包阶段设计共享日志边界。
- `gr-signal` 当前没有业务源码，`gr-agent` 仅剩 gateway 空命名空间；确认不再需要独立发布后，可考虑移除这两个 workspace member。
- uv 当前提示 `polars==1.41.0` 与 `polars-runtime-32==1.41.0` 已被 yanked；本轮未升级依赖。

## 2026-08-12：空 workspace 占位项目瘦身

### 已完成

- `gr-agent` 与 `gr-signal` 不再提供 `getrich.*` 兼容 import，只保留各自的 `pyproject.toml`。
- 两个占位项目使用 `py-modules = []` 显式声明为仅含元数据的可构建项目。
- 保留 `gr-agent`、`gr-signal` 作为发行项目名；连字符不影响 uv／PyPI 依赖解析。未来增加 Python 源码时，import 名应使用下划线形式 `gr_agent`、`gr_signal`。
- 删除仓库内所有空目录，包括已经失效的根级 `tests/`，并从 pytest 的 `testpaths` 删除不存在的测试目录。

### 验证

- `uv lock --check` 与 `uv sync --frozen --all-packages` 通过，两个仅含元数据的占位项目均可构建安装。
- `getrich.apps.gateway`、`gr_agent` 与 `gr_signal` 均不可导入，确认占位项目没有暴露兼容模块或新的 import 包。
- pytest 成功收集 2,169 项测试；排除 Git、虚拟环境、依赖和缓存目录后，仓库内剩余空目录为 0。
- `git diff --check` 通过。

## 2026-08-12：本地 Compose 配置统一

### 已完成

- 固定本地及 CI 基础设施镜像：TimescaleDB `2.28.3-pg17-oss`、ClickHouse `26.3`、Redis `8.2.8`。
- `docker-compose.yml` 的数据库用户、密码、端口、容器名、网络名、时区、宿主机绑定地址和持久化目录均改为从根 `.env` 读取。
- 默认只向 `127.0.0.1` 发布数据库端口；本地数据默认写入被 Git 忽略的 `.docker/`，服务器可在 `.env` 改为 `/opt/getrich/...`。
- PostgreSQL 与 ClickHouse 健康检查使用容器自身环境变量；Redis 启用密码认证和 AOF 持久化。
- 重写 `.env.example`，统一 Compose 与 Python 应用的 `PG_*`、`CLICKHOUSE_*` 和 Redis／Celery 配置，不包含真实凭据。
- README 增加 `.env` 初始化、密码生成和 Compose 配置验证说明。

### 验证

- `docker compose --env-file .env.example config --quiet` 通过，解析出的镜像版本与目标完全一致。
- `docker-compose.yml`、Dependabot 和 3 个 GitHub Actions workflow 均可由 PyYAML 解析。
- python-dotenv 成功解析 14 个必要配置，Redis／Celery URL 能展开 `REDIS_PASSWORD` 与 `REDIS_PORT`。
- 仓库中未发现被替换的旧基础设施镜像引用；`git diff --check` 通过。
- Docker Desktop daemon 当前未运行，因此没有下载、启动或执行容器级健康检查。

## 2026-08-12：生成本地环境配置

### 已完成

- 补齐根 `.env.example` 中的 PostgreSQL 连接池、Flower、回测产物目录、JWT 和支付 webhook 占位配置，并统一本地数据库主机为 `127.0.0.1`。
- 生成被 Git 忽略的根 `.env`，分别为 PostgreSQL、ClickHouse、Redis 和 JWT 写入独立随机密钥；文件权限设为 `600`。
- `.env` 与 `.env.example` 的 48 个有效配置项保持一致，未向仓库写入真实凭据。

### 验证

- `docker compose config --quiet` 通过。
- python-dotenv 成功解析全部配置，Redis／Celery URL 变量展开、随机密钥长度和占位符清理检查通过。
- `.env` 未被 Git 跟踪，`.env.example` 通过 `git diff --check`。

### 后续关注

- monorepo 迁移后，`find_project_root()` 会先命中 `packages/gr-data/pyproject.toml`，因此应用自动加载配置时尚未选择 workspace 根 `.env`；代码修复前，启动 Python 服务需显式使用 `uv run --env-file .env ...`。

## 2026-08-12：Docker 部署目录迁移

### 已完成

- 将 docker 编排相关文件从仓库整体迁出到独立部署目录 `/Volumes/myssd/getrich-docker/`：`docker-compose.yml`、`config/`（`clickhouse/logger.xml`、`redis/redis.conf`、`config/README.md`）、`scripts/cleanup-logs.sh`、`.env.example`。
- 仓库内删除 `docker-compose.yml`（`git rm`，git status 显示 `D`）、`config/`、`scripts/cleanup-logs.sh`；根 `.env` 保留（FastAPI／Celery 仍读取），未删。
- 新目录生成独立的精简 `.env`（仅 compose 所需变量，三个数据库密码继承自仓库 `.env`），并新建 `.docker/{postgres,clickhouse,redis}/{data,logs}` 目录树。
- 新目录 `README.md` 说明：目录结构、启动／停止／重启命令、日志轮转与清理（含 cron 定时）、SSH 隧道外部访问、生产注意事项（Linux 属主、防火墙、强密码、ClickHouse 9009 勿开放）。
- 根 `README.md` 同步更新：3.2 节、目录树、Quick Start 的 docker 引用改为指向 `/Volumes/myssd/getrich-docker/`（`docker compose -f ...` 或 `cd` 后执行）。

### 验证

- 新目录 `docker compose config --quiet` 通过；新 `.env` 三个数据库密码键齐全（非 `change-me-*` 占位符）。
- 删除前对仓库文件与新目录副本逐一 `cmp`，内容全部一致后才删除。
- 仓库 `git status`：`docker-compose.yml` 为 `D`（staged）；`config/`、`scripts/cleanup-logs.sh` 已移除。
- Docker daemon 未运行，容器级验证仍待进行。

### 后续关注

- 仓库根 `.env` 中 `POSTGRES_DATA_DIR`、`CLICKHOUSE_LOG_DIR` 等变量对 compose 已无意义（compose 已迁至新目录），保留无害，应用侧不使用。
- Docker Desktop 启动后需在 `/Volumes/myssd/getrich-docker/` 执行 `docker-compose up -d` 做容器级运行验证（日志轮转、健康检查、清理脚本）。

## 2026-08-12：部署目录新增 db.sh 与脚本路径修复

### 已完成

- 新增 `/Volumes/myssd/getrich-docker/scripts/db.sh`：从部署目录 `.env` 自动读取密码，一条命令连接三个数据库（`./scripts/db.sh pg|ch|redis`），psql／redis-cli 用 `PGPASSWORD`／`REDISCLI_AUTH` 环境变量传密码，ClickHouse 因无可靠环境变量支持用 `--password`；支持透传额外客户端参数。
- 修复 `db.sh` 与 `cleanup-logs.sh` 的 `PROJECT_ROOT` 推导 bug：脚本从仓库迁到 `scripts/` 子目录后，原推导把根目录算成了 `scripts/` 自身，导致 db.sh 找不到 `.env`、cleanup-logs.sh 实际在清理 `scripts/.docker`（静默空跑）。已改为取脚本目录的上一级（`dirname .../..`），两个脚本均已用假客户端冒烟验证。
- 部署目录 `README.md` 新增「快速连接数据库」小节（db.sh 用法 + 客户端安装 + `.pgpass` 永久免密），并把 SSH 隧道示例中带明文密码的 psql URL 改为 `PGPASSWORD` 环境变量版。

### 验证

- `bash -n` 语法检查通过；假客户端冒烟测试验证三个子命令的连接参数、环境变量长度／前缀（未回显完整密码）、透传参数及任意调用目录均正确。
- `cleanup-logs.sh` 推导的根目录已指向部署根，能定位 `.docker/{postgres,clickhouse,redis}/logs`。
- 本机未安装 psql／redis-cli／clickhouse-client，真实连接测试待客户端安装后补做。
