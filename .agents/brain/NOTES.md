# GetRich 当前状态

读者：接续任务的 Claude/Codex/Antigravity；维护者也可用它快速定位工作。
最后整理：2026-10-29。只写现状与待办；已完成的工作留一行结论和证据位置，过程与测试数字不写入（可从 Git、代码和 docs/history 追溯）。

## 开始任务

1. 先读根 `AGENTS.md`，再读本文。
2. 按任务查 [待决问题](../../docs/plans/backlog.md) 和 [决策主题索引](DECISIONS.md)。
3. 使用说明从 [文档目录](../../docs/README.md) 定位；历史材料不作为现行指令。

## 当前方向与阻塞

- iMac 准备（2026-10-29）：PG18／TimescaleDB 已运行，目标工作库当日核验尚无业务表；用户已更新 RAW_PARQUET_ROOT 并复制根 config.yaml，离线加载确认 raw 根生效但目录尚不存在。本机米筐配置已改沪深 A 股动态名单／production，用于后续全市场任务；仍为 v1，日期保留原三天窗口，运行前按迁移账本调整，不自动滚动。硬盘带回后复制普通文件并以逻辑备份恢复 PG，正式调度未启用。顺序见[迁移盘点](../../docs/plans/imac-collector-migration.md)。

### Tushare ETF／三类期权

- 现状：已合入 dev（`588a2c5`，样本修复 A1–A5 为 `24e0fdd`）。期权 OHL 全零占位、基金非标准代码、ETF 待上市 P 按源义留在 raw 并软告警；opt_basic 按显式标的分页。四个期权 writer 正式写入默认关闭，仅 `TUSHARE_OPTION_VALIDATION_ONLY=1` 的隔离验证可写，APP_ENV=prod 拒绝（D-026）。用法见 gr-data README「ETF 与三类期权」。
- 2026-10-29：离线子集和合成样本 PG 往返／幂等验收通过；真实 2024-01 复验仅部分完成，基金日线／因子及八所日历已取得。ETF 已上市名单出现 `158008.OF`；期权日线触发 OHL 全零且 close 非正的门禁，未发布整月，元数据因前置缺失未完成。原响应与审计在独立验证目录，位置见[迁移盘点](../../docs/plans/imac-collector-migration.md)；未改源码／校验，未写工作库。
- 待办：
  1. 核对上述两类真实源异常的语义与处理契约，再补齐受限样本及真实数据隔离 PG 验收，不改码、不静默删行或填价。
  2. opt_basic 全历史去重请求预算未测；旧逐代码方案的 2024-01 预算见 gr-data README，不能套用为当前批量方案预算。
  3. 全量回补需单独授权。
  4. ETF 分类改用 `fund_basic.fund_type` 并更正存量：另开分支实施，工作库数据更正需单独授权；目前沿用旧规则（equity／cn_a，已知不准确）。

### 米筐风险模型

- 现状：三个 production 模型 2024-01-02～2026-10-21 回补完成（2026-10-26），全部 `calibrated=false`。账本与终验在仓库外运行目录，当前位置见[迁移盘点](../../docs/plans/imac-collector-migration.md)；验证与首批验收见[米筐验证记录](../../docs/history/2026-10-23-rq-risk-validation.md)。2024-12-11 v2 旧 run 已标 publishable=false（check_id=37），发布时必须排除，见 [REAL 修复验收](../../docs/history/2026-10-24-rq-real-recovery.md)。
- 待办：
  1. **正式风险读取仍关闭**：D-022 2b（发布清单、发布程序、统一读取入口）待评审，完成并发布前不得开放。
  2. 已完成批次的 importer 版本记在各导入收据的 `importer_version` 与运行目录的 `version-policy.json`，不需要沿用。同一份 raw 换 importer 版本重导会在写库前被拒绝，所以用迭代后的版本启动新批次前，先在版本策略里登记新版本。
  3. 补充方案 R1–R3（与风险五件套独立）已有离线契约与 raw 采集，默认关闭；尚缺逐项去重、模块权限、真实样本契约和采集区间证据，先取得准入材料再推进 P1c。R4–R10 仅登记候选。

