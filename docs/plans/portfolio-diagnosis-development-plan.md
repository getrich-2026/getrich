# GetRich 组合持仓深化开发计划

**评审修订稿 · 2026-11-25 · 待负责人审定**　面向产品负责人和接手实现的开发 agent。实现基线为 `getrich dev@8cd5e9d`，设计基线为 `getrich-design master@0df17d5`。权重分母、发布事务、历史快照和验收库的约定写入对应工作包。文中验收均为开发交付条件。[当前状态](../../.agents/brain/NOTES.md) · [诊断 API](../guides/diagnosis-api.md)

## 1. 开发顺序与交付边界

**建议先批准 A 和 B 的覆盖预检。** A 能用现有快照立即做出一份可读报告。B 的扩面应由哪些完整组合被挡住来决定。C 先验证一个基准、一份数据及其日期，实测有可服务的诊断日，再做产品接入。

| 批次 | 用户要回答的问题 | 可验收的最小交付 | 依赖与停止条件 |
|---|---|---|---|
| A　仓位与风险 | 哪只股票、哪个行业承担的风险份额高于其仓位？差多少？ | 已登录用户从一份报告读到一句发现、一张可查的明细表和适用范围 | 只读现有快照。A 可独立交付，B、C 的数据缺口不阻塞 A |
| B　历史回放 | 这篮子股票在选定区间跌得最深时经历了什么？与所选基准相差多少？ | 扩大可回放组合的验证范围，给出回撤路径、组合及基准的区间收益，并解释缺口 | 覆盖盘点与 A 并行。先在已验收样本做计算和报告，再接当日数据发布。无真实样本的边界单列 |
| C　行业偏离 | 相对沪深 300，我的哪些行业多配或少配了多少？ | 数据可行性小样。通过后才交付同日、同分类的行业对照表 | 如权重日期、完整性、可用时点或使用权无法核实，交付缺口及命中日期，结束本批 |

