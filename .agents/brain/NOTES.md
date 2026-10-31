# GetRich 当前状态

读者：接续任务的 Claude/Codex/Antigravity；维护者也可用它快速定位工作。
最后整理：2026-10-31。只写现状与待办；已完成的工作留一行结论和证据位置，过程与测试数字不写入（可从 Git、代码和 docs/history 追溯）。

## 开始任务

1. 先读根 `AGENTS.md`，再读本文。
2. 按任务查 [待决问题](../../docs/plans/backlog.md) 和 [决策主题索引](DECISIONS.md)。
3. 使用说明从 [文档目录](../../docs/README.md) 定位；历史材料不作为现行指令。

## 当前方向与阻塞

- BJ 待处理项，后续单独核实：最新已完成 2010-05，本月 2 条／1 个代码；本回补累计 4 条／1 个代码。仅 .BJ 行级失败暂存 `ops.tushare_bj_pending`，合格记录照常入库，沪深失败仍停止；逐月明细见 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/bj-pending-months.json`，后续单独核实原始值与历史口径。

- iMac 准备（2026-10-31）：工作库迁移、主数据及 2024-01-01～2026-10-29 股票 34 个月全部验收完成，逐月 canonical 字段、价格及首月幂等／独立单位检查通过，原始完成账本和源码指纹保留。正式 raw 为 `/Volumes/neoimac/data/raw_parquet`，状态／证据在 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20240101-20261029/`。myssd 主要为米筐风险因子，后续迁移；米筐与定时调度未启用，日常 config.yaml 起点未扩展。详情见[迁移盘点](../../docs/plans/imac-collector-migration.md)。
- Tushare 早期股票续接（2026-10-31 BJ 策略调整后已恢复）：从 2010-04 续跑，该月四 writer 全部 canonical 读回／价格／幂等验收通过，股票日线与估值各 35,763 行、复权 37,721 行、停复牌 1,460 条；2 条／1 个 BJ 代码写入待处理，重复导入仍为 2 条，raw 未改。2010-01～03 已用新源码重验且原月账本不改；2024-01～2026-10-29 的 34 月完成账本未改。后台按月继续，当前进度以 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/state.json`／queue.json 为准，后续品种控制器已恢复等待。规则见 D-023，待处理与主表同事务；沪深及共享设施失败仍停止。证据同目录 `bj-pending-april-acceptance.json`／`approved-source-change-bj-pending-20261031.json`。
- 股票之后的多品种接续（2026-10-31）：用户确认股票两批全验收并退出后，按 8 只核心指数 → ETF → 六所期货 → 八所期权接续，范围 2010-01-01～2026-10-29。已按已审查的换码／极端值审计／BJ 分流源码及迁移 050／052 修订计划并归档原计划，接续控制器已恢复为 `waiting_for_all_stock`；尚未启动其他品种采集。计划／状态为 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/plan.json`／queue.json。期权只采 raw 和独立验证库，正式 writer 及历史参数发布仍关闭；期货合约乘数／最小价位留给米筐。源码、DDL、lock、目标与质量异常门禁保持，详情见迁移盘点。
- 估值容量与审计（2026-10-31 用户授权）：迁移 050 已将 `fundamental.valuation_1d.pe/pe_ttm/ps/ps_ttm` 及分区列扩为 `NUMERIC(20,4)`；执行前无依赖视图／其他会话占锁，原 369 万行的行数、数值汇总及分区文件标识未变。四字段有限值绝对值 >1e6 逐字段写 `ops.data_quality_check`（`tushare_valuation_extreme_ratio`），备注“极端值保留原值、因子层处理”，与估值同事务，规则见 D-027。首月 20 个极端值逐条源／PG／审计一致，两次导入计 40 条审计、去重 20；相关迁移／事务回归、类型及静态检查通过，证据为运行目录 `valuation-widen-applied-20261031.json`／`valuation-first-month-acceptance-20261031.json`。
- DDL 新库基线（2026-10-29）：用户授权将增量列／最终约束／索引并回 CREATE，历史编号保留占位；旧库 schema 改名、历史回填／截断不再执行，演示账号从初始化即停用。041／042 注释按代码语义修正，注释覆盖由基线测试守卫；旧库不就地升级（D-006）。两源字段互验已于 2026-10-30 完成有界真实样本，缺口转为 backlog 后续处理，不代表全历史验收。
- 字段互验（2026-10-30）：Tushare 官方／真实字段与全部 writer、contract、DDL 双向核对，米筐三模型原生响应／raw／隔离 PG 逐值与单位重测通过；完整矩阵、报告、复现脚本及验证范围见[迁移盘点第二节](../../docs/plans/imac-collector-migration.md#字段互验与补充验证2026-10-30)。2026-10-30 已按用户确认实施（D-027，提交 `b563d69`～`4028beb`）：daily_basic 只落 valuation_1d、风险模型 `observed_at` 更名及无来源列删除、股票／指数／期货／ETF 档案表、ETF 按 fund_type 分类、opt_basic 补字段、米筐期货合约参数。同日真实采集验收（隔离 raw＋一次性 PG，未写工作库）：tushare 主数据／fund_basic／2024-01 daily_basic 与米筐 future_contracts 全部入库，期货合约 10860 个、六所最小变动价位齐全，暴露的世纪推断与股息点基点问题已修（`89b3909`）；证据见 `/Volumes/neoimac/data/getrich-validation/field-expansion-20261030/summary.md`。opt_basic 新字段未真实采集，daily_basic 只验一个月。外部复核后又修复分类残留、估值／行情非法值静默置空、可选档案软跳过与米筐期货两文件跨批次混用（`de16551`、`4830498`）；米筐最小变动价位文件现须带合约快照哈希，验收目录里修复前的 future_tick 已不可导入，正式采集时重采 `future_contracts`。正式 raw 根已按新字段重采 `tushare/instruments`（2026-10-30）；从硬盘复制旧 raw 时不要覆盖这四个文件，否则 profile 组会因缺字段硬失败。根 config.yaml 已由用户去掉 ingest 的 `daily_basic`。
- 风险证据归域（2026-10-29）：用户确认 variant／receipt／checkpoint 及风险校验函数归入 `factor`，新库直接建立，代码／测试／回补审计／现行文档引用同步；通用 ETL、质量、归属和迁移记账仍在 `ops`。证据表写入前校验单表单源，capture 及其归属独立保留。不开放正式风险读取；重导带不回的人工否决等见迁移盘点。
- 构建副本清理（2026-10-29）：确认安装均指向 `src` 后，已按用户授权删除未跟踪的 `packages/gr-data/build` 与 `packages/gr-tools/build`；保留 basedpyright 的构建目录排除规则，后续重新构建也不重复扫描。

### Tushare ETF／三类期权

- 现状：已合入 dev（`588a2c5`，样本修复 A1–A5 为 `24e0fdd`）。期权 OHL 全零占位、基金非标准代码、ETF 待上市 P 按源义留在 raw 并软告警；opt_basic 按显式标的分页。四个期权 writer 正式写入默认关闭，仅 `TUSHARE_OPTION_VALIDATION_ONLY=1` 的隔离验证可写，APP_ENV=prod 拒绝（D-026）。用法见 gr-data README「ETF 与三类期权」。
- 2026-10-29：离线子集和合成样本 PG 往返／幂等验收通过；真实 2024-01 复验仅部分完成，基金日线／因子及八所日历已取得。ETF 已上市名单出现 `158008.OF`；期权日线触发 OHL 全零且 close 非正的门禁，未发布整月，元数据因前置缺失未完成。原响应与审计在独立验证目录，位置见[迁移盘点](../../docs/plans/imac-collector-migration.md)；未改源码／校验，未写工作库。
- 2026-10-30 续验完成：用户确认的 ETF L 缺上市日隔离、CZCE 缺失 OHLC 不限制量额、CZCE／GFEX 零结算须核对到期日三项处理已实施（D-026）。2024-01 ETF 及八所期权 raw／合约资料齐备，真实整月隔离 PG 的字段、源值单位与两轮幂等验收通过。工作库未改动，期权仍未正式发布；输入、源码指纹、脚本及结果见迁移盘点第二节。
- 待办：
  1. opt_basic 全历史去重请求预算未测；本月有缓存的按标的实测不能当作冷启动或全历史预算，见 gr-data README。
  2. 全量历史回补已于 2026-10-30 获用户授权并排在全部股票之后（范围见多品种接续）；期权仅 raw／独立隔离验证，正式写入仍关闭，不能用本次授权绕过 D-026。
  3. ETF 分类已按 `fund_basic.fund_type` 实施（`0b655c5`，D-026）：股票型／债券型／货币型且纯境内才写，“其他”、QDII 与未匹配的不写；新库从 raw 重新入库，无存量需更正。“其他”类与跨境市场的真源仍待确认。

### 米筐风险模型

- 2026-10-30 复验：用户恢复本机认证后，固定名单三模型的真实字段／入库与单位检查通过；P6 在独立复权超额收益和前日暴露口径下样本数值自洽。完整供应商时间／基准约定和全区间仍待确认，不改生产契约、校准或发布状态；初次认证失败保留为过程证据，不再是当前阻塞。

- 现状：三个 production 模型 2024-01-02～2026-10-21 回补完成（2026-10-26），全部 `calibrated=false`。账本与终验在仓库外运行目录，当前位置见[迁移盘点](../../docs/plans/imac-collector-migration.md)；验证与首批验收见[米筐验证记录](../../docs/history/2026-10-23-rq-risk-validation.md)。2024-12-11 v2 旧 run 已标 publishable=false（check_id=37），发布时必须排除，见 [REAL 修复验收](../../docs/history/2026-10-24-rq-real-recovery.md)。
- 待办：
  1. **正式风险读取仍关闭**：D-022 2b（发布清单、发布程序、统一读取入口）待评审，完成并发布前不得开放。
  2. 已完成批次的 importer 版本记在各导入收据的 `importer_version` 与运行目录的 `version-policy.json`，不需要沿用。同一份 raw 换 importer 版本重导会在写库前被拒绝，所以用迭代后的版本启动新批次前，先在版本策略里登记新版本。
  3. 补充方案 R1–R3（与风险五件套独立）已有离线契约与 raw 采集，默认关闭；尚缺逐项去重、模块权限、真实样本契约和采集区间证据，先取得准入材料再推进 P1c。R4–R10 仅登记候选。

### Tushare 指数／期货

- 2026-10-26 已合入 dev（`962957b`，`a4b7ecd` 修正类型错误）。指数必须配置 `index_codes`／`index_markets` 白名单；期货默认六所含 GFEX，逐所逐日取数。用法见 `packages/gr-data/config.tushare-markets.example.yaml` 与 gr-data README。
- raw 回补 2024-01-01～2026-10-23 已完成，账本与源码指纹在仓库外运行目录，位置见[迁移盘点](../../docs/plans/imac-collector-migration.md)。该 raw 由合并前源码产出，`source-pin.json` 与当前源码哈希不一致属预期。**正式 PG 入库尚未验收**。
- SCTAS 的 OHLC 是结算价偏移量（D-025）：入库时整行排除并计软告警；普通 `future_bar_1d` 尚无 TAS 价差映射，消费前须另定语义。
- 2024-01 真实样本对账通过（仅覆盖该月，报告位置同上）。2026-10-30 补充 GFEX 早期日历和期货上市当日的有界探针；不代表全区间通过，所有已停发指数的 `exp_date` 完整性仍缺独立停发清单，范围见迁移盘点。

### Tushare 股票

- 现状：iMac 的 2024-01-01～2026-10-29 股票已全部验收；2010～2023 进度与源码修复见上方接续条目及仓库外运行账本。MBA 旧数据不作为本机完成证据。口径见 D-012／D-023／D-024，坏文件、缺分区、未知代码、缺标的或日历仍硬失败；软告警须复核。
- 待办：
  1. 剩余审核疑点以 strict xfail 留在 `packages/gr-data/tests/test_tushare_review_findings.py`，清单见 backlog。
  2. 2010～2023 历史回补按账本继续；已核实的两对换码仅适用 D-012 明确例外。其他差异、历史开市日空响应仍硬失败，不把无数据当完整分区。
  3. BJ 待处理项，后续单独核实：回补结束后汇总代码／日期／年月分布，核实原始值、list_date 历史口径、换码与复权来源；集中时优先修正经证实有误的主数据，详见 backlog。

### 持仓诊断与供应商

- 2026-10-20：持仓诊断一期口径在设计仓 `getrich-design` 确认（`governance/scope.md` PA-01～PA-20），数据集清单见 `data-platform/portfolio-diagnosis-phase1-datasets.md`。先完成 gr-data 一期数据；盲点阈值与画像规则等真实数据后再定。不能用估算值填满界面。
- 2026-10-31 P0 接口对齐已合入 dev（`43cbba2`）：`options`／`/recompute`、只诊断最新发布日、范围外资产 422、历史别名、TopN 1/3/5 与缺失档、PA-13 覆盖率、纯计算模块 `gr_api/diagnosis_calc/`（D-021）；2026-10-21 审核项 D1／D2／D4 随之关闭。B/C/D 与压力测试为 `feature_not_available`，画像与盲点为「未能判断」；重算在 D-022 2b 前恒 409。迁移 051 新增口径版本 `v1-model-20261031`，风险模型按用户确认选米筐 v2，但 v2 尚未入工作库，`factor_model` 暂空。**051 依赖未提交的 050，二者须一并提交后再推送，否则 CI 迁移因编号不连续失败**；工作库尚未执行 051，API 连工作库前需 `uv run gr-db migrate --target pg`。前端接口层与类型已合入（`9bbc2da`，`src/api/diagnosis.ts`、`src/types/diagnosis.ts`）；`PortfolioDiagnosisPage.tsx` 仍是写死的 mock，用户将单独重做页面。
- 设计仓 DP-02 供应商方向（2026-10-18）：Tushare 为主要来源，风险因子用米筐，DataYes 为第二档备用，银河为最后备用，INSIGHT 不再使用（代码与历史资料保留）。`factor.*` 归属已转给 ricequant；DataYes 风险因子方案保留但暂不启用。
- 数据接入 P0–P2 已实现，P5 的 ETF／期权已部分合入（待办见上方 ETF 一节）。待推进：P6 完整口径／全区间校验（有界样本已有经验复现）、行业分类真源（DS11）、P3／P4 排期。SW14/SW21 切换仅在恢复 DataYes 时处理。
- `diag.data_version` 的维护流程未完成；数据更新后如何推进版本必须与缓存策略一起处理（D-022）。2026-10-31 工作库只有 2026-08-30 种子行，诊断日期因此被钉在该日；`available_options` 无写入流程，行业体系与基准都按未验证处理。工作库 `factor.model`／`model_run` 为空、`classify.scheme` 为空、`fundamental.indicator_q` 为空（只读核对）。
- 历史代码别名在选股导入侧未生效，同一证券新旧代码会算成两笔，见 backlog；诊断侧已于 2026-10-31 走 `meta.symbol_map`。

### 其他未决

- JWT 默认密钥的启动检查尚未处理（mock 认证已按 D-020 默认关闭；本机用 `VITE_DEMO_USER_ID` 开发前端时需在自己的 `.env` 加 `GETRICH_ALLOW_MOCK_AUTH`）。
- 策略／信号接口仍有契约与管理导入缺口；不能把诊断接口已有响应模型推广为所有接口均已覆盖。
- 回测 `oi` 映射、公司行为接入、Black-Litterman 建模口径及选股历史关联回填见待决问题。
- DDL 审核遗留（2026-10-10／10-22 记录，未处理）：分钟线压缩后重灌会触发 `timescaledb.max_tuples_decompressed_per_dml_transaction`（默认 100000），回填前需定 chunk 间隔、压缩参数并暂停压缩作业；`004` 的 `*_1d_ca` 物化视图无人引用且 WITH NO DATA；034 `chk_item_option_type` 放行 NULL；回测比率列 DECIMAL(20,10) 可能溢出；app schema 缺外键、meta 交易所码缺 CHECK；btree_gist 装在 pg_catalog；重复索引、选股约束、runner 默认阻断；`gr-db migrate --dry-run` 会建记账表且汇总行误报 0；`lint_migrations.py --comments --base-ref` 只查已提交差异，未提交的新迁移需直接调用 `comment_violations` 自查。
- `apps/backtest-web` 暂停维护（2026-09-17 移除独立 CI），其 `src/lib/` 缺失，恢复前需补齐安全插件、HTML 清洗及 UI 工具并重跑 lint／测试／构建，见该目录 README。`gr-agent` 仍为空包。

## 运行模式与公共工具

- 配置：gr-tools 提供无导入副作用的环境快照与日志能力（`gr_tools.config.setup_logging`），gr-data 保留数据模型，gr-api 组装 API／worker 配置，其他 CLI 按需加载；旧全量 Settings 已移除（D-002）。布尔环境键统一走 `parse_bool`，未知值直接报配置错误。
- 默认 worker backend 为 inproc；CI 默认仅 PG，手动 `extra_services` 可启用 CH／Redis。本地 `.env` 只存连接与凭证，未迁入源码或 YAML。
- Python 最低 3.11，开发默认 3.12；CI 跑 3.11／3.12，3.12 开启选股／诊断 PG 集成测试与 75% 覆盖率检查。
- 类型检查用 basedpyright（standard，全仓唯一，配置在根 pyproject）；存量错误记在 `.basedpyright/baseline.json`，CI 只拦新增。gr-tools 是否启用 strict 待定。
- `gr_tools` 的 `fs`／`human`／`io` 已于 2026-10-24～26 精简（删除的公开函数仓外调用方需迁移）；`io` 只用 Polars，Excel 经 fastexcel 读取，需要 pyarrow。

## 验证边界

- 2026-10-31 诊断 P0（worktree `feat/diag-p0`，本机 Python 3.12）：全量 `pytest -m 'not live_sdk'` 3602 passed（指向一次性 PG18 时 gr-data 自起容器的用例因端口冲突跳过，随后单独重跑 gr-data／gr-db 1483 passed）；一次性 PG18 上 52 个迁移两次执行幂等、数据字典 `--fail-on-drift` 通过、诊断集成 9 passed（含 5×100 边界，不作性能证据）；Ruff、格式、迁移 lint、051 注释检查、basedpyright 0 errors（基线缩减 26 条）、`uv lock --check` 通过。工作库仅做只读取数冒烟（5 只真实股票 2026-10-29 估值与分档、北交所 422），未执行迁移、未启动服务。测试时临时复制了未提交的 050，已删除。
- 2026-10-30 字段专项：两源有界真实样本双向核验、PG 往返／幂等、风险源单位及隔离逻辑恢复通过；P6 仅为明确范围的数值复现。相关故障／约束回归通过，既有 strict xfail 保留；具体范围和结果见迁移盘点及独立审计目录。未执行生产恢复、全历史对账或无人值守验收。

- 历史记录中的主机路径、服务健康、凭证配置、数据行数均不能当实时事实；使用前查当前配置、代码或执行对应检查。失败时记录具体命令、日期、范围与原因。
- 2026-10-29 风险证据归域专项：gr-db、全部米筐用例、回补审计和新库重放共 582 项通过；新增证据表换源冲突回归，覆盖独立 capture 归属保留及业务回滚。一次性 PG18 中，映射已授权的表／函数 schema 后其余字段、约束、索引、触发器、函数和物化视图定义一致；默认 basedpyright、改动文件 Ruff、迁移与注释检查及 lock 检查通过。工作库和真实供应商未访问；历史记录中的旧 `ops` 名称保留为当时证据。
- 2026-10-29 DDL 专项：一次性 PG18／TimescaleDB 中，合并前后字段（含顺序）、约束、索引、触发器、函数及物化视图定义一致，全 SQL 直接重放与 runner 幂等通过；gr-db、风险约束／收据／导入、股票别名及完整导入用例通过。迁移安全、显式注释覆盖、改动测试 Ruff 和 lock 检查通过。后续已在根 basedpyright 配置中排除 `packages/*/build/**`，解决旧 setuptools 构建副本被重复扫描的问题；默认 `uv run --frozen basedpyright` 现为 0 errors／0 warnings，无需手列源码或修改 baseline。未连接工作库或供应商，临时容器与卷已清理。
- 最近全仓基线（2026-10-26，本机 Python 3.12，ETF／期权合并后的组合版本）：`uv run --frozen pytest -q -m 'not live_sdk'` 3557 passed／22 skipped／28 deselected／4 既有 xfailed；Ruff、495 文件格式检查、basedpyright 0 errors、迁移 lint（1 CH／50 PG）、`uv lock --check` 通过。去除供应商 token 和 `GETRICH_TEST_PG`，未连接工作库。约 44 条既有 warning（ORJSONResponse 弃用、mock 协程未 await）保留。
- 2026-10-27 远程 CI 两个 Python 版本都因回测产物 MIME 测试失败（[运行记录](https://github.com/getrich-2026/getrich/actions/runs/40457446826)），2026-10-28 已修正 `test_backtest_runs.py` 并随 `7b8e650` 推送；**待确认远程 CI 恢复通过**。
- 2026-10-28 提交前本机全仓（Python 3.12，排除 live_sdk，未设 `GETRICH_TEST_PG`，含一次性 Docker PG 用例）：3594 passed／22 skipped／28 deselected／4 既有 xfailed；Ruff、495 文件格式、basedpyright 0 errors、迁移 lint（50 PG）、`uv lock --check` 通过。

<a id="rq-three-model-history-20261022"></a>

已入库的米筐 units_evidence 引用本锚点，原章节现位于 [米筐验证记录](../../docs/history/2026-10-23-rq-risk-validation.md#rq-three-model-history-20261022)。

## 文档维护

- `AGENTS.md`：执行规则；本文：当前状态；`DECISIONS.md`：仍有效的取舍与防错理由。
- `docs/guides/`：怎么用；`docs/plans/`：未决问题与验收条件；`docs/history/`：已完成材料。