### Tushare 指数／期货

- 2026-10-26 已合入 dev（`962957b`，`a4b7ecd` 修正类型错误）。指数必须配置 `index_codes`／`index_markets` 白名单；期货默认六所含 GFEX，逐所逐日取数。用法见 `packages/gr-data/config.tushare-markets.example.yaml` 与 gr-data README。
- raw 回补 2024-01-01～2026-10-23 已完成，账本与源码指纹在仓库外运行目录，位置见[迁移盘点](../../docs/plans/imac-collector-migration.md)。该 raw 由合并前源码产出，`source-pin.json` 与当前源码哈希不一致属预期。**正式 PG 入库尚未验收**。
- SCTAS 的 OHLC 是结算价偏移量（D-025）：入库时整行排除并计软告警；普通 `future_bar_1d` 尚无 TAS 价差映射，消费前须另定语义。
- 2024-01 真实样本对账通过（仅覆盖该月，报告位置同上）。尚未验收：GFEX 早于 2024 的日历、`list_date` 当日是否有数、已停发指数是否都填 `exp_date`。

### Tushare 股票

- 现状：工作库已回补 2024-01-02～2026-10-22（2026-10-22），口径见 D-012／D-023／D-024。导入门禁对坏文件、缺分区、未知代码、缺标的或日历硬失败，软告警退出码 3；其他供应商未接入门禁。
- 待办：
  1. 剩余审核疑点以 strict xfail 留在 `packages/gr-data/tests/test_tushare_review_findings.py`，清单见 backlog。
  2. 2013–2023 的 raw 未扫描。若某个过去交易日供应商确实无数据，空响应拒绝规则会让该月每次抓取都失败，且 `raw.run_provider` 遇错即停；回补更早历史前先用临时 raw 根目录预演。

### 持仓诊断与供应商

- 2026-10-20：持仓诊断一期口径在设计仓 `getrich-design` 确认（`governance/scope.md` PA-01～PA-20），数据集清单见 `data-platform/portfolio-diagnosis-phase1-datasets.md`。本仓实现仍按旧设计（A 已有计算，B/C/D、压力测试与多方案 E 未开放），对齐缺口见 backlog「持仓诊断与数据供给」。先完成 gr-data 一期数据；盲点阈值与画像规则等真实数据后再定。不能用估算值填满界面。
- 2026-10-21 现有实现审核的问题清单与已定口径见 backlog「2026-10-21 现有实现审核」；D-021／D-022／D-023 同日确认，口径已同步设计仓。T1／T2 已修复，其余审核项待处理。
- 设计仓 DP-02 供应商方向（2026-10-18）：Tushare 为主要来源，风险因子用米筐，DataYes 为第二档备用，银河为最后备用，INSIGHT 不再使用（代码与历史资料保留）。`factor.*` 归属已转给 ricequant；DataYes 风险因子方案保留但暂不启用。
- 数据接入 P0–P2 已实现，P5 的 ETF／期权已部分合入（待办见上方 ETF 一节）。待推进：P6 五表自洽校验、行业分类真源（DS11）、P3／P4 排期。SW14/SW21 切换仅在恢复 DataYes 时处理。
- `diag.data_version` 的维护流程未完成；数据更新后如何推进版本必须与缓存策略一起处理（D-022）。
- 历史代码别名在诊断与选股导入侧未生效，同一证券新旧代码会算成两笔，见 backlog；不阻塞数据导入。

### 其他未决

