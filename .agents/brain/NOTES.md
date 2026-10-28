# GetRich 当前状态

读者：接续任务的 Codex／Antigravity；维护者也可用它快速定位工作。
最后整理：2026-10-28（ETF／期权样本修复验收）；2026-10-26（Tushare ETF／三类期权合入 dev，米筐回补完成）；2026-10-23（米筐动态名单第一阶段）；2026-10-22（Tushare 导入门禁）；2026-10-21（测试基线与 mock 认证）；2026-10-20（持仓诊断与供应商方向）；其余条目 2026-09-18。仅保留当前方向、阻塞与验证边界；不追加施工流水账。

## 开始任务

1. 先读根 `AGENTS.md`，再读本文。
2. 按任务查 [待决问题](../../docs/plans/backlog.md) 和 [决策主题索引](DECISIONS.md)。
3. 使用说明从 [文档目录](../../docs/README.md) 定位；历史材料不作为现行指令。

## 当前方向与阻塞

- 2026-10-28（ETF／期权样本修复验收）：完成 A1–A5 离线修复：期权 OHL 全零且 close>0 的精确占位在 raw 保留源值、ingest 映射 OHL 为 NULL；基金非标准代码保留 raw；ETF 待上市 P 只留 raw、身份与 symbol_map 跳过并软告警；opt_basic 按显式标的分页，未知标的精确引导、漏码精确回退，完整源响应归档且不覆盖已跳过的到期合约。修正 PG 往返测试的告警数据集预期，新增三个离线用例覆盖 ETF 告警进入运行结果和记账。
  本机隔离外部网络与 PG、排除 live_sdk，`uv run --frozen --no-sync python -B` 调用 pytest 全仓 **3468 passed／147 skipped／28 deselected／4 既有 xfailed**，46 条 warning 保留；三个新增用例 **3 passed**。全仓 Ruff、495 文件格式检查、basedpyright **0 errors／0 warnings／0 notes**、迁移 lint（1 CH／50 PG）、`uv lock --check --offline`、`git diff --check` 均通过。主目录已有 MIME 修复另验 **28 passed**。Docker daemon 未运行，PG 用例跳过，未声称 PG 往返通过；真实样本 B 复验和全量回补仍待单独授权，期权正式 writer 门禁与 ETF 分类任务不变。用户已授权本批提交并合入 dev，主目录其他修改保留未提交；未推送。完整输出在 `/tmp/getrich-sample-merge-6ebv4vqt/feature-pytest.log`，临时日志不作为长期证据。

- 2026-10-26（用户授权合并，ETF／三类期权已合入 dev，未推送）：将 `codex/tushare-etf-options` 的 `537592d` 无冲突合入 dev `9dd0af1`，保留其工具库／选股 Excel 导入两笔更新；先 `--no-commit` 验证组合版本，检查通过后生成合并提交。`uv sync --frozen --all-packages` 已同步环境；未改锁文件、依赖声明、DDL 或类型 baseline。组合版本 `uv run --frozen pytest -q -m 'not live_sdk'` 为 **3557 passed／22 skipped／28 deselected／4 既有 xfailed，0 failed**；44 条 API／异步测试等 warning 保留。全仓 Ruff 通过，格式 **495 files already formatted**，basedpyright **0 errors／0 warnings／0 notes**，迁移 lint **1 CH／50 PG**，`uv lock --check`、暂存差异检查通过；实际输出在 `/tmp/tushare-etf-options-merge-check-*.log` 和 `tushare-etf-options-merge-validation.json`。测试去除供应商 token 和 GETRICH_TEST_PG，仅使用隔离临时库，未启动真实采集、工作库写入或回补。后续顺序：先另行安排 option_instruments 请求预算测量和真实样本验收，再决定正式回填；ETF 分类改用 fund_basic.fund_type 及存量更正在本次合并后从 dev 独立开分支实施，数据更正仍需明确授权。功能默认范围和四个期权 writer 的验证门禁保持不变；未改米筐已完成批次或版本策略。下方各轮“未提交／待审核”是合并前历史记录。

- 2026-10-26（P1-3 首次发布崩溃补丁，待审核）：本条补充上一轮“缺收据拒绝”的首次发布例外。仅修改 raw `fetchers/asset_markets.py`、对应测试及 README／本文；新增 `_recoverable_manifest` 供两条恢复路径共用。缺收据时只接受本数据集、目录 ID 一致、previous_observation_id 为空、当前文件和 data.parquet 双哈希匹配且没有后继的首次观察，记原格式 WARNING 并原子补写收据；已被取代的观察或无匹配文件仍拒绝，字节不变。入库 read_asset_observation 未改，仍严格拒绝缺收据或哈希不符。替换原无收据用例为无匹配观察的文件，并同步原“无效旧文件不遗留空目录”边界语义；另新增首次崩溃恢复、防旧观察回滚两项。
  三项指定用例修复前 **1 failed／2 passed**，修复后 **3 passed**。按补充清单五条命令依次运行，全部退出码 0：三份指定测试 **156 passed**；全仓 **3450 passed／22 skipped／28 live_sdk deselected／4 既有 xfailed，0 failed**；Ruff check 通过，格式 **495 files already formatted**，basedpyright **0 errors／0 warnings／0 notes**。全仓 43 条既有 API／异步测试等 warning 及退出时 run_directory 协程未 await 提示保留，未扩大修复范围。完整临时输出在 `/tmp/tushare-first-publish-check-results.txt`，复现前后为 `tushare-first-publish-before.log`／`tushare-first-publish-after.log`。其他既有 14 个变更文件哈希未变；未 commit／合并／推送、未连接真实 Tushare 或工作库、未启动采样或回补。

- 2026-10-26（ETF／期权审核清单 v2，P0→P3 修复完成，待审核）：按用户提供清单先原样追加 15 项复现测试，生产实现未改时确认 **9 failed／6 passed**；P0 后 2 failed／13 passed，P1 后 1 failed／14 passed，最终 **15 passed**，另补 10 项边界回归。P0：当天未发布按交易所记 WARNING／scope.pending_days，仅替换成功请求，保留当天旧行；过去空响应仍失败。四个期权 writer 含身份／symbol_map 统一连库前门禁及库调用 run 门禁。P1：采集侧仅恢复由本数据集完整观察清单、数据副本和前版关联证明的中断发布；入库仍严格拒绝哈希不符，缺收据／篡改仍拒绝，失败校验不留空观察目录。ETF 分类代码及原断言已完整恢复为 9f41ce3；暂沿用旧 equity／cn_a（已知不准确）。P2：合约最近观察日存于独立 observation_dates.parquet，清单／收据校验哈希；update 重查新增、缺有效观察、缺到期日或上次尚未到期的代码，到期后已观察的跳过，零查询不发布；init 强制重查。P3：README／样例记录按各所正式上市范围收窄 option_exchanges、pending 状态及既有 APP_ENV 约定。
  按清单七条命令顺序验证：三份指定测试 **154 passed**；全仓 **3448 passed／22 skipped／28 live_sdk deselected／4 既有 xfailed，0 failed**；Ruff check 通过，格式 **495 files already formatted**，basedpyright **0 errors／0 warnings／0 notes**，迁移 lint **1 CH／50 PG**，指定分类文件 `git diff 9f41ce3 -- ...` **无输出**，全部退出码 0。全仓仍有 46 条既有 API／异步测试等 warning，以及退出时 run_directory 协程未 await 提示，未压制或扩大修复范围。临时日志 `/tmp/tushare-fix-before.log`、`tushare-fix-after.log`、`tushare-fix-validation.json` 及 `tushare-fix-check-*-final.log` 留存实际输出。本轮未调用真实 Tushare、未连接工作库、未新增或改动 SQL、未 commit／合并／推送。真实月份请求预算测量／历史覆盖验收未执行；后续 ETF 分类以 fund_basic.fund_type 单一来源显式映射，存量“删除后按上市日重写”及注释迁移均留待独立任务和授权。

- 2026-10-26（ETF／三类期权，代码与测试完成，待用户审核）：从 dev `9f41ce3` 新建独立 worktree `/Users/linnan/.codex/worktrees/tushare-etf-options/getrich`，分支 `codex/tushare-etf-options`，未提交／推送／合并。新增显式 raw：ETF L／D／P 名单、fund_daily／fund_adj、八所 opt_daily、按行情实际代码精确补查 opt_basic，以及不可变观察／哈希收据；新增 ETF／option 身份、独立 symbol_map、合约静态契约与日线 writer。保留旧默认任务及 all／reference／bars_1d 范围；ETF 分类按维护者决定恢复并保留基线旧规则（equity／cn_a，已知不准确）；后续独立任务统一改用 fund_basic.fund_type，存量更正另行授权。ETF 份额 ×100／金额 ×1000，期权手数保持／金额 ×10000；Decimal、NULL、精度、交易日、生命周期及 source 映射异常硬拒绝。按 D-026，四个期权 writer（含身份／symbol_map）正式写入默认关闭，在连库前门禁；只有环境 `TUSHARE_OPTION_VALIDATION_ONLY=1` 的隔离验证可写且记录未发布软告警，APP_ENV=prod 拒绝；该开关不替代验证库目标核对。真实历史乘数／行权价、权限、分页行为及历史覆盖仍须另行真实样本验收，未声称历史研究可用。样例与命令见 gr-data README「ETF 与三类期权」及 `config.tushare-etf-options.example.yaml`。
  验证（2026-10-26）：去掉供应商 token／GETRICH_TEST_PG，`uv run --frozen pytest -q -m 'not live_sdk'` 为 **3423 passed／22 skipped／28 deselected／4 既有 xfailed，0 failed**，包含新功能 66 项（65 离线＋1 隔离 Docker PG 往返／幂等；对全部 canonical 字段核对）。44 条测试 warning 主要来自未改动的 API 依赖／异步测试，退出时另有 run_directory 协程未 await 提示，未扩大修复范围。全仓 `ruff check`、495 文件 `ruff format --check`、`basedpyright` 0 errors、迁移 lint（50 PG／1 CH）、`uv lock --check`、`git diff --check` 通过；依赖、DDL、类型 baseline 未改。只读查四张生产目标表归属：meta.instruments=tushare，其余三张未登记；没有 claim 或写业务库。未调用真实供应商、未启动样本或全量回补、未改米筐批次。本任务未写 dev；开发期间 dev 的 gr-tools/io.py 等有并行新增修改，未复制或覆盖，分支基线仍为 9f41ce3。临时测试容器和 named volume 已清理。

- 2026-10-26（米筐完成，Tushare 指数／期货合入 dev，未推送）：米筐 2024-01-30～2026-10-21 回补账本 `getrich-runs/ricequant-20240130-20261021/ledger.json` 为 completed；无米筐进程、cron、launchd 任务，用户确认 Codex 后台跟进已暂停。dev 依次提交 `7119fd5`（公共配置与 basedpyright）、`706e234`（米筐零预留授权），合并 `962957b`（`feat/tushare-index-futures` 的 `2cbdf5f`），再以 `a4b7ecd` 逐条修正 Tushare 代码的 11 个 basedpyright 错误（未写入 baseline）。合入后验证（2026-10-26，去掉供应商 token、未设 `GETRICH_TEST_PG`）：全量 pytest 3357 passed／50 skipped／4 xfailed，含一次性 Docker PG 用例；basedpyright 0 errors、baseline 未改写；ruff、491 文件格式、迁移 lint、`uv lock --check` 通过。Tushare worktree 合并前另补跑 gr-data 含 Docker 用例 1125 passed（`test_full_flow.py` 7 项通过）。dev 领先 `origin/dev` 15 个提交，远程 CI 未运行。**米筐版本**：dev 受保护路径最近提交为 `a4b7ecd`，已与完成批次的 `6320f70` 分叉；以后从 dev 启动米筐新批次前须先登记版本策略。下一步 ETF／期权从 dev 开分支，规划见设计仓 `data-platform/proposals/tushare-etf-options-ingestion.md`（v0.3，待评审）；Tushare 指数／期货 raw 已完成至 2026-10-23，正式 PG 入库仍待单独验收。
- 2026-10-25（独立 worktree，审查修复；已于 2026-10-26 合入 dev，见上条）：独立 code-review 发现 3 个 Major，已修复并经复审补漏，共补 13 条回归用例（其中 11 条在还原旧逻辑的副本上失败、修复后通过，2 条为对照）。① raw 重抓（`update` 与整月 `init`）只替换当前白名单内代码／交易所在请求日期上的行，收窄白名单或旧版全量指数 raw 不再被删（`_in_scope`、`SCOPED`）；期货另要求不早于该所有效起点，起点前旧行保留。② `FutureBars1dImporter` 按代码形态整行排除 SCTAS 价差行并计软告警，不再把负价差置 NULL、正价差当绝对价入库（D-025）。③ 期货各所检查起点取 `start_date` 与清单中该所最早 `list_date` 的较晚者，开业前不要求日历、不请求日线、不判旧月过期；清单无上市日时仍严格。验证（2026-10-25）：去掉 `TUSHARE_TOKEN` 全量 `uv run --frozen pytest` 3189 passed／174 skipped／4 xfailed；改动文件 Ruff／格式、`git diff --check` 通过；本机沙箱连不上 Docker，50 个 PG 集成用例（含 `test_full_flow.py`）未运行。已完成的 raw 回补由修复前源码产出，回补期间白名单未收窄，`source-pin.json` 与当前源码哈希不再一致属预期。米筐实际运行于固定 worktree `ricequant-pinned-importer`（`6320f70`），下文旧条目中的“米筐原目录”应按此理解。

