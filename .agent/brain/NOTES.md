# GetRich 当前状态

**这个文件是状态快照，可以整体覆写。** 不要在这里追加施工流水账 —— 历史沿革查 `git log`，长期决策和踩坑写 `DECISIONS.md`。

最后更新：2026-08-16 · 分支 `dev-refactor`

---

## 刚完成：monorepo 结构化重构

推翻了 2026-06-06 按「文件进入 git 的时间」切包的方案（D-002），按职责重新划分。

- **六个包各有独立顶层 import 名**，`getrich.*` 命名空间包已废除（D-018）。
  规则：发行名 = 目录名 = `gr-x`，import 名 = `gr_x`。
- **依赖方向单向**：`gr-data ← gr-db`，`gr-data ← gr-backtest ← gr-signal ← gr-api`。
  六个包都能单独 `uv run --isolated --with ./packages/<pkg>` 安装并 import。
  `test_package_boundaries.py` 用 AST 静态扫描守住这条边界。
- **`getrich-database` 已 subtree 合并**进 `packages/gr-data`（51 个提交历史保留，D-022）。
  源仓库应转为只读，不要再往那边提交。
- **`gr-db` 收口全部 DDL**：33 个 PG 文件 + 1 个 CH 文件，checksum 记账（D-021）。
- **schema 重划**：`frontend` → `app`（22 张业务表）+ `backtest`（10 张回测产物表）（D-020）。
- **行情主存改为 PostgreSQL/TimescaleDB**，ClickHouse 收窄为只放因子时序（D-019）。
- Ruff 从既有的 362 个问题清到 **0**。

## 当前基线

| 项 | 状态 |
|---|---|
| `uv run pytest` | **2220 passed, 1 failed, 17 skipped** |
| `uv run ruff check packages/ scripts/` | 通过 |
| `uv run ruff format --check` | 通过 |
| 六个包单独安装 import | 全部通过 |

唯一失败是**接手前就存在**的 `TestBlackLitterman::test_mixed_scores_long_short`
（权重方向问题），不是本次重构引入的。

## 已验证（真实环境，非 mock）

在 PG 17 + TimescaleDB 容器上实测过：

- `gr-db migrate --target pg` 建出 7 个 schema、21 个 hypertable，重跑幂等。
- 模拟旧 `frontend` 布局的库跑 `ddl/upgrade/001_frontend_to_app_backtest.sql`，数据无损。
- `import gr_backtest` → `PgBarLoader` 读 `market.stock_bar_1d` → 回测 → HTML 报告
  → 落库 `backtest` schema，全链路通。
- `uvicorn gr_api.main:app` 起得来，4 个安全头齐全；`/v1/strategies`、
  `/v1/strategies/{code}`、`equity-curve`、`signals`、`categories` 全部 200 并返回真实数据。
- `apps/web` 的 `npm run dev` 正常启动，入口与三个页面模块编译零错误。

## 未验证

- **ClickHouse 侧没有实测**：本机没起 CH 容器，`ddl/clickhouse/001_factors_long.sql`
  只过了解析级测试，没在真实 CH 上跑过 `gr-db migrate --target ch`。
- **银河与 Tushare 的真实接口没跑通**：根 `.env` 里没有 `TUSHARE_TOKEN`／`YINHE_*`，
  银河 SDK（`AmazingData`）也未安装。只验证了缺凭证时会**立刻**报出该设哪个变量
  （不重试、不静默降级）。配好凭证后的验证命令见 `packages/gr-data/README.md`。
- `deploy/` 只做过 Compose 静态解析；本机与 greencloud 的部署目录未同步。

## P0

- [ ] **轮换 RiceQuant license key**：`packages/gr-data/reference/design/ricequant/config.md`
      含明文 license key，随 subtree 合并进了 git 历史。文件已从索引移除并加进
      `.gitignore`，但**历史里仍在**，必须视为已泄漏并轮换。该文件目前只留在本机磁盘上，
      请自行转移到密码管理器后删除。
- [ ] 配好 `TUSHARE_TOKEN` 后跑一遍 `gr-data raw/ingest tushare`，确认真实链路。
- [ ] 起一个 ClickHouse 容器，验证 `gr-db migrate --target ch`。

## P1

- [ ] 修 Black-Litterman 权重方向失败（既有基线）。
- [ ] `gr-factor` 至今没有测试；`NPY002`（legacy `np.random`）因此暂时豁免，
      补上测试后再改成 `np.random.Generator`（会改变随机数流）。
- [ ] `market` 表缺 `oi`（持仓量）列，期货策略用不了；`PgBarLoader` 现在请求 `oi` 会显式报错。
- [ ] gr-data schema 里没有公司行为（分红送转）表，`load_corp_actions()` 显式报错。
- [ ] `apps/backtest-web` 暂停维护：缺 `src/lib/utils`、`src/lib/sanitize`，`npm run build` 报 8 个 TS2307。
- [ ] `apps/web` 45 个既有 ESLint 错误、`tsconfig.app.json` 的 `ignoreDeprecations` 导致 `npm run build` 失败（`npm run dev` 不受影响）。
- [ ] `polars==1.41.0` 与 `polars-runtime-32==1.41.0` 已被 yanked，需评估升级。
- [ ] 评估 `archive/root-web-scaffold/` 与 `packages/gr-db/archive/legacy-sql/` 的保留期限
      —— 删除前必须明确确认（D-010）。
- [ ] `gr-agent` 仍是空占位包（只有 `pyproject.toml`，`py-modules = []`）。
      要么明确它的职责并写代码，要么删掉 —— 空包会让 workspace 成员列表产生误导。
- [ ] CI（`.github/workflows/`）仍按旧包名与旧路径写，需要跟着改；Ruff 已清零，
      可以去掉 `continue-on-error`。