- JWT 默认密钥的启动检查尚未处理（mock 认证已按 D-020 默认关闭；本机用 `VITE_DEMO_USER_ID` 开发前端时需在自己的 `.env` 加 `GETRICH_ALLOW_MOCK_AUTH`）。
- 策略／信号接口仍有契约与管理导入缺口；不能把诊断接口已有响应模型推广为所有接口均已覆盖。
- 回测 `oi` 映射、公司行为接入、Black-Litterman 建模口径及选股历史关联回填见待决问题。
- DDL 审核遗留（2026-10-10／10-22 记录，未处理）：分钟线压缩后重灌会触发 `timescaledb.max_tuples_decompressed_per_dml_transaction`（默认 100000），回填前需定 chunk 间隔、压缩参数并暂停压缩作业；`004` 的 `*_1d_ca` 物化视图无人引用且 WITH NO DATA；034 `chk_item_option_type` 放行 NULL；回测比率列 DECIMAL(20,10) 可能溢出；app schema 缺外键、meta 交易所码缺 CHECK；042 对 `pick.item.symbol` 的注释写错；btree_gist 装在 pg_catalog；重复索引、选股约束、runner 默认阻断；`gr-db migrate --dry-run` 会建记账表且汇总行误报 0；`lint_migrations.py --comments --base-ref` 只查已提交差异，未提交的新迁移需直接调用 `comment_violations` 自查。
- `apps/backtest-web` 暂停维护（2026-09-17 移除独立 CI），其 `src/lib/` 缺失，恢复前需补齐安全插件、HTML 清洗及 UI 工具并重跑 lint／测试／构建，见该目录 README。`gr-agent` 仍为空包。

## 运行模式与公共工具

- 配置：gr-tools 提供无导入副作用的环境快照与日志能力（`gr_tools.config.setup_logging`），gr-data 保留数据模型，gr-api 组装 API／worker 配置，其他 CLI 按需加载；旧全量 Settings 已移除（D-002）。布尔环境键统一走 `parse_bool`，未知值直接报配置错误。
- 默认 worker backend 为 inproc；CI 默认仅 PG，手动 `extra_services` 可启用 CH／Redis。本地 `.env` 只存连接与凭证，未迁入源码或 YAML。
- Python 最低 3.11，开发默认 3.12；CI 跑 3.11／3.12，3.12 开启选股／诊断 PG 集成测试与 75% 覆盖率检查。
- 类型检查用 basedpyright（standard，全仓唯一，配置在根 pyproject）；存量错误记在 `.basedpyright/baseline.json`，CI 只拦新增。gr-tools 是否启用 strict 待定。
- `gr_tools` 的 `fs`／`human`／`io` 已于 2026-10-24～26 精简（删除的公开函数仓外调用方需迁移）；`io` 只用 Polars，Excel 经 fastexcel 读取，需要 pyarrow。

## 验证边界

- 历史记录中的主机路径、服务健康、凭证配置、数据行数均不能当实时事实；使用前查当前配置、代码或执行对应检查。失败时记录具体命令、日期、范围与原因。
- 最近全仓基线（2026-10-26，本机 Python 3.12，ETF／期权合并后的组合版本）：`uv run --frozen pytest -q -m 'not live_sdk'` 3557 passed／22 skipped／28 deselected／4 既有 xfailed；Ruff、495 文件格式检查、basedpyright 0 errors、迁移 lint（1 CH／50 PG）、`uv lock --check` 通过。去除供应商 token 和 `GETRICH_TEST_PG`，未连接工作库。约 44 条既有 warning（ORJSONResponse 弃用、mock 协程未 await）保留。
- 2026-10-27 远程 CI 两个 Python 版本都因回测产物 MIME 测试失败（[运行记录](https://github.com/getrich-2026/getrich/actions/runs/40457446826)），2026-10-28 已修正 `test_backtest_runs.py` 并随 `7b8e650` 推送；**待确认远程 CI 恢复通过**。
- 2026-10-28 提交前本机全仓（Python 3.12，排除 live_sdk，未设 `GETRICH_TEST_PG`，含一次性 Docker PG 用例）：3594 passed／22 skipped／28 deselected／4 既有 xfailed；Ruff、495 文件格式、basedpyright 0 errors、迁移 lint（50 PG）、`uv lock --check` 通过。

<a id="rq-three-model-history-20261022"></a>

已入库的米筐 units_evidence 引用本锚点，原章节现位于 [米筐验证记录](../../docs/history/2026-10-23-rq-risk-validation.md#rq-three-model-history-20261022)。

## 文档维护

- `AGENTS.md`：执行规则；本文：当前状态；`DECISIONS.md`：仍有效的取舍与防错理由。
- `docs/guides/`：怎么用；`docs/plans/`：未决问题与验收条件；`docs/history/`：已完成材料。
