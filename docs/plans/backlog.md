# 待决问题与后续工作

面向安排工作的项目维护者。本文只保留未关闭、可落实的实现缺口与待定口径，不是已批准的实施计划，不授权变更 API、schema、依赖或工作库。

基线核对：2026-10-28，静态核对代码、测试与设计。2026-10-30 补充两源真实字段、隔离 PG 与 P6 有界诊断，仅更新相应条目，其余问题未重新现场核验。当前采集进度与验收阻塞见 [NOTES](../../.agents/brain/NOTES.md)，实现取舍见[决策记录](../../.agents/brain/DECISIONS.md)。

## 持仓诊断与数据供给

优先补齐 gr-data 一期数据，再开放依赖它的指标。范围以设计仓的[范围决策](../../../getrich-design/governance/scope.md)、[接口设计](../../../getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md)及[一期数据集清单](../../../getrich-design/data-platform/portfolio-diagnosis-phase1-datasets.md)为准；相邻仓库链接用于本地双仓布局。

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| B、C、D 等计算未开放 | 2026-10-31 接口与 A 区已按新结构落地（`options`、重算、TopN 1/3/5、缺失档、范围校验），B/C/D 返回 `feature_not_available`。按 PA-04、PA-09～PA-12、PA-17～PA-20 在 `gr_api/diagnosis_calc/` 实现风险、相关性、Beta、回放与历史指标；完整组合模型指标要求全部正权重持仓数据有效（PA-13）；模型风险只用米筐同一模型／日期／版本，不回退历史协方差。L4 为最小扭转正交化后风险源方差份额的 HHI 倒数，配套市场源占比与最大风险源占比；验证方差守恒、近奇异及单位换算，历史分位按 PA-19 保持关闭 |
| D-022 发布清单与统一读取（2b）未落地 | 2a 的收据、run 绑定与双水位已有实现；下一步设计组成版本、发布／失效原子衔接和一致性读取，替换当前 `now()` 取数截止（原 D3）。数据库层拒绝 validation run，消费旧 run 禁用记录；组成变化后旧版本不可复算，不承诺恢复被 UPSERT 覆盖的历史值。验收前正式风险读取保持关闭。落地时同步：`services/diagnosis.py::_base_data_version_available` 现一律返回 False，`/recompute` 恒为 409；`diag.data_version.available_options`（051）尚无写入流程，行业体系与基准因此均按未验证处理；工作库 `diag.data_version` 只有 2026-08-30 种子行，诊断日期被钉在该日；米筐 v2 入库并发布后另发带 `model_id` 的口径版本（051 的 `forward_model_selector` 只记选择） |
| 回放仍缺分红送转事件、全收益基准与退市终止价值依据 | 完成 DS06～DS08 的来源、单位、时点与接入；停复牌及涨跌停沿用 [D-023](../../.agents/brain/DECISIONS.md#d-023)／[D-024](../../.agents/brain/DECISIONS.md#d-024)，不重复建来源。事件缺失不能填值继续回放，价格指数不能替代全收益基准 |
| 报告缺个股估值展示块 | `/result` 的 `instrument_facts` 已逐股给出总市值、PB、估值日期与 ROE 状态，但设计 §7.3.4 的报告块类型没有承载它，`/report` 暂不输出。需在设计仓补块类型后实现，前端在此之前从 `/result` 读取 |
| 行业与年度 ROE 数据未对齐 | DS11 核验 Tushare SW2021 官方代码与历史归属后显式转移表归属；DS10 核验 `fina_indicator.roe_waa` 单位，只取已披露完整年度加权平均 ROE。通过新迁移更新旧注释，不改已记账 SQL |
| P6 全区间与收益／暴露日期约定待确认（2026-10-30 有界样本数值自洽） | 固定 100 股三模型合计 500 个股日模型观测，以前日暴露、复权简单收益扣独立实际 3M 国债收益的 252 日复利日化值，复现 `r_excess_pct = 100·X_prev·f_decimal + u_pct`；原未复权价格收益与同日暴露反例保留。详见[迁移盘点](imac-collector-migration.md#字段互验与补充验证2026-10-30)。须取得供应商完整时间／无风险基准约定，并明确基准源值留存与历史可用时间，再扩日期／全区间；不把经验拟合成正式契约，不自动修改生产数据，保持 `calibrated=false` |

## 数据接入可靠性

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| 全供应商可靠采集尚未闭环 | 按[可靠采集实施计划](gr-data-reliability-implementation-plan.md)推进 A0 状态机、quarantine、开始记录／本地 spool、不可变观察、收据、防回退与发布；Tushare 最低门禁和米筐 2a 不代表整套协议完成。细项与故障用例在专项计划维护 |
| 停复牌空响应与观察时间语义 | 当日尚未发布的 `suspend_d` 空响应可能被记为已覆盖；局部重抓会刷新整月观察时间。纳入可靠性计划 C1／C2，区分未发布与合法空，保留分片观察／修订证据；估值交易日 17:00 的文档值不能冒充实际观测时间（原 T3） |
| Tushare 仍有 4 项 strict xfail | [回归用例](../../packages/gr-data/tests/test_tushare_review_findings.py)：#4 强制换源无日志、#5 坏日历误报缺失、#26 未知股票上市状态默认 active、#37 收盘价越过高低价范围。修复后移除相应 xfail，保留行为断言 |
| BJ 待处理项，后续单独核实（2026-10-31 用户调整） | 回补结束后用 `ops.tushare_bj_pending`、`bj-pending-months.json` 和最终汇总核对全部待处理记录的代码／日期／年月分布，区分数据集与源观察。集中在少数代码时，查证并修正有误的 `list_date`／历史上市区间、旧代码或复权来源，不长期依赖待处理；修正须保留证据并重验受影响观察。当前 920047.BJ 两条缺因子观察已转待处理，其他合格记录照常入库，股票回补已从 2010-04 恢复；不再以旧上市前隔离条件阻断 BJ |
| 日线重复键处理口径 | 当前按重复键保留最后一行（原 #35）；需决定冲突值是否拒绝或记录修订，覆盖同值重复、异值冲突与跨分区重放 |
| Tushare 字段审计后的缺口处理（2026-10-30 已实施，见 D-027） | 已落地：扩采集主数据与 fund_basic、档案表、ETF 分类、valuation_1d 专列、米筐期货合约参数。2026-10-30 已完成隔离真实采集验收（证据见 NOTES）。剩余：opt_basic 新字段的真实采集；可推导字段与 AH 盘后成交暂不采集；全历史覆盖仍未验收 |
| RiceQuant 字段审计后的语义与发布缺口（2026-10-30 有界真实互验完成） | 13 张风险表逐列、142 个模型因子字段、三模型原生响应→raw→隔离 PG 逐值与重放、120 日单位重测通过，证据见[迁移盘点](imac-collector-migration.md#字段互验与补充验证2026-10-30)。5 张动态平台证据表无 SDK 对应字段，以真实 DDL 和本轮现有事务／约束回归验证。待处理：`estimated_at` 实存观察时间、`model_version` 为本地版本、half_life/window_days 未填的消费语义；P6 全区间／约定及 D-022 2b 发布。初轮认证失败已由用户恢复，不再作为阻塞；互验不等于校准或正式发布 |
| 米筐补充数据准入仍排除 DataYes 重复项 | `gr_data/config/ricequant.py` 仍要求 `tushare_overlap` 和 `datayes_overlap` 均为 `distinct`；按 DP-02 确认去重门槛并同步配置、README 与测试，准入完成前不启用补充 writer |

DataYes 历史 SW14／SW21 切换仅在恢复该备用源时按 [D-013](../../.agents/brain/DECISIONS.md#d-013)处理；不作为当前采集前置。ETF／期权验收、全历史预算及分类更正的当前待办见 NOTES。

## 策略／信号接口与选股导入

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| 信号枚举域不一致 | `services/signal.py` 直传 DB 的 type／urgency，前端列表／详情类型与未读统计的 `normal` 分组不一致；确认真实取值及归一化责任，增加代表性响应契约验证，不依旧样本放宽联合类型 |
| 信号详情仍有数据占位 | `SignalDetail.tsx` 仍有 `spread_std`、`basis`、最佳／最差收益及关联信号的 TODO；逐项确认是否保留，保留项补来源与语义，取消项移除对应占位与需求 |
| 管理导入通道缺存储契约 | `services/admin_import.py` 使用 `import_jobs/import_job_errors`，现行 DDL 未定义；先决定是否保留该通道，再核对 `upsert_strategy` 列契约，保留时以新库端到端测试验收 |
| 历史代码别名与选股关联回填缺失 | 诊断已于 2026-10-31 改为先查当前代码、再查 `meta.symbol_map`，按 `instrument_id` 合并；选股导入仍仅查当前 `meta.instruments.symbol`；先定输入／回显契约，再按 `instrument_id` 合并新旧代码，补历史 `pick.item.instrument_id` 的幂等回填。验收含旧代码、新旧码同输、HTTP 契约及 PG 集成用例 |

接口类型以实际返回为准，按 [D-007](../../.agents/brain/DECISIONS.md#d-007)维护。

## 回测正确性

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| Black-Litterman 量纲与后验退化 | 按 [D-009](../../.agents/brain/DECISIONS.md#d-009)先确定 Q 与 Ω 口径；验收包含非退化后验及观点符号回归 |
| PostgreSQL loader 未完整适配 | `PgBarLoader` 仍拒绝 `oi`，未映射 `trading_status`，公司行为表入口仍报未接入。结合已有 `open_interest`、停复牌数据及待建事件契约适配，不能用全零持仓量或缺事件冒充有效数据 |
| 撮合与公司行为处理有偏差 | `api.py` 先撮合后处理公司行为、`_load_corp_actions()` 吞异常；`execution.py` 允许买价等于涨停价。按明确撮合规则补可核算回归，验证分红权益、失败传播和停牌／涨跌停边界；修复前不将真库回测视为已验收 |

诊断组合回放按 [D-021](../../.agents/brain/DECISIONS.md#d-021)另写，不复用上述撮合路径。