- 2026-10-25（SCTAS raw 门禁修复并恢复）：交易所规则及源基础信息确认 SCTAS OHLC／前收为结算价偏移量，允许规则范围内负值（D-025）；普通合约及结算价／量额／持仓量仍维持原检查。独立 worktree 新增 `raw/tushare/quote_rules.py` 与回归测试，独立执行器调用；原米筐目录不变。相关 raw／按月门禁 164 项通过，追加前收用例后 TAS＋恢复用例 47 项通过；Ruff 与格式通过。54 个已成功分区重新核验且 SHA 不变，2025-09 共 22,409 行验收通过，25 行有 TAS 负价差字段，原值及 NULL 未改；直接复用已有 raw，未重抓。已带用户明确授权恢复，账本状态 running、恢复后期货已完成至 2025-10、活动任务 fut_daily-2025-11，截至 2026-10-25T11:24:24.999515+08:00，后续以实时账本为准。旧执行器／账本／源码指纹／失败 raw 已归档到 `/Volumes/myssd/data/tushare-backfill/20240101-20261023/recoveries/20261025-sctas/`，新指纹变更清单与恢复确认均留证。仍仅 raw，不写工作库、不合并、不提交推送；普通 future_bar_1d 尚无 TAS 价差映射，正式入库前须单独处理，不能直接混作绝对行情。米筐复核正常完成到 2026-07，importer 仍为 6320f70，未修改其源码／配置／账本。
- 2026-10-25（独立 worktree，用户已授权 raw 回补）：固定 2024-01-01～2026-10-23，8 个指数＋六所期货，仅 raw、不连接工作库、不调用米筐、不合并代码。运行目录 `/Volumes/myssd/data/tushare-backfill/20240101-20261023/`，raw 位于其 `raw/`；独立低优先级后台执行器 `run.py`、日志及 `ledger.json` 保存断点，异常／超时／代码指纹变化即 needs_attention 停止。复用 2026-10-24 已验收参考数据与 1 月样本，SHA256 核验通过；源码与样本版本一致，17 项离线门禁检查通过。启动核验：指数 34 个月／5,424 行完成；期货已完成至 2024-03，活动任务 fut_daily-2024-04（截至账本 2026-10-25T00:36:49.163533+08:00，后续以实时账本为准）。每月检查范围、重复键、代码映射、数值、各所日期覆盖及有明确上市／到期边界的合约逐日覆盖；NULL 保留。米筐原目录 importer 仍为 6320f70，代码／配置／账本／工作库未改；当前米筐账本已完成到 2025-08，其状态仍由原执行器管理。未添加额外自动化，未提交推送。（2026-10-26：米筐结束后已合并，见首条）本轮 raw 完成后仍需安排正式 PG 入库验收。
- 2026-10-24 23:33（独立 worktree，真实样本验收完成）：用户授权实取 Tushare 2024 年 1 月指数／期货，独立目录 `/Volumes/myssd/data/tushare-smoke/2024-01-20261024/` 保存 raw、配置、日志、两轮快照及 [验收报告](/Volumes/myssd/data/tushare-smoke/2024-01-20261024/report.md)。8 个指数各 22 日共 176 行；六所期货含主力／连续共 1,010 个代码、20,696 行，各所 22 日完整；GFEX 26 个代码／528 行。全部 raw 与独立临时 PG 逐键逐字段对账无差异、无丢行；再次真实 update 后 raw 全值相同，再导入后行情值与行数不变；7 条 ETL 全 success／0 warning。期货保留 1,731 行仅结算价与 102 行持仓量 NULL；明确生命周期的 16,758 个合约交易日无缺失，另 179 个无源上市日的序列共 3,938 行单独留证，不推断生命周期。临时 TimescaleDB 2.30.1-pg18 50 个迁移通过，独立容器及 named volume 已清理；未访问工作库、未改米筐源码／配置／账本、未调用米筐；本轮源码不变，只更新当前状态。完整命令见报告及 commands.json。仅覆盖上述代码的 2024-01，不外推其他月份／全部指数，不启动全历史回补；未提交推送。
- 2026-10-24（独立 worktree，待用户代码审核）：本轮只修复并验证 Tushare 指数／期货日线，不调用真实供应商、不写工作库、不启动回补；原目录与米筐版本／配置／账本均未修改，米筐实时状态仍以原目录执行账本为准。本 worktree 留供审核，未提交推送，不合并回正在运行米筐的目录。指数：`index_daily` 必须配置 `index_codes`／`index_markets` 白名单（取并集，拒绝未知代码与申万；本机 index_basic 有 9,746 个非申万指数，全量逐代码逐月约 33 万次请求），每代码按连续月份段整段请求，任一代码过去开市日缺数据即汇总报错、不落盘，按请求自然日区间替换旧 raw。期货：页上限改为 2000，独立采集 `fut_trade_cal` 并逐所逐日取数；新增 `future_exchanges` 白名单；官方文档未列 GFEX，用户在 worktree 用 live 用例 `test_future_calendar_exchange_supported[*]`、`test_gfex_daily_matches_exchange` 实测 7 项全部通过（2026-10-24），按用户要求默认六所含 GFEX 一并导入。扩大白名单后 `update` 会重抓缺新代码／新交易所的旧月份。两者检查日历自然日覆盖、错代码／错日期／重复响应键；ingest 按月校验必需列、先归一键再去重、丢行记软告警、成交量／金额／持仓非数值或非有限／负数拒绝，期货手数不可为小数，金额用 Decimal 换算，到期合约不再一律 active。新增可选日线 `end_date`，审核样例为 2024-01-01～2026-10-23，见 `packages/gr-data/config.tushare-markets.example.yaml` 与 gr-data README。验证（2026-10-24）：`uv run --frozen pytest packages/gr-data/tests -q` 1070 passed／28 skipped（含 7 个新增 live 用例）／4 既有 xfailed；Ruff check、487 文件 format check、迁移 lint（50 PG）、`uv lock --check`、`git diff --check` 通过；含自动清理的一次性 TimescaleDB PostgreSQL 全链路。无 schema／依赖变更；真实回补权限、GFEX 早于 2024 的日历、`list_date` 当日是否有数、已停发指数是否都填 `exp_date` 及真实覆盖尚未验收，审核后先小样本核对再回补。ETF／期权仍为后续阶段，未实现或启用。
- 2026-10-23：第一阶段与 2a 已提交到 dev，049 工作库迁移完成且 checksum `04fc73b0d1a2` 核对通过；未推送。production 三模型 2024-01-02～01-29 首 20 个交易日共 60 批均完成并通过验收，最低完整率 99.9608%，未知身份／上市边界为 0。27 条覆盖缺口均为 9 只股票上市首日缺特异收益，下一交易日全部恢复；没有数值异常。用户已授权后续至2026-10-21按月回补，用户已确认保留格式、先用RICEQUANT_API_KEY单账号并在配额不足后次日续跑；月度执行器已通过 15 项 mock、16 项审计 mock 和独立审查；1 月 30～31 日新增 6 批及 2 月 45 批已通过，3 月已由后台跟进启动；[容量与续跑准备](#rq-production-capacity-20261023)已记录。2b 发布清单／统一读取另审，正式风险读取仍关闭。详见[生产首20日记录](#rq-production-first20-20261023)。
- 2026-09-19：新增 `docs/index.html` 静态项目介绍页与 `.nojekyll`，Pages 发布步骤见 docs README。已检查桌面／手机布局及页面链接对应的本地文件。页面已随 `75f3292` 提交并推送到 `dev`；GitHub Pages 设置与部署结果本仓未核实。
- 2026-10-20：持仓诊断一期口径已在相邻设计仓 `getrich-design` 确认（`governance/scope.md` PA-01～PA-20），并整理了一期数据集清单（`data-platform/portfolio-diagnosis-phase1-datasets.md`）。本仓现有实现仍按旧设计（A 已有计算，B/C/D、压力测试与多方案 E 未开放），对齐缺口见 backlog「持仓诊断与数据供给」。用户决定先完成 gr-data 一期数据；盲点阈值与画像规则等真实数据后再定。不能用估算值填满界面。
- 2026-10-18 设计仓 DP-02 供应商方向：Tushare 为主要来源，风险因子先选米筐，DataYes 为第二档备用，银河为最后备用，INSIGHT 不再使用（代码与历史资料保留）。运行配置与表归属未随之改变。
- 数据接入 P0–P2 已有实现；P6 五表自洽校验、SW14/SW21 模型切换、行业分类真源仍需推进。后续 P3–P5 的历史规划需先核实现有能力与数据权限。
- 米筐补充方案首期 R1–R3 已有离线契约、raw 采集与观察读取，默认关闭。还缺逐项的 Tushare／Datayes 去重、米筐模块权限、真实样本契约和采集区间证据；按设计 P0 门槛，尚未新增 DDL／目标表 contracts／代码映射／PG writer，补充 ingest 在连接 PG 前拒绝。R4–R10 仅登记条件候选，不代表已支持。配置与阶段边界见 gr-data README；下一步先取得准入材料，再推进 P1c。
- 2026-09-18 用户因 DataYes 试用到期，明确新增米筐风险五件套接替入口 `rq_risk_model`（独立于上条 R1–R10）。已实现标准 v1/v2/v2trd 的日度 raw → factor.* writer，默认关闭，未改 DDL。真实取数仍待模型／行业体系、日期／股票范围、模块权限和源单位依据；未调用真实 SDK 或切换业务库 owner。示例配置和操作入口见 gr-data README。历史 CNE6 不覆盖，新米筐 run 保留实际观测时间与未校准状态。
- 2026-10-21：完成诊断、Tushare 一期链路、米筐风险链路的只读审核，问题清单与已定口径见 backlog「2026-10-21 现有实现审核」；同日确认 D-021（gr-api 内纯计算模块、回放另写）、D-022（数据版本发布清单，gr-data 发布）、D-023（停复牌事件表）。T1／T2 已按 D-023 修复并验证 9 月真数，其余审核项仍待处理；口径决定已同步至设计仓 scope.md PA-02／PA-04／PA-07 与表与接口设计 v0.3.5（§7.2、§7.3、§7.4、§7.8，新增原因码 `valuation_lagged`；设计仓已提交为 `02e0f47`）。
- 2026-10-22 D-024：新增迁移 045（`stock_bar_1d.price_limit_status`，LIMITED／NO_LIMIT／UNKNOWN，NULL 为未评估）及两条一致性约束；Tushare 涨跌停哨兵值写 NULL 并标 NO_LIMIT，不计软告警。验证：一次性容器空库 45 个迁移成功，两种后端全量各 2834 通过、0 失败、22 跳过，覆盖率 85.4%（含审查后修正 +Inf 误判为哨兵）。同日用户在本机工作库应用 045 并重导 9 月：退出码 0，股票日线 116,588 行中 LIMITED 116,525、NO_LIMIT 63（北交所 9 行／9 只、沪市 25 行／5 只、深市 29 行／8 只），无 UNKNOWN，库内不再有哨兵量级的涨跌停价；`ops.data_quality_check` 记 63 行。只读查询核对，仅覆盖 9 月。
- 2026-10-22：Tushare 导入最低门禁落地（坏文件、所选月份缺必需分区、未知代码、质量问题、缺股票标的或沪深日历硬失败并记 `failed`；软告警退出码 3），并修复 D-023 审查 P2-1、P2-2 与残留 `*.tmp-*` 被当作月份的问题；未新增迁移。验证：一次性 TimescaleDB 2.30.1-pg18 容器，celery／inproc 两种后端全量各 2810 通过、0 失败、22 跳过，覆盖率 85.4%（含独立审查后修复的首日 pre_close 误计软告警、断连时失败契约、非门禁异常堆栈）。同日用户在本机工作库用新门禁重导 9 月：行数与此前一致，退出码 3 来自 9 行北交所上市首日的哨兵涨跌停价；排查另发现沪深 54 行哨兵值被当作涨跌停价写入，见 D-024。其他供应商未接入门禁。范围与剩余项见 backlog。
- 2026-10-22 Tushare 链路人工审核疑点：修复 #12（raw 非稀疏数据集今天以前的交易日空响应拒绝写出该月，今天视为未发布）、#36（股票成交量／成交额缺失、非数值、非有限硬失败）、#46（daily_basic／估值缺目标列对应源字段硬失败，按月分区逐个校验，独立审查发现拼接后校验会被列齐全的月份掩盖）；未改 DDL。其余疑点以 strict xfail 留在 `packages/gr-data/tests/test_tushare_review_findings.py`，清单见 backlog。验证：本机 raw 2024-01～2026-10 共 34 个月只读扫描，无过去交易日缺失、无非有限成交量／成交额、daily_basic 必需列齐全无空值，修复不影响现有 raw；一次性 TimescaleDB 2.30.1-pg18 容器空库 45 个迁移，`GETRICH_TEST_PG=1` 下 inproc／celery 全量各 2851 通过、0 失败、22 跳过、8 xfail，覆盖率 85.4%；Ruff、463 文件格式、迁移 lint、`uv lock --check` 通过。未重抓或重导真实数据，未提交。剩余风险：2013–2023 未扫描，若供应商某个过去交易日确实无数据，#12 会让该数据集该月每次抓取都失败，且 `raw.run_provider` 遇错即停、后续数据集本轮不抓；历史回补前先用临时 raw 根目录预演。
- 2026-10-22：旧库升级脚本由 `ddl/upgrade/` 并入迁移序列，改名 `ddl/postgres/000_frontend_to_app_backtest.sql`（须先于 001 建 app schema 执行），去掉自带 BEGIN/COMMIT，随 `gr-db migrate` 自动执行并记账；`upgrade/` 目录与打包配置已删。新库与已是新结构的库上为空操作：已应用 001–045 的库下次 migrate 只多记一条 000。验证（一次性 TimescaleDB 2.30.1-pg18，迁移目录取 000–045）：空库 46 个迁移成功、数据字典漂移检查通过；已有 45 条记账的库补跑 000 前后 schema dump 一致；含 frontend 数据的模拟旧库改名与搬表正确、重跑为空操作；gr-db 测试 84 通过。
- 2026-10-22 DDL 审核跟进：迁移 047 替换 037 的风险模型数组约束（`factor_order`、载荷、协方差、因子收益须非空、一维、下标从 1 起、长度与 `factor_count` 一致、元素非 NULL 且有限；旧约束对空数组、多维、NaN／Inf 放行）；明细行 `factor_count` 与所属 `model_run` 一致由 `gr_data.ingest.factor_gate` 入库门禁检查，米筐与通联三张数组表接入；通联载荷／因子收益写库前另查有限性并带日期样例硬失败（此前允许 NaN 入库，恢复 DataYes 前须用真实 raw 定口径，见 D-010）。独立审查无正确性缺陷，已按其建议补门禁去重、约束名断言与 047 表达式变更须新开迁移的说明。工作库只读核查：factor 六张表均为 0 行，记账尚无 000 与 047，下次 migrate 一并执行。验证：一次性 TimescaleDB 2.30.1-pg18 空库 48 个迁移、数据字典漂移检查通过，`GETRICH_TEST_PG=1` 下 inproc／celery 全量各 2911 通过、0 失败、22 跳过、8 xfail，覆盖率 85.5%；Ruff、466 文件格式、迁移 lint、`uv lock --check` 通过；未提交。审核其余项（D-022 发布清单、选股约束、外键、004 物化视图、重复索引、runner 默认阻断）未处理。
- 2026-10-22：用户确认历史代码显示口径（一期显示当前代码与名称、注明输入的旧代码；有效期与换码流程按触发条件补齐，见 D-012）。核对发现诊断与选股导入只按当前代码解析，旧代码别名未生效、诊断按代码字符串合并持仓，已记入 backlog，不阻塞数据导入。
- 2026-10-21：`X-User-Id` mock 认证改为 `GETRICH_ALLOW_MOCK_AUTH` 显式开启、仅限 dev，无效 JWT 一律 401（D-020）。本机用 `VITE_DEMO_USER_ID` 开发前端时需在自己的 `.env` 加该开关。JWT 默认密钥的启动检查尚未处理。
- `diag.data_version` 的维护流程未完成；数据更新后如何推进版本必须与缓存策略一起处理。
- 策略／信号接口仍有契约与管理导入缺口；不能把诊断接口已有响应模型推广为所有接口均已覆盖。
- 回测 `oi` 映射、公司行为接入、Black-Litterman 建模口径及选股历史关联回填见待决问题。
- `apps/backtest-web` 暂停维护，2026-09-17 移除独立 CI；其 `src/lib/` 缺失，恢复维护前需补齐安全插件、HTML 清洗及 UI 工具，并重跑 lint／测试／构建，见该目录 README。`gr-agent` 仍为空包。

## 日志与默认运行模式

- 2026-10-26：按用户确认精简 `gr_tools.human`，仅保留 `unit`、`bytes_size`、`sec2str`；删除其余五个公开函数及日期／进度辅助实现，同步清理包入口导出。未发现已删函数的仓内业务调用，仓外调用需迁移。保留函数统一拒绝非有限或超出 float 范围的数值，数量按显示值选择单复数、未缩放整数保留精度，数量／字节数舍入后继续进位；字节数沿用 1024 进位与 KB/MB 命名，时长改用整数 divmod 拆分并保留常用输出。通过 uv 移除 gr-tools 的 tqdm 直接依赖并更新锁文件，gr-data 声明保留；类型基线仅删除 human.py 已消失的三条旧错误。验证（均使用 `UV_CACHE_DIR=/tmp/getrich-uv-cache`）：`uv run --no-sync pytest packages/gr-tools/tests packages/gr-api/tests/test_picks_cli.py -q` 131 通过，`uv run --no-sync basedpyright` 0 错误／警告；全仓 `ruff check packages/ scripts/`、`ruff format --check packages/ scripts/`、`uv lock --check --offline` 及 `git diff --check` 通过。未运行全仓业务测试、未调用真实服务、未提交。
- 2026-10-25：完成公共配置 P1–P7。日志默认格式移至 `gr_tools.logging`，`config` 顶层导入日志设施，消除反向导入；根目录查找解析 TOML 并跳过不可读／损坏文件，环境加载去掉重复分支，`LOG_FILE` 先展开 `~`，日志选项错误统一抛 `SettingsError`。`parse_bool(value, *, name)` 统一六个布尔键的解析：空值为 False、合法值不区分大小写、未知值直接报配置错误，消息不含原值；gr-data／gr-api 调用方已迁移。`APP_ENV=prod` 的严格模式判断不区分大小写。配置指南已同步。验证：`UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --no-sync pytest packages/gr-tools/tests -q` 83 通过；`env -u GETRICH_TEST_PG TUSHARE_TOKEN='' DATAYES_TOKEN='' UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --no-sync pytest packages/gr-data/tests packages/gr-api/tests -q` 1804 通过／167 跳过／8 xfail，32 条 ORJSONResponse 弃用及 mock 协程未 await 告警未处理。跳过包括测试报告 Docker 不可用的临时 PG 用例、未启用的工作库集成、真实 SDK 与 Windows 用例；未连接真实服务。`uv run --no-sync ruff check packages/`、`ruff format --check packages/`（均使用上述 UV_CACHE_DIR）及 `git diff --check` 通过。同日已按用户指定核验 workspace `.env`：六个布尔键均合法，其中两个未设置并使用 False 默认值，日志配置及 mock 认证环境约束校验通过；使用显式文件和空进程来源隔离检查，未核验其他部署文件、进程覆盖值或服务连通性。未输出凭据、未修改真实环境文件、未提交。
- 2026-10-24：按用户确认精简 `gr_tools.fs`，仅保留 `PathLike`、`list_paths` 与 `get_files`，同步删除包入口的其余文件系统函数导出；复制、移动、删除及属性查询直接使用标准库。仓内未发现已删除函数的非测试调用；仓外调用方需迁移。目录遍历继续递归、解析路径并排序，新增非目录根路径与互斥筛选参数校验。验证：`UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --no-sync pytest packages/gr-tools/tests -q`，43 项通过；四个修改的 Python 文件 Ruff 检查、格式检查及 `git diff --check` 通过。未运行全仓测试。
- 2026-09-18 配置入口拆分已实施：gr-tools 提供无导入副作用的环境快照／日志能力；gr-data 保留数据模型；gr-api 组装 API／worker 配置，其他 CLI 按需加载。旧全量 Settings／settings／load_settings 已移除，导入不再创建 `.env`；Python 调用迁移见 gr-data 手册。
- API 请求、支付验签与后台任务使用应用实例配置；Celery 使用队列应用配置，数据库池接收显式参数。公共日志入口为 gr_tools.config.setup_logging，详见 D-002。
- 默认 worker backend 为 inproc；CI 默认仅 PG，手动 extra_services 可启用 CH／Redis。未启动或停止本机数据库服务。
- 2026-09-17：按用户决定，最低 Python 版本统一为 3.11，停止支持 3.10；各包声明、uv.lock、Ruff／类型检查配置已对齐，开发默认仍为 3.12。CI 保留 3.11／3.12 并显式用 UV_PYTHON 选择解释器；3.12 开启选股／诊断 PG 集成测试与 75% 覆盖率检查，覆盖率包范围读取 pyproject.toml。手动 CH／Redis 环境仅在 3.12 运行。主前端 Node 24 的 lint／build 保留。泛型兼容说明见 `gr_api/schemas/diagnosis.py` 的相邻注释。
- 本地 .env 仅更新 worker backend；连接与凭证未迁移到源码或 YAML。

## 验证边界

- 2026-10-26：补齐 IO 错误边界：excel_sheet_names 将 fastexcel 读取异常包装为含路径的 RuntimeError 并保留异常链，MemoryError 原样传播；gr-picks CLI 捕获 RuntimeError，损坏 XLSX／CSV 返回 1，在 CLI 里输出一行 `[failed]`，不打印报错堆栈。read_frame 的全字符串转换仅将 PolarsError 包装为 ValueError，使 read_directory 遇到无法转成字符串的嵌套列时按单个坏文件跳过并汇总告警；MemoryError 不被转换。日期三类错误统一英文，Excel 序号提示仅用于 1～5 位纯数字，20261332、100000、46321.0 使用普通日期格式错误。定向测试先复现 15 项失败后修复，最终 IO／CLI／选股导入 100 项通过，包含异常链与两处 MemoryError 传播。验证（均使用 `UV_CACHE_DIR=/tmp/getrich-uv-cache`）：`uv run --frozen pytest packages/gr-tools/tests packages/gr-api/tests -k "io or pick" -v` 597 passed／21 skipped／522 deselected／15 warnings，跳过为未启用 GETRICH_TEST_PG 的真库测试，警告仍来自既有 ORJSONResponse 弃用和 worker mock 协程未 await；`uv run --frozen ruff check packages/gr-tools packages/gr-api`、`uv run --frozen ruff format --check packages/gr-tools packages/gr-api`（136 文件）、`uv run --frozen basedpyright`（0 errors／warnings）、`git diff --check` 通过。未改依赖／锁文件，未连接真实服务、未提交。最终验证（2026-10-26，本机，Python 3.12）：`uv run --frozen pytest` 3464 通过／50 跳过／4 xfail；Ruff 检查、491 个文件的格式检查、basedpyright（0 errors）、`uv lock --check`、`git diff --check` 均通过。选股导入真库集成测试（`GETRICH_TEST_PG=1`）未运行；远程 CI 未运行。

- 2026-10-26：选股导入正式支持 .csv/.parquet/.xlsx/.xls，其他后缀在读文件前报 BadRequest。gr-tools 新增 excel_sheet_names（fastexcel 延迟导入），工作簿必须恰好有一个工作表，隐藏工作表也计入；日期兼容 YYYYMMDD 与无时区的午夜时间文本，非零时间／时区及数字日期序号返回带行号的 invalid_date，CSV／Excel 均按表头为第 1 行的记录序号计数。完整 xlsx dry-run 已核对代码、date、整数 rank 和 Decimal("0.25") 百分比权重。嵌套列沿用未知列忽略契约：Parquet 保留原类型，业务层先筛列再转字符串；未知 List/Struct 告警忽略，已知嵌套列报 BadRequest，覆盖 Polars／pandas／Parquet。CLI、选股指南和 pyarrow 依赖注释同步，本轮不改依赖版本或 uv.lock；新增测试先复现 17 项失败后修复。验证（均使用 `UV_CACHE_DIR=/tmp/getrich-uv-cache`）：`uv run --frozen pytest packages/gr-tools/tests packages/gr-api/tests -k "io or pick" -v` 最终 585 passed／21 skipped／522 deselected／18 warnings（-k 同时匹配 anyio 标记，包含额外异步测试）；跳过均为未启用 GETRICH_TEST_PG 的真库用例，警告来自既有 ORJSONResponse 弃用与 worker mock 协程未 await。`uv run --frozen ruff check packages/gr-tools packages/gr-api`、`uv run --frozen ruff format --check packages/gr-tools packages/gr-api`（136 文件）、`uv run --frozen basedpyright`（0 errors／warnings，基线本轮未改写）、`uv lock --check`、`git diff --check` 通过。只读查看 Docker 仅发现工作用 getrich-pg18，无已知临时测试库，因此未运行条件命令 `GETRICH_TEST_PG=1 uv run pytest packages/gr-api/tests/test_pick_pg_integration.py -v`，未连接／写入工作库、未启动容器、未提交。

- 2026-10-26：`gr_tools.io` 统一使用 Polars（本机 1.44.2），通过 uv 移除 gr-tools 的 pandas 直接依赖并添加 fastexcel 0.21.0；根 dev 的 pandas-stubs 与其他包的 pandas 依赖保留。五个函数名不变，移除公共 engine 参数、Engine 与 READERS；CSV／Excel 的 all_string 默认在读取阶段关闭推断，Excel 数字 1 输出 "1"、午夜日期输出 "2026-10-26 00:00:00"，文件中已存为数字的代码不补零。trading_dates 可独立使用，按闭区间过滤、去重升序；全部文件失败抛带文件名的 RuntimeError，部分失败汇总告警，空目录／成功空表仍返回空表，MemoryError 原样传播。六个问题已先在旧实现／原依赖环境复现；其中 Excel 丢零以默认 100 行采样后的文本代码复现，修复后通过。验证（均使用 `UV_CACHE_DIR=/tmp/getrich-uv-cache`）：`uv lock --check` 通过；`uv run --frozen pytest packages/gr-tools/tests -v` 150 通过（含 io 30 项、Excel 用例实际执行）；`uv run --frozen pytest packages/gr-api/tests -k pick` 72 通过／8 跳过／870 未选，跳过为未启用 GETRICH_TEST_PG 的真库测试，保留 2 条既有 ORJSONResponse 弃用警告；`uv run --frozen ruff check packages/gr-tools`、`uv run --frozen ruff format --check packages/gr-tools` 通过；`uv run --frozen basedpyright` 0 errors／warnings，自动删除本次消失的 3 条旧诊断（pick_import 1 条、test_io 2 条），未新增基线豁免；`uv run --frozen python -c "import gr_tools, sys; assert 'pandas' not in sys.modules"` 及 `git diff --check` 通过。未改包入口、pick_import 或选股指南，未连接真实服务、未提交。

- 2026-10-25 类型检查改为 basedpyright（standard 模式，全仓唯一，配置在根 pyproject；mypy 已从 dev 依赖移除）。池连接标注统一为 `gr_data.db.DictConnection`（`AsyncConnection[DictRow]`），源码 standard 错误由 1102 降至 232；其余存量 1221 条记在 `.basedpyright/baseline.json`，CI python-quality 只拦新增错误。31 处 psycopg「非字面量 SQL」报错已逐条核对，拼接的标识符都来自常量或白名单，未改代码。本机全量 pytest 3229 通过／43 跳过／8 xfail，Ruff 与格式检查通过；未运行远程 CI。gr-tools 启用 strict 待其改动收尾后再定。已随 7119fd5 提交（2026-10-26）；未做独立子 Agent 审查。
- 2026-10-22 Tushare 历史回补完成（2024-01-02 至 2026-10-22，34 个月）：工作库应用迁移 046，新增 248 个北交所旧代码及 300114.SZ 的同证券别名，修复未知代码门禁；依据与重复观察口径见 D-012。只补抓最新月并从已有 raw 逐月续导；股票日线／每日指标／估值各 3,664,950 行，复权因子 3,685,268 行，停复牌事件 10,571 条、覆盖 677 天。续导 170 个按月任务及 4 个参考任务均 success、warning_count=0；逐月 canonical 行数、行情与估值键和 PB／PE TTM 空值对账通过（NULL 分别 23,659／960,270，未填零）。涨跌停 LIMITED 3,663,630／NO_LIMIT 1,320，无 UNKNOWN；交易状态 NORMAL 3,664,822／INTRADAY_HALTED 127／UNKNOWN 1。唯一 UNKNOWN 为 603003.SH 在 2025-06-10 同日无时段 S/R 且有成交，覆盖完整，按 D-023 保留冲突而不推断。相关回归 95 项通过（含一次性 PG 迁移、幂等及完整链路），Ruff／格式／迁移 lint／差异检查通过。历史两次失败保留在流水：未知别名、换码后重复主键，均已修复续导；本次未推进 D-022、未采集米筐、未提交推送。详细运行证据在本机临时目录 getrich-symbol-audit 与 getrich-tushare-backfill-20261022，不是永久备份。

- 2026-10-21 首批真实 Tushare 试导：按本机被忽略的 `config.yaml` 从 2026-09-01 采集至 2026-10-21，7 个 raw 任务成功、15 个 Parquet；仅执行 `uv run --frozen gr-data ingest tushare --months 2026-09`。本机工作库 8 个 importer 成功：标的／映射各 27,933、日历 832、股票日线／每日指标／估值各 116,588、复权因子 116,858、资产分类 5,917。行情与估值等按月数据仅覆盖 9 月 21 个交易日；10 月仅 raw，参考数据不受月份筛选限制。入库前确认 43 个迁移校验和一致且目标表为空；入库后逐键、主要数值字段、单位换算与空值对账通过，行情列与复权明细无差异。全范围 raw 检查 21 PASS／2 WARN／0 FAIL；9 月显式 `--end 20260930` 检查 21 PASS／1 WARN／0 FAIL，另补整月日历、数值与映射检查。9 条北交所上市首日 raw 跌停价为 0／涨停价 99999.99，按现有 importer 保留 raw、库内涨跌停均为 NULL；PB 缺 1,115 行、PE TTM 缺 34,296 行，未填零。该次初始 `trading_status` 有 10 行 HALTED，已由下述 D-023 修复与再验证替代。ETL 的 warning_count=0 未反映 importer 内日志警告，不代表数据无降级。未推进 diag.data_version、未发布诊断、未采集米筐、未提交推送。临时检查脚本仅供本轮人工试导，不能替代 A1／D-022 的工程门禁。


- 2026-10-21 D-023／T1／T2 已完成：044 新增停复牌事件及覆盖表，本机已应用；仅重抓 suspend_d 后确认原 9 月 265 条事件逐条一致，成功请求覆盖 21 天，事件导入与 bar 状态刷新同事务完成。现有 116,588 行的全部非状态字段摘要保持一致；状态为 NORMAL 116,577、INTRADAY_HALTED 11。沪深日历读取另外识别 HALTED 227、UNKNOWN 1（601238.SH 在 9 月 15 日无时段 S/R 同日）；北交所缺独立日历时读取器拒绝。行情仍仅入 9 月；本机忽略的 config.yaml 已加入 suspend_d importer。646 项离线测试通过、21 项真实 SDK 测试跳过，9 项临时 PG 集成通过（新增旧观察／归属／日历边界后另重跑 2 项通过）；既有 mock 协程 warning 保留。Ruff、460 文件格式、44 PG／1 CH 迁移静态检查通过。PB 缺 1,115、PE TTM 缺 34,296，均与 raw 一致；PE 空值符合供应商亏损语义，PB 具体财务原因仍未逐股核验。尚未接入回放／诊断消费者，未发布 D-022 数据版本；无提交推送。

- 2026-09-18 米筐风险五件套：新增 53 项离线测试随既有 raw／ingest／common／config 合计 341 项通过，8 项集成／真实 SDK 排除；独立审查发现行业全零及市场载荷缺少约束，最小修复并补 4 项回归后米筐目录 183 项通过，1 项集成排除，审查项复核关闭。Fake SDK → zstd Parquet → 现有完整 DDL 的 PostgreSQL COPY／JSONB 链路实际通过，覆盖重复导入、真实 available_at 和 owner 冲突拒绝；测试使用仓库外一次性 TimescaleDB 2.30.1-pg17-oss 容器及 named volume，已清理。真实账户单位、权限、覆盖和五表市场自洽仍未验收；未提交或推送。
- 2026-09-18 米筐独立审核后的最小修复：采集在同一 variant 下原子保存本轮计划及观察序号下界，同范围恢复优先补缺片、跳过本轮成功片并直接续跑拆分子片，修复配额反复耗在首片导致后续日期缺失的问题；本轮结束后下一轮仍正常回扫。close 显式拒绝 nullable Float64／Int64／Arrow 类型的缺失值，保持有效数值原样。新增 18 项回归先复现旧实现的 7 项失败，修复后米筐 126 项、连同既有 raw／ingest／common／config 共 288 项通过，7 项真库／SDK 用例排除；Ruff、441 文件格式及差异检查通过。未调用真实服务、改动 DDL／owner 或提交推送；SDK 对北交所成分与权重的过滤差异仍需在 P0 真实样本验收时核对。
- 2026-09-18 米筐 R1–R3：新增配置准入、显式任务选择、SDK 薄封装、日历快照分片、超时／内存预算二分、配额暂停、不可变观察与断点恢复，以及按月离线读取。成员接口显式声明 enable_bjse，避免 SDK 静默过滤北交所；成分 create_tm 保留源义但 PIT 未核实，权重只存查询日及原尺度。108 项新增离线测试与既有 raw／ingest／common／config 合计 270 项通过，7 项真实库／SDK 用例排除；Ruff、441 文件格式及差异检查通过。未调用真实米筐、未连接业务库、未迁移或变更 owner。80 次相同观察写盘的本地模拟比较：逐次重扫恢复元数据 1.373 秒、持锁期间缓存恢复索引 0.123 秒，观察序号和值一致；仅代表该 fixture。新改动尚未提交或推送。
- 2026-09-18 Tushare 现有 11 接口链路补齐：分页／重试遵守配置间隔，offset 超限不重试；按依赖排序执行所选 raw／ingest；月中重抓保留未请求日期，空停复牌响应清除旧事件，已有行情日期空响应拒绝覆盖；股票辅助表关联先归一日期／代码并去重，拦截无穷前收盘与涨跌停价，修复闰日日历抓取。范围限现有接口，未扩展财报／宏观或改 schema。使用说明见 gr-data README。
- 首轮离线 raw／ingest／common／config 回归 154 项通过；Fake SDK 的 11 接口 → Parquet → PostgreSQL 全部 10 个 importer 与 JSONB 集成 2 项通过，覆盖重复导入、单位／时间戳及 ownership 拒写。使用 TimescaleDB 2.30.1-pg17-oss 独立临时容器与 named volume，完成后清理；未调用真实供应商、未向业务库导入或转移主源。结果仅代表 fixture 链路，真实账号权限与供应商覆盖仍需另行验收。
- 同日审核修复：月内新旧 `trade_date` 的整数／字符串统一保存为 YYYYMMDD 字符串；完整自然月 `init` 可不依赖旧分区可读性进行重建，局部更新／当前未结束月份／重建响应不完整时仍保留旧文件并拒绝覆盖。新增 8 项回归，末轮上述四个目录离线测试 162 项通过；Ruff、429 文件格式检查与差异检查通过。本轮未重跑 PG 集成或调用真实供应商。

- 2026-09-18 配置组装迁移：Python 3.12 受影响包离线回归 1385 项通过、6 项跳过、42 项排除；Python 3.11.16 相关回归 408 项通过。末轮调整另通过 69 项定向检查及 10 项 API 配置／ASGI 入口检查。测试使用隔离环境目录，保留既有 mock 协程警告；未执行全仓测试、真库集成或远程 CI。
- 本次 Ruff、429 文件格式检查、PG 42／CH 1 迁移静态检查、uv lock 检查、差异检查通过。独立 Python 3.11 wheel 环境验证 gr-tools 配置不依赖 gr-data、gr-data 配置不依赖 gr-api；这不是完整包运行时集成验证。18 个决策编号、69 处有效引用及 68 个本地链接／锚点通过检查。

- 2026-09-18 决策清理：18 个连续编号与锚点、72 处有效引用、68 个本地链接／锚点检查通过；唯一旧编号为已记账 040 迁移的历史引用，在决策文档注明映射。8 个 Python 文件仅注释／docstring 变化，可执行 AST 一致；全部 DDL 未改，Redis 仅改引用与说明、运行配置未变，`git diff --check` 通过。本次未运行交易／数据库业务测试或连接服务。

- 2026-10-10 本机库迁移：本机 PG18 实例已应用 gr-db 001–043（全新库，43 条记账，6 个压缩策略 + 1 个保留策略）。一次性容器实测清空记账表后全量重放成功，schema dump 一致。043 补 `app.users.display_name`（auth.py 登录／刷新令牌依赖，缺列时全新库登录 500），并停用 011 的公开演示账号 demo@getrich.io；新增 `test_auth_pg_integration.py` 在 042 状态下 3 项失败、043 后通过，gr-api PG 集成合计 21 项通过。审查后仍待决、未修改：① 分钟线压缩后重灌数据会触发 `timescaledb.max_tuples_decompressed_per_dml_transaction`（默认 100000），回填前需定 chunk 间隔、压缩参数，并暂停压缩作业；② `004` 的 `*_1d_ca` 物化视图无人引用且 WITH NO DATA；034 `chk_item_option_type` 放行 NULL；回测比率列 DECIMAL(20,10) 可能溢出；app schema 缺外键、meta 交易所码缺 CHECK；042 对 `pick.item.symbol` 的注释写错；btree_gist 装在 pg_catalog；`gr-db migrate --dry-run` 会建记账表，且汇总行误报 0；`lint_migrations.py --comments --base-ref` 只检查已提交差异，未提交的新迁移需直接调用 `comment_violations` 自查。
- 2026-10-10：PostgreSQL 部署改为 TimescaleDB 2.30.1-pg18（非 oss，见 D-004），CI 与 gr-data 测试 fixture 同步；新增 initdb 参数、tune 上限透传、停止宽限期、日志 7 天循环，CH／Redis 改为 profile 按需启用。仓库外一次性栈实测：initdb（校验和、builtin 排序）、gr-db 42 个迁移、6 个压缩策略 + 1 个保留策略、gr-api PG 集成 18 项、gr-data integration 9 项、正常停机均通过，测试卷已删。gr-data 测试 fixture 迁移后暂停策略作业，避免保留策略删除用例写入的历史 tick。未运行远程 CI；本机部署目录已按模板准备，实例是否启动以 `docker compose ps` 为准。2026-09-18 曾把 pg17-oss 模板同步到另一台主机的外部部署（主机未确认）；若该实例已有数据，同步新模板前必须按 deploy/README 的 PG17 升级步骤导出迁移，否则容器会拒绝启动。ClickHouse、Redis 在 CI 与部署中的版本仍不一致（CI 26.3／8.2.8，部署 26.8.6.5／8.10.1），未处理。
- 2026-09-17 环境核对：Python 3.11.16 已安装到用户持久目录，项目 `.venv` 保持 3.12.14 并完成 `uv sync --locked --all-packages --python 3.12`。用户随后暂停全仓测试；在临时 PG 迁移阶段已停止，pytest 尚未启动，临时容器及专用 named volume 已确认清理。外部部署检查等待用户提供主机、部署目录及运行任务信息。
- 2026-09-17 Python 下限调整：独立 Python 3.11.16 环境完成锁定依赖安装，全仓 2540 项测试收集无错误；诊断单元／HTTP 契约 73 项在 3.11.16 与 3.12.14 均通过。Ruff、423 文件格式检查、actionlint、9 份项目声明与锁文件版本一致性、uv lock 检查通过；未执行全仓测试或真库集成，未检查外部部署解释器版本，3.10 部署升级前必须先换解释器。
- 2026-09-17：CI 调整通过 actionlint 1.7.12、YAML／shell 语法检查、Ruff、423 文件格式检查、43 个迁移静态检查、5 项迁移 lint 测试和离线 uv lock 检查。未运行 GitHub Actions、全量测试或真实数据库集成；未查询远程分支保护，若旧回测检查被设为 required，需同步移除该设置。
- 2026-09-08：日志／配置、API 中间件与 worker、CLI、包边界相关回归 157 项通过（9 条既有 mock 协程警告）。使用隔离配置目录，未连接真实数据库；没有执行全仓测试或远程 CI。
- 同日 Ruff 检查与 423 文件格式检查、迁移静态检查（PG 42／CH 1）、`uv lock --check`、`git diff --check` 通过；CI YAML 与默认服务条件静态验证通过。98 个本地链接／锚点、50 个唯一决策编号检查通过。
- 历史记录中的主机路径、服务健康、凭证配置、数据行数和依赖问题均不能当实时事实；使用前查当前配置、代码或执行对应检查。
- 2026-10-21 全仓基线（Python 3.12，本机）：开启 `GETRICH_TEST_PG=1` 并指向仓库外一次性 TimescaleDB 2.30.1-pg18 容器（空库 43 个迁移全部应用），worker 后端 celery 与 inproc 各跑一次，均 2759 通过、0 失败、22 跳过（21 项缺真实供应商 token、1 项仅 Windows），覆盖率 85.1%；gr-data 容器集成由 fixture 自起临时容器。Ruff、454 文件格式、迁移 lint、`uv lock --check` 通过。修复了 Celery 日志测试依赖 `current_app` 导致 celery 后端下失败的隔离问题。未调用真实供应商、未连接本机工作库、未运行远程 CI。
- 失败时记录具体命令、日期、范围与原因；上条基线不代表之后的代码状态。
- 2026-09-07 的历史记录：诊断单元／HTTP 契约 73 项、PG 集成 5 项通过；该记录不代表当前全仓测试或数据库状态。

<a id="rq-dynamic-stage1-20261023"></a>
### 2026-10-23 米筐动态名单第一阶段（单日样本完成，保留覆盖降级）

- 用户已确认设计并明确两阶段边界。动代码前已将当时 7 个文档文件单独提交为 `ac7543b`（未推送）；后续代码与文档仍未提交。固定名单 v1 raw 身份和既有历史观察保持兼容。
- 已实现：只读一致性事务冻结 PG 身份／别名；结合米筐上市含首日、退市不含当日的明确参考边界生成每日沪深 A 股名单；保留边界未知与 SDK 过滤，B 股明确排除留证；300114 与 302132 通过已验证整码别名关联同一证券。v2 variant 包含名单策略／映射版本／validation 用途，不包含每日变化名单；每日原始请求、完整响应、名单快照及覆盖 hash 不可变保留，reader 重算名单与三表交集。未知新 SDK 代码没有已核实别名时仍拒绝入库，不猜身份。
- 新 `factor.model_run_coverage` 与五件套、模型元数据、映射和成功 ETL 同日事务提交；失败流水独立记录。覆盖降级保留 ETL 告警及完整候选，纯覆盖降级可成功；数值质量告警仍遵循既有复核语义。空完整集、数值／轴／身份异常阻断，不放宽 R1／R2。v2 run 的 units 明确 purpose=validation、日期及名单／覆盖身份，calibrated=false，available_at 为实际观察时间。
- 首版 DDL（已被下方修订取代）：`048_factor_model_run_coverage.sql`，SHA256 `89f5cafb6ff506422d8ad9ff850493ef82b9092c99dca52d78cbee62f2cbee1a`。一次性 TimescaleDB 2.30.1-pg18 先应用基线 000～047，再 dry-run 确认仅 048，正式应用和重放成功；4 个合法用例通过、21 个非法数组／状态／JSON／主外键用例被拒绝。用户要求工作库执行前看 DDL，已展示并发出批准问题，**尚未获得本次工作库迁移确认，未执行工作库迁移或采样**。
- 全仓验证命令：`GETRICH_TEST_PG=1 GETRICH_WORKER_BACKEND=inproc PG_HOST=127.0.0.1 PG_PORT=55439 PG_USER=postgres PG_PASSWORD=test PG_DB=getrich TUSHARE_TOKEN='' RICEQUANT_API_KEY='' RICEQUANT_ENABLED=false COVERAGE_FILE=/tmp/getrich-rq-stage1.coverage UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen pytest --cov --cov-report=term-missing --cov-report=xml:/tmp/getrich-rq-stage1-coverage.xml --cov-fail-under=75`。全部 DB 测试指向一次性容器；3029 passed、22 skipped（21 个真实供应商测试、1 个 Windows 专属）、8 个既有 xfail，覆盖率 85.5%，退出 0。新增真实 PG 用例验证 partial bundle／JSONB 与数组 COPY／重复导入／coverage 写失败整日回滚／300114 别名冲突。独立审查无阻断项；其建议的“SDK 接受新代码但未核实 alias”回归补充运行 1 passed。
- 静态验证：`uv run --frozen ruff check packages/ scripts/`、`ruff format --check packages/ scripts/`、`python scripts/lint_migrations.py`、`uv lock --check`、`git diff --check` 通过。本任务一次性测试容器与 named volume 已清理；gr-data 集成 fixture 的容器亦已自行清理。日志 `/tmp/getrich-rq-stage1-full-tests.log` 及临时覆盖率文件仅为本机验证附件；以上摘要为可持久追溯记录。未调用真实供应商进行本阶段采样，未启动正式风险读取。
- 样本准备：只读核验 2026-10-21 为沪市开市日且有 Tushare 日线，三个模型的四项源单位及证据沿用各自已验收历史 run 原文，配置不含凭据。v1/v2/v2trd 的 v2 raw variant 已预登记在 [设计表](../../docs/plans/ricequant-historical-universe.md#验证-run-与正式读取隔离)。实际候选、完整、未返回、异常数与流量尚无本轮实测值，**不得以固定 100 股结果或预登记冒充全市场采样结果**。工作库迁移批准后，先核对 dry-run 仅 048，再应用、核对 owner，顺序各采一天并按 2026-10 入库；质量异常先检查。
- 第二阶段另行给出 D-022 发布清单、B1 提交收据／双水位、B2 观察顺序与防回退的表结构供评审，本阶段 ETL 流水不冒充这些能力。当前诊断没有新增读取 factor.* 的入口；第二阶段完成前正式风险读取保持关闭。全量回补与覆盖阈值均未批准启动。


#### 2026-10-23 覆盖表审阅修订（审批前验证记录，已获后续批准）

- 用户未批准首版工作库迁移，要求按六点修订后再审阅。本版 DDL SHA256：`0488aa6eac51065d489ce2006e7fde22465919cdbf1ac40b1098d4f56086b71c`。删除库内 invalid_value；unmapped_symbol 明确为已知证券身份但无请求代码，真正未知身份仅在 raw unresolved_identity 保留。unsupported_exchange 不落覆盖表，范围外来源记录仅留 raw；数值异常保留原响应和失败凭据、整日阻断。
- 统一请求前状态语义：unmapped_symbol、sdk_filtered、universe_boundary_unknown 均要求 request_code IS NULL、三个 pieces 全为 false；被 SDK 过滤的输入码留 input_codes／该股证据。DDL 与 writer 同步拒绝伪造请求或有效返回。evidence 仅允许 canonical、supplier、sdk_mapping、reason；共用快照 hash、SDK 版本、边界规则及别名选择规则改存 run.units.universe_evidence／ETL request，完整快照仍在 raw。实际每行和 evidence 的平均／最大 pg_column_size 待全市场样本后按模型报告，当前不填合成值。
- MODEL_RUN_COVERAGE 纳入米筐契约列表；动态导入在同日事务登记／校验 ricequant 归属，固定 v1 仍跳过新表。gr-data fixture 的 TRUNCATE 显式加入覆盖表。工作库表归属尚未登记，需在用户批准迁移后核对并执行 own set，再开始采样。
- 一次性 TimescaleDB 验证：000～047 基线 → dry-run 048 → 应用 → migration 重放／SQL 重放均通过。旧 25 项约束检查重跑通过；新增状态矩阵 42 次插入检查（6 合法、36 拒绝，包括三状态全部非零布尔组合、非空请求码、JSON 缺键／类型错误及已排除状态）通过。持久回归文件为 packages/gr-data/tests/ingest/test_risk_coverage_checks.py。相关套件命令 `uv run --frozen pytest packages/gr-data/tests/ricequant packages/gr-data/tests/ingest/test_risk_coverage_checks.py packages/gr-db/tests -q --no-cov` 当轮 395 passed；其后补充共用规则不落逐股 evidence 回归，已纳入下面最终全仓结果。
- 最终全仓：沿用上方一次性 PG 环境（GETRICH_TEST_PG=1、inproc、PG 端口 55439，供应商凭据置空），执行 `uv run --frozen pytest --cov --cov-report=term-missing --cov-report=xml:/tmp/getrich-rq-048-revision-coverage.xml --cov-fail-under=75`，3039 passed、22 skipped、8 既有 xfail，覆盖率 85.5%，退出 0。日志 /tmp/getrich-rq-048-revision-full-tests.log。Ruff、473 文件格式、迁移 lint、lock check、diff check 均通过；独立代码复核及共用规则后续增量复核均无阻断项。
- 本轮与 fixture 的一次性容器、named volume 均已确认清理。没有工作库迁移、真实采集、归属变更、提交或推送。新版 DDL 重新交用户确认；批准前不执行工作库操作，原计划单日样本仍未开始，第二阶段及正式读取边界不变。

#### 2026-10-23 工作库执行与全市场样本进展

- 用户明确批准后执行 `uv run --frozen gr-db migrate --target pg --dry-run`，日志计划仅 048（49 个文件中 1 个待应用）；随后正式执行同命令去掉 `--dry-run`，应用 1 项、退出 0。读取 `ops.schema_migrations` 验证完整 checksum 为 `0488aa6eac51065d489ce2006e7fde22465919cdbf1ac40b1098d4f56086b71c`，前缀符合批准版本。此 SQL 已记账，不再修改。`gr-data own set factor.model_run_coverage ricequant ingest` 成功；此前 8 张 factor 表也均为 ricequant / ingest。上方“等待批准／未迁移”仅为审批前历史。
- 单日范围仍为 2026-10-21，三个模型均为验证 variant。v1 首次参考预检（2026-10-23 11:09:52～53 Asia/Shanghai）触发 `Canonical stock exchange mismatch`，尚未调用风险五件套或入库，v2／v2trd暂停。只读定位为 instrument_id=33510、`T600018.SH`、上市 2000-07-19、退市 2006-10-20；这是独立历史身份，不能剥 T 合并到现 600018.SH。账户计数 54,815,789→57,432,397，参考加载窗口增量 2,616,608 字节，不记作五件套消耗。失败报告按尝试时间保留。
- 修复：不能安全生成请求代码的历史身份保留原码；有效日期之外排除（明确晚于退市日才排除），边界当天／异常日期保留 unmapped_symbol 且不请求。reader 与 writer 同步接受已知未请求身份；非标准整码 canonical／Tushare 冲突及当前已登记别名冲突仍拒绝。独立审查发现的冲突漏检已补回归并复核关闭。未修改元数据或已记账 DDL。
- 最终全仓命令（全部数据库测试仅指向一次性容器）：`GETRICH_TEST_PG=1 GETRICH_WORKER_BACKEND=inproc PG_HOST=127.0.0.1 PG_PORT=55439 PG_USER=postgres PG_PASSWORD=test PG_DB=getrich TUSHARE_TOKEN='' RICEQUANT_API_KEY='' RICEQUANT_ENABLED=false COVERAGE_FILE=/tmp/getrich-rq-tcode-final.coverage UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen pytest --cov --cov-report=term-missing --cov-report=xml:/tmp/getrich-rq-tcode-final-coverage.xml --cov-fail-under=75`。3,058 passed、22 skipped、8 既有 xfail、覆盖率 85.53%、退出 0；44 条既有测试警告仍记录在日志。Ruff、473 文件格式、迁移 lint、lock check、diff check 通过。独立增量审查无未解决阻断项；一次性容器和卷已清理。

| 本轮代码修复 | 修复前 | 修复后 |
|---|---|---|
| 非六位历史 canonical | T600018.SH 即使早已退市也让当前日整日失败 | 保留独立身份，按有效日期边界排除；可能在市则仅记 unmapped，不发请求 |
| 同历史整码别名冲突 | 非标准码存在漏检路径 | 生成名单及写库均核对完整原码冲突，不剥前缀合并身份 |

#### 2026-10-23 全市场单日验收结果（数据日 2026-10-21）

| 模型 | 因子数 | 候选 | 完整 | 未返回 | 边界未知 | 协方差条件数 | 年化总波动中位数 | evidence 平均字节 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 | 42 | 5,224 | 5,222 | 0 | 2 | 1,340.37 | 43.94% | 350.025 |
| v2 | 48 | 5,224 | 5,222 | 0 | 2 | 2,075.32 | 43.52% | 350.025 |
| v2trd | 52 | 5,224 | 5,222 | 0 | 2 | 2,042.04 | 43.42% | 350.025 |

- 三模型候选、完整集及覆盖状态完全相同，完整率 99.9617%；partial_bundle、sdk_filtered、unmapped_symbol 均为 0，真正未知身份 0。`anomalous=2` 指已记录的边界未知，不是数值异常；数值异常 0。同日成功事务各写入 20,892 行（五件套 15,668 + 覆盖 5,224），每个 run 的 ETL 成功 1 条、失败 0 条、覆盖告警 1 条；三个 CLI 均退出 0。参考预检失败发生在 raw 编排之前，无对应业务 run／ETL，不伪造失败流水。
- 运行命令：`RICEQUANT_ENABLED=true UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen python /tmp/getrich-rq-full-market-20261023/run_raw.py <model>`，模型依次 v1、v2、v2trd；每个使用无凭据临时配置，start=end=2026-10-21。入库逐个执行 `UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen gr-data --config /tmp/getrich-rq-full-market-20261023/<model>.yaml ingest ricequant --only rq_risk_model --months 2026-10`，没有扩大日期范围。
- 三个实际 run：v1 `4f7259d9-6269-5823-a8b8-a83a0d521011`；v2 `91aed631-dd4b-5877-ab17-1859d8c1e7ab`；v2trd `66e1bd4f-3d0f-59ba-a37b-25cc1c2d72a6`。对应 observation：`f808732000cc4b4294dd10c375c8284c`、`9addbd393f974f488965dec604f99a7a`、`5e61eb607b704621ba6fc0d6becb3d44`。variant 见设计文档验证表，均 purpose=validation、calibrated=false，不可用于正式诊断。
- 验收命令：`UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen python -I /tmp/getrich-rq-full-market-20261023/audit_samples.py --models v1 v2 v2trd --output /tmp/getrich-rq-full-market-20261023/final-audit.json`，只读一致性事务，退出 0。原始返回到 PG 按声明单位逐值核对（REAL 按 float32 精度精确往返，covariance 按 float64）；三张个股表完整集一致，五表日期／run／因子序一致，所有数组有限，行业哑变量和为 1，COUNTRY/comovement 恒为 1。协方差正定、对角正、上三角镜像对称；最小特征值（年化 %²）依次 0.76194／0.46394／0.44926。R1／R2 无数值告警，总波动范围分别 18.42～99.79%、17.97～98.76%、18.18～100.67%。
- 四项源单位仍为 dec_daily／dec_daily／dec2_annual／dec_annual，各模型沿用已确认的 units_evidence 原文；入库协方差／特异方差为年化 %²，因子收益为日频小数，特异收益为日频百分数。available_at 与 raw 实际完成观察严格相同：2026-10-23 11:18:30.848253、11:20:19.028858、11:21:19.906217（Asia/Shanghai），未回填为历史可得时间。
- 两个覆盖降级逐股保留：`302132.SZ`／历史 `300114.SZ` 已核实同一 instrument_id=30636，但米筐旧码 de_listed_date=2025-02-17、新码仍存续，当前保守边界规则把多段区间记为 unknown；不是无法确定证券身份。`000016.SZ`（33499）Tushare delist_date 为空，米筐参考为 2026-10-23，当前按供应商边界不一致保留 unknown。二者 request_code=NULL、pieces 全 false，未调用个股接口、未写数值，不擅自改 metadata 或放宽覆盖阈值；后续需评审边界分段处理。
- 与 Tushare 当日日线比较：沪深 A 股 5,216 只，北交所 352 只明确不在米筐范围；沪深有行情却未完整覆盖的只有 302132.SZ。候选中 8 只没有当日 Tushare bar，逐股均查到同日 S 事件且 timing=NULL：688496.SH、601326.SH、301468.SZ、301314.SZ、002731.SZ、002717.SZ、002388.SZ、000016.SZ；前 7 只有完整风险数据，最后一只按边界未知保留。无 bar 不等于不在市，也未因此删除候选。
- 覆盖表真实存储：每模型 5,224 行，`avg(pg_column_size(evidence))=350.024885` 字节、最大 484；`avg(pg_column_size(c))=536.033691` 字节、最大 696。三模型合计 15,672 行，`pg_total_relation_size=9,781,248` 字节（9.328125 MiB，含索引及 TOAST），其中 table 含 TOAST 8,601,600 字节、索引 1,179,648 字节。此为 2026-10-23 三样本完成后实测，不与 JSON 文本长度或以后全历史占用混用。
- 预测与实际历史波动对照：Tushare 2026-04-23～10-21 共 120 个交易日，close/pre_close−1 的样本标准差 × √252；不填停牌空日，至少 100 条有效收益，配对 5,185 只，37 只不足 100 条单独排除于对照（仍保留风险数据）。v1／v2／v2trd 预测／历史比值中位数 0.8913／0.8816／0.8798，P05～P95 分别 0.7561～1.1124／0.7285～1.1114／0.7267～1.1008；预测中位比例约低 10.9%／11.8%／12.0%。这是同日往前的历史对照，不是未来预测表现、单位重新推断或校准结论。
- 主对照三模型均有 8 只比值低于 0.5（0.1543%）：001237.SZ、001365.SZ、001393.SZ、301599.SZ、603407.SH、301531.SZ、688808.SH、603435.SH。逐股只读核查最大收益恰为上市首日（+109.9%～+875.8%）。额外敏感性对照仅剔除 list_date 当天收益，保留原主对照：40 条首日收益被剔除，配对仍为 5,185 只，三模型超出 [0.5,2] 均降为 0；最小比值 0.5486／0.5394／0.5552，中位数未变。首日 pre_close 不是该证券上一交易日的市场收盘价；未外部确认它一定等于发行价。没有改 raw／PG 数据或门禁。

| 流量观测窗口 | v1 | v2 | v2trd |
|---|---:|---:|---:|
| 参考名单加载增量（字节） | 2,616,608 | 2,616,608 | 2,616,608 |
| 五件套请求窗口增量（字节） | 1,259,474 | 1,433,937 | 1,640,330 |
| 五件套请求窗口增量（MiB） | 1.2011 | 1.3675 | 1.5643 |

- 五件套窗口合计 4,333,741 字节（4.1330 MiB）；从失败预检前 54,815,789 到收尾 70,338,669 的账户总增量为 15,522,880 字节（14.8038 MiB），含四次参考加载、SDK 初始化及延迟计数等。收尾在 11:22:12 和 11:22:32 计数相同；账户限额 1,073,741,824 字节。不能把窗口差值称为逐请求精确计费，也未独立排除账户其他消费者。按同日风险窗口机械外推 676 日约 2.728 GiB、每天 0.9 GiB 预算约 4 个配额日，仅校验此前 4～5 日规划量级；一个日样本不能确定早年规模或保证期限，尚未启动全量。
- 详细 audit、quota／迁移／owner 复核、Tushare 差异、8 股极端值证据保存在各验证 variant 的 `validation/20261023-full-market/` 目录（通过 RawPaths 定位），原响应与失败报告均保留。临时配置、脚本和测试日志位于 /tmp/getrich-rq-full-market-20261023，仅用于重现本轮操作；持久结论以上述记录和 raw 证据为准。最终复查 048 checksum 不变、9 表归属一致、三模型覆盖集合相同。没有新增提交或推送。
- 当前结论：数值、单位转换、同日事务、raw／PG 与 ETL 追溯验收通过；覆盖降级仍明确保留，不能宣称 100% 覆盖或正式发布通过。下一步评审两类日期边界及正式覆盖门槛；D-022／B1／B2 的发布清单和诊断隔离读取仍属第二阶段，完成前正式读取继续关闭，暂不全量回补。

### 2026-10-22 米筐一次性探针（首轮历史记录）

后续进展：以下首轮“待确认／待授权”已由用户授权的 [120 日单位探针](../../docs/history/2026-10-22-rq-risk-units-probe.md) 及下文三天样本验收取代；本段仅保留首轮历史证据。

- 范围：`rqdatac 3.7.1`，`model=v1`、`industry_mapping=sws_2021`、`horizon=daily`；数据日仅 2026-10-14，股票仅平安银行 `000001.XSHE`、宁德时代 `300750.XSHE`、贵州茅台 `600519.XSHG`。2026-10-22 22:04（Asia/Shanghai）开始请求。直接调用 SDK，不走 raw 流程；不落盘或打印密钥；五件套各请求一次，无失败重试，无扩大风险样本。
- 实际结果：exposure 3×42、factor_return 1×42、covariance 42×42、specific_return 1×3、specific_risk 1×3，解码均成功，数组数值有限；因子集合一致并按同一顺序计算。协方差最大非对称误差 3.47e-18、最小特征值 7.6244e-5、条件数 1470.9370，对角元范围 0.000171379～0.081128141，市场因子对角元 0.027482788。三只股票行业分别为银行／电力设备／食品饮料，行业载荷行和均 1、comovement 均 1（米筐市场因子字段名；目标 COUNTRY 类型）。这不是三个交易日、100 只股票的完整验收。
- 源样本与量级对照（收益率／风险原值不作单位转换；历史参考为 Tushare 2025-10-14～2026-10-13 的 242 条 close/pre_close 简单收益率，用样本标准差 × √252 年化；仅作量级参考，不视为风险模型应相等的真值）：

| 股票 | 特异收益原值 | 特异 σ 原值 | xΣx 原值 | 假设 Σ=dec2_annual、σ=dec_annual 时总年化波动率 | Tushare 历史参考 |
|---|---:|---:|---:|---:|---:|
| 000001.XSHE | -0.003202655 | 0.098586465 | 0.029300861 | 19.75% | 15.93% |
| 300750.XSHE | -0.006620961 | 0.246349133 | 0.044035009 | 32.36% | 35.57% |
| 600519.XSHG | 0.003896877 | 0.130323908 | 0.041322772 | 24.15% | 22.45% |

- 收益率判断：factor_return 原值范围 -0.011613388～0.031252162。两类收益均按日频小数解释时，使用当日载荷算 x·f+特异收益为 -0.6219%／-3.2069%／0.8456%，Tushare 当日为 -0.6050%／-3.1062%／0.8714%，差约 1.69／10.07／2.58 bp；量级支持 `factor_return=dec_daily`、`specific_return=dec_daily`，不是百分比原值。并非精确收益分解恒等式，载荷时点／模型收益口径差异尚未解释，不将差额直接判为数据错误。
- 风险单位判断：若 Σ 与 σ 均为日频小数，总年化波动率为 313.58%／513.71%／383.32%；若均为日频百分比口径则为 3.14%／5.14%／3.83%；若均为年化百分比口径则为 0.20%／0.32%／0.24%。两者均为年化小数最符合量级，但此比较不能独立确认各接口单位：例如 Σ=dec2_annual、σ=pct_daily 时仍得到 17.19%／21.35%／20.43%，不能仅因处于常见范围就排除或接受。公开官方 API 文档 https://www.ricequant.com/doc/rqdata/python/risk-factors-mod.html 将 horizon 解释为预测期限，相关返回说明未明确数值的年化和百分比口径；horizon=daily 本身不能证明源数值未年化。
- 结论：权限探针通过，源单位验收未完成。`covariance=dec2_annual`、`specific_risk=dec_annual` 仅是最符合样本的候选解释，不写入正式 source_units，不将本记录当作已确认 units_evidence。等待米筐对两接口单位的确认（尤其 daily 预测期限与年化输出的关系）；用户明确要求判断不出就停，故停止正式采集。没有创建 model_run；未来仍保持 calibrated=false、available_at 为真实采集时间。
- 名单准备：工作库三只股票均在起始日前上市，2026-10-14～16 停复牌事件为 0，三个日期均有 tushare 覆盖记录；库内行业归属表为空，尚无样本期非 ST 的充分证据。用户授权筛选 100 只、至少 20 个申万一级行业；待确认可额外查询行业与 ST 参考接口后完成名单，不能将 Tushare stock_basic 的行业标签直接当申万一级。
- 验证范围：探针进程及只读 PG 对照进程退出码均 0；未调用正式 raw／ingest，未运行全仓测试，无临时容器。脱敏数值摘要 `/tmp/getrich-rq-risk-probe-20261022.json` 为临时核查文件，关键数值已记录于本文，不作为永久备份。未修改代码／配置，未新增提交或推送。

- 2026-10-22 单位探针方法、比值分布与100只名单已归档：[米筐风险单位探针](../../docs/history/2026-10-22-rq-risk-units-probe.md)。

### 2026-10-22 米筐三天样本验收（数据与存储通过，未校准）

- 用户已确认四项源单位、归档后的units_evidence及正式采集／入库。按要求将原#rq-risk-units-20261022章节原样迁移至docs/history/2026-10-22-rq-risk-units-probe.md，内容SHA256为3c7b812de7b68a977ab4ed48534c1c44313a94e4fe6f727eacabab2a49983f47；配置证据只替换引用路径，其他文字不变。展示证据原文后再设selected=true；RICEQUANT_ENABLED=true仅用于本次raw进程，未修改.env。迁移后的档案为当时快照，含“待确认”历史措辞及旧证据原文，不代表现在仍待采集授权。
- 实际命令：`RICEQUANT_ENABLED=true UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen gr-data --config config.yaml raw ricequant --only rq_risk_model --mode init`；`UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen gr-data --config config.yaml ingest ricequant --only rq_risk_model --months 2026-10`。均退出0。raw汇总435是五份DataFrame的行数计法（每天100+42+1+1+1=145），不是业务库行数；入库每天302行，合计906行。SDK另提示账号19天后到期，为采集时的账户提示，不是数据失败。
- 模型v1、行业sws_2021，配置100只沪深股票，42个因子。variant=`9b342891035f90ab97fa9c7cbfb5c9f20c750e3f375a87013532a5ec50c2175c`。8张factor表归属ricequant ingest；模型1条、因子定义42条、model_run 3条；五数据表合计exposure=300、covariance=3、factor_return=3、specific_risk=300、specific_return=300。

| 数据日期 | model_run.run_id | 实际采集时间（Asia/Shanghai，2026-10-22） | 协方差条件数 | 最小特征值（年化%²） | 个股总年化波动率 最小／中位／最大 |
|---|---|---|---:|---:|---|
| 2026-10-14 | `a68992c8-d462-5d9f-8b38-2eac3d530809` | 22:48:23.153622 | 1470.937 | 0.762442 | 21.12%／32.22%／71.84% |
| 2026-10-15 | `9e149322-86d6-594c-84e7-d848a8832f18` | 22:48:31.107182 | 1474.816 | 0.742829 | 21.25%／32.35%／73.77% |
| 2026-10-16 | `3756c184-69c0-589b-8aa3-bd746f2c1b27` | 22:48:38.920551 | 1474.102 | 0.779702 | 21.75%／32.56%／74.09% |

**完整性、单位与时间验收**

- 用read_bundles复核manifest文件哈希与配置身份，三天各100股，无缺失／重复股票或日期；所有数组有限。五表逐日run_id／trading_day／标的集合一致，三张数组表factor_count=42。model_run.factor_order与definition.ordinal及顺序／集合hash一致，三日因子顺序不变；按此顺序逐值核对入库与raw（REAL列容许float32舍入，协方差DOUBLE用更严容差），全部通过。
- 协方差入库为源值×10000；特异风险入库为源σ平方×10000，均为年化%²；没有再乘252。因子收益保持日频小数，特异收益×100成为日频百分比。model_run.units完整保存已确认source_units和新units_evidence。三日协方差对称、对角正、Cholesky通过且最小特征值为正；条件数如表。
- 300条载荷行业哑变量均为0/1且每行和为1；市场因子comovement（本模型COUNTRY角色）恒为1。100股在风险模型中覆盖30个行业。model_run.calibrated均false；五表全部906行available_at逐行等于对应raw manifest.observed_at，model_run.estimated_at也相等，是2026-10-22实际观察时间，而非回填为10月14～16。当前没有model_run.available_at字段。
- ETL检查：ops.etl_job_run 213／214／215均success，各rows_written=302、warning_count=0，命令日志明确三条数据日及model_run UUID。追溯缺口：当前writer没有填trading_day/start_date/end_date，也没有将model_run UUID放入request；started_at与finished_at均使用同一事务now()，不能据此测耗时。因此日期与run对应关系本轮靠命令日志、manifest和五表联合核对，不能声称ETL记录自身已有完整关联。历史批量导入前建议连同门禁补齐，未擅自改代码。

**质量问题停查与结论修正**

- 入库前额外行业对照断言失败（检查进程退出1），当即暂停入库。三日稳定出现5只参考行业差异：002261.XSHE拓维信息 社会服务→计算机；002841.XSHE视源股份 社会服务→电子；600292.XSHG电投水电 环保→公用事业；600301.XSHG华锡有色 商贸零售→有色金属；603268.XSHG松发股份 轻工制造→国防军工。箭头左侧为筛选时shenwan_instrument_industry返回，右侧为risk model载荷。
- 用另一接口get_instrument_industry(source=sws,level=1,date=每日)独立复核，三天各100股与风险模型行业全部一致；行业参考接口存在差异，不能混用。未改风险raw、未手工改载荷、未替换样本股票；确认五件套内部与另一日期参考接口一致后重做原检查通过，再入库。不能由此断言旧接口差异的供应商内部原因已查明。原单位探针归档保持原样，本记录明确更正：100股仍覆盖30行业，但30只单位探针按风险模型实际覆盖27行业，并非原旧参考下的30行业；30股名单、120日比值、源单位判断及units_evidence中的“30只股票”不受影响。
- 华锡有色600301.XSHG在120日Tushare行情里只有115条：缺2026-09-14～18，共5天，逐天都有S且suspend_timing为空的事件和tushare覆盖记录，为已证实全天停牌；不填零、不补价，从严格120日个股总波动对照中排除，因此总波动对照为99股。这5天不在本次10月14～16样本内，不影响三天完整性。

**覆盖差异（以2026-10-14为截面）**

- Tushare按上市／退市日期筛出的沪深股票5225只、北交所349只。米筐all_instruments(CS,date=2026-10-14,enable_bjse=false)参考清单5225只，通过canonical代码及Tushare别名归一到instrument_id后，与沪深5225只集合一致，无无法解析代码。SDK该接口按日期筛选证券，其他元数据仍为当前值，不能视为全部字段的历史PIT快照。
- 本次请求100只风险数据，三天全部覆盖，缺失0。另5125只沪深股票没有请求风险五件套，风险覆盖尚未验证；不能把“未采集”写成“米筐不覆盖”。349只北交所在此标准模型支持范围外。首轮1000候选的126只行业参考缺失也不能当作风险接口缺失。未扩大成全市场风险采集。

**预测波动／历史实现波动比值偏差**

对照终点均为2026-10-16，历史窗口为2026-04-20～10-16含终日120个交易日，样本标准差ddof=1、按√252年化。因子／特异收益用已保存的米筐120日单位探针，个股总收益用Tushare close/pre_close简单收益。下面是预测风险与过去实现波动的比较，不是用未来收益衡量的事后预测误差；三天样本不能证明风险模型已校准。

| 对照 | 样本数 | 比值中位数 | 中位偏差 | 最小～最大 |
|---|---:|---:|---:|---|
| 因子波动 | 42 | 0.8847 | -11.53% | 0.6899～1.3126 |
| 特异波动 | 30 | 0.8648 | -13.52% | 0.7684～0.9854 |
| 个股总波动 | 99 | 0.9558 | -4.42% | 0.6883～2.0565 |

- 最大差异为000538.XSHE云南白药：预测32.36%，历史120日15.73%，比值2.0565；20日／60日历史波动为9.67%／12.91%。600900.XSHG长江电力比值1.6878；最低600188.XSHG兖矿能源比值0.6883。已复核raw→DB单位与数值一致，不能据此判作单位错误，也没有证据解释供应商具体估计机制；保留偏差，calibrated=false，不把输入乘一个经验系数“校正”。下游依赖指标仍须标降级。

**三天样本后提出的 R1／R2 初始阈值（后续已确认并落地，见本轮验收）**

| 门禁 | 建议 | 本次依据与限制 |
|---|---|---|
| R1 源单位复核 | 对本次年化小数口径，沿用120交易日历史检验：r_f中位数[80,800]、r_s中位数[5,50]；任何一组区间外比例>20%则阻断。首批／模型或单位变更必须复核，历史按月批次至少在一个基准日复核；历史参考不足或不完整不能默认通过。 | 42因子中位197.24、30股中位13.73，均0越界；30股覆盖27行业。参考样本须事先固定，不能根据检测结果换股。 |
| R1 每日量级兜底 | 归一化后，个股总年化波动率的截面中位数须在[5%,150%]，越界阻断；单股在[1%,300%]外告警，比例>20%阻断。预测／历史波动比值在[0.5,2]外先告警，不自动认定单位错。 | 三天中位32.22%～32.56%、个股21.12%～74.09%；云南白药2.0565触发偏差告警。此宽区间是待确认的工程兜底，不是从3天推定的普遍市场规律。 |
| R2 协方差 | 有限、相对非对称误差max(abs(C-Cᵀ))/max(abs(C))≤1e-8、对角>0、Cholesky成功且λ_min>0；失败阻断，不加对角扰动或静默改矩阵。每个run记录λ_min、λ_max和2范数条件数κ；κ>1e6告警、κ≥1e8阻断。 | 当前κ约1471～1475，正定；条件数阈值为待确认的数值稳定性上限，并非由三天样本统计拟合。 |

以上保留最初提议依据；后续用户已确认阈值、实现门禁与 ETL 追溯，并授权固定 100 股历史验证，见下文。D-022 及诊断旧代码别名解析仍不在本次范围。

- 验证：完整只读验收脚本/tmp/getrich_rq_sample_acceptance_20261022.py退出0；历史缺口／偏差复核退出0。核心数字已写本文，完整临时结果见/tmp/getrich-rq-sample-acceptance-20261022.json、行业诊断和后续核查JSON。未运行全仓测试，没有改业务代码／DDL或启动容器，未提交／推送。

<a id="rq-three-model-history-20261022"></a>

### 2026-10-22～23 三模型固定 100 股历史链路验收（数据与存储通过，未校准）

- 范围：v1／v2／v2trd、sws_2021、daily，固定原 100 股；2024-01-02～2026-10-21，每模型 676 个交易日，共 2028 个 run、五张数据表 612,456 行，2028 条 success ETL，0 条 failed。所有日期／run 唯一且覆盖沪深交易日日历；不含原先 v1 三天样本的 3 个 run／906 行。这是历史链路验证数据，不是正式全市场数据。
- 起点遵循 max(2024-01-01、名单最晚上市日后的首个交易日、该模型可用起点)。样本最晚上市为 601868.SH，2021-09-28；三模型 100 股于 2024-01-02 五件套均完整，因此实际统一从该日开始。终点按任务启动时已结束日期固定，跨午夜没有扩展。

| 模型 | 最早因子收益 | 三股边界探针五件套首个完整日 | 因子数 | 日度条件数最大值 | 个股年化波动率全段范围 |
|---|---|---|---:|---:|---|
| v1 | 2005-01-07 | 2009-04-03 | 42 | 3500.64 | 14.97%～130.10% |
| v2 | 2007-02-05 | 2011-04-28 | 48 | 4782.41 | 15.10%～128.91% |
| v2trd | 2007-02-05 | 2011-04-28 | 52 | 4975.19 | 15.00%～127.88% |

- 可用起点证据仅限本账户／行业／期限及 000001.XSHE、600000.XSHG、600519.XSHG 三只长期上市股；因子收益最早日的协方差和特异风险为空。五件套边界日检查返回有限值，不代表 100 股当时已上市或整个早年区间连续／已通过本轮门禁。
- 源单位均为 factor_return=dec_daily、specific_return=dec_daily、covariance=dec2_annual、specific_risk=dec_annual（标准差）；库内协方差和特异方差为年化 %²，因子收益为日频小数、特异收益为日频百分比。units_evidence 按模型分别为：`账户样本复核：.agents/brain/NOTES.md#rq-three-model-history-20261022；2026-10-22，MODEL+sws_2021，2026-10-16及2024-01-02的120交易日、固定30股单位检验通过；固定100股历史链路验证，非正式数据。`，MODEL 替换为 v1/v2/v2trd；该字符串已在设 selected=true 前展示。
- 月度单位复核：2024-01～2026-10 共 34×3=102 份全部通过，固定 30 股只是单位探针，正式采集始终为原 100 股。每月首交易日取截至当日完整 120 个交易日，确认日期／轴一致后检查 rf 中位 [80,800]、rs 中位 [5,50]、任一组越界不超过 20%；参考 Parquet、哈希与报告保留在各 variant 的 unit_checks/YYYY-MM。原生 CLI 不自动下载 120 日参考，本轮由月度编排执行前置，不能将裸 CLI 称为完成该预检。

| 模型 | 月度因子预测／过去波动比值中位数范围 | 特异波动比值中位数范围 | 最大因子单位比值越界比例 |
|---|---|---|---:|
| v1 | 0.811～1.595 | 0.837～1.306 | 19.05% |
| v2 | 0.818～1.501 | 0.836～1.303 | 14.58% |
| v2trd | 0.802～1.490 | 0.836～1.293 | 9.62% |

- 逐日验收：raw 哈希、解码轴、数组有限、行业哑变量行和为 1、comovement（COUNTRY 类型）恒为 1；协方差对称容差、正对角、严格正定与条件数均通过。按 PG 实际上三角镜像做 R2 和总风险计算，独立审查发现的上下三角检查不一致漏洞已修复并复核关闭。五表每个数值与归一化 raw 一致（按 REAL 精度容差）；日期、run、因子顺序／定义序号／哈希一致，全部 calibrated=false。available_at 与 model_run.estimated_at 等于实际 raw observed_at，采集发生在 2026-10-22～23，不能当作历史当时可得的数据。
- 原生每日量级／条件数门禁的 ETL warning_count 均为 0；这不包含以下离线预测比值告警，不可表述为“没有预测偏差”。ETL 保留真实开始／结束时间、单日 start/end/trading_day、model/run/observation、质量与配额摘要；失败业务日回滚后独立记 failed。

预测／过去实现波动对照采用 Tushare close/pre_close 简单收益、截至当日 120 个交易日、ddof=1、sqrt(252) 年化、不补缺口；三个模型共有 54,183 个可比股票日。这是过去窗口对照，不是未来预测准确率或校准验收。

| 模型 | 比值中位数 | 中位偏差 | 比值范围 | [0.5,2] 外股票日 |
|---|---:|---:|---|---:|
| v1 | 0.9925 | -0.75% | 0.466～3.216 | 826（1.52%） |
| v2 | 0.9934 | -0.66% | 0.473～3.253 | 778（1.44%） |
| v2trd | 0.9932 | -0.68% | 0.474～3.442 | 767（1.42%） |

- 已暂停后核查比值告警：600900.SH 在 2024-10-10 预测 57.85%／55.75%／62.30%，过去实现 18.10%；原始市场因子协方差升高是主要贡献，11 月末比值回落至约 1.33。300999.SZ 在 2025-03-20 的 v1 预测 24.42%、过去实现 52.39%，比值 0.466。2026-06-01 的 600900.SH 在 v1/v2 中预测 38.53%／38.97%、过去实现 11.98%，比值 3.216／3.253，主要贡献转为公用事业行业风险。新增近边界异常包括 601728.SH、600177.SH。raw→PG 逐值一致且月度单位通过，没有转换／存储错误证据；按已确认“比值仅告警”规则保留异常后继续，未改阈值或经验缩放。不能据此证明供应商预测正确。
- 参考缺口：全区间 100 股共有 72 个无 Tushare 日线的股票日，72 个均有当日 S 事件且停复牌采集覆盖完整，未发现没有停牌事件依据的缺口；不填零。首 119 日历史不足及含缺口的 120 日窗口不参与比值比较。此前 2026-10-14 清单对照为 Tushare 沪深 5,225 股、北交所 349 股；本轮仅请求 100 股，其余 5,125 股不能登记为米筐不覆盖。该 100 股按 2026 年选定，存在选择偏差，不能外推全市场效果。

配额证据：逐历史日保存采集前后 bytes_used／bytes_limit 及实际观测时间，完整表为 daily_quota_observations.parquet。服务端计数更新延迟，多日差值为 0，不等于零消耗；无法把账户计数精确归因到每个历史日。本次跨午夜观察到一次计数重置，跨重置窗口不参与估算。以下是排除受并行探针影响的 1 月、并剔除每批前 5 日启动窗口后的“月内平均账户增量”的分布，不是逐请求计费量。

| 模型 | 稳定窗口中位 KiB／模型日／100 股 | 月内均值 P05～P95（KiB） |
|---|---:|---|
| v1 | 26.15 | 23.77～30.18 |
| v2 | 37.27 | 31.45～43.64 |
| v2trd | 41.57 | 35.41～50.43 |

- 粗容量估算：把全体响应按 5,225/100 线性放大，三模型 676 个历史交易日约 3.54～4.19 GiB，对 1 GiB／日且预留 10% 的配额约 3.9～4.7 个满额日，向上取整约 4～5 个配额日。这是保守线性代理，不是耗时承诺：协方差／因子收益不随股票数线性增长，SDK 首次证券映射加载、分块、重试、动态历史名单、其他任务消耗及延迟计费会改变结果；正式估算仍需独立全市场样本。
- 证据持久化：各 variant 的 `$RAW_PARQUET_ROOT/ricequant/rq_risk_model/v1/<variant>/validation/20261022-history/` 保存 audit.json、逐股票日比值 Parquet、逐日配额 Parquet、异常核查、参考缺口、月度单位摘要、原 100 股名单及脱敏 configs/YYYY-MM.yaml；manifest.json 保留文件 SHA256 和本轮实现文件哈希。配置仅保存环境变量名，不含密钥或机器路径；加载后已断言 variant 身份相同。根 config.yaml 保留原 v1 三天样本，不是三模型调度入口。

| 模型 | 本轮 variant_id |
|---|---|
| v1 | `1ca8691394e9926c1926ae3a05b6d411c0bc63e809c5d73bd5fa6cda26b3ab56` |
| v2 | `9157b952b11b53fba6f3bf54f4bc4daa9af952fefdabe07f5f253c3a4cef4290` |
| v2trd | `17b6adc528b4a896a6156671ebc657c4a296072d11052d537208e881c27fa5ae` |

- 验证命令：`UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen pytest packages/gr-data/tests/ricequant -q --no-cov`：241 passed（含一次性 PG）；相关文件 Ruff／格式／git diff --check 通过。一次性容器与卷已清理，无 DDL 改动、commit 或 push。真实 ingest 逐模型逐月使用 `uv run --frozen gr-data --config <batch.yaml> ingest ricequant --only rq_risk_model --months YYYY-MM`，所有批次退出 0；raw 由同一配置调用原生 run_risk_raw(init)，断言 100 股及交易日完整。
- 排障记录：临时核对脚本曾误用 ETL 主键和复用日历变量，修正后只读重查通过，未重抓或重导已成功批次。首次整区间执行曾因自动审批误认为仅授权 1 月及 30 股而被拒，未执行；明确 100 股采集／30 股单位探针用途及完整用户授权后续跑获准，目前没有该审批阻塞。
- 2026-10-23 用户已认可[全市场动态名单与逐股覆盖设计](../../docs/plans/ricequant-historical-universe.md)方向。本版补充：下限 2024-01-01，更早需先列 Tushare 补齐范围；正式读取仅走 D-022 钉住的 run，发布排除验证用途且禁止 latest 回退；诊断按 D-017 保留缺覆盖持仓及权重，相关指标不可用、不估算；三模型配额粗估 4～5 日并列明依据。本轮仅修订文档，DDL／代码等用户复核确认后再做；正式覆盖阈值等独立全市场样本后再定。固定 100 股验证已完成，不重复采集。D-022 及校准仍未完成，不能放行正式全市场读取。

<a id="rq-boundaries-20261023"></a>

### 2026-10-23 换码／摘牌边界修复与新 variant 全市场样本（完成，验证用途）

- D-012 已记录触发原因：动态历史名单必须按交易日选当时有效代码。最小规则 `cn_stock_code_intervals_v1` 仅含 300114.SZ → 302132.SZ；[公司公告](https://static.cninfo.com.cn/finalpage/2025-02-15/1222544408.PDF) 确认 2025-02-17 开市生效。上市区间、代码区间、停牌分别处理，同一证券身份不拆分，不覆盖北交所，不建设通用公告核定系统。
- 先执行 `uv run --frozen gr-data raw tushare --only instruments --mode update`，再 `uv run --frozen gr-data ingest tushare --only instruments,symbol_map`，均退出 0（12:05～12:06）。Tushare 已自行补齐 000016.SZ 的 delist_date=2026-10-23，未做人工数据覆盖。其最后行情日是 2026-09-03，9 月 4 日至 10 月 22 日有 29 个 S 事件；10 月 21、22 日在市且停牌，23 日摘牌排除。
- 统一上市区间为 `list_date <= day < delist_date`。真实核验范围是 2024-01-01～2026-10-23 摘牌的沪深 A 股 103 只：两源退市日期 103/103 一致；100 只在库内有行情，摘牌当日／之后行情均为 0。002898、000004、002808 等最后行情紧邻摘牌，000016、601059、601198 等存在停牌间隔，因此退市日不能代替最后行情日。000046、002776、600290 在本库 2024 年后无行情，不作为行情边界正证据。已退市而缺结束日仍降级，不以当前 active 状态过滤历史；普通未退市证券空结束日开放。当前人工核定例外清单：**0 条**。未来仅对有公告依据的源冲突逐条登记，超过 5 条停止确认。
- 边界小探针：三模型分别请求 2025-02-14 的 300114.XSHE、2025-02-17 的 302132.XSHE、2026-10-21／22 的 000016.XSHE，共 12 个股票日模型组合，五件套全部完整，数值门禁通过。摘牌日 2026-10-23 由新规则和参考日期验证排除，不发送个股请求，也不采未结束交易日。探针账户计数窗口增加 3,351,938 字节，不能视为逐请求精确计费。
- 新策略 `listed_cn_a_v2 / alias_v2`，规则正文冻结在 raw，版本／哈希纳入新 variant，逐股只给受影响证券存换码证据；共用规则摘要进 run／ETL。旧 `listed_cn_a_v1`、旧 raw、旧降级 run 原样保留，三个旧 raw 只读重放／PG 逐值验收通过。048 磁盘及工作库 checksum 仍为 `0488aa6eac51`，9 张 factor 表归属未变。
- 全仓测试和独立代码审查通过后，重采并用 `ingest ricequant --only rq_risk_model --months 2026-10` 导入三个新 variant 的 **2026-10-21 单日全市场**；每个模型 20,898 行（含覆盖表），各 1 条 success ETL、0 failed、0 warning。用途仍是 validation、calibrated=false；新 variant 已登记在[设计文档验证表](../../docs/plans/ricequant-historical-universe.md)。旧样本每模型 2 个 unknown、99.9617% 完整率及原流量结论继续保留，未追溯修改。

| 模型 | 候选 / 完整 | 未返回 / 边界未知 / 异常 | 协方差条件数 | 年化波动率中位 | 预测／过去波动比值（偏差） | 五件套请求窗口账户增量（字节） |
|---|---:|---:|---:|---:|---|---:|
| v1 | 5,224 / 5,224 | 0 / 0 / 0 | 1340.37 | 43.93% | 0.8914（-10.86%） | 1,176,525 |
| v2 | 5,224 / 5,224 | 0 / 0 / 0 | 2075.32 | 43.52% | 0.8816（-11.84%） | 1,511,307 |
| v2trd | 5,224 / 5,224 | 0 / 0 / 0 | 2042.04 | 43.41% | 0.8798（-12.02%） | 1,734,370 |

- 完整验收：raw 哈希／规则与名单重构、五表逐值及单位转换、日期／run／因子顺序、数组有限、行业哑变量行和 1、COUNTRY 恒 1、协方差对称／正定／条件数、ETL 追溯全部通过。因子数 42／48／52。available_at 与 run.estimated_at 都等于真实 observed_at（北京时间 2026-10-23 12:17:07.816868／12:18:15.459656／12:19:21.466459），不能当作 2026-10-21 当时已可得。
- Tushare 对照：当日沪深 A 股有行情 5,216，只数全部被覆盖；另 8 只候选无行情，全部有当日 S 停牌事件且风险五件套完整，包括 000016。352 只北交所行情属范围外，不记米筐缺失。
- 波动对照仍是截至 10 月 21 日的过去 120 个交易日，至少 100 个有效简单收益，ddof=1、sqrt(252)，不是未来预测验收。每模型可比 5,186 只，38 只历史不足；[0.5,2] 外 8 只，均为已核查的上市首日收益影响。敏感性分析去掉 40 条上市首日收益后仍有 5,186 对，越界为 0；未修改原数据、主比较结果或门禁阈值。
- 存储：新三模型各 5,224 条覆盖，pg_column_size(evidence) 平均 **350.11 字节**、最大 915；整行平均 536.11、最大 1,120。新旧六个单日 run 合计 31,344 行，覆盖表总大小 **19,472,384 字节（18.57 MiB，含索引／TOAST）**。规则共用信息未逐股复制。
- 流量：三模型五件套请求窗口合计 **4,422,202 字节（4.22 MiB）**；三次参考加载各 2,616,608 字节；含初始化及延迟计数的整个采样账户窗口 **12,416,587 字节（11.84 MiB）**。它是实测账户增量，不是精确逐请求费用。按同规模 676 天估算风险请求约 2.78 GiB、预留 10% 的 1 GiB/日配额向上约 4 个配额日；不能包含任意重复参考加载、并行任务、失败重试或承诺历史全市场规模相同。旧样本的流量结论没有废弃。
- 证据已保存至各新 variant 的 `validation/20261023-boundary-upgrade/`：配置（无凭据／机器路径）、reference-universe、capture-report、boundary-probe、tushare-delist-study、old-replay-audit、final-audit、final-operational-checks、tushare-coverage-comparison。临时执行脚本位于 `/tmp/getrich-rq-boundaries-20261023/`，不作为永久依赖。
- 验证命令：隔离一次性 PG 上 `uv run --frozen pytest --cov --cov-report=term-missing --cov-report=xml:/tmp/getrich-rq-boundaries-20261023/coverage.xml --cov-fail-under=75`：**3,082 passed、22 skipped、8 已有 xfailed，85.59%**；全仓 Ruff、format --check、迁移 lint（49 PG／1 CH）、uv lock --check、git diff --check 通过。独立只读审查通过；一次性容器和卷已清理。未提交或推送。仍不全量回补、不设正式覆盖阈值、不开放正式风险读取；D-022／B1／B2 为第二阶段。

<a id="rq-receipts-2a-20261023"></a>

### 2026-10-23 风险收据 2a（已批准，先提交再迁移）

- 用户已批准范围：variant 用途、风险五件套与覆盖表单一逻辑收据目标 `factor.risk_bundle`、model_run_binding、capture／DB 双水位。验证用途不原地转正；production 只允许 listed_cn_a_v2。前序全市场三个新样本 5,224/5,224 完整、旧降级 run 和 raw 保持不变。
- 049 草稿 `packages/gr-db/src/gr_db/ddl/postgres/049_risk_import_receipts.sql` 的 SHA256 为 `04fc73b0d1a26add572c0ab827f875ce0be52352c9f153a422216df224da6caf`。新增 ops.dataset_variant、ops.import_receipt、factor.model_run_binding；扩展 ops.import_checkpoint。用途／证据不可 UPDATE/DELETE，绑定必须与 run 的来源、模型、行业、variant、观察、日期、用途一致；receipt 与 run 一对一；未绑定的旧 RiceQuant 观察也不能改用途或删除后换标签。旧检查点兼容，旧 048 checksum 仍 `0488aa6eac51`，未执行工作库迁移。
- 原生生产 raw 在 SDK 初始化前检查 049 记账并登记用途；原子落地后独立提交 capture。回调 PG 失败保留已完成 raw／journal，恢复只重建检查点；已完成轮次再次 init 可查询日历，但不重复风险请求或参考名单。动态 v2 ingest 强制使用收据，fixed v1 保持原兼容行为并禁止 production。
- 检查点粒度为 variant/day/observation：captured_at 保留 raw observed_at；DB 水位只在整包事务成功后一次绑定收据，不用 MAX 日期冒充连续完成。业务五件套、覆盖、收据、绑定、DB 检查点和 success ETL 同事务提交；失败 capture 保留。已有收据必须连同 binding／checkpoint 核实后才跳过业务 UPSERT，重放行数为 0，ETL 标 replay。
- production 发布资格：candidate>0，complete×1000≥candidate×999，身份／上市边界未知为0；数值合法但资格不足的整包可入库留证，标 publication_eligible=false 后停止批次。CLI 退出4明确数据已提交但不可发布，不追加普通 failed；提交响应异常退出5，区分收据已确认提交／commit_outcome_unknown。SQLSTATE 23类、40001、40P01视为确定拒绝，40003、57P01等不误称已回滚。未知提交按同 raw 收据恢复，不重抓。数值非法／身份冲突仍执行原硬门禁。
- 2a importer_version 使用最近影响 gr-data 源码或 gr-db DDL 的完整 Git 提交号，文档提交不改变版本；生产拒绝相关源码未提交修改，Git 不可用或同进程源码提交变化均拒绝；同 raw 换 importer 版本在业务写入前明确拒绝，旧成果不变。新的导入算法重处理身份另行设计。本轮不是全供应商 B1、B2 权威顺序或 B3 full 原子代际发布完成。
- 用户一期范围调整已记 D-022：只诊断最新日，暂不建可变数据版本表；2b 清单逐项钉住组成收据，组成变化使旧版本已修订／不可复算，需新发布，不回退当前最新。诊断专用 DB 角色延后，但2b数据库约束／触发器必须拒绝发布明细引用 validation run，并保留直接 SQL 绕过应用被拒绝的反例。历史已计算报告仅保留产物，不承诺可复算。
- 隔离验证：一次性 TimescaleDB/PG18 上全套50迁移成功，049重放／记账／直接SQL约束54项通过；用途伪造、NULL绕过、绑定复用、旧观察改标签、检查点倒退、事务回滚、legacy兼容均覆盖。全仓命令 `GETRICH_TEST_PG=1 ... uv run --frozen pytest --cov --cov-report=term-missing --cov-report=xml:/tmp/getrich-rq-2a-20261023/coverage.xml --cov-fail-under=75`：**3,165 passed、22 skipped、8已有xfailed、85.60%**。最后40003白名单修正后定向 `pytest packages/gr-data/tests/ricequant/test_risk_ingest.py packages/gr-data/tests/ingest/test_import_gates.py -q --no-cov`：**109 passed**（含一次性PG）。独立审查发现的假failed审计、收据复用、旧用途改写及40003误判均已关闭。
- 全仓 Ruff／format、迁移lint（50 PG／1 CH）、049专项注释检查、uv lock --check、git diff --check通过。测试日志在 `/tmp/getrich-rq-2a-20261023/`；没有连接工作库运行测试，没有真实供应商采集、提交或推送。工作库仅只读核对交易日历，沪深首20日一致：2024-01-02～2024-01-29。
- 用户已批准049；全部改动提交后先工作库 migrate --target pg --dry-run 确认仅049，再执行并核对checksum。2a工作库验证完成后启动三个新production variant 的首20个交易日，逐批报告覆盖／配额／告警；达标再继续，出现质量问题先检查。2b完成并发布前正式读取仍关闭。

## 文档维护

- `AGENTS.md`：执行规则；本文：当前状态；`DECISIONS.md`：仍有效的取舍与防错理由。
- `docs/guides/`：怎么用；`docs/plans/`：未决问题与验收条件；`docs/history/`：已完成材料。
- 2026-09-18 按用户授权将 50 条决策精简合并为 18 条并连续重编号；仅保留业务口径、数据可信度与架构取舍。同步现行引用；040 迁移中的旧编号通过文档映射解释，不改 SQL checksum。

- 2026-10-23 第0步提交：`91d9042`（048／049 DDL）、`aa54d80`（第一阶段＋2a源码及测试），随后提交相关文档；未推送。生产 importer_version 已实测为 `aa54d8063b2d933b35742339a2e8ed408a0b5745`。新增版本专项15项通过，连ingest回归95 passed／3 PG skipped；独立增量复核通过。该次记录时049工作库迁移与production采集尚未开始。


<a id="rq-production-first20-20261023"></a>

### 2026-10-23 production 首 20 个交易日验收（已完成，未发布）

- 第0步已按用户要求先提交：`91d9042`（048／049 DDL）、`aa54d80`（第一阶段／2a源码及测试）、`00ba7ba`（相关文档）；全部在 dev，未推送。运行前工作区干净。所有新收据 `importer_version=aa54d8063b2d933b35742339a2e8ed408a0b5745`；文档提交不改变源码版本。
- 工作库执行 `UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen gr-db migrate --target pg --dry-run`，计划仅 `049_risk_import_receipts.sql`；去掉 `--dry-run` 后应用1项、退出0。记账 checksum `04fc73b0d1a26add572c0ab827f875ce0be52352c9f153a422216df224da6caf`，048仍为 `0488aa6eac51…`。没有新增发布表或正式读取入口。
- 执行范围：v1／v2／v2trd，sws_2021，daily，production + listed_cn_a_v2；2024-01-02～01-29 沪深共同20个交易日。不是原100股验证variant改标签。源单位和已确认units_evidence未改变。
- 每批原生命令：`RICEQUANT_ENABLED=true UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen python -m gr_data.cli --config <单日模型配置> raw ricequant --only rq_risk_model --mode init`；随后同配置 `ingest ricequant --only rq_risk_model --months 2024-01`。每批完成后独立只读审计；60批 raw／ingest／audit 最终均退出0。
- 核验结果：60个run、60份receipt、60个binding和60条双水位一一对应，无缺批／重复；ETL 60条success、0条failed，累计写入计数1,224,027行（五件套＋覆盖，不是股票数）。覆盖305,997股日记录：305,970 included、27 partial_bundle；未知身份／边界和其他状态均0。10张factor表归属均ricequant/ingest。
- 每批均验证：raw→PG逐值（REAL按float32精度）一致；日期／run／因子顺序一致；行业行和1、COUNTRY=1、数组有限；协方差对称／正对角／Cholesky正定／条件数；R1量级；源单位与依据、收据manifest哈希、ETL关联、双水位一致。60批 `calibrated=false`；available_at/estimated_at/captured_at均为2026-10-23实际观测时刻，不能把回填视为2024年当时可得。
- 本轮没有重做120交易日预测／实际波动比较：行情从2024年起，当前20日不够前置窗口；该项沿用先前已确认的单位探针依据，不据此宣称校准完成。

| 模型 | production variant | 各日年化波动率中位数范围 | 协方差条件数范围 |
|---|---|---:|---:|
| v1 | `402d1294e4237eaf3d769ad3102af3d5c0ef835aff14a0cad802918dc8746c89` | 30.79%～50.72% | 1135.0～2438.0 |
| v2 | `4fb69a71608f749953d1dcc5563cf36e60f67888742a1d7db3d2fc68a15a3666` | 30.61%～49.29% | 2117.5～2944.2 |
| v2trd | `28478c1c79b0a124273820b35a54309e27ebda511e8ddf3ded3126db20a3327e` | 30.74%～49.44% | 2099.1～2914.1 |

逐日结果如下。三个模型的覆盖计数相同；“每模型告警”按覆盖告警类别计数，不是缺失股票数。共7个有缺口交易日×3模型＝21条ETL告警，R1／R2数值告警为0。

| 交易日 | 每模型完整／候选 | 完整率 | 每模型告警 | 上市首日缺特异收益股票 |
|---|---:|---:|---:|---|
| 2024-01-02 | 5,096／5,096 | 100.0000% | 0 | — |
| 2024-01-03 | 5,096／5,097 | 99.9804% | 1 | 688717.SH |
| 2024-01-04 | 5,097／5,097 | 100.0000% | 0 | — |
| 2024-01-05 | 5,097／5,097 | 100.0000% | 0 | — |
| 2024-01-08 | 5,097／5,097 | 100.0000% | 0 | — |
| 2024-01-09 | 5,097／5,097 | 100.0000% | 0 | — |
| 2024-01-10 | 5,097／5,098 | 99.9804% | 1 | 603325.SH |
| 2024-01-11 | 5,098／5,100 | 99.9608% | 1 | 603312.SH, 001387.SZ |
| 2024-01-12 | 5,100／5,100 | 100.0000% | 0 | — |
| 2024-01-15 | 5,100／5,100 | 100.0000% | 0 | — |
| 2024-01-16 | 5,099／5,100 | 99.9804% | 1 | 301567.SZ |
| 2024-01-17 | 5,100／5,100 | 100.0000% | 0 | — |
| 2024-01-18 | 5,100／5,101 | 99.9804% | 1 | 601033.SH |
| 2024-01-19 | 5,101／5,102 | 99.9804% | 1 | 001379.SZ |
| 2024-01-22 | 5,102／5,102 | 100.0000% | 0 | — |
| 2024-01-23 | 5,102／5,102 | 100.0000% | 0 | — |
| 2024-01-24 | 5,102／5,104 | 99.9608% | 1 | 603375.SH, 301577.SZ |
| 2024-01-25 | 5,103／5,103 | 100.0000% | 0 | — |
| 2024-01-26 | 5,103／5,103 | 100.0000% | 0 | — |
| 2024-01-29 | 5,103／5,103 | 100.0000% | 0 | — |

- 首个告警（688717.SH）出现后暂停检查：Tushare／米筐上市日均2024-01-03；三模型单股探针该日specific_return均None，2024-01-04均有值，载荷／特异风险存在。确认供应商上市首日覆盖缺口，未改名单、未填补、未降门禁；随后逐批对照双方上市日及缺失pieces，只接受同一已核实类别，不同类型立即停。最终27条缺口都已只读验证下一交易日included。缺失持仓仍按D-017不可用，不能因总体>=99.9%就视为组合100%。
- 批次控制修正记录：首版临时driver仅检查非零退出，软覆盖告警后多跑了1月3日后续模型，并开始1月4日v1；定位后中断，1月4日仅留未发布pending，续跑生成新观察，旧pending保留。修正临时driver后，未核实覆盖类型／数值告警立即停止。另一次1月11日暂停来自临时脚本误把ETL告警类别数与缺失股数比较，核对writer按类别计数后修正续跑；不是数据错误。未修改已提交源码或既有raw/run。
- 流量：任务开始账户bytes_used=86,129,264；2026-10-23T07:13:52.751787+00:00（UTC）复查=341,476,606，窗口增量 **255,347,342 bytes（243.52 MiB）**；账户总使用 **325.66 MiB / 1024 MiB**。API计数集中延迟刷新，很多批次before/after相等，因此无法可靠给出各模型／各日独立扣费；0差值不等于0流量。窗口增量含参考名单、暂停中断的请求及小探针，且最后若干请求可能尚未到账，不能当精确最终账单；逐批原始计数保存在本次运行证据。
- 覆盖存储：本次新增行evidence平均 **350.35 bytes**。整个factor.model_run_coverage（含旧验证run）总大小 **216,784,896 bytes（206.74 MiB）**，其中表／TOAST 176.05 MiB、索引 30.69 MiB；不是仅本次新增占用。
- 运行证据：`/tmp/getrich-rq-production-20261023/` 内batches.json、final_check.json、688717-probe.json及逐日逐模型audit JSON／日志；配置不含凭证。最终整体检查 `UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen python /tmp/getrich-rq-production-20261023/final_check.py` 通过，追加27条次日恢复核对通过。增量版本测试95 passed／3 PG skipped、Ruff和独立复核通过；此前完整隔离测试3165 passed／22 skipped／8既有xfailed／85.60%见2a记录，本轮未重复跑无关全仓测试。
- 下一步：本次20日达标，停止在2024-01-29；后续历史批次另行安排。2b发布清单／发布程序／统一读取须单独评审DDL，完成并发布前正式风险读取保持关闭。production用途不等于发布资格已完成，更不等于已发布。


<a id="rq-production-capacity-20261023"></a>

### 2026-10-23 全区间容量与月度续跑准备（保留格式及单账号已确认）

- 用户确认首20日达标，并授权后续范围2024-01-30～2026-10-21，三production模型按月回补；终点不得滚动延长，正式风险读取保持关闭，不推送。继续前先决定存储格式。已向用户提出“保留现格式、六表预留20 GiB”的建议与确认问题，未启动后续采集，未改生产源码／DDL／数据。
- 测量仅筛选ops.dataset_variant.purpose=production且有model_run_binding的60个run，完全排除validation。将六表production行复制到一次性PG18同列同索引普通堆表（索引先建，再按日COPY），测量pg_table_size／pg_indexes_size／pg_total_relation_size。源工作库仅只读；一次性getrich-rq-capacity-20261023容器及专用named volume已清理。
- 全区间2024-01-02～2026-10-21，沪市日历676个交易日，Tushare沪深A股按list_date<=day<delist_date计3,481,291股日；3模型预计10,443,873条覆盖行。个股三表同样按全部候选外推，未扣首日缺失，略保守；协方差及因子收益各2,028行。

| 表 | 数据／TOAST GiB | 索引 GiB | 合计 GiB |
|---|---:|---:|---:|
| factor.model_run_coverage | 5.336 | 0.979 | 6.314 |
| factor.exposure | 2.905 | 1.173 | 4.078 |
| factor.covariance | 0.022 | 0.001 | 0.023 |
| factor.specific_risk | 0.995 | 1.184 | 2.179 |
| factor.factor_return | 0.002 | 0.001 | 0.003 |
| factor.specific_return | 0.755 | 1.184 | 1.939 |

- 总计14.54 GiB，其中覆盖表6.31 GiB、五件套合计8.22 GiB；这是全量最终总量，不是额外增量。建议这六表预留20 GiB，raw／WAL／备份／其他meta与ops表另计。估算假设每模型日只有一次正式观察、沿用当前列及因子维度、样本行宽可代表历史；年分块额外页、后续索引碎片和行宽变化用余量覆盖，不是精确容量承诺。
- 生产coverage evidence平均350.35字节，按全量约3.41 GiB逻辑体积；潜在瘦身存在，但不能把这全部视为可无损节省。当前总量可控，保留格式可避免改写首20日／新variant／收据版本迁移及重复验收，生产全程一致。测量证据`/tmp/getrich-rq-capacity-20261023/measurement.json`及脚本；临时堆表只用于测量，不是迁移目标。
- 双账号：用户称总计每天2GB；有效环境目前仅RICEQUANT_API_KEY已配置，未发现第二个米筐命名凭据。已询问第二变量名或是否先用现账号，不接受聊天密钥。license_env不属于variant身份，可分进程选择凭据；rqdatac登录态是进程全局，不能同进程切换两账号并共用quota客户端。
- 断点：完整raw／capture／receipt可复用；日中配额失败保留_failed证据，下次新observation整天重抓该模型日，不能承诺按chunk续传。raw退出2并非仅配额不足，必须核实BudgetDeferredError或账户配额证据，不能把配置／权限错误当配额轮换。续跑用init，不用update重复生成已完成日观察。
- 后续需将运行脚本升级为月度计划、单日执行／验收、持久化尝试账本和跨月IPO恢复待查列表。当前首20日临时driver硬编码日期／月份、退出4即停且审计强制publication_eligible=true，不可直接扩日期使用。原生writer无需放宽发布阈值：退出4已经原子提交收据／绑定／水位，只在原因唯一为覆盖率且所有缺口均符合已核实IPO模式时独立核验后从次日继续，保留publication_eligible=false。
- 已知IPO模式：上市首日仅specific_return缺失，exposure／specific_risk完整，双方上市证据一致，无身份／上市边界未知或数值告警；必须在下一交易日同模型同instrument_id恢复included。月末待复核带入下月，终点当日未复核项不能算已确认恢复，不能为此延长终点。每月列明IPO缺口数量、<99.9%的日期和覆盖率，发布口径由用户决定；其余新缺失／异常立即停查。
- 专项日期：2025-02-14请求300114.XSHE、2025-02-17请求302132.XSHE，核对同canonical身份与覆盖；2026-10-21前核查000016的在市区间及停牌事件。首20日仍保持已完成状态；下一步待格式决定后实施执行脚本，再按配置账号启动2024-01剩余日期。

- 后续确认：用户选择保留现有格式并继续，先用RICEQUANT_API_KEY，配额不足后次日续跑。运行目录固定为 `/Volumes/myssd/project/getrich-runs/ricequant-20240130-20261021/`，配置无凭据，沿用原三production variant及已提交importer版本；工作库容器只读df显示可用约326 GiB。月度运行脚本／审计在仓库外验证，生产源码及DDL不变，未提交／推送。

### 月度续跑进度（2026-10-23）

用户已确认保留现有格式，先使用现有账号；固定回补终点 2026-10-21，不推送。仓库外执行目录 `/Volumes/myssd/project/getrich-runs/ricequant-20240130-20261021/` 保存 `run_monthly.py`、审计脚本、固定日历、模板、逐次尝试账本与月报。导入版本仍为 `aa54d8063b2d933b35742339a2e8ed408a0b5745`，三个 production variant 未变化。

- 2024-01：新增 01-30、01-31 共 6 模型日全部成功；连同已验收基线共 66 模型日。全月最低完整率 99.9608%，低于 99.9% 的日期为 0；30 条已知 IPO 首日缺口涉及 10 只股票，全部在下一交易日恢复，无待核实项。新增批次收据、run binding、采集和导入双水位逐一通过；无新类型缺失或数值告警。月报 `reports/2024-01.json` / `.md`。本次流量计数前后均为 341,476,606 bytes，存在更新延迟，零差值不能解释为零消耗。
- 2024-02（2026-10-23 17:20 复核）：15 交易日 × 3 模型共 45 批全部完成，45 份收据／绑定／双水位审计 passed，失败尝试为 0。最低完整率 99.9608%，低于 99.9% 的日期为 0；15 条 IPO 首日缺口涉及 5 只股票、4 个日期，下一交易日全部恢复，无待核实项或新类型异常。账户计数观测增量 123,436,120 bytes（约 117.72 MiB），有延迟，不等于最终计费流量。详见运行目录 `reports/2024-02.json`。
- 2024-03：2 月通过且锁空闲后，已用 `run_monthly_accounts.py --account-env RICEQUANT_API_KEY --through-month 2024-03` 启动；固定终点与质量规则不变，最终状态以账本和月报为准。
- 非配额异常锁定为 `needs_attention`，只能核查后显式恢复；配额为 `budget_deferred`，同日不重试、次日可续。跨月 IPO 缺口持续跟踪，终点未恢复时停下，不扩展日期。
- 用户已明确批准每小时后台跟进，自动化 `automation` 已创建并启用。只在新月份完成、配额／质量阻塞或全部完成时通知。最新指令：额度耗尽后等待用户配置第二账号，再显式切换，不自动次日重试。显式账号切换入口 `run_monthly_accounts.py --account-env NAME` 已通过 22 项 mock 和独立审查并部署，与旧入口共用锁／账本；当前 2 月运行结束后再使用新版。流量按账号变量名与上海日期分组，密钥只在内存和 raw 子进程环境中；未提供第二账号变量名。正式风险读取仍关闭。

### 单账号续跑更新（2026-10-23）

最新用户指令取代先前第二账号／次日续跑约定：只有一个账号，仅使用 RICEQUANT_API_KEY；每日 3G 尚待申请，不假定已生效。额度耗尽就停止并通知，等待用户明确恢复，不自动次日续跑、不切换账号。后台每小时跟进规则已同步更新。

2024-03 的 21 个交易日 × 3 模型共 63 批已完成，63 份收据／绑定／双水位审计通过、失败尝试 0；最低完整率 99.9609%，低于 99.9% 的日期为 0。21 条 IPO 首日缺口涉及 7 只股票，下一交易日全部恢复，无待核实或新类型异常。账户流量观测增量 82,087,449 bytes（约 78.28 MiB），计数有延迟，不能视为最终计费值。

3 月月报通过且执行锁空闲后，已启动 2024-04（原账号、新版入口）。结果以执行目录 ledger.json 与 reports 为准。正式风险读取仍关闭，固定终点 2026-10-21，未提交／推送。

2026-10-23 19:24 后台复核：2024-04 共 60/60 模型日完成，60 份收据／绑定／双水位审计通过，失败尝试 0；最低完整率 99.9804%，低于 99.9% 的日期为 0。12 条 IPO 首日缺口涉及 4 只股票，均在下一交易日恢复，待核实项为 0，无新类型异常。流量观测增量 197,569,860 bytes（188.42 MiB），计数存在延迟。账户在当月执行期间实际返回的 bytes_limit 从 1,073,741,824 升至 3,221,225,472，末次观测 bytes_used=1,008,141,981；这是 SDK 实测变化，不是假定升级完成。执行器未触发 budget_deferred。已启动 2024-05，仍仅原账号、额度触发即停且不自动次日恢复。详见 reports/2024-04.json。正式读取关闭，固定终点未变，未提交推送。

2026-10-23 20:20 后台复核：2024-05 共 60/60 模型日完成，60 份收据／绑定／双水位审计通过，失败尝试 0；最低完整率 99.9804%，低于 99.9% 的日期为 0。6 条 IPO 首日缺口涉及 2 只股票，下一交易日全部恢复，无待核实或新类型异常。流量观测增量 180,896,299 bytes（172.52 MiB），计数存在延迟；末次账户用量 1,238,431,209 / 3,221,225,472 bytes。已用原账号启动 2024-06，固定终点和额度／质量停机规则不变。详见 reports/2024-05.json。

2026-10-23 21:28 后台复核：2024-06 共 57/57 模型日完成，57 份收据／绑定／双水位审计通过，失败尝试 0；最低完整率 99.9609%，低于 99.9% 的日期为 0。18 条 IPO 首日缺口涉及 6 只股票，下一交易日全部恢复，无待核实或新类型异常。流量观测增量 152,127,373 bytes（145.08 MiB），计数存在延迟；末次账户用量 1,456,632,839 / 3,221,225,472 bytes。已用原账号启动 2024-07；固定终点、额度及质量停机规则不变，正式风险读取仍关闭，未提交推送。详见 reports/2024-06.json。

2026-10-23 22:30 后台复核：2024-07 共 69/69 模型日已完成导入，69 份收据／绑定／双水位审计通过，失败尝试 0；最低完整率 99.9804%，低于 99.9% 的日期为 0。18 条 IPO 首日缺口涉及 6 只股票，其中 603391.SH 于 07-31 首日缺特异收益，三个模型待 08-01 恢复检查；其余已恢复。因此月报 validation_complete=false，不能称整月恢复验收完成。该项符合已授权跨月跟踪规则，已启动 2024-08，先检查该证券同 instrument_id=29352 的三个模型恢复。流量观测增量 250,967,093 bytes（239.34 MiB），计数有延迟；末次用量 1,790,219,005 / 3,221,225,472 bytes。无其他新类型异常，固定终点与额度停机规则不变，正式读取关闭。详见 reports/2024-07.json。

### 当前停机：数据库连接被终止（2026-10-23）

用户要求核实 603391.SH：8 月 1 日 v1/v2/v2trd 已全部恢复，账本三条恢复记录 confirmed，工作库只读查询同 instrument_id=29352 的三个 run 覆盖均为 included，收据审计 passed；7 月报告 validation_complete 已为 true。

8 月完成 5/66 批后，在 2024-08-02 v2trd 的 raw 阶段停止，ledger.status=needs_attention，reason=raw_failed_unclassified。日志明确为 psycopg.errors.AdminShutdown（terminating connection due to administrator command），并非额度或已确认数值问题。失败前 raw 已发布 observation=d19bc87e4dcc464192b8fb0d45ed7eb0，候选/完整均为5108；随后 record_capture 开启事务时连接被终止，因此未进入 ingest。只读复核数据库现可连接，pg_postmaster_start_time=2026-10-23 22:34:29+08:00，失败观察在 ops.import_checkpoint 中无记录。账号当时用量1,823,409,279/3,221,225,472 bytes，未触发额度停机。原始观察日志及失败尝试保留，未重试／改账本／重启服务。

按用户“新问题先停”要求保持停机，等待恢复决定。恢复时应先核实已发布 raw 完整性，用原生 init 重放补采集检查点，再导入审计；不可删 raw 重抓或跳过检查。301608.SZ 的 08-01 IPO 缺口仍有 v2trd 待 08-02 恢复验证，v1/v2已完成，不误报该待查为新类型质量异常。后台须继续尊重 needs_attention，不能自动 --resume-after-review。

### 停机已复核恢复（2026-10-23 23:21）

用户明确要求继续。持锁只读确认原始 observation=d19bc87e4dcc464192b8fb0d45ed7eb0 可完整读取，5108/5108 included，导入版本仍为 aa54d8063b2d933b35742339a2e8ed408a0b5745；数据库连接正常、重启时间仍为22:34:29。以显式 --resume-after-review 记录此次授权与核查依据，原生 init 重放成功，8月2日 v2trd 已完成补登记／入库及审计，observation_id 未变、收据审计 passed，IPO待查已恢复。未删raw、未修改质量门禁，原失败尝试保留。8月余下日期继续执行；后续按月推进，新的异常仍停查，额度触发仍停止等待明确恢复。未推送，正式读取关闭。

2026-10-24 00:29 后台复核：2024-08 共 66/66 模型日完成，66 份收据／绑定／双水位审计通过；最低完整率 99.9804%，低于 99.9% 的日期为 0。21 条 IPO 首日缺口涉及 7 只股票，下一交易日全部恢复，无待查项。保留一次已核查并经用户批准恢复的 AdminShutdown 失败尝试，后续无新异常；旧 last_stop 留作证据，当前状态为 through_month_completed。流量观测增量 247,050,295 bytes（235.61 MiB），计数有延迟。额度从未触发 budget_deferred，因此本次正常跨日继续月度计划，不属于额度停机后的擅自恢复。已用原账号启动 2024-09，仍遵守额度／新质量异常停机，正式读取关闭，固定终点未变。详见 reports/2024-08.json。

2026-10-24 01:26 后台复核：2024-09 共 57/57 模型日已导入，57 份收据／绑定／双水位审计通过，无失败尝试；最低完整率 99.9608%，低于 99.9% 的日期为 0。24 条 IPO 首日缺口涉及 8 只股票，其中 301618.SZ（instrument_id=30655）9月30日首日缺口三个模型待10月8日验证，其余已恢复；因此整月 validation_complete=false，按已授权跨月跟踪继续。流量观测增量 213,871,025 bytes（203.96 MiB），计数有延迟；未触发额度停机。已用原账号启动2024-10，先核对该证券三个模型恢复。正式读取关闭，固定终点不变。详见 reports/2024-09.json。

2026-10-24 02:28 后台复核：301618.SZ 的9月末缺口已在10月8日三个模型恢复，9月 validation_complete=true。2024-10 共54/54模型日已导入，54份收据／绑定／双水位审计通过，失败尝试0；最低完整率99.9608%，低于99.9%的日期为0。24条IPO首日缺口涉及8只股票，其中301628.SZ（instrument_id=30652）10月31日三个模型待11月1日恢复，其余已恢复；10月 validation_complete=false，按既定跨月跟踪继续。流量观测增量201,557,317 bytes（192.22 MiB），计数有延迟，无新类型异常或配额停机。已启动2024-11，先验证该证券恢复。正式读取关闭、固定终点不变，未提交推送。详见 reports/2024-10.json。

2026-10-24 03:34 后台复核：301628.SZ 的10月末缺口已在11月1日三个模型恢复，10月 validation_complete=true。2024-11 共63/63模型日已导入，63份收据／绑定／双水位审计通过，失败尝试0；最低完整率99.9609%，低于99.9%的日期为0。18条IPO首日缺口涉及6只股票，其中688449.SH（instrument_id=28578）11月29日三个模型待12月2日验证，其余已恢复；11月 validation_complete=false，按既定跨月跟踪继续。流量观测增量226,323,010 bytes（215.84 MiB），计数有延迟，无新类型异常或配额停机。已启动2024-12，先验证该证券恢复。正式读取关闭、固定终点不变，未提交推送。详见 reports/2024-11.json。

### 当前停止：REAL 写入舍入差异（2026-10-24 04:34）

12月执行器已于03:46停止，needs_attention / independent_audit_failed；位置2024-12-11 v2，attempt=37cc5ee504ab4671b87516dd64491773，observation=608016044ef54173a077abe5445c03b5，run=4cc48d3d-663a-5fc9-be51-17548ec23966。raw与ingest退出0，已提交20463行，但独立审计exposure_value失败，不能将该批算验收通过。当前12月22/66批通过；11月688449.SH跨月缺口已在12月2日三个模型恢复，11月验收完整。额度未耗尽（末次774,107,621/3,221,225,472 bytes）。

只读逐值核对定位一个差异：002426.XSHE 的 investment_quality，raw float64=1.394935429096222，numpy float32预期=1.3949353694915771，PG实际=1.3949354887008667，差1个float32 ULP（1.1920928955078125e-7）。PG文本和二进制读取结果相同，排除读取文本展示问题。writer以Python float列表经文本COPY写REAL[]；需要修订写入量化路径并补回归，而不能放宽审计。已保持停机，未重试、未改数据／代码／审计阈值；该run已入库但未验收，正式读取持续关闭。后续修复涉及已提交收据与importer版本，须明确旧run处理方案，不能直接覆盖原收据或删除证据。301617.SZ的12月11日v1首日缺口仍待下一交易日恢复，属于既有待查。

### REAL 修复已验证，问题批次处理待确认（2026-10-24）

用户授权先修代码及回归，不放宽审计，旧批次先给方案、确认后恢复。米筐 writer 新增 _storage_values：在原float64质量检查后、业务写库前，把 exposure/factor_return/specific_return/specific_risk 四个REAL目标先按binary32量化，再经Python float序列化；covariance仍double precision，raw和归一化计算值不改。非有限／超范围继续拒绝，非零下溢为零也拒绝。原独立审计脚本未改。

回归先在一次性PG中复现生产精确差异（1.3949354887008667 != 1.3949353694915771），修复后test_risk_ingest 91项通过，米筐目录462项通过（含真实COPY、四项REAL二进制读回、非有限／溢出／下溢及协方差不变），Ruff check/format及git diff --check通过。测试fixture一次性容器/volume自动清理；独立只读审查无阻断项。只修改riskmodel.py和test_risk_ingest.py以及本状态文档，保留用户gr-tools/config.py改动；未提交推送、未改工作库数据、未恢复回补。

待用户确认的建议：保留2024-12-11 v2旧raw、run=4cc48d3d-663a-5fc9-be51-17548ec23966、receipt及失败审计作为证据，明确排除未来发布；不改purpose、不删数据、不篡改不可变收据。修复获准提交后固定新importer SHA；只重采该日v2五件套生成新observation/run，以实际新采集时间为available_at，记录新旧run关联并比较源数据是否修订。先补显式observation选择及按批次记录importer版本的续跑/审计能力：目前reader会遍历同日所有observations、执行器要求单观察且ledger锁定单SHA，不能只改版本常量直接续跑。新观察五件套、覆盖、收据、绑定、水位与严格数值审计全部通过后，保留历史已通过批次原版本，才从2024-12-11断点推进剩余已授权范围（固定终点2026-10-21）。该处理方案尚未执行，生产仍needs_attention，正式读取关闭。

### REAL 处理已获确认并完成，回补恢复（2026-10-24）

用户明确批准方案及三项补充。REAL修复独立提交0111b4c；显式observation选择与不可变反例独立提交6320f70，新importer固定6320f70a7dc4a5e4a4d7ae51cbfbf00bb8c1eab3。逐份核实682个已通过批次全部行、四类REAL全部元素审计，无抽样；数值与新writer等价，无需重导。数据库ops.data_quality_check check_id=37已对旧run写publishable=false，旧收据quality未改。

仅重采2024-12-11 v2，新observation=dd575eefbfb44f2386be86cb50776d23，新run=206dc517-ad18-55ba-a7cd-6e2d56e36f36；新旧raw五件套及覆盖逐值完全相同。新run完整审计passed后才记录supersession，当前继续12月。新run协方差最小特征值0.5950293622、条件数1396.661858，无数值告警；候选5116/完整5115，唯一缺口为已知IPO首日特异收益，保持跨日跟踪。原失败attempt、旧run/raw/receipt全部保留，未来发布必须查询禁用审计，正式读取仍关闭。

执行目录version-policy.json固定历史622成功job+60基线及旧attempts的摘要，新job记录新SHA；policy首次运行后哈希锁定，禁止重绑旧observation或只换版本常量。新版执行器已部署并通过49项mock；源码审查及执行器独立审查通过。米筐478通过，全gr-data在importlib模式997通过/21跳过/8预期失败；真实PG一次性容器清理。版本追溯运行脚本另纳入packages/gr-data/ops/ricequant_backfill，验收依据见[REAL修复记录](../../docs/history/2026-10-24-rq-real-recovery.md)。后台规则已更新为正常月度续跑，近配额边界或新问题停下通知，不自动次日恢复。只以明确文件清单提交，gr-tools/config.py用户改动未包含，未推送。

2026-10-24 10:36 后台复核：2024-12 共66/66模型日完成，66份收据／绑定／双水位审计全部passed，validation_complete=true。最低完整率99.9609%，低于99.9%的日期为0。24条IPO首日缺口涉及8只股票，下一交易日全部恢复，无待查。保留一次已修复并经用户批准替代的REAL历史失败，恢复后无新异常。流量观测增量247,105,820 bytes（235.66 MiB），末次用量963,740,289/3,221,225,472 bytes，计数可能延迟。执行锁空闲后已启动2025-01，仍仅原账号，版本策略不变；额度边界或新问题即停，不自动次日恢复，正式读取关闭，未提交推送。

### 用户主动暂停（2026-10-24）

用户要关机，明确要求等其命令再启动。已将 automation 后台跟进设为 PAUSED，并在提示首段写入禁止自动恢复。实时核对无回补或审计进程、.runner.lock 空闲、ledger.status=through_month_completed、active_job=null；不改历史账本和证据。恢复前必须获得用户明确命令，再核对最新月报与断点；不能因配额重置或启动应用自动恢复。

### 用户明确恢复（2026-10-24）

用户要求继续，暂停已解除，后台automation恢复ACTIVE。启动前锁空闲，版本策略validate-only通过，工作库只读核实2025-01-27 v2trd五件套和覆盖均已落库，旧run审计check_id37仍publishable=false。2025-01完成54/54模型日，收据审计全passed，无新失败、无低于99.9%日期；688411.SH和001395.SZ于1月27日首日缺特异收益，三模型待2月5日验证，按已授权跨月规则启动2025-02。2月14/17换码专项仍由执行器核对。数据流程是raw采集→PG入库→独立审计，正式读取关闭仅表示未发布。额度边界或新问题即停，不自动次日恢复，不提交推送。

2026-10-24 App升级后用户明确要求继续：锁空闲且无父子执行进程，账本停在2025-02-07 v2 raw阶段；该次日志为空，发布manifest=0、失败receipt=0，未进入ingest。固定importer及policy validate-only通过。用本次用户授权和具体核查依据执行resume-after-review，执行器自行保留原attempt为interrupted，从原生init恢复，不删除证据、不放宽审计。2月此前7/54模型日已通过，1月末两只IPO三模型已于2月5日恢复，1月validation_complete=true。最新历史流量观测1,215,469,572/3,221,225,472 bytes，实际额度由续跑实时查询；新问题或额度边界仍停。

2026-10-24 17:23 后台复核：2025-02完成54/54模型日，54份收据／run绑定／采集与入库双水位审计全passed，validation_complete=true，覆盖率全部100%，无IPO首日缺口、无低于99.9%日期、无待查或新质量问题。2月14日三个模型均请求300114.XSHE，17日均请求302132.XSHE，instrument_id均30636且included。App升级中断attempt保留，已按用户明确授权核查恢复，无新失败。流量观测增量209,241,108 bytes（约199.55 MiB），最后1,424,710,680/3,221,225,472 bytes，计数可能延迟。锁空闲后正常启动2025-03；仅原账号，固定终点不变，额度或新问题停查，正式读取关闭，未提交推送。

2026-10-24 18:18 后台复核：2025-03完成63/63模型日，63份收据／run绑定／采集与入库双水位审计全passed，validation_complete=true。最低完整率99.9610%，无低于99.9%日期；39条IPO首日缺口涉及13只股票，均下一交易日恢复，无待查或新异常，失败attempt为0。流量观测增量148,453,329 bytes（141.58 MiB），最后1,589,872,434/3,221,225,472 bytes，计数可能延迟。锁空闲后启动2025-04，固定终点及单账号、版本策略不变；额度边界或新问题停查，正式读取关闭，未提交推送。

2026-10-24 19:22 后台复核：2025-04完成63/63模型日，63份收据／run绑定／双水位审计全passed，validation_complete=true。最低完整率99.9612%，无低于99.9%日期；30条IPO首日缺口涉及10只股票，下一交易日全部恢复，无待查、新异常或失败尝试。月内账户计数首尾均1,701,240,602/3,221,225,472 bytes，观测增量0，按已知计数延迟处理，不能解释为零流量或最终计费。锁空闲后启动2025-05，由执行器实时复查配额；单账号、固定版本与终点不变，新问题或额度边界停查，正式读取关闭，未提交推送。

5月启动后的实时配额查询为1,961,173,817/3,221,225,472 bytes（约1.83/3 GiB），证实先前4月计数观测有延迟；不将滞后增量全部归给5月。当前2025-05-06 v1运行中，未触发配额预留边界。

2026-10-24 20:21 后台复核：2025-05完成57/57模型日，57份收据／run绑定／双水位审计全passed，validation_complete=true。最低完整率99.9611%，无低于99.9%日期；15条IPO首日缺口涉及5只股票，下一交易日全部恢复，无待查、新异常或失败尝试。流量观测增量41,011,433 bytes（39.11 MiB），最后2,002,185,250/3,221,225,472 bytes；计数有延迟，非最终计费及精确月归属。锁空闲后启动2025-06，原账号、固定版本与终点不变，近配额边界或新问题停查，正式读取关闭，未提交推送。

2026-10-24 21:25 后台复核：2025-06完成60/60模型日，60份收据／run绑定／双水位审计全passed，validation_complete=true。最低完整率99.9612%，无低于99.9%日期；18条IPO首日缺口涉及6只股票，均下一交易日恢复，无待查、新异常或失败尝试。流量观测增量119,443,639 bytes（113.91 MiB），最后2,315,802,314/3,221,225,472 bytes，计数有延迟，非最终计费。锁空闲后启动2025-07；仅原账号、固定版本及终点不变，实时配额达到预留边界或新问题即停，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-24 22:27 后台复核：2025-07完成69/69模型日，69份收据／run绑定／双水位审计全passed，validation_complete=true。最低完整率99.9612%，无低于99.9%日期；21条IPO首日缺口涉及7只股票，下一交易日全部恢复，无待查、新异常或失败尝试。流量观测增量152,396,504 bytes（145.34 MiB），最后2,596,314,603/3,221,225,472 bytes，计数有延迟。锁空闲后启动2025-08，实时配额达到10%预留边界即停，保持单账号、固定版本及终点，禁止自动次日恢复；正式读取关闭，未提交推送。

### 当前配额暂停（2026-10-24 23:28复核）

执行器于22:50因raw_budget_deferred停止，status=budget_deferred，.runner.lock已释放，无并发续跑。断点2025-08-20 v2trd，attempt=179f84a914db4c1dbaf5594e45fe6431，raw退出2，日志明确配额安全余量，未进入ingest；不是新质量异常。2025-08已完成41/63模型日（至8月19日三个模型，8月20日v1/v2），41份收据／run绑定／双水位审计全部passed；最低完整率99.9806%，无低于99.9%日期，9条IPO首日缺口涉及3股且均已恢复，无待查。8月流量观测增量119,420,917 bytes（113.89 MiB），末次2,847,983,160/3,221,225,472 bytes（约2.65/3 GiB），因计数延迟和请求安全余量不能把剩余量当可继续额度。保留未完成raw分片与失败收据，等待用户明确恢复，即使次日配额重置也禁止自动启动。正式读取关闭，未提交推送。

### 配额恢复后用户明确续跑（2026-10-25）

SDK只读查询bytes_used=0、上限3,221,225,472，用户随后明确要求从断点按月继续。启动前锁空闲，旧停机仅budget_deferred；固定importer6320f70及policy validate-only通过。正常启动2025-08-20 v2trd继续8月，不使用resume-after-review、不改账本或既有证据。后台automation已更新本次恢复授权，后续额度安全边界或新质量问题仍停止通知，等待新的明确恢复授权，不自动次日重置续跑。保留当前全部gr-tools用户改动，未提交推送，正式读取关闭，固定终点2026-10-21不变。

2026-10-25 00:29 后台复核：2025-08已完成63/63模型日，63份收据／run绑定／双水位审计全passed，validation_complete=true。最低完整率99.9806%，无低于99.9%日期；9条IPO首日缺口涉及3股，下一交易日均恢复，无待查、新质量问题；原10月24日quota_deferred尝试继续保留，用户25日授权恢复后无新停止。跨两天分组流量观测合计123,270,088 bytes（117.56 MiB），10月24日119,420,917、25日3,849,171；计数延迟，非最终计费。锁空闲后启动2025-09，实际额度由运行时查询，单账号、固定终点及版本不变；新预算暂停或质量异常仍停止等待新授权，正式读取关闭，未提交推送。

2026-10-25 01:25 后台复核：2025-09完成66/66模型日入库，66份收据／run绑定／双水位审计全passed，最低完整率99.9612%，无低于99.9%日期、失败尝试或新类型异常。24条IPO首日缺口涉及8股；其中301563.SZ（30690）与001285.SZ（33049）9月30日三模型共6条待10月9日恢复，其余已恢复，故整月validation_complete=false。按已授权跨月跟踪正常启动2025-10，优先核对这两股同身份三模型恢复。流量观测增量230,833,631 bytes（220.14 MiB），最后321,323,860/3,221,225,472 bytes，计数有延迟。固定版本、单账号及终点不变，预算边界或新异常停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 02:31 后台复核：9月末301563.SZ、001285.SZ已在10月9日三个模型全部恢复，9月validation_complete=true。2025-10完成51/51模型日，51份收据／run绑定／双水位审计全passed，validation_complete=true；最低完整率99.9419%，无低于99.9%日期，18条IPO首日缺口涉及6股且均下一交易日恢复，无待查、新异常或失败尝试。流量观测增量123,798,615 bytes（118.06 MiB），最后486,607,080/3,221,225,472 bytes，计数有延迟。锁空闲后启动2025-11，单账号、固定版本及终点不变；配额安全边界或新问题停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 03:27 后台复核：2025-11完成60/60模型日，60份收据／run绑定／双水位审计全passed，validation_complete=true。最低完整率99.9613%，无低于99.9%日期；18条IPO首日缺口涉及6股，下一交易日全部恢复，无待查、新异常或失败尝试。流量观测增量235,279,518 bytes（224.38 MiB），最后808,563,368/3,221,225,472 bytes，计数有延迟。锁空闲后启动2025-12，单账号、固定版本及终点不变；配额安全边界或新问题停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 04:27 后台复核：2025-12完成69/69模型日入库，69份收据／run绑定／双水位审计全passed；最低完整率99.9421%，无低于99.9%日期、失败尝试或新类型异常。45条IPO首日缺口涉及15股，其中301687.SZ（30637）12月31日三模型待2026年1月5日恢复，其余已恢复，整月validation_complete=false。按已授权跨月跟踪启动2026-01，优先核对该股同身份三模型恢复。月内流量计数首尾均820,947,856/3,221,225,472 bytes，观测增量0仅表示计数延迟，不能视为零实际流量。单账号、固定版本及终点不变；实时额度安全边界或新问题停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 05:26 后台复核：301687.SZ跨年缺口已在1月5日三个模型恢复，2025-12 validation_complete=true。2026-01完成60/60模型日，60份收据／run绑定／双水位审计全passed，validation_complete=true；最低完整率99.9807%，无低于99.9%日期，12条IPO首日缺口涉及4股且均下一交易日恢复，无待查、新异常或失败尝试。月内流量计数首尾均1,105,865,338/3,221,225,472 bytes，观测增量0仅表示计数延迟，不能作为零流量或最终计费依据。锁空闲后启动2026-02，实际配额实时查询，原账号、固定版本及终点不变；安全额度边界或新问题停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 06:27 后台复核：2026-02完成42/42模型日，42份收据／run绑定／双水位审计全passed，validation_complete=true；最低完整率99.9615%，无低于99.9%日期，15条IPO首日缺口涉及5股且均下一交易日恢复，无待查、新异常或失败尝试。月内流量计数首尾均1,353,706,514/3,221,225,472 bytes，观测增量0，按计数延迟保留限制，不解释为实际零流量。锁空闲后启动2026-03，原账号、固定版本与终点不变；实时配额安全边界或新问题停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 07:29 后台复核：2026-03完成66/66模型日入库，66份收据／run绑定／双水位审计全passed，最低完整率99.9615%，无低于99.9%日期、失败尝试或新类型异常。15条IPO首日缺口涉及5股；688813.SH（28030）、001257.SZ（28055）3月31日三模型共6条待4月1日恢复，其余已恢复，故整月validation_complete=false。按已授权跨月跟踪启动2026-04，先核对这两股同身份三模型恢复。流量观测增量210,774,320 bytes（201.01 MiB），最后1,738,041,559/3,221,225,472 bytes，计数有延迟。原账号、固定版本及终点不变；安全额度边界或新问题停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 08:29 后台复核：3月末688813.SH、001257.SZ已于4月1日三个模型全部恢复，3月validation_complete=true。2026-04完成63/63模型日入库，63份收据／run绑定／双水位审计全passed；最低完整率99.9615%，无低于99.9%日期、失败尝试或新类型异常。33条IPO首日缺口涉及11股，其中301599.SZ（28049）4月30日三模型待5月6日恢复，其余已恢复，整月validation_complete=false。按已授权跨月跟踪启动2026-05，优先核对该股恢复。流量观测增量186,028,603 bytes（177.41 MiB），最后1,986,068,144/3,221,225,472 bytes，计数有延迟。固定版本、单账号及终点不变，安全额度边界或新异常停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 09:33 后台复核：301599.SZ已于5月6日三个模型全部恢复，4月validation_complete=true。2026-05完成54/54模型日，54份收据／run绑定／双水位审计全passed，validation_complete=true；最低完整率99.9616%，无低于99.9%日期，21条IPO首日缺口涉及7股且均下一交易日恢复，无待查、新异常或失败尝试。月内流量计数首尾均2,060,499,930/3,221,225,472 bytes，观测增量0，计数延迟不代表实际零流量。锁空闲后启动2026-06，由运行时实时查询配额；单账号、固定版本与终点不变，预算安全边界或新问题停查，不自动次日恢复，正式读取关闭，未提交推送。

2026-10-25 10:37 后台复核：2026-06完成63/63模型日，63份收据／run绑定／双水位审计全passed，validation_complete=true；最低完整率99.9808%，无低于99.9%日期，9条IPO首日缺口涉及3股且均下一交易日恢复，无待查、新异常或失败尝试。流量观测增量227,248,300 bytes（216.72 MiB），最后2,511,099,173/3,221,225,472 bytes，计数有延迟。锁空闲后启动2026-07，实时配额达到安全预留边界即停止，单账号、固定版本及终点不变；新异常停查，不自动次日恢复，正式读取关闭，未提交推送。

### 接近配额主动暂停（2026-10-25 11:35）

2026-07完成69/69模型日，69份收据／run绑定／双水位审计全passed，validation_complete=true；最低完整率99.9808%，无低于99.9%日期，15条IPO首日缺口涉及5股且均下一交易日恢复，无待查、新异常或失败尝试。流量观测增量285,348,089 bytes（272.13 MiB）。锁空闲；只读SDK复查2,829,785,617/3,221,225,472 bytes（约2.64/3 GiB），距离2.7 GiB预留线仅约66.1 MiB，且计数有延迟。按用户“额度快用完即停”主动不启动8月，等待用户新的明确恢复；这不是SDK耗尽或新数据质量问题，不篡改ledger的through_month_completed。下一批2026-08-03 v1。持久暂停证据acceptance/quota-hold-20261025.json。禁止次日重置自动恢复，后台提示同步；正式读取关闭，未提交推送。

### 今日零预留续跑（2026-10-25，用户明确授权）

用户要求今天不保留10%且继续。新预算入口--use-full-quota-on 2026-10-25同时将runner和raw SDK预留设0；默认仍10%，上海2026-10-26 00:00失效，子进程启动前重查日期并以授权截止点限制raw超时。每新attempt记录quota_policy，原模板／variant／门禁与历史policy不变。补预算耗尽、过期、配置写入后跨日、账号准备期间跨日等反例；ops61项通过，Ruff和差异检查通过，独立复核通过；既有测试依赖/tmp seed已改自包含合成fixture。主仓库gr-data/config/settings.py有用户未提交修改，版本预检拒绝，因此创建独立干净固定6320f70检出 /Users/linnan/.codex/worktrees/ricequant-pinned-importer/getrich，uv sync --frozen --package gr-data建立隔离环境；实际require_clean版本与原3variant验证通过。原仓库用户源码和环境未覆盖、不提交不推送。实际运行必须用该检出/.venv/bin/python -I，cwd仍原仓库以复用.env；external runner共用原账本／锁。已从2026-08-03 v1启动8月，今日用量查询2,829,785,617/3,221,225,472 bytes。预算脚本旧版与授权记录在acceptance/full-quota-20261025；先前近配额暂停证据保留。新额度耗尽或质量问题仍停止通知，不自动次日恢复；正式读取关闭、固定终点不变。后台已同步隔离Python和今日参数。

2026-10-25 12:40 后台复核：2026-08完成63/63模型日，63份收据／run绑定／采集与入库双水位审计全部passed，validation_complete=true；最低完整率99.9616%，无低于99.9%日期、新异常或失败尝试。27条IPO首日缺口涉及9股，均次交易日恢复，无待查。月内账户流量观测增量140,377,670 bytes（133.87 MiB），末次2,970,163,287/3,221,225,472 bytes，计数有延迟，非最终计费。锁空闲后用干净固定6320f70检出的隔离Python及今日--use-full-quota-on 2026-10-25启动2026-09，现2026-09-01 v1 raw运行且锁已持有；仅今日双层预留0，过期／耗尽或新质量问题即停并通知，不自动次日恢复。固定终点2026-10-21、单账号与policy不变；正式读取关闭，未提交推送。

2026-10-25 用户要求关机，已主动暂停：后台automation状态PAUSED，回补进程组1324已SIGINT退出，复核无raw／ingest／audit存活，.runner.lock释放。三个模型已完成至2026-09-11；中断断点2026-09-14 v1 raw，attempt=41fcb83fa36b4e7fbf551c7699665a07。原ledger/attempt保留原样，其running仅为中断遗留，不表示进程存活；恢复必须先核实该日raw与待确认IPO，不擅自标记验收通过。主动暂停证据acceptance/user-pause-20261025T125628.json。等待用户明确恢复，不自动启动；今日零预留到期后不可沿用。正式读取关闭，未提交推送。

2026-10-25 20:55 用户要求恢复回补。固定6320f70、policy与三variant validate-only通过，锁空闲；原9月14日v1仅_pending分片无manifest，原raw日志KeyboardInterrupt。按明确恢复授权通过已审查入口resume-after-review记账，旧attempt保留并标interrupted；新attempt=253c51e5e45a41689ed93f4dd34bee59在raw capture callback连接PG即失败：127.0.0.1:5432 Connection refused，raw退出1，未进入风险采集／ingest，runner needs_attention/raw_failed_unclassified。docker ps只读确认Docker daemon不可连接，属于关机后基础设施未就绪，不是新数值质量异常；未自动重试／未启动服务。锁已释放，后台维持PAUSED等待用户恢复数据库并明确继续。额度前后观测均3,205,777,483/3,221,225,472 bytes，仅14.73 MiB；10月25日零预留不跨日沿用。已通过至9月11日；688801.SH三个模型9月14日恢复待查。正式读取关闭，未提交推送。

2026-10-26 用户再次明确要求恢复米筐回补。固定6320f70干净检出及执行器validate-only均通过（原三production variant／policy不变），进程锁空闲。启动前PG只读连接失败，TCP明确ConnectionRefusedError；docker ps确认Docker daemon仍不可连接，因此本轮未启动采集／入库，账本与attempt未改。独立SDK额度查询bytes_used=0、bytes_limit=3,221,225,472（3 GiB），额度已恢复；昨天零预留授权已到期，后续默认10%预留。仍等待启动Docker Desktop及工作库；后台保持PAUSED，断点2026-09-14 v1，688801.SH三模型次日恢复待核对。没有运行docker compose、未重启服务、未提交推送，正式读取关闭。

2026-10-26 用户明确确认Docker与工作库就绪并授权继续。只读预检PG SELECT 1成功，账号bytes_used=0、bytes_limit=3,221,225,472，锁空闲；固定干净6320f70及冻结policy/三production variant validate-only通过。已通过人工复核恢复参数记录上次PG连接拒绝的原因，保留旧失败attempt，启动9月剩余批次；新attempt=e5add37f53054fb680e9390200c81182，2026-09-14 v1 raw退出0并进入ingest，锁持有。今日恢复默认10%预留（quota_policy.reserve_fraction=0.1、use_full_quota_on=null），不沿用昨日零预留。后台automation恢复ACTIVE，后续按月核对后继续10月至固定2026-10-21；新额度预留边界或新质量问题即停，不自动次日恢复／不复用本次resume-after-review授权。优先核对688801.SH（27951）9月14日三模型恢复。正式读取关闭，原源码／policy不变，未提交推送。

2026-10-26 08:43 后台复核：2026-09完成63/63模型日，63份收据／run绑定／采集与入库双水位审计全部passed；最低完整率99.9616%，无低于99.9%日期或恢复后的新失败。36条IPO首日缺口涉及12股，其中688801.SH已于9月14日三个模型全部恢复；001246.SZ（27942）9月30日三模型待10月8日恢复，其余已恢复，整月validation_complete=false。旧关机中断与PG未启动失败attempt保留，不当作新异常。按已批准跨月跟踪正常启动最后2026-10（固定只到21日），优先核对001246恢复，默认10%额度预留；旧停止原因不复用恢复参数。9月跨观测日流量增量合计201,816,635 bytes（192.47 MiB），10月25日115,381,334、26日86,435,301；计数有延迟，不代表最终计费。固定版本、policy和单账号不变，额度边界或新质量问题即停；正式读取关闭，未提交推送。

2026-10-26 09:44 全范围完成：ledger.status=completed、终点2026-10-21、无active_job且锁空闲。10月完成30/30模型日，30份收据／run绑定／双水位及数值审计均passed，最低覆盖99.9809%，2只IPO均次日恢复，无新异常／低于99.9%日期；流量观测增量111,801,024 bytes（106.62 MiB），非最终计费。9月末001246.SZ已于10月8日三模型恢复，9月validation_complete=true；000016于10月21日三模型均在市、全天停牌S且included，专项审计passed。完整范围含基线2024-01-02～2026-10-21，共676交易日×3模型=2,028个模型日；本次账本1,968个+基线60个，34个月全部validation_complete，待查0，低于99.9%日期0，全范围最低覆盖99.9419%。终验重新读取全部1,968份既有逐值审计文件并通过，真库核对全部2,028个run收据／绑定／双水位存在一致、production用途且calibrated=false；没有重复全范围数值重扫。旧失败run排除记录check_id37/publishable=false仍保留，全部旧attempt／raw／supersession不动。终验汇总acceptance/final-completion-20261026.json。正式风险读取仍关闭，D-022 2b待后续评审；本轮不再扩大日期，未提交推送。完成后关闭后台自动化。