**范围建议。** 使用现有沪深 A 股个股输入、1～5 个独立方案、每方案至多 100 个原始行。仓位分母是本次输入的股票组合。三批都在 `dev` 和隔离环境开发。A 的网页是验证报告的最小阅读入口。V1 标签、线上日更和云端发布继续按 D-032 管理。暂缓策略推荐、自动调仓、全市场公司行为回补、通用指标平台与全账户收益计算。[版本边界](../../.agents/brain/DECISIONS.md#d-032)

### 已有能力与本轮增量

| 已有能力 | 状态和使用方式 | 本轮实际要加什么 |
|---|---|---|
| 构成、Top 1/3/5 权重、HHI、按资金权重的有效持仓数、行业分布、市值/PB 分桶、个股财务事实 | 诊断基础结果已有，个别值可因资料缺失降级。沿用完整输入及未分类说明 | A 复用仓位、当日逐股行业和中文名称。C 复用组合行业权重 |
| 年化方差、年化／日预测波动率、逐股风险贡献／贡献份额／边际贡献、L3 有效数量 | V1 v3 发布准入上述 7 项模型指标。V2 v4 再增 L4 有效数量、市场源份额、最大风险源、风格暴露、模型相关性，共 12 项。当前模型披露 `calibrated=false` | A 只做两种份额的差与排序。沿用实际发布准入和模型披露 |
| 个股波动与相关性、组合历史净值、历史波动率、Beta、基准相关性、最大及当前回撤、历史 VaR/CVaR、调仓前后客观对比 | 能力分属不同层次，受数据发布、窗口和持仓覆盖约束。V2 本机此前验收覆盖三股、253 个净值点、三条全收益基准；这组样本不能代表其他组合 | B 补完整组合覆盖、回撤解释、同窗累计收益差。C 才引入外部成分权重 |

## 2. 批次 A · 仓位与风险贡献对照

**正常读法示例。** “甲股占这篮子股票资金的 10%，模型估计它贡献了 24% 的组合波动风险，高出仓位 14 个百分点。” 同屏提供模型日期、覆盖范围和未校准说明。单股组合、全部相等或只有负差值的可展示分组，用实际结果生成平实文字。

| 步骤 | 怎么做 | 输入与输出 |
|---|---|---|
| A1　算出明细 | 按 `plan_id` 独立处理。先核验完整输入和模型覆盖，再按冻结的有效计算证券对齐风险份额。下文固定展示权重及舍入口径 | 读 `plan.input`、`section_b.value.risk_contribution_ratio`、`model_coverage` 和发布的 `declared_metrics`。每行输出股票代码／名称、模型采用的资金权重、风险贡献份额及差值 |
| A2　行业与排序 | 行业内分别加总两种份额后作差。按未舍入的差降序，股票同值按完整代码、行业同值按行业代码。列出全部明细，首屏只摘一条 | 用固定 `instrument_facts` 的逐股归属和同快照的 `industry_distribution` 对账，`industry_labels` 仅供命名。体系不可用或无法还原当时逐股归属时，只展示逐股结果 |
| A3　交到用户手上 | 在已认证的 `GET /v1/diagnosis/snapshots/{id}/report` 增加可选 `detail=holdings`。在原有报告内按方案呈现，默认调用保持兼容。V2 联调页消费结构化报告 | 首屏为范围、最大差值及其原始两列、限制。展开可查其余股票和行业。负数表格用带符号数值。既有三个波动相关数字收进模型明细 |

**权重口径。** `input_weights` 还原完整原始份额，包括输入为正、按 8 位量化后归零的证券。先要求 `unresolved_weight == 0`、原始正份额无未识别项、模型 `status == complete`，原指标已准入且有值。行集合取 `calculation_holdings` 中计算权重大于零的 ID，要求与风险份额的 ID 完全一致。按证券合并后核对，避免一条零权重或重复输入行掩盖同一证券的非零持仓。

**舍入与披露。** `capital_weight` 取冻结的 `calculation_weight`，标签注明“模型采用的资金权重”。按现有 `quantize_weights` 核对原始份额与冻结整数单位，仅允许有 `zero_weight` 回显且按规则确实量化为零的证券缺行。原始输入仍可查，披露归零只数及合计原始份额。令 `n` 为合并后、量化前的正权重证券数，一个单位为 `1e-8`。按 Decimal 核对每股与原始份额的绝对差上限 `0.5 × n × 1e-8`，所有有效行的整数单位合计须为 `100_000_000`。例如两只股票原始份额为 0.999999999 和 0.000000001，模型仓位为 1 和 0，前者进入对照，后者留在输入披露；不得给它虚构风险份额。加测最大权重并列的尾差归属、缺少一只有效股票及真正未识别的微小仓位。[权重量化实现](../../packages/gr-api/src/gr_api/diagnosis_calc/weights.py)

**行业与旧快照。** 7.2 以前的载荷可被响应模型补出 `industry_code=None`。若冻结分布显示已分类行业有正权重，但逐股事实无法重建相应小计，行业对照返回 `unavailable/data_not_validated`，逐股对照照常读取。仅在固定事实和冻结分布能核对未分类桶时，才把确实缺归属的份额列入“未分类”。缺证据时也不使用今天的分类。测试旧快照默认空值、当日部分未分类、整组确实均未分类三种情况。[旧载荷约定](../guides/diagnosis-api.md)

**数值与状态。** API 返回小数份额，`gap = risk_share − capital_weight`。贡献及差值保留符号，页面只做一次百分点格式化。输入、证券集合、模型数据或舍入核验失败时给出原因，方差为零或数值非有限时整组不可用。可用但未校准的值继承原指标的降级。页面读取固定结果。

**验收样例。** 三只股票的资金权重为 10%、55%、35%，风险份额为 24%、80%、−4%。差分别为 +14、+25、−39 个百分点。前两只同属一个行业时，行业差为 +39 个百分点。完整组合的资金与风险份额各自合计约为 1，差合计约为 0。另测一只股票、多方案、重复及零仓位、未知股票、缺行业、并列、旧快照和未校准。使用者能指出哪一行支持结论，并说出本次覆盖的资产或模型局限。

## 3. 批次 B · 扩大可回放范围，解释回撤与基准差

### B1　先按完整组合盘点数据

以已有三股样本为对照，从授权试用案例或可公开复核的示例篮子选择下一组有实际缺口的组合。试用组合只在私有验证环境按匿名编号记录。**按组合计数**，记录目标组合数、扩面前／后能完整计算的组合数、每个受阻组合的窗口和首个缺口。一个正权重标的缺失就不能把其余股票重新归一化成整个组合。优先补能让一个完整组合首次可用的股票。

| 数据与粒度 | 取数、处理和证据 |
|---|---|
| 标的、开市日及行情 | `meta.instruments`、`meta.symbol_map`、`meta.trading_calendar`、`market.stock_bar_1d`。完整交易所代码映射本库 ID。按交易日读未复权开收盘、开盘买入判定所需的涨停价和状态，核对上市日期 |
| 停复牌与覆盖 | `market.stock_suspend_event` 与 `market.stock_suspend_coverage` 共同判断开市日是否已观察。分别保留停牌、首日涨停无法建仓、状态未知的处理结果 |
| 实施分红、送转及退市 | 复用 Tushare 逐股完整分红原件／收据、全量退市名录原件／收据；读取 `finance.dividend`、`finance.dividend_coverage`、`market.stock_delisting`。零事件也要有完整采集证据。记录事件数、规范化摘要、原件 SHA、观察时间和覆盖截止日 |
| 基准 | 复用 `market.index_total_return_1d`，按已选全收益指数 ID、版本、交易日读取 `simple_return`。复用整版内容哈希校验。指数价格日线不能替作全收益序列 |

覆盖核验至少覆盖正常建仓、实施分红／到账／再投资、停牌后复牌、开盘涨停延迟买入、退市无可靠终值及观察中断。每种场景分别标明“真实原件已覆盖”或“仅固定测试覆盖”。对于发布证券池已排除的退市样本，用隔离历史回放验证截断，不为测试放宽现行证券池。

### B2　把新范围纳入可重放的日更版本

1. **取数与预检。** 给现有日更 `prepare` 增加可选回放证据包输入。对 Tushare 全退市原件先运行 `read_delisting_coverage`，核对原件字节 SHA-256、总行数、分页终止、唯一源代码、观察时间及退市日期。由完整原件按历史身份生成准入证券的 `delist_dates`。经核实的代码在完整名录中查无记录，才可记为 null。
2. **生成版本。** `prepare` 将范围、`through_date`、逐股 `dividend_sha256`、`dividend_signatures`、整份 `delisting_sha256`、逐股 `delist_dates` 和所选基准版本绑定到冻结产物及其 `artifact_hash`。保持旧 `pa12-local-v1` 清单可读，新清单若变更结构则增加明确版本分支。读端按完整持仓逐项核验。
3. **限定退市写入范围。** 在 `replay_actions.py` 增加日更专用入口或显式模式，保留原有严格导入行为。整份原件保持原样，在已核验业务范围内按 `meta.symbol_map` 的 Tushare 身份、历史有效代码、证券类型及交易所筛出已映射沪深 A 股退市记录，再以整份原件的 SHA 写 `market.stock_delisting`。只看后缀无法排除沪深 B 股。对范围外及未映射项分别记录数量、原因和可追溯的仓外明细；准入证券自身有映射歧义、日期冲突或原件有记录而库中缺行时拒绝其证据。至少一条真实退市记录须能按该 SHA 从库中核验。若可写行数为零，本包不能开放回放，已承诺该能力的候选发布应失败。验收样例同时含已映射退市 A 股、在市 A 股、范围外及未映射证券；另测全都不可写。数据库匹配一行与逐股的正／负证据须分别验证。[导入器](../../packages/gr-data/src/gr_data/ingest/tushare/replay_actions.py) · [回放读端](../../packages/gr-api/src/gr_api/services/diagnosis_replay.py)
4. **固定发布事务的顺序。** 见下表。逐项构造或重验当日回放、基准和 C 的行业权重。沿用旧基准也要核对身份、完整内容和新窗口。候选包一旦包含某项输入，`apply` 遇到失配时整笔回滚。预检没有该项时可生成明确关闭此能力的新版本。成功后的同包重放应为零写入。

| 同一事务内的顺序 | 约束与验收 |
|---|---|
| ① 取得现有发布锁，校验前一版本、基线指纹及源归属 | 在首次可能创建 chunk 的写入前显式设置 `SET LOCAL timescaledb.enable_event_triggers = 'on'`。同时覆盖独立调用的 `import_total_return` 写入路径。使用调用方的同一连接和事务 |
| ② 写基础表，再导入分红、退市与全收益序列，完成风险输入写入 | 所有可能首次 `OwnershipManager.claim` 的操作放在签收**之前**。同源已有归属走只读核对。归属变化可使所有 `ops.diag_input_head` 标脏，重新取得本次全部组成的当前 revision；完成可选输入和 C 的当日分类核对 |
| ③ 对本发布的基础组成调用 `accept_input`，再签风险组成并准入 | 对实际写入后的事实签收，核对本次发布依赖的 head 全部干净。签收后至提交前无归属补写或其他会重新标脏的业务写入 |
| ④ `publish_version`，触发约束并验证有效性，最后提交 | 验证新建 chunk 有已启用的 `diag_chunk_truncate`、`diag.publication_is_valid(new_id)` 为真。注入失败后对比旧版有效性、收据、归属、事件与基准行，均须回到事务前。成功另验同包重放 |

现行 057 仍检查 `_timescaledb_internal` 下每张普通表的保护触发器。058 建立的全收益超表采用一年分块，其写入无需先经过受保护基础表。**跨年回归须证明实际新建了 chunk**：先用已登记归属、无先前基础表写入的连接单独调用导入器，再测日更内首次认领归属。分别核对新 chunk 的触发器及目标发布有效性。缺触发器期间全局有效性检查会失败；已提交的 `diag.data_version_invalidation` 则会持续使所涉版本失效。两种结果在验收中分开判定。[发布屏障](../../packages/gr-db/src/gr_db/ddl/postgres/054_diag_publications.sql) · [现行有效性判断](../../packages/gr-db/src/gr_db/ddl/postgres/057_diag_v4_model_metrics.sql) · [全收益超表](../../packages/gr-db/src/gr_db/ddl/postgres/058_total_return_benchmark.sql)

**从 B2 起收紧整个 `GET /v1/diagnosis/options` 响应。** 服务端继续用完整内部清单计算，对客户端按字段构造 `available_options` 及顶层 `publication_scope`。保留版本、日期、模型和准入指标、既有公开证券 ID 清单、可选行业体系和全收益基准标识。回放只给可用状态、覆盖证券数及截止日；C 只给可用基准和生效日。旧版与新版的逐股 `dividend_sha256`、`dividend_signatures`、`delist_dates`、私有原件路径及组合清单都留在服务端，不在嵌套键旁路透出。查清旧客户端对公开字段的读取并更新接口指南。用小范围及千股样本对比响应序列化字节数；合法的公开证券 ID 清单可以增长，回放摘要不能随股票数逐项增长。保留切回页面时刷新发布日期的能力。

### B3　计算与呈现

| 展示项 | 算法与边界 | 用户可以核对什么 |
|---|---|---|
| 最大回撤路径 | 复用 `max_drawdown.value` 中的幅度、峰值日、谷底日、恢复日和 `duration_days`。持续时间为峰值到恢复日的交易日间隔，未恢复则到窗口最后可靠收盘。窗口跨过回放截断日时沿用现有不可用语义 | 展示跌幅、发生日期、恢复状态和交易日数。零回撤显示“窗口内无回撤”。不足 120 个收盘点继承降级，少于两点不可用。曲线止于最后可靠收盘并说明原因 |
| 同期收益差 | 令 `S,E` 为已解析统计窗口的首、末交易日收盘。组合累计简单收益为 `NAV(E)/NAV(S) − 1`；全收益基准为 `∏(1+r[d]) − 1`，仅取 `S < d ≤ E`；两者相减得百分点差。按已验证日历逐日匹配，需两个可靠收盘、至少一个完整区间。区间内缺日、基准版本不符或越过截断日则该对照不可用 | 同时显示起止日、组合累计收益、所选全收益基准名称和累计收益、差值及观察数。基准缺失时，仍可显示独立可用的组合净值／回撤。切换基准不能改变组合曲线 |
| 回放说明 | 沿用 PA-12 建仓后买入持有、权重自然漂移、税前分红再投资、小数股、现金不计息、未扣成本等约定。权重和现金流按现有回放引擎处理；改变统计窗口只裁窗口，保留原建仓状态 | 标注“这篮子股票的假设历史回放”，日期与输入范围可见，截断、未成交与样本不足有各自说明 |

**容易算错的一天。** 现有 Beta 等统计以日收益的归属日取样，包含窗口首日从上一收盘到当日的收益。新增累计收益从窗口首日收盘起，必须从下一交易日开始连乘。固定样例中组合净值为 1、1.02、1.0404，基准后两日各涨 1%，结果为 4.04%、2.01%、**+2.03 个百分点**。另给首日一笔很大的窗口前变动，结果应相同。周末、缺一个中间开市日、换基准、仅一天、负收益、零收益和截断均覆盖。

**基准读取与窗口。** 收益对照成功时，`window_actual=(S,E)` 表示首末收盘日，`sample_count` 是 `S < d ≤ E` 的完整交易日收益个数。上例有三个收盘点，样本数为 2。新增带状态的基准读取结果，包含冻结的代码、名称（无名称时显示代码）、版本、日收益及失败原因。从同一已发布版本取身份，不在读旧报告时查当前名称。现有 `fetch_benchmark_returns` 在整版核验后只裁闭区间，窗口中间缺一天仍可返回非空字典。保留既有个股和组合 Beta 对共同有效日期的配对行为，在累计对照处才要求交易日集合完整。

| 基准状态 | 收益对照的返回约定 |
|---|---|
| 未选到可用基准 | `unavailable/benchmark_missing`，保留目标区间，样本数为 0 |
| 已绑定版本无记录或整版内容哈希失配 | `unavailable/data_not_validated`，说明版本无法验证，样本数为 0 |
| 版本通过核验，窗口缺一个或多个应有的日收益 | `unavailable/history_insufficient`，说明缺失交易日及数量，样本数为已验证的配对数。不可用时省略 `window_actual`，不把不连续数据写成连续的实际区间 |

**重算按方案复用。** 同一有效数据版本、同一持仓、`replay_start` 相同，只改 `stats_window` 或基准身份／版本（含二者同改）时，按 `plan_index` 读取已固定的 `replay_state`，重新裁窗或换基准。测试中验证回放读端调用数为零且净值序列逐点相同。原方案因覆盖不足等原因确实没有回放状态，沿用该方案的正常不可用结果，其余方案继续；显式传递该状态，避免用 `None` 误触发重新回放或整请求 409。原来成功的回放若声称有状态但证据缺失或损坏，走已有不可复现错误。原版本失效仍返回 409。改变建仓日起点时按原固定版本重新建仓，另测一份多方案混合结果。

**单日边界。** 显式请求窗口须有 `start < end`，解析后至少跨两个开市日。`replay_start == as_of` 且省略统计区间会生成首末相同的默认窗口，在 `_resolve_options` 进入响应模型校验前返回带参数位置的 422。加测提交与重算两条入口。“只有一个可靠收盘点”属于纯函数或合规请求中途截断，指标走样本不足或回放截断语义。

**回撤验算。** 连续四个交易日收盘净值为 1.00、1.10、0.88、1.10。峰值在第二日，谷底在第三日，最大回撤为 −20%，第四日恢复，持续两个交易日间隔。若窗口结束于第三日，应显示“截至第三日尚未恢复”，持续一个交易日间隔。

**批次完成条件。** 至少给出一个此前不可用、扩面后完整可用的实际案例并独立复算，再给出一个仍应不可用的对照。真实案例不足时，如实交付覆盖盘点和已通过的软件用例，保留“扩面尚未实证”状态。

## 4. 批次 C · 只试一个基准的行业偏离

**C0 为独立可交付工作。** 先给一张日期命中表，列出试验期内的目标诊断日、权重原件中的实际日期、当时何时可获得、同日可用与缺失原因。取至少一个有快照和一个没有快照的诊断日；跨一次成分调整核对成员身份。历史实验固定当时可用的发布和分类，无法证明当时可知的样本仅作事后研究。Tushare 将 `index_weight` 标为月度数据，返回字段为 `index_code/con_code/trade_date/weight`。官方示例中的返回日期也提示应检查每行的实际日期。仓中米筐 `rq_index_weights` 的现有契约面向特色 `.RI` 指数，不能据此认定沪深 300 已有已验收日权重。[Tushare 官方接口](https://tushare.pro/document/2?doc_id=96) · [现有米筐接入范围](../../packages/gr-data/README.md)

1. **先判数据能否使用。** 核实权重指数与当前默认沪深 300 全收益序列 `H00300.CSI` 的对应关系、源单位、精度、全成员集合、缺页和调整日，分别记录权重生效日、供应商发布时间（若提供）与本地观察时间。保存获取和派生展示使用依据。若只能覆盖少数月末，负责人根据日期命中表决定是否值得做 C1。日频需求留作单独的数据源决策。
2. **归一化与可追溯性。** 原件按 `RawPaths` 写 zstd Parquet，保留源代码、日期和权重原值。自然键为源指数代码 × 生效日 × 成分代码。映射本库证券后拒绝重复、歧义、无效值。把已核验的单位转换为小数份额，用源精度确定合计容差，验证成分集合和计数。总和接近 1 单独不足以证明完整。明确记录分类映射、源摘要、方法版本和分类时点，以同一原件可独立复算为验收。
3. **行业聚合。** 库内按 `scheme_code='sw2021'`、`level=1` 查询 `classify.instrument_industry`、`classify.industry_node`，Tushare 请求的 `src` 才写 `SW2021`。使用 `in_date ≤ D < out_date`（或开放结束日）及发布截止时间。基准成分逐只归类，组合使用完整原始输入份额逐股加总。基准和组合的行业取并集，两边均完整时，某行业确实未持有可记为 0。输出组合权重、基准权重与 `active_weight = portfolio_weight − benchmark_weight`。如银行业为 30% 对 18%，显示 **+12 个百分点**。
4. **发布与读取。** 首版只消费一个基准的一组行业小计。将小计、源哈希、有效日、截止时间、分类／方法版本和验证结果随当日 `diag.data_version.available_options` 固定，纳入既有发布哈希。在 B2 的发布事务内复核冻结原件与当日分类。API 计算时取固定版本，写入新快照的可选行业偏离结果。读报告不回查最新成分。只向客户端公开必要的基准、日期和状态。
5. **不可用的情形。** 权重日与诊断日不同、所选基准不受支持、必要数据晚于截止时间、成员不全、行业归属缺失或多个有效归属，都给出具体原因。保留原始组合行业分布。一个发布只选一个权重来源。首版不前填月度权重，不从指数收益反推成分，不恢复 `062` 已退役的 `market.index_component`。

**C2 的完整分母门禁。** `compute_exposure` 现有参数只有已识别子集内的归一化仓位。由 `_compute_plan` 将 `input_weights(item.summary)` 还原的完整正份额、未识别项和当日逐股归属传给行业偏离纯函数。原始正份额证券（含 A 中量化归零者）均须有有效行业；必要时按完整 ID 集合取当日归属。读端的 `apply_exposure_coverage` 在当前请求上独立核验 `resolved_weight < 1` 或存在未识别正份额，整体返回 `unavailable/coverage_below_threshold`。专门处理这项完整组合指标，普通分组的 80%／95% 阈值和降级路径不适用。80% 银行＋20% 未识别、基准银行 18% 的用例必须无偏离值；完整 100% 银行且基准相同时才是 +82 个百分点。

新载荷写状态明确的指标，历史 JSON 兼容字段缺失和显式 null。在 `apply_exposure_coverage` 的 `has_value` 调用及 `_plan_issues` 的状态索引之前分别处理缺值。测试旧载荷经模型默认值展开后，`/result`、`/report` 和 `/data-quality` 都能正常读取；已有行业分布的覆盖口径照原规则展示。[覆盖率合成](../../packages/gr-api/src/gr_api/diagnosis_calc/coverage.py)

**C 的数据库决策。** 本轮推荐新增表 **0 张**。A 用请求和结果中已有的事实；B 用四张已有的回放／基准表及已有行情、停牌和发布表；C 的原始证据存仓外，供应用读取的行业小计随 PostgreSQL 不可变发布版本保存。用户报告仍属于原快照。出现第二个确需逐股历史权重查询的消费者时，再评审独立成分表、索引和保留期。[数据库职责与迁移规则](../../AGENTS.md) · [发布清单实现](../../packages/gr-data/src/gr_data/diagnostic_publication.py)

## 5. 工作包、文件所有权与交接顺序

下表路径相对于 `getrich/`。为便于派工，`API` 指 `packages/gr-api/src/gr_api/`，`DATA` 指 `packages/gr-data/src/gr_data/`，`WEB` 指 `apps/web/src/`。带“新增”的文件是建议落点，其余均为现有文件。一个人可以连续承担多个角色。

| 工作包／负责人 | 主要改动文件 | 输入、交付与交接 |
|---|---|---|
| A1–A2 · 计算 | 新增 `API/diagnosis_calc/holding_risk.py`、`packages/gr-api/tests/test_diagnosis_holding_risk.py`。复用 `API/services/diagnosis_scope.py` 与 `API/diagnosis_calc/weights.py` | 交付带数值例的纯函数，区分原始份额、有效计算证券、真实未分类和旧快照行业证据缺失 |
| A3 · 接口整合 | `API/schemas/diagnosis_response.py`、`API/services/diagnosis_presentation.py`、`API/services/diagnosis.py`、`API/routers/diagnosis.py`、`packages/gr-api/tests/test_diagnosis_frontend_contract.py`、`packages/gr-api/tests/test_diagnosis_batch1.py` | 增加有符号的私有报告块和独立的分享投影，通过分享成功响应与旧版私有报告契约测试。有符号行使用专用字段 |
| A3、B3、C2 · 前端 | `WEB/pages/PortfolioDiagnosisPage.tsx`、`WEB/types/diagnosis.ts`、`WEB/api/diagnosis.ts`。建议新增 `WEB/components/diagnosis/HoldingsReport.tsx` | A3 将 `RiskMetric` 与 `metricLabels` 补齐至 v4 的 12 项，逐股事实补 `industry_code` 和 `industry_name`，行业区补 `industry_labels`，兼容旧快照空值。年化方差用同一快照 `/result` 的 `section_b.value.annual_variance`，按指标状态用方差单位展示。现有 `/report` 负责文字和报告块。沿用 React Query、已有请求签名、各状态及身份隔离，查询键含身份、快照、阅读级别、详情选项 |
| B1–B2 · 数据发布 | `DATA/diagnosis_daily/__init__.py`、`DATA/diagnosis_daily/cli.py`、`DATA/diagnosis_daily/collect.py`、`DATA/diagnosis_daily/evidence.py`、`DATA/diagnostic_publication.py`、`DATA/ingest/tushare/replay_actions.py`、`DATA/ingest/tushare/total_return.py`。复用 `DATA/raw/tushare/dividend_capture.py`、`DATA/common/replay_evidence.py`、`DATA/common/benchmark.py`。回放包可集中到新增 `DATA/diagnosis_daily/replay_inputs.py` | 交付覆盖盘点、退市范围审计、冻结包和事务验证。测试在 `packages/gr-data/tests/test_diagnosis_daily.py`、`packages/gr-data/tests/test_diagnosis_daily_pg.py`、`packages/gr-data/tests/test_diagnostic_publication.py`、`packages/gr-data/tests/ingest/test_replay_actions.py`、`packages/gr-data/tests/test_tushare_total_return.py` |
| B3 · 回放计算 | `API/diagnosis_calc/replay_section.py`、`packages/gr-api/tests/test_diagnosis_replay_section.py`。依赖现有 `API/diagnosis_calc/replay.py` | 按 S、E 两端收盘和开市日序列计算累计差，交给接口负责人包含完整、缺口、截断的样例。纯函数不发 SQL |
| B2–B3 · 接口整合 | 延续 A3 的接口文件，改 `API/services/diagnosis_benchmark.py`，核对 `API/services/diagnosis_replay.py`。测试 `packages/gr-api/tests/test_diagnosis_replay_reader.py`、`packages/gr-api/tests/test_diagnosis_pg_integration.py`、`packages/gr-api/tests/test_diagnosis_v1_scope.py` | B2 交付 `/options` 公开投影与大小对比；B3 交付有身份和状态的基准读取结果、`HistorySection` 可选收益对照、单日 422、逐方案重算复用。同步所有基准读取调用方和测试替身，验证旧 Beta 结果及旧回放清单 |
| C0、C1 · 数据发布 | C0 先留仓外日期／证据对照。通过后，建议新增 `DATA/raw/tushare/index_weight_capture.py`、`DATA/diagnosis_daily/benchmark_industry.py`、`packages/gr-data/tests/test_benchmark_industry.py`。沿用 B2 的日更文件和测试 | 采集只对一个已核实指数开放，复用现有源客户端、原件路径和日更 CLI。权重归一化、成员与分类核验、固定发布分开可测。交付一个同日通过和一个日期不符的版本。无需更改 `gr-db` |
| C2 · 接口整合与计算 | 计算负责人改 `API/diagnosis_calc/exposure.py`、`API/diagnosis_calc/coverage.py`；若集中处理空指标，同时改 `API/diagnosis_calc/metrics.py` 的 `has_value`。接口负责人改 A3 的模型、服务和 `_plan_issues`。覆盖 `packages/gr-api/tests/test_diagnosis_enhanced.py`、`packages/gr-api/tests/test_diagnosis_calc_boundaries.py` | 将完整输入分母独立传给 C2，核验前不出偏离值。覆盖 80%＋20% 反例、单边行业为零、换基准、旧快照缺字段／null 的三个读取接口 |
| 分批收尾 · 接口整合／设计维护 | `docs/guides/diagnosis-api.md`。设计确认后更新相邻 `getrich-design/portfolio-analysis/持仓诊断_计算指标清单.md`；C0 通过后同步 `getrich-design/data-platform/portfolio-diagnosis-phase1-datasets.md`。若改变已确认的产品范围，再更新其 `governance/scope.md` | 每批只记录已验证接口、单位、缺失和可用范围。公开文档只用合成或公开样例。产品试用记录、原件和许可记录按各自既有位置保管 |

**接力顺序。** 首轮可以同时派 A1–A2 和 B1，C0 可单独核验。A1 的输入输出确认后，接口负责人先给前端一份真实 schema 可校验的样例，再集成 A3。B3 计算可与 B2 发布并行，在 B 的端到端验收时会合。C1 依赖 C0 评审以及 B2 的版本生成方式，C2 再接已验证的小计。共享的 `diagnosis.py`、响应模型、路由和展示服务由同一接口负责人顺序修改；每日发布由同一数据负责人维护。每次交接附变更文件、测试结果、仍缺的数据或案例。

**版本与接口兼容。** A 只在读固定终态时派生，阅读偏好不进计算哈希。B 首次新增持久化结果时，从现有 `PAYLOAD_SCHEMA_VERSION = "7.5"` 升版，C 若独立交付并再扩持久化形状，继续按同一规则升版。新代码须读取旧 JSON，老快照不回填。派生项不加入 v4 固定的 12 项模型指标白名单。测试原默认报告、显式详情报告、跨用户访问及分享白名单；分享响应按嵌套区块检查，不自动公开逐股明细或私有诊断信息。重算沿用版本边界，失效原版本按现有语义拒绝重算。

**A3 分享成功响应。** 当前分享路由仅按顶层 `kind != "instrument"` 筛选。改为明确列出允许分享的 section 及各自允许的 block 类型，未知组合默认略过。有些现存 `metric_cards` 标签带单股名称，`text` 或不可用原因也可能带股票代码；用允许的组合级指标 ID 和可公开文案构造分享内容，逐股卡片、持仓明细、新增私有块和含私有标识的字段不进入输出。用有效分享 token 调用并断言 HTTP 200。核对现有可分享的组合统计和方法披露保留，私有块即便放在允许的 section 下也被滤除，且整份响应不含测试股票标识、输入权重、内部路径。另测失效 token、私有报告权限及安全响应头。将公开范围变化注明在接口指南。

### 建议先定下来的接口字段

下列均为**拟增字段**，供计算、接口和前端对齐。实现后以响应模型为准。沿用现有 `MetricValue` 的 `ok/degraded/unavailable`，缺值不编码为数字 0。

| 入口 | 建议返回 | 兼容与交互 |
|---|---|---|
| A · 私有详情报告的 `holding_risk_comparison` 块 | `stocks`、`industries` 分别包装状态和行列表。每行有对应股票或行业的代码、名称、`capital_weight`、`risk_share`、`risk_share_minus_weight`。报告沿用该方案的模型日、校准及覆盖信息 | 默认和分享报告不输出新块。A3 在结果就绪后直接展示第一条发现。原始三列一起可查。分类体系缺失时，逐股表和行业表可分别表明状态 |
| B · `section_c.value.period_comparison` | 单个带状态的对象内含 `portfolio_simple_return`、`benchmark_simple_return`、`return_difference`、基准代码、名称及版本。成功时 `window_actual=(S,E)`，`sample_count` 为两端收盘之间的开市日收益个数。不可用时使用 B3 表中的原因与样本数 | 现有 `options.benchmark`、`stats_window` 足以表达请求。V2 报告显示当前选择；切换已验证基准经现有 `recompute` 创建新快照再展示。图表缩放只改变视图 |
| C · `section_a.value.benchmark_industry_comparison` | 一个带状态的对象内含基准标识、权重生效日、行业版本及行列表。行含 `industry_code`、`industry_name`、`portfolio_weight`、`benchmark_weight`、`active_weight` | 仍按所选基准判断是否可用。`_plan_issues` 会遍历 A 区字段，新代码要处理老载荷缺字段或空值，继续正确生成 `/data-quality` |

## 6. 开发 agent 的验收清单

从 `getrich/` 根运行。下面是**实施时**需要执行的命令；新增测试文件在对应批次落地后运行。

```bash
# A 的数值、旧契约和私有报告
uv run pytest -q packages/gr-api/tests/test_diagnosis_holding_risk.py packages/gr-api/tests/test_diagnosis_frontend_contract.py packages/gr-api/tests/test_diagnosis_v1_scope.py packages/gr-api/tests/test_diagnosis_batch1.py

# B 的回放、数据读取、发布和幂等
uv run pytest -q packages/gr-api/tests/test_diagnosis_replay.py packages/gr-api/tests/test_diagnosis_replay_section.py packages/gr-api/tests/test_diagnosis_replay_reader.py packages/gr-api/tests/test_diagnosis_v2_2a.py
uv run pytest -q packages/gr-data/tests/ingest/test_replay_actions.py packages/gr-data/tests/test_tushare_total_return.py packages/gr-data/tests/test_diagnosis_daily.py packages/gr-data/tests/test_diagnosis_daily_retry.py packages/gr-data/tests/test_diagnostic_publication.py

# C 的来源、汇总、发布和历史报告兼容
uv run pytest -q packages/gr-data/tests/test_benchmark_industry.py packages/gr-api/tests/test_diagnosis_enhanced.py packages/gr-api/tests/test_diagnosis_calc_boundaries.py packages/gr-api/tests/test_diagnosis_frontend_contract.py

# 合并前质量检查
uv run ruff check packages/ scripts/
uv run ruff format --check packages/ scripts/
CI=true uv run --frozen basedpyright
uv run --frozen pytest -n auto --dist loadgroup -m 'not live_sdk'
(cd apps/web && npm run lint && npm run build)
```

上述本地全量 pytest 显式排除 `live_sdk`，真库启用变量仅在下方目标命令内设置。本地验收采用的筛选与 CI 分片及覆盖率任务分别记录。

**API 与日更测试使用两个独立的 PostgreSQL 数据库，同一实例内建两个不同库即可。** `DIAG_API_TEST_DB` 指向仅完成迁移的可丢弃测试库，无须发布基线。`DIAG_DAILY_TEST_DB` 指向独占的 `getrich_diag_*` 基线克隆，`DIAG_PREPARED_ARTIFACT` 中的 `prepared.json` 须与该克隆的 previous_version、输入指纹和证券 ID 分配相符。API 用例会提交主数据、日历的修改和清理，清理不会撤销已提交的发布失效记录，也不会倒退序列。日更用例成功后会推进发布；重跑整组从原始基线另起干净克隆。同一测试文件内新增的跨年场景用可回滚的事务或独立克隆，不得消耗其他用例的基线。[API 用例](../../packages/gr-api/tests/test_diagnosis_pg_integration.py) · [日更用例](../../packages/gr-data/tests/test_diagnosis_daily_pg.py)

```bash
(
  set -eu
  # 本计划的命名示例为 getrich_diag_api_contract 和 getrich_diag_daily_acceptance
  case "${DIAG_API_TEST_DB:?}" in getrich_diag_?*) ;; *) exit 2 ;; esac
  case "${DIAG_DAILY_TEST_DB:?}" in getrich_diag_?*) ;; *) exit 2 ;; esac
  test "$DIAG_API_TEST_DB" != "$DIAG_DAILY_TEST_DB"
  test -f "${DIAG_PREPARED_ARTIFACT:?}/prepared.json"
  PG_DB="$DIAG_API_TEST_DB" GETRICH_TEST_PG=1 uv run pytest -v packages/gr-api/tests/test_diagnosis_pg_integration.py
  GETRICH_DIAG_DAILY_DB="$DIAG_DAILY_TEST_DB" GETRICH_DIAG_DAILY_ARTIFACT="$DIAG_PREPARED_ARTIFACT" uv run pytest -v packages/gr-data/tests/test_diagnosis_daily_pg.py
)
```

| 验收层 | 需提交给审查人的证据 |
|---|---|
| 数值 | A 的有符号三股例、B 的两日收益例和回撤日期例、C 的行业对照例。用独立手算或直接对原件复算，给出差异与容差 |
| 发布与兼容 | 隔离库中一次成功发布、同包重放、一次触发失败后的原版本可用、前后两个日期的不同可用项。旧快照按旧版本读取，新快照复现结果。测试跨用户、默认报告、分享、仍有效的 202/错误回应与安全响应头 |
| 用户入口 | 用 V2 私有接口走 `/options → POST /snapshots → /result → /report?detail=holdings`，配对查看 `/data-quality`。用两个独立方案核对页面归属、百分号和百分点、缺失原因及小屏可读性。保留一份匿名响应或页面截图 |
| 产品审查 | A 看使用者能否指出一条持仓事实和一个限制。B 看完整可用组合是否增多、具体受阻原因是什么。C 看试验期内多少实际诊断日能返回同日结果。根据各批证据决定下一笔投入 |
