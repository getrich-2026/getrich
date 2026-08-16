# GetRich 当前状态

**这个文件是状态快照，可以整体覆写。** 不要在这里追加施工流水账 —— 历史沿革查 `git log`，长期决策和踩坑写 `DECISIONS.md`。

最后更新：2026-08-16 · 分支 `dev-refactor`

---

## 进行中

- **AI 指令文件重构（2026-08-14）**：`AGENTS.md` 改为唯一真源，`CLAUDE.md` 瘦成 `@AGENTS.md` 导入入口；`.agent/brain/` 拆成 `NOTES.md`（状态快照）+ `DECISIONS.md`（只增不改）+ `archive/`；`.agent/` 从 `.gitignore` 移出准备提交。原 249 行 NOTES.md 归档在 `archive/2026-08-11_12-monorepo-refactor-log.md`。
- **数据库部署模板归入 `deploy/`（2026-08-16）**：`deploy/docker-compose.yml`、`deploy/config/` 和 `deploy/.env.example` 只保存可复现定义；GetRich 仓库内不实例化 Docker。同步时将 `deploy/` 中的文件放到外部部署目录根，不保留外层 `deploy/`。真实 `.env`、数据、日志和运维脚本只存在于仓库外的部署目录，见 `DECISIONS.md` D-016、D-017。
- **应用与部署环境变量分离（2026-08-16）**：根 `.env.example` 只保留应用连接和运行配置；部署侧的容器名称、端口、数据目录和资源上限移到 `deploy/.env.example`。本机根 `.env` 已删除非敏感的 Docker 专用键，真实连接密码未改动。
- **基础设施配置状态**：Redis 使用 `noeviction` + `REDIS_MAXMEMORY`（D-013）、关闭 RDB 双写；ClickHouse 固定时区并为 5 张 `system.*_log` 表设置 7 天 TTL；PostgreSQL 用 `include_if_exists` 继承 timescaledb-tune 调优（D-014）。
- **同步状态**：

  | 环境 | compose | config/ | 服务已重启 | 状态 |
  |---|---|---|---|---|
  | 仓库 `deploy/` | 新 | 新 | — | 部署模板真源，不创建实例 |
  | 本机部署目录 | 新 ✅ | 新 ✅ | ✅ | 三服务 healthy；本次目录整理未同步或重启 |
  | `greencloud:/opt/getrich-docker` | **旧** ❌ | 新 ✅ | ❌ | **PG 崩溃重启中**，见下 |

  - 本机重建时踩到：`docker compose up -d` 不会重建 ClickHouse（service 定义没变，检测不到 bind-mount 文件内容变化），只改 `logger.xml` 时必须显式 `docker compose restart clickhouse`。
- **`dev-refactor` 分支有大量未提交改动**：删除了 `docs/`、`backtest/docs/`、`Dockerfile`、`MANIFEST.in`、`GEMINI.md`、`components.json`、`.github/workflows/docs.yml` 等。提交前需整体过一遍。

## greencloud 服务器待办（用户手动处理）

远端 `/opt/getrich-docker/`，Linux（getrich.jp）。`config/` 已同步（旧配置备份在 `config.bak-20260814-233723`），其余未做：

1. **修 PG 崩溃循环**（根因见 D-015，与配置内容无关）：
   `sudo chown 70:70 /opt/getrich-docker/.docker/postgres/logs`
2. **同步部署模板** —— 将仓库 `deploy/docker-compose.yml` 和 `deploy/config/` 的内容同步到远端部署目录根。远端仍是 2026-08-12 旧版，导致 PostgreSQL 配置完全不生效，Redis 配置也只生效一半。
3. **重启使配置生效**：同步 compose 后 `docker compose up -d`；若只改 config 则 `docker compose restart clickhouse redis`。
4. 可选：远端 `.env` 补 `REDIS_MAXMEMORY=2gb`（compose 有默认值兜底，不加也能跑）。

## 已知失败基线

下面这些是**接手前就存在**的失败，用来区分「我改坏的」和「本来就坏的」。修复前不要把它们当成自己引入的回归。

| 位置 | 现象 | 数量 |
|---|---|---|
| `apps/web` | ESLint 既有错误 | 45 |
| `apps/web` | `tsconfig.app.json` 的 `ignoreDeprecations` 值不兼容，`npm run build` 失败 | 1 |
| `apps/backtest-web` | 缺 `src/lib/utils`、`src/lib/sanitize`，`npm run build` 报 TS2307 | 8 |
| `apps/backtest-web` | 缺 ESLint 插件文件，lint 失败 | — |
| `packages/` | Ruff 既有问题（CI 暂为 `continue-on-error`） | 362 |
| `gr-backtest` | `TestBlackLitterman.test_mixed_scores_long_short` 失败，单独复跑仍失败 | 1 |
| pytest | 未 await coroutine warning | 若干 |

## P0

- [ ] **推翻 2026-06-06 的包切分**，按职责边界重新划分 —— 见 `DECISIONS.md` D-002。这是当前最大的结构债。
- [ ] 修复 `find_project_root()` 命中 `packages/gr-data/pyproject.toml` 的问题（D-003）。修好前启动服务必须带 `--env-file .env`。
- [ ] 解除 `gr-signal` 对 `getrich.apps.web.metrics`、`gr-data` 对 `getrich.libs.logging` 的反向 import（D-004），再收紧包依赖边界。
- [ ] 修 `apps/backtest-web` 缺失的 `src/lib/utils` 与 `src/lib/sanitize`。
- [ ] 清理 `apps/web` 的 45 个 ESLint 错误和 `tsconfig.app.json` 构建失败。
- [ ] Ruff 362 个问题清理完后，移除 CI 里的 `continue-on-error`。
- [ ] 更新 `.github/workflows/`、`.pre-commit-config.yaml`、`reinstall.sh` / `reinstall.bat` 里残留的旧路径。
- [ ] README 仍有 2025 年的旧架构和数据表设计，需重写；`.env.example` 按当前 workspace 重新核对。

## P1

- [ ] 把 `getrich_backtest.data` 的 PIT 契约抽入 `gr-data`，因子评估与归因抽入 `gr-factor`。
- [ ] 为 `gr-factor` 建立首批独立测试。
- [ ] 修 Black-Litterman 权重方向失败，处理未 await coroutine warnings。
- [ ] 评估是否恢复 `getrich.__version__` 兼容入口（当前 namespace package 不提供根级快捷导出）。
- [ ] `polars==1.41.0` 与 `polars-runtime-32==1.41.0` 已被 yanked，需评估升级。
- [ ] 评估 `archive/root-web-scaffold/` 保留期限 —— 删除前必须明确确认（D-010）。

## 待验证

- `deploy/` 只做过 Compose 静态解析；容器运行状态由仓库外的部署目录独立验证。
- 本机未装 psql / redis-cli / clickhouse-client，`db.sh` 只做过假客户端冒烟测试，真实连接未验证。
