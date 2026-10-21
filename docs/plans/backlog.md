# 待决问题与后续工作

读者：安排工作的项目维护者；Agent 仅在用户选择相关任务后读取对应小节。
状态：未决问题清单，2026-09-08 整理，持仓诊断小节 2026-10-20 按设计仓更新；不是已批准的实施计划，不授权变更 API、schema 或依赖。
“代码核对”表示本次只读确认；“历史记录待核验”不代表现网当前状态。完成后删除该待办，长期理由写入决策记录。

## 持仓诊断与数据供给

2026-10-20 更新：持仓诊断一期口径已在设计仓确认（[范围决策](../../../getrich-design/governance/scope.md) PA-01～PA-20，[表与接口设计](../../../getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md) v0.3.4），一期所需数据见 [一期数据集清单](../../../getrich-design/data-platform/portfolio-diagnosis-phase1-datasets.md)。设计正文以设计仓为准，本节只登记本仓实现与之对齐的缺口。用户已决定先完成 gr-data 一期数据；盲点阈值与画像规则等真实数据后再定。相邻仓库链接用于本地双仓布局。

| 问题／证据 | 下一步需要确定什么 | 完成条件 |
|---|---|---|
| 现有实现按旧设计：A 已有计算；B/D 曾以历史协方差为方向；C 口径未定（响应组装代码及最近交付记录） | 按设计对齐：模型风险统一用米筐同一模型、日期、版本，不以历史协方差回退（PA-04、PA-10）；PA-12 组合回放；历史回放 VaR/CVaR、回撤、个股历史波动率（PA-17、PA-18、PA-20）；历史分位一期固定不开放（PA-19） | 每个开放指标有数据依据，计算及不可用分支都有验证；与设计不一致处有记录 |
| 请求与响应契约落后于设计：缺 `options`（行业体系、基准、三个统计区间、建仓起点）、`POST /snapshots/{id}/recompute`、一期只诊断最新日期的 422、§7.3 新结构（TopN 三档、分布缺失档、个股估值与 ROE、个股及组合 Beta、回放序列、回撤明细、L4 配套指标）（代码核对待做） | 以设计仓表与接口设计 §7 为契约草案，核对路由前缀等现有差异后实施；`calculation_hash` 纳入解析后的 `options`（PA-15） | 生成的 OpenAPI 与设计一致或差异有记录；缓存按 `options` 隔离 |
| [D-017](../../.agents/brain/DECISIONS.md#d-017) 写“部分覆盖只在已知子集内归一化”；设计 PA-05、PA-07 要求带缺失档的分布单列缺失、不重新归一化，PA-13 要求完整组合模型指标任一正权重持仓缺数据即不可用 | 实施 PA-13 时同步修订 D-017，或记录保留差异的理由 | 覆盖率规则按 `coverage_groups` 配置执行，D-017 与实现一致 |
| L4 定义已改为最小扭转正交化后的风险源方差份额 HHI 倒数，配套市场源占比与最大风险源占比（设计 2026-10-20，见[计算清单 §4](../../../getrich-design/portfolio-analysis/持仓诊断_计算指标清单.md#4-分散度统计量l1l4)） | 按设计实现，并用米筐真实数据复跑模拟中的检查（方差守恒、近奇异、单位换算） | 结果与设计口径一致；特异波动率平方、期限一致已验证 |
| `diag.data_version` 仍依赖手动推进（040 迁移注释及最近交付记录）；设计要求记录各数据集自身的日期与版本、已验证可用的基准与行业体系（PA-15 B5），并能判断数据自某版本以来是否被修订（T22） | 2026-10-21 已定方向（[D-022](../../.agents/brain/DECISIONS.md#d-022)）：发布清单模型，gr-data 发布步骤写入；待设计表结构、失败与重试策略，与可靠性计划 B1 收据联动 | 数据更新可追溯到各组成部分版本；不会复用旧数据的计算缓存；区间重算能判断原版本是否可取得 |
| 回放所需数据缺表：停复牌、分红送转事件表在 DDL 中不存在；全收益基准与退市终止价值来源未定（清单 DS04、DS06～DS08） | 停复牌 2026-10-21 已定新建事件表（[D-023](../../.agents/brain/DECISIONS.md#d-023)）；分红送转建表；涨跌停沿用 `stock_bar_1d.limit_up/limit_down`；确定全收益基准与退市终止价值来源 | 回放执行与公司行动数据有单一来源与单位依据 |
| `fundamental.indicator_q.roe` 注释仍写“单季 vs TTM 未定”；设计 PA-07 已定为最近已披露完整年度加权平均 ROE（清单 DS10） | 接入 `fina_indicator.roe_waa` 时确认单位并更新注释与取数口径 | 只取年报记录，按公告日防前视 |
| 模型校准历史状态为 `calibrated=false`；本次未查真库。设计 DP-04 区分接入验证（单位、映射、顺序、跨表一致）与模型校准 | P6 的 `r = 100·X·f + u` 五表自洽校验；确认一期开放模型指标需要的是接入验证还是全区间校准，以及 `calibrated=false` 的披露方式 | 校验范围、量纲与容差有依据；开放条件与设计 DP-04 一致 |
| 当前 SW21 导入窗口历史记录从 2021-12 起；2021-08～11 存在体系切换（D-015）。设计 DP-02 已将 DataYes 定为第二档备用 | 仅在恢复 DataYes 时处理：拆 model_id 或调整版本建模；不能单方改 `factor.definition` | 每个 run 内因子集合及五张表逐日一致，跨体系不会混用 ordinal |
| 行业分类来自 datayes 一级暴露值（D-013）；设计 PA-05 定为申万一级、Tushare 优先 | 接入 `index_classify`（SW2021）与 `index_member_all`，核验官方代码与生效区间后转移表归属（清单 DS11） | 官方代码、层级、生效日期有真源，旧数据限制可追溯 |
| 米筐补充数据准入仍要求 `datayes_overlap=distinct`；设计 2026-10-18 起以 Tushare 数据契约为去重对象，DataYes 不再作为米筐准入的排除条件（[米筐方案](../../../getrich-design/data-platform/providers/ricequant.md)） | 是否调整准入配置与 README 描述 | 准入门槛与设计一致或差异有记录 |

### 2026-10-21 现有实现审核

只读审核诊断服务、Tushare 一期链路与米筐风险链路；P0／P1 已逐条对照代码或官方文档核实，未查真库、未调用供应商。P2 及以下暂缓。

| 级别 | 问题（位置） | 已定处理 |
|---|---|---|
| P0 | T1 `trading_status` 语义错：`daily` 全天停牌日无行，HALTED 只落在日内停牌日；抓取请求不存在的 `suspend_reason`、漏 `suspend_timing`（`raw/tushare/fetchers/market.py`、`ingest/tushare/importers/market.py::_trading_status`） | 抓取字段 2026-10-21 已改为官方字段（补 `suspend_timing`、去 `suspend_reason`），此前落地的 raw 需重抓；入库按 D-023 改事件表，未完成前 `trading_status` 语义仍错 |
| P1 | D1 风格分布覆盖率只看"有估值行"，PB≤0 或市值无效的持仓未计入缺失（`services/diagnosis.py::_style_distribution`） | 按实际覆盖权重判阈值 |
| P1 | D2 解析接受 ETF 与北交所个股并照常出数，穿透覆盖率显示 0%，违反 PA-01／PA-02（`_resolve_symbols`） | 范围外资产返回 422，删除穿透覆盖率分支 |
| P1 | D3 估值、行业、类别取数截止用 `now()`，与 `data_fingerprint` 脱钩 | 改用数据版本发布时刻 |
| P1 | D4 定性阈值写死（L2、HHI>0.25、最大行业>0.5），违反 PA-04／PA-05"另议" | 一期只展示数值，去掉画像标签与盲点定性判断 |
| P1 | T2 停复牌 raw 缺月时该月静默记 NORMAL，并覆盖库内正确值 | 缺分区时状态写未知 |
| P1 | T3 估值 `available_at` 恒为交易日 17:00，补抓历史被当作当时已知 | 记为已知限制（一期只诊断最新日，属 DP-03 最新数据描述分析）；实际观测时间随可靠性计划 C1 落地 |
| P1 | R1 米筐单位全靠配置声明，无量级兜底（`config/ricequant_risk.py`、`ingest/ricequant/riskmodel.py::_normalize`） | 阶段 3 加量级断言与期限一致检查，阈值用真实样本定 |
| P1 | R2 协方差只校验半正定（`raw/ricequant/risk_shapes.py`） | 阶段 3 改正定校验并记录条件数，近奇异阈值待定 |

2026-10-21 已定口径，已同步至设计仓 [范围决策](../../../getrich-design/governance/scope.md) PA-02（极小权重）、PA-04（未知代码时的分母、一期不输出定性判断，对应上表 D4）、PA-07（估值日期与时效）：
- 有未知代码时，TopN 以全组合原始权重为分母（85% 股票＋15% 未知 → Top1=85%）；HHI、L1、L2 在已识别部分内归一化，并按 PA-13 披露覆盖率。
- 估值不设时效上限，取不晚于诊断日的最近一条，逐股回显估值日期；早于诊断日的标降级。
- 量化后为 0 的极小权重按零权重处理：保留回显、不计入持仓数与计算。

主要 P2（暂缓）：分档参数超出两档时被静默截断、缺键静默用默认值；NaN／Inf 估值未防御；缓存键不含算法版本；披露语描述了未执行的回放；`updated_at` 不随 UPSERT 刷新；表归属 claim 先查后插无锁；米筐 `model_run.units` 未写期限、每日每次观察各一个 run；`adj_factor` 单次行数上限未核实。

数据接入历史规划为 P0–P2 已完成，P3 财报、P4 reference/macro/sentiment、P5 ETF/期权扩容、P6 校准。
这些是旧规划名称，不表示相关模块完全不存在；开工前对照 provider 的 raw／ingest 注册表检查具体缺口。
优先级建议由依赖决定：先按 [一期数据集清单](../../../getrich-design/data-platform/portfolio-diagnosis-phase1-datasets.md) 第 4 节的顺序补齐一期诊断所需数据，再决定 P3–P5 排期，不沿用旧的人天估计。

历史数据检查点（2026-08-31，未重新查库）：行情曾覆盖 2013-01-04～2026-08-28；
CNE6 可取起点曾核验为 2021-08-02，但当时一致的入库窗口为 2021-12 起。
不保留行数、凭证已配置或“服务 healthy”作为验收依据。重跑方法见 gr-data 手册，分批限制见 D-016。

## 策略／信号接口与选股导入

| 问题／证据 | 下一步 | 完成条件 |
|---|---|---|
| `services/signal.py` 直接返回 DB 的 type／urgency；前端联合类型与后端 `normal` 分组不一致（代码核对） | 明确真实取值域、产品含义与归一化责任 | 真实响应样本有契约验证，未知值显式处理 |
| 旧实测曾出现 `signal_type=stock`、`urgency=normal`（历史记录待核验） | 查询当前合法值；不据旧样本直接放宽类型 | 前后端同一枚举域，不再静默落入错误显示分支 |
| 信号详情的 `reason_detail.spread_std`、`market_snapshot.basis`、`historical_performance.best_return/worst_return`、`related_signals` 曾缺失（本次已核对 service 返回缺少这些字段，UI 待核验） | 确认功能仍需要，再核查 UI TODO | 字段有来源与语义，或明确删除对应产品需求 |
| 诊断路由已有 response_model，其他路由仍需逐个核查 | 决定是否补完整响应模型并生成前端类型；引入生成工具另行授权 | `/openapi.json` 能描述目标接口，CI 能发现契约漂移 |
| `admin_import.py` 使用 import_jobs/import_job_errors，DDL 未定义（代码核对） | 确认保留管理导入通道，再设计表与事务；一并核查 upsert_strategy 的列契约 | 新库上通道可用，有真实 PG 集成测试 |
| pick.item.instrument_id 的历史回填流程缺失（最近状态记录，开工前核查） | 明确调度与补映射范围，保留交易所码转换 | 历史记录能关联行情，重复运行幂等 |
| 成交流水与前端“开平配对回合”粒度不同 | 产品确认是否需要回合聚合 | 明确接口粒度与计算口径，不由前端猜配对 |

## 回测与维护缺口

- **Black-Litterman**：τ 在当前 Ω 取法下约掉，Q=score 的量纲未标定。修改前先决定模型口径，验收须包含非退化后验与观点符号回归（D-009）。
- **持仓量**：DDL 的期货／期权表已有 `open_interest`；`PgBarLoader` 却明确拒绝 `oi`（代码核对）。先决定 canonical contracts 与 loader 映射，不能继续用“整个 market 没有持仓量”描述问题。
- **公司行为**：`PgBarLoader._table_name_corp_actions()` 显式报未接入（代码核对）；需要先明确事件类型、PIT／复权语义和表归属，再设计 DDL 与 importer。已有 DataFrameBarLoader 输入方式不等于 PG 接入已完成。
- **撮合与公司行为缺陷（2026-10-21 代码核对）**：先撮合后处理公司行为，除息日开盘买入的股数也拿到分红，且测试固定了该行为（`api.py` 主循环、`test_backtest_corp_actions.py`）；公司行为加载失败被 `except Exception: return None` 吞掉；`PgBarLoader` 未映射 `trading_status`，读真库时停牌判定不生效；开盘价等于涨停价仍成交（`execution.py`）。不在一期诊断路径上（回放另写，见 D-021），修复前不要把真库回测结果当作已验收。
- **gr-factor**：测试目录只有占位 README（代码核对）；修复数值逻辑时同步补测试，并核查相关 NumPy lint 豁免，不单独为覆盖率填用例。
- **apps/backtest-web**：暂停维护且缺 `src/lib`；重做前先确认接口范围，不从主前端已升级推断它已完成迁移。
- **归档代码**：`archive/root-web-scaffold/`、`packages/gr-db/archive/legacy-sql/` 的保留期需另行决定；本次文档清理不删除这些代码。
- **环境类旧提醒**：Polars yanked、旧 CI 路径、旧端口／主机目录等需要基于当前 lock／工作流／部署配置重查；不再作为已确认失败留在 Agent 状态中。

参考：[决策记录](../../.agents/brain/DECISIONS.md)、[诊断调用指南](../guides/diagnosis-api.md)。
