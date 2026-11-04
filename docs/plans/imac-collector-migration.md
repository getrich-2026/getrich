# iMac 采集主端：当前状态与下一步

面向采集环境维护者。2026-11-03 12:31 上海时间实查：股票及8核心指数均完成；ETF身份筛查1845只全完，4只转型候选已归类，统一登记提案待确认。ETF正式入库47/202月保持；raw已独立续跑，当前2014-05、共52/202月raw可用，不能当作正式验收。正式raw仍在myssd，数据库和Tushare运行账本在neoimac；用户确认机制后按月边界交接正式入库，后续期权仅raw／隔离验证。详情与证据见NOTES及运行账本。

**米筐工作库重放（2026-11-01 全量验收完成）**：D-030 显式映射不改原 raw／名单／源账本；固定独立副本 `f2dddc9` 完成三个模型各 676 个交易日、合计 2,028 模型日重放。逐值、覆盖、收据／绑定／检查点及各表总行数独立对账通过；旧 2024-12-11 v2 run 的 publishable=false 保留，替代观察选择正确，未新增工作库别名，calibrated=false，正式读取关闭。锁冲突已由 PG 日志定位为 Tushare 长事务归属 RowExclusiveLock 与米筐全表 ShareRowExclusiveLock 冲突，本轮通过既有任务锁互斥完成，未修改 Tushare 源码或已绑定 importer；任务退出已释放锁，Tushare 状态文件前后哈希一致。全量验收、逐日审计与版本／输入指纹在 `/Volumes/neoimac/data/getrich-runs/ricequant-replay-20261101/` 的 `full-replay-acceptance.json`／`days/`／`version-policy.json`。代码已随 rq-history 合入本地 dev，后台仍使用原冻结副本，未 push。

**2024 年前米筐 raw（2026-11-02，身份规则批准、七日重验通过、逐月探测进行中）**：新独立源码提交 `5598ed2` 已授权提交未 push，D-012 的上药实际请求码／普天单例边界及新 v3 variant 已生效，旧规则、raw 与账本不改。七个旧待审目标在新观察中全部通过，共同原数值逐接口一致；v2trd 的2011-04-28五件套及04-29四IPO恢复已确认。新运行目录 `/Volumes/myssd/data/getrich-runs/ricequant-history-20100104-20231231-20261102/` 的 `seven-reassessment.json`／`gate.json`／`state.json`／`run.log` 记录证据及实时状态，PID见 `background-process.json`；当前独立证据库仅capture。v2/v2trd须各完成2011-04～2023-12共153个月实际交易日样本，缺口或行业轴变化即停，不后移起点；全通过后已获用户授权自动按v2→v2trd→v1正式只采raw（候选起点2011-04-28／2011-04-28／2010-01-04），历史写工作库另授权且按月等Tushare及单位/数值验收。每天实查保留3%，首次次日续跑完成一个目标后保存 `first-next-day-resume.json` 并等待用户确认。行业轴一致未证明当时分类，可能为2021申万历史回套，回测须据此解读。169退市实体仅普天不一致，不推广+1；其公告PDF重试仍为HTML验证响应，上交所原页面／官方13条列表JSON／检索替代存档与SHA在 `/Volumes/myssd/data/getrich-validation/rq-history-identity-approved-evidence-20261102/archive-index.json`。原2024+2,028观察验收与正式读取关闭状态不变。

## 1. 已完成的准备

**指数2017-11缺口恢复（2026-11-02 20:55上海时间）**：原白名单请求在000016.SH缺22个交易日时按完整性门禁停止，未放宽检查。两次独立重查均完整22条且逐值/Parquet SHA一致；以原冻结运行源恢复控制器后，2017-11全月154条归一化/PG canonical/四价和量额检查通过，缺口22条与独立重查逐值相同。原94月已完成账本及raw、股票两批账本保持，其他规则与计划不改。当前指数已验收122/202月至2020-02、后台2020-03；后续ETF、期货、期权顺序及期权隔离验证边界不变。两次重查证据 `/Volumes/myssd/data/getrich-validation/tushare-index-gap-201711-20261102T124632Z/probe.json`，备份/启动/运行验证收据 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/index-gap-resume-201711-20261102.json`。

股票回补终态汇总 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/alias-rule-summary.json` 已标final，按原规则区分重放审计事件与唯一字段命中，含代码/日期分布。上市前隔离为0条；BJ待处理91177条/241个代码仍待单独核实，未因回补完成而转为正式合格记录。


**沪市双精确哨兵与双月重验恢复（2026-11-02，用户授权，[D-024](../../.agents/brain/DECISIONS.md#d-024)）**：仅沪市六位 `.SH`、源上限精确 `10000.0`、源下限精确 `0.001` 或 `0.01` 三条件同时满足时 NO_LIMIT／NULL，取代原单一组合；原 `up≥99999` 阈值不降。深市／北交所的10000组合在BJ行级待处理之前整批停止，近似值、单侧及未知组合仍停，不类推深市退市整理首日。独立提交 `0acd712453d1ef44c5dd74ae0b102cd3b060b0d4`，未 push；仅两份授权运行源码更新，既有换码／IPO限价缺行／B股／米筐工作区修改保留。343项组合回归、隔离提交52项回归、改动文件类型／Ruff／格式及部署门禁通过。

启用前盘点的181个`stk_limit` raw分区经投影查询仅有两条up=10000观察：600610.SH／2020-08-17下限0.001、600145.SH／2022-03-30下限0.01。后者的[2022-038](https://static.cninfo.com.cn/finalpage/2022-03-23/1212644112.PDF)／[2022-040](https://static.cninfo.com.cn/finalpage/2022-03-30/1212725521.PDF)确认03-30退市整理首日无涨跌幅、之后10%；[2022-031](https://static.cninfo.com.cn/finalpage/2022-03-04/1212502190.PDF)确认03-03起停牌。PDF原件、页码、SHA、直接证据与停牌边界推导的区分，以及旧600610两份已核验公告副本均在`/Volumes/myssd/data/getrich-validation/tushare-sh-exact-sentinel-evidence-20261102/`；旧冻结证据未改，原值不是由公告补造。

2020-08四表canonical、价格与两轮幂等通过，全部业务字段与原验收指纹不变，LIMITED=82102、NO_LIMIT=194，90条创业板1e6/0.01全部NO_LIMIT。2022-03四表重验通过，仅600145.SH／03-30 UNKNOWN→NO_LIMIT，其余业务值和键集合不变；03-03～29共19个交易日由日历／覆盖／S事件共同推导HALTED、无bar，03-30及03-31为NORMAL，03-31限价0.31/0.25。两月raw哈希、BJ待处理幂等均通过。逐条审计与业务共事务；新规则`sh_exact_pair_10000_down_0001_or_001_no_limit`，旧`exact_pair_10000_0001_no_limit`审计保留，月报`exact-no-limit-sentinel-months.json`逐条列代码日期、原值、公告、处理规则及事件数，不把重导次数冒充唯一命中。

原146月（含2020-08）和近期34月完成账本保持；旧月重验另存`sh-exact-sentinel-reacceptance-20261102.json`并登记`historical_month_revalidations`，仅待审2022-03新验收为第147月。只读运行源`/Volumes/myssd/data/getrich-validation/tushare-sh-exact-sentinel-source-20261102T062404Z`；审核`approved-source-change-sh-exact-sentinel-20261102.json`（SHA `6be3661d002e700d82f03eda8585f7ec0d8262e535f40cbb32c630f39e7f266b`）、注册/备份`sh-exact-sentinel-source-registration-20261102.json`、启动`sh-exact-sentinel-background-process-20261102.json`均在早期股票运行目录。已从2022-04续跑，后续指数→ETF→期货→期权仍等全部股票；期权正式写入门禁不变。


**招港 B 精确范围单例与恢复（2026-11-02，用户授权，[D-029](../../.agents/brain/DECISIONS.md#d-029)）**：仅新增 `201872.SZ`，且排除前必须查询确认当前 Tushare 来源映射不存在；已有映射、查询失败或无法查询均停止，不建 B 股身份、不映射 A 股。常规 `200xxx.SZ`／`900xxx.SH` 不变，不扩大到 `20xxxx`，`201873.SZ` 等相邻未知代码仍停止。依据为[招商港口 2018-124](https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF)及[深交所 2018-12-21 公告](https://www.szse.cn/disclosure/notice/general/t20181221_563712.html)：2018-12-26 B 股由 200022 换为 201872，证券类别不变。原件及 SHA 在 `/Volumes/myssd/data/getrich-validation/tushare-b-share-201872-evidence-20261102/evidence.json`。本次独立提交 `45a68ff8254a25b2348aa78ba46c1912a8dd1014`，未 push；包含尚未提交但使规则独立可运行的 B 股过滤基础及直接接入，排除其他换码／限价／米筐变更。

全 raw 库存按 `2026-11-02T02:18:49.894480+00:00` 枚举，扫描 235,565 个文件和 7,017 个唯一代码。逐文件清单、分块扫描结果、代码清单、候选与动态暂存边界见 `/Volumes/myssd/data/getrich-validation/tushare-b-share-exception-scan-v2-20261102T021849Z/summary.json`。对已封存 Parquet 检查代码列值、代码列名与文件身份，结构化清单检查全部代码字符串；不修改源文件，扫描后新采集文件不属于这一时点库存。没有自动纳入其他非常规 B 股。另有 `990018.XSHG` 仅见米筐供应商快照元数据，实际 Parquet 代码列中为零；其旧／新实体日期与上港历史吻合仍是供应商身份推断，不能确认为 B 股或批准别名，不作排除、不建映射。原始符号不改，补证在同证据目录 `990018-review.json`。

2020-09 四 writer canonical 全字段、持久化价格及两轮幂等通过；`201872.SZ` 在重验前后均无证券或 Tushare 映射，`001872.SZ` 身份和映射不变。09-18 估值接口的 38 只 B 股观察全部按范围外事务留证（37 个常规段加该单例），收盘价／估值／股本为空，但 `volume_ratio` 有值，审计逐行保留源值；重导不增加范围外审计。每月明细在 `b-share-scope-months.json` 及 `state.json` 各月 `b_share_scope`，源观察与目标审计事件分开统计。原 128 月、近期 34 月完成账本和原 raw 哈希未改，仅将失败的 2020-09 按新规则验收。

329 项组合回归、隔离“HEAD 加本次提交”43 项回归、改动文件 Ruff／格式／类型及接续部署门禁通过。只读运行源 `/Volumes/myssd/data/getrich-validation/tushare-b-share-201872-source-20261102T024722Z` 仅 stock_scope.py 比前版审核源改变，Python 其余文件／DDL／lock／数据库目标不变。新审核 `approved-source-change-b-share-201872-20261102.json`，SHA-256 `6cb9edbbc23e0da394040c087d1e21aa03b107153166251c489af29322c176b0`；验收 `b-share-201872-september-acceptance-20261102.json`、注册／备份 `b-share-201872-source-registration-20261102.json`、启动 `b-share-201872-background-process-20261102.json` 均在早期股票运行目录。已从 2020-10 续跑；后续指数／ETF／期货／期权继续等待全部股票验收，期权正式发布门禁不变。

**恢复上市精确哨兵与恢复（2026-11-02，用户授权，[D-024](../../.agents/brain/DECISIONS.md#d-024)）**：仅新增源数值双侧精确 `(10000.0, 0.001)` 为 NO_LIMIT／NULL，原阈值不降，单侧／近似／其他未知组合仍停报。精确匹配在 float 转换前用源值 Decimal 比较，避免近似文本被转换舍入；`ops.data_quality_check` 的 `tushare_stk_limit_exact_no_limit_sentinel` 逐代码日期记录原始上下限、规则、批次与公告链接，与业务写入同事务。规则独立提交 `7361d30f0ed26ac7aab1aee3eef0ecf541b2fee9`，未 push；五文件提交仅含本条规则／独立测试／D-024 与 README 增量，其他原有 B 股／换码／上市首日缺行／米筐工作区改动保留。

600610.SH／2020-08-17 的两份发行人原公告已实际下载核验：[2020-048](https://static.cninfo.com.cn/finalpage/2020-08-11/1208149410.PDF) 确认恢复上市日期、首日不设涨跌幅和参考价 3.26，[2020-050](https://static.cninfo.com.cn/finalpage/2020-08-17/1208182631.PDF) 再次确认首日无涨跌幅、次日起 5% 限幅。PDF、提取文本、SHA-256 与检索凭据位于 `/Volumes/myssd/data/getrich-validation/tushare-exact-sentinel-announcements-20261102/`；SSE 050 直接请求未返回 PDF，因此采用有效的 cninfo 原件，不将失败下载当验证成功。

2020-08 四 writer canonical 全字段／价格／两轮幂等通过。状态分布 LIMITED=82,102、NO_LIMIT=194、UNKNOWN=0；其中 103 条 100000／0.01、90 条创业板注册制新股 1000000／0.01 和 1 条精确新值对均已逐值对应，90 条创业板代码日期全部 NO_LIMIT。唯一状态变化为 600610.SH／2020-08-17 UNKNOWN→NO_LIMIT，其他业务列指纹、各表业务键和 raw 哈希不变。新精确值对唯一命中 1 次，两轮业务导入产生 2 个审计事件；每月在 `state.json` 各月 `exact_no_limit_sentinels` 与 `exact-no-limit-sentinel-months.json` 记录唯一命中、代码数、事件数及代码日期原值。此前 127 月和近期 34 月完成账本不改，仅将待审 2020-08 按新规则验收。

308 项组合回归和“HEAD 加本次提交”隔离副本的 48 项回归通过；改动文件类型、Ruff／格式及接续部署门禁通过。只读运行源为 `/Volumes/myssd/data/getrich-validation/tushare-exact-sentinel-source-20261102T000359Z`，语义为原已审核源码加本次提交的精确增量；除 market.py 和新增 limit_sentinels.py 外，其余 Python／DDL／lock／PG 目标保持旧审核指纹，其他并行工作未纳入本次运行。新审核为历史股票运行目录 `approved-source-change-exact-sentinel-20261102.json`（SHA-256 `f5727728394bab7e40edea2800ec67cbdb7ca8200043b06d064b6db328414207`），验收 `exact-sentinel-august-acceptance-20261102.json`，注册／备份 `exact-sentinel-source-registration-20261102.json`，启动 `exact-sentinel-background-process-20261102.json`。已从 2020-09 续跑至授权目标 2023-12-31，剩余 40 月不因新规则跳过未知哨兵；后续品种仍等待全部股票验收，期权正式发布门禁不变。

按用户要求创建本机当前对话 heartbeat 配置 `/Users/neolin/.codex/automations/getrich-tushare-progress-15m/automation.toml`，ACTIVE、每小时 0／15／30／45 分只读查询账本并在当前对话报告，不自动恢复／修改采集；目标线程 `01a18c84-e5dc-7b60-b1c7-544c3caeb736`。已核对 TOML、目标和 15 分钟复现间隔，但当前桌面 UI 工具不允许操作 ChatGPT，首次实际调度／投递尚未验证，不能将配置成功说成已确认自动报告。实时采集状态仍以运行账本为准。

**上市首日整行缺限价与恢复（2026-11-01，用户授权，[D-024](../../.agents/brain/DECISIONS.md#d-024)）**：工作库与 Tushare 身份映射核实 688033.SH 的 list_date=2019-07-22；2019-07 科创板样本复核通过，其他 24 只首批股票当日均为 100000.0／0.01 双侧哨兵，688033 次四日为相同哨兵、07-29 起正常 ±20% 限价。证据为 `/Volumes/myssd/data/getrich-validation/tushare-listing-day-limit-20261101T145246Z/probe.json`，原 raw 不改。仅交易日等于持久化 list_date 且整条 stk_limit 行缺失时不阻塞，仍保持 UNKNOWN／NULL、不推断 NO_LIMIT、不补造限价；无前收盘不能代替上市日核实。已有行但值缺失、单侧哨兵、非首日缺行、限价与前收／OHLC 矛盾均仍触发复核，BJ 行级边界不变。

例外随主表事务写 `ops.data_quality_check` 的 `tushare_stk_limit_listing_day_missing` 规则，代码／日期／主数据上市日／批次逐条留痕；每月 `state.json.months[月份].listing_day_missing_limits` 及运行目录 `listing-day-missing-limit-months.json` 汇总唯一代码日期与审计事件数。2019-07 原一条缺限价告警的人工审核结论保存在该月 `reviewed_warnings`，审核对象严格为 688033.SH／2019-07-22，结论为供应商漏行、保留 UNKNOWN 与 NULL。四 writer canonical 全字段／价格／两轮业务幂等通过，逐字段输出指纹与原待审月完全相同：停复牌 603、日线 83,282、复权 87,928、估值 83,282 行，无结果软告警；上市首日正常未知唯一记录 1 条，两轮审计事件 2 条。验收遵守既有串行任务锁，等待米筐重放完成并释放锁后才写工作库，未修改或中止米筐任务。

284 项相关回归（含完整 Tushare 流程、首日／次日、已有空行、OHLC 矛盾与事务提交／回滚／幂等）通过，六个改动源码／测试文件类型检查 0 errors，Ruff／格式和接续部署门禁通过。源仅 market.py 相对上次审核更新，其他生产 Python、DDL、依赖与目标指纹不改；并行米筐工作区内容保留，新只读运行源为 `/Volumes/myssd/data/getrich-validation/tushare-listing-limit-source-20261101T145927Z`。新审核为运行目录 `approved-source-change-listing-limit-20261101.json`（SHA-256 `cad5882d657723644b20395e16a11610a1c5026c21d55b6de40e625229187754`），单月验收 `listing-day-july-acceptance-20261101.json`、注册／备份 `listing-limit-source-registration-20261101.json`、后台收据 `listing-limit-background-process-20261101.json`。此前 114 月与近期 34 月完成账本不改，验收至 2019-07 共 115/168 月后从 2019-08 继续；后续品种及期权正式发布门禁保持既定顺序和边界。实时进度以运行账本为准。

**000043 → 001914 复权舍入例外与恢复（2026-11-01，用户授权）**：规则已补入 [D-012](../../.agents/brain/DECISIONS.md#d-012)，仅该换码对的 `adj_factor` 两有限值绝对差 ≤0.001 时用新值；NaN／Inf 视缺失、旧缺新有限用新、双缺对账留 NULL、新缺旧有限停止，最终表的有限正值／非空契约不放宽。其他换码对最后一位差异仍停止，价格、量额及未授权字段仍严格。原审计规则 `tushare_stock_alias_metadata_override` 为两个 writer 逐次记录日期／新旧代码和值／字段／处理规则，随对应业务写入同事务提交／回滚；结束或失败时汇总 `adj_factor_rounding_use_new`／`adj_factor_tolerance_stop`，在 `alias-rule-summary.json.adj_factor_rounding` 区分事件、唯一日期与各目标表，避免将幂等重放及两表重复当成新增命中。

有界重查 2019-06-01～12-20 确认 000043／001914 的差异恰为 2019-06-06～12-13 全部 130 个交易日，每日 8.333／8.334；同日 OHLC／前收／量额逐值一致。12/12、12/13、12/16、12/17 新代码因子均为 8.334，换码无因子跳点，12/16 前收等于 12/13 收盘。源证据为 `/Volumes/myssd/data/getrich-validation/tushare-alias-factor-20261101T120817Z/probe.json` 及同目录四份 zstd Parquet，正式 raw 不改。2019-06 四 writer 全字段 canonical 读回、价格与两轮业务幂等通过：停复牌 481、股票日线 68,395、复权明细 72,286、估值 68,394 行，无结果软告警；16 个唯一命中日，首轮两表共 32 个提交事件，重复导入后 64 个事件，逐条与 raw 新旧值一致。BJ 待处理本月 651 条／85 码，两轮数量不变；验收时累计 36,982 条／176 码，后续单独核实。

225 项相关回归通过，含 0.001 采用、0.002 拒绝、其他换码对 0.001 拒绝、NaN／Inf 缺失方向、两表真实临时 PG 审计提交／回滚／幂等；改动文件 basedpyright 0 errors，Ruff／格式与多品种部署门禁通过。全仓 basedpyright 发现并行米筐测试 16 项错误，本次未修改。新只读运行快照为 `/Volumes/myssd/data/getrich-validation/tushare-factor-source-20261101T120901Z`，仅 `symbols.py`／`importers/market.py` 两份已授权代码相对上次审核改变；其余 Python、DDL、lock 与目标保持旧审核指纹，并行米筐源码不进入本次运行。源码登记为历史股票运行目录 `approved-source-change-adj-factor-20261101.json`（SHA-256 `e1bd987f2761e191ba60a011494446534fe7ebb7f8cc0644730ede65b0a7d97b`）；单月验收 `adj-factor-june-acceptance-20261101.json`、注册／备份 `adj-factor-source-registration-20261101.json`、后台收据 `adj-factor-background-process-20261101.json`。原 113 月及近期 34 月账本保留，新增 2019-06 验收后共 114/168 月，从 2019-07 继续；指数 → ETF → 期货 → 期权控制器恢复等待全部股票完成，期权正式发布门禁不变。实时状态仍以运行账本为准。

**空响应恢复与运行源固定（2026-11-01）**：2018-11 原日线采集因 `2018-11-28` 返回空响应停止，原完整性门禁保持。该日两次独立重查均为 3,572 条，Parquet 及内容 SHA-256 一致；随后完整重采 2018-11 日线，77,916 条覆盖沪市日历全部 22 个交易日，该日与两次重查逐值一致，正式月分区哈希为 `1a0e8a9626c5e61d24ed5576e8a1ffc50036d0504670e5742d570fee04628925`。重查及整月恢复凭据位于 `/Volumes/myssd/data/getrich-validation/tushare-empty-daily-20261101T100451Z/`。为保留并行米筐待审改动，Tushare 运行源固定到 `/Volumes/myssd/data/getrich-validation/tushare-approved-source-20261101T100400Z` 只读快照：全部 Python、PG DDL 和 lock 逐文件匹配既有审核哈希，工作区变更的米筐 `riskmodel.py` 从已提交版本按原哈希恢复进快照，未审核的新米筐模块不进入快照；工作区源码不改、不复制凭据，环境和 NOTES 引用原位置。接续部署门禁在该快照下通过，股票队列／worker 与多品种等待控制器均已确认持锁运行，目标仍为 2023-12-31／2026-10-29。原失败状态及队列已备份到历史股票运行目录 `resume-empty-daily-20261101T100856Z/`，启动及健康收据为 `empty-daily-resume-20261101.json`。该恢复不放宽 B 股、BJ、沪深或期权门禁，也不构成米筐工作库写入授权；2018-11 整月正式验收仍以回补账本为准。

**B 股范围与恢复（2026-11-01，用户授权，[D-029](../../.agents/brain/DECISIONS.md#d-029)）**：仅 `900xxx.SH`／`200xxx.SZ` 登记范围外，raw 原样保留，不写正式表，不映射同公司 A 股；范围内沪深仍严格停止，BJ 沿用行级待处理。逐条记录在 `ops.data_quality_check` 的 `tushare_b_share_out_of_scope`，按目标／批次／原观察指纹去重，并与正式写入共用事务。已补登记已完成批次限价 raw 的 26,035 条 B 股观察，不重写该批行情和完成账本；2018-08 的 24 条／3 个 B 股代码在股票日线辅助读取及复权明细两处共登记 48 个事件，仍只有 24 条唯一源观察。恢复前快照合计 26,059 条唯一源观察、26,083 个登记事件、43 个代码，未新增 B 股身份或映射。2018-08 四 writer 全字段读回／价格校验通过：股票日线 78,606、复权 85,159、估值 78,605、停复牌事件 2,901 行，无软告警；真实复权 writer 重放的主表、审计、BJ 待处理计数均不变。BJ 当月为 599 条／72 个代码，验收时累计 31,076 条／167 个代码；前 103 月记录及所有已验收 raw 哈希不变。相关 252 项回归（含一次性 PG 提交／回滚／重放）、类型、改动文件 Ruff／格式与迁移静态检查通过；多品种接续部署门禁复验通过。续跑前另核实已有 052 列注释与 gr-api 显式声明现有 numpy 依赖造成的指纹变化，正式表字段／约束一致、依赖版本未变，未执行迁移。新审核为运行目录 `approved-source-change-b-share-20261101.json`，旧状态／脚本／计划备份在 `b-share-scope-20261101T005820Z/`，单月验收为 `b-share-august-acceptance-20261101.json`，历史范围外登记为 `b-share-existing-raw-registration-20261101.json`，后台进程收据为 `b-share-background-process-20261101.json`。恢复实查已从 2018-09 继续采集至目标 2023-12-31，多品种控制器持锁处于 `waiting_for_all_stock`，状态快照为 `b-share-resume-status-20261101.json`；仍按股票全部完成后接续 8 指数 → ETF → 期货 → 期权，实时进度以 state／queue 为准。

**raw 存储切换（2026-11-01，用户授权，[D-028](../../.agents/brain/DECISIONS.md#d-028)）**：根 `.env` 的 `RAW_PARQUET_ROOT` 现为 `/Volumes/myssd/data/raw_parquet`。neoimac 最新 Tushare 共 834 个文件、1,007,492,158 字节已复制到新根，逐文件 SHA-256 全部一致；neoimac 原件保留。myssd 原有的 210 个旧 Tushare 文件整体归档至 `/Volumes/myssd/data/getrich-raw-archives/tushare-before-imac-cutover-20261101T002853Z`，没有与新数据混合；原有 `ricequant` 目录未改。数据库连接及数据卷位置未变，没有迁移或重启数据库。运行账本／日志仍在 `/Volumes/neoimac/data/getrich-runs`，历史股票及后续多品种脚本的 raw 路径与继续使用原账本的路径已分别同步；未来历史预检 raw 写 `/Volumes/myssd/data/getrich-validation/tushare-stock-history-preflight/raw`。已完成批次的原始账本与哈希不重写，历史快照中的 neoimac raw 路径仅表示当时来源。切换清单、旧脚本／未完成状态备份及收据在 `/Volumes/neoimac/data/getrich-runs/raw-storage-cutover-20261101T002853Z/`。路径切换当时未启动采集；2018-08 的 `900906.SH`、`900930.SH`、`900951.SH` 共 24 条复权记录缺映射造成的停止点，现已按上述 D-029 范围规则处理，不再为它们补 A 股映射。

以下从待办移出；只代表 2026-10-29 的核验范围，不代表迁移或无人值守已验收。

| 项目 | 本机实查结果 |
| --- | --- |
| 硬件与系统 | arm64、24 GiB 内存、10 逻辑 CPU，macOS 26.7.1 |
| 外接 SSD | `neoimac` 已挂载，可用约 699 GiB；容量是本次快照，复制前重查 |
| Docker | Engine 29.9.2，虚拟机 10 CPU、约 7.75 GiB 内存；磁盘镜像已位于外接 SSD，AutoStart 已开启，不再搬镜像或重复安装 |
| PostgreSQL | `getrich-pg18` 正在运行，PG 18.6／TimescaleDB 2.30.1，监听本机 `5432`；数据使用 named volume，配置／日志在仓库外部署目录 |
| 目标工作库 | 2026-10-30 经用户授权从空库执行 50 个 PG 迁移，账本校验和与当前 DDL 全部一致；现有证券身份、代码映射、三类档案及沪深日历已导入；2024-01 股票日线／估值／复权／停复牌已通过两轮验收，后续月份以运行账本为准 |
| 开发环境 | Git、uv、Python 3.12、Tushare SDK 及测试依赖可用，代码在 `dev`；保留当前文档改动，不复制 MBA 的 `.venv` 或 node_modules |
| Tushare 测试 | 本轮离线测试通过，4 个既有 strict xfail 保留；合成样本的 ETF／期权 PG 往返与幂等测试通过，临时容器／卷已清理，不影响 `5432` 工作库 |
| 账号与样本 | 已有 Tushare 凭据并成功读取日历和 ETF 名单；不代表所有接口权限、历史覆盖或数据质量都通过 |

**配置进展（2026-10-29）**：用户已修改根 `.env` 的 `RAW_PARQUET_ROOT` 并复制根 `config.yaml`；加载检查确认环境中的 raw 根优先生效，但目标目录尚不存在、父目录存在。原受限采样仍使用独立验证根，不把样本写入未来正式 raw 根。

本机 `config.yaml` 的米筐风险模型已移除固定 100 股名单，改用 `universe_policy: listed_cn_a_v2`、`purpose: production`，raw／ingest 默认仅选择 `rq_risk_model`；模型仍为 `v1 + sws_2021`，不自动运行其他模型。该配置覆盖各历史交易日在市的沪深 A 股，不含北交所、B 股和港股。起止日期暂保留原 2026-10-14～16；正式运行前按迁移后的账本确认待处理窗口，不能直接当作日常更新日期。raw／ingest 均要求显式日期，日常补缺与重抓语义见 [gr-data README](../../packages/gr-data/README.md#米筐风险模型五件套)。本次只修改配置并离线校验，未采集或入库；工作库建表、证券身份依赖、归属和收据预检仍按下文完成。

**工作库准备与 Tushare 回补（2026-10-30，用户授权）**：正式 raw 为 `/Volumes/neoimac/data/raw_parquet`，本机四个新字段 instruments 文件保留。用户澄清 `/Volumes/myssd/data/raw_parquet` 主要为米筐风险因子，后续再处理，不阻塞本次 Tushare；股票 raw 直接在 iMac 补采，2024-01 daily_basic 复用已验收的完整 22 日分区，其余单日验证样本未提升为全月数据。根 config.yaml 已补 profile，默认仍只启用股票行情链路。50 个 PG 迁移校验和一致；主数据两轮字段读回／幂等验收通过。沪深日历已入库；2024-01 股票日线及估值各 117,381 行、复权 118,086 行、停复牌事件 301 条／覆盖 22 日，四个 writer 的全部 canonical 字段读回及两轮幂等通过，无软告警；另以固定随机种子独立核对 750 条源记录的 5,750 个数值字段与估值 17:00 上海时间。全量历史目标固定 2024-01-01～2026-10-29，按月采集、入库、读回校验，用户选择先收取首月汇总，历史回补已转为独立后台进程；实时已验收月份以账本为准，不能视作全区间验收通过。状态与源码／raw 哈希见 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20240101-20261029/state.json`，首月独立单位验收见同目录 `2024-01-independent-audit.json`；后台进程定位见 `background-process.json`，日志为 `run.log`，中断后可用同目录 `runner.py --end 2026-10-29` 按账本续跑（先确认没有同一任务在运行）。尚未启用米筐、指数／期货／ETF 行情、期权正式写入或定时调度。

**历史换码修复与恢复（2026-10-31）**：2024-01-01～2026-10-29 已完成全部 34 月：股票日线／估值各 3,692,802 行、复权时序 3,713,146 行、停复牌事件 10,600 条。2010～2023 原首次预检因旧代码未映射停止；已按公司实施公告补充 000022.SZ→001872.SZ、000043.SZ→001914.SZ 的同一证券身份，旧 raw 不改。三字段处理以 [D-012](../../.agents/brain/DECISIONS.md#d-012) 的用户显式授权为准：股息率绝对差 ≤0.01 或相对差 ≤1%，NaN／Inf 视作缺失、旧缺新有限用新、双缺留 NULL、新缺旧有限停止；涨跌状态差异须真实 OHLC／前收／限价反证一致。两对 2010-01-04 真实样本共 6 个字段决策通过且探针全部回滚，未由探针写行情。213 项相关回归（含临时 PG 审计提交／回滚）、basedpyright、改动文件 Ruff／格式检查通过；多品种接续部署门禁复验通过。运行目录 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/` 内保存 `recovery-validation-20261031-missing-policy.json`、`approved-source-change-20261031.json`、恢复前脚本／队列备份及 `alias-rule-summary.json`。仅两份已审核源码允许变更，前批完成账本不重写；多品种计划仅同步这两份哈希并保留原版。覆盖审计在 `ops.data_quality_check`，拒绝决策在 run.log，结束或失败时汇总各规则命中，区分提交事件、唯一日期／代码／字段及拒绝尝试。2026-10-31 12:38 本机快照：2010-01～03 共 3/168 月已验收；四列估值扩容及事务审计已执行，当前 2010-04 因 920047.BJ 在 2010-04-22／29 的日线缺复权因子停止。新旧代码有界重查均空，且两条日线早于源主数据上市日 2020-11-24；拟按“上市前且缺因子”隔离并审计，改变样本范围须用户确认，尚未实施。指数／ETF／期货／期权队列 blocked_by_stock。实时状态以运行账本为准。多品种控制器已恢复，当前 `blocked_by_stock`，仍须全部股票完成后才启动；期权正式门禁不变。

**估值容量扩展与续跑（2026-10-31）**：按用户授权新增迁移 050，`pe`／`pe_ttm`／`ps`／`ps_ttm` 扩为 `NUMERIC(20,4)`，其余列不改，不重写旧迁移校验和。执行前递归依赖视图为空、无其他会话占锁、4 个分区均未压缩；设锁超时 5 秒／语句超时 60 秒，正式迁移耗时约 0.02 秒。原 3,692,802 行的数量与四列汇总一致，父表及分区 relfilenode 不变；结果见运行目录 `valuation-widen-preflight-20261031.json`／`valuation-widen-applied-20261031.json`。源值不截断、不置空；四字段绝对值严格 >1e6 的有限观察逐字段事务审计，备注“极端值保留原值、因子层处理”。首月 20 个 ps_ttm 极端源值逐条与 PG／审计一致，重复导入计 40 个审计事件、20 个唯一日期／代码／字段；全部 canonical 字段与首月幂等通过，见 `valuation-first-month-acceptance-20261031.json`。244 项相关回归（含临时 Timescale 扩容不重写／正负极端值／事务回滚）通过，既有 mock 协程告警保留；Ruff、格式、basedpyright、51 个 PG 迁移安全与新迁移注释检查通过。已归档原失败账本和计划，显式审核市场 importer 的审计变更及新增 DDL 哈希，已验收前批 34 月账本不改。2026-10-31 12:38 本机快照：2010-01～03 共 3/168 月已验收；四列估值扩容及事务审计已执行，当前 2010-04 因 920047.BJ 在 2010-04-22／29 的日线缺复权因子停止。新旧代码有界重查均空，且两条日线早于源主数据上市日 2020-11-24；拟按“上市前且缺因子”隔离并审计，改变样本范围须用户确认，尚未实施。指数／ETF／期货／期权队列 blocked_by_stock。实时状态以运行账本为准。缺复权重查证据为 `missing-adj-probe-201004.json`；原 raw 与严格缺因子门禁保留。

**BJ 行级待处理与恢复（2026-10-31 用户再次调整；本条取代下方旧停止快照）**：北交所照常采集，只将 `.BJ` 校验失败的源观察写入迁移 052 的 `ops.tushare_bj_pending`，保留代码、原始及可解析日期、失败规则、完整源值／辅助观察、分区行序、固定批次和指纹；不按代码或日期整组排除，其他合格观察及其他 writer 照常入库。沪深校验不放宽，坏文件／缺分区／连接及程序错误不降格为待处理。待处理表及主表同事务；对原始重复键先验证各观察，固定批次 UPSERT 保证待处理幂等。仅执行本次迁移 052，无关迁移 051 在工作库中的状态未改。

2010-01～03 的全 canonical 指纹经新源码回滚复核一致，原月账本和前批 34 月完成账本保留；显式审核九份已有源码变更、一份新增路由源码、DDL 新增与 lock／PG 目标后恢复后台。2010-04 已正式验收，股票日线／估值各 35,763 行、复权 37,721 行、停复牌 1,460 条；全部字段读回／价格／重复导入通过。BJ 待处理 2 条／1 码（920047.BJ，2010-04-22、04-29，缺复权），两次导入不增加条数，原值逐字段核对一致，未将失败观察写入主表，raw 哈希不变。记录见运行目录 `bj-pending-april-acceptance.json`、`bj-pending-deployment-probe-201004.json` 和 `approved-source-change-bj-pending-20261031.json`。

后台逐月把 BJ 待处理记录数／代码数／各数据集数量写入 state.json、`bj-pending-months.json`、日志和 NOTES 专属行“BJ 待处理项，后续单独核实”；最终汇总追加 BJ 待处理代码和月份分布，后续核实待办见 [backlog](backlog.md#数据接入可靠性)。273 项相关组合回归、basedpyright、改动文件 Ruff／格式、53 个 PG 迁移安全和新表注释门禁通过；月度汇报幂等及保留其他 NOTES 内容的验证通过。股票任务已继续后续月份，多品种控制器重新等待所有股票完成，期权仍仅独立验证库。

**历史：上市前候选停止门禁（2026-10-31；已被 BJ 待处理策略取代）**：2010-04 的 920047.BJ 在 4/22、4/29 均 OHLC=30、源成交量 400 手，主数据 list_date=2020-11-24，且有 430047.BJ 历史别名。按用户补充条件，两条均触发“正常价格且有成交”及“代码变更”停止条件；真实只读 build 复验通过，未隔离、未写 4 月行情、raw 哈希未变，任务及后续品种保持停止。前述“拟隔离、等待确认”为本次补充条件前的历史快照，不再是可直接实施的方案。隔离上限为累计 20／单月 5 个唯一代码日期，事务锁保护计数，重导不重复占额；缺失、过时或阳性的代码／重新上市历史核实证据均停止。现有质量表保留逐条审计，结束或失败时的 `alias-rule-summary.json.prelisting_quarantine` 已补全代码／日期／年月分布及事件与唯一记录计数，当前均为 0。192 项相关回归（含一次性 PG 提交／回滚、20／21 与 5／6 边界及并发锁失败）通过，汇总分布／重放去重验证通过；源码 delta 与原账本指纹分开保留，未重启后台。证据为运行目录 `prelisting-guard-stop-201004.json`／`prelisting-guard-review-20261031.json`，规则见 [D-023](../../.agents/brain/DECISIONS.md#d-023)；用户要求的回补后集中度与主数据修正待办已记入 [backlog](backlog.md#数据接入可靠性)。

**早期股票接续的原部署记录（2026-10-30；现状以上述 10-31 快照为准）**：当前 2024-01～2026-10-29 股票任务全部验收成功并退出后，自动接续 2010-01-01～2023-12-31，共 168 个月，沿用 daily／adj_factor／stk_limit／suspend_d／daily_basic 与四个股票 writer，不改根配置的日常采集起点。当前任务失败、软告警待复核、月份或验收证据不齐时均不启动后续。接续控制器已在独立后台等待，状态为 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/queue.json`；启动后另记同目录 `state.json`／`run.log`，控制日志为 `queue.log`。先在同目录 preflight/raw 隔离抓取早期年份有界样本，核对日历、空响应、代码映射、字段和价格；通过后才扩展正式日历并按月回补，首月另验重复导入。不能把接口接受历史日期等同于已验证全历史；官方参考为 [复权因子](https://tushare.pro/document/2?doc_id=28)、[每日指标](https://tushare.pro/document/2?doc_id=32)、[每日涨跌停价格](https://tushare.pro/document/2?doc_id=183) 和 [每日停复牌](https://tushare.pro/document/2?doc_id=214)。等待及回补期间仅由进程临时阻止空闲睡眠，退出后释放，不修改系统电源设置。首次接续启动的脚本命名冲突已修复，失败日志保留；安装位置的依赖导入、前置任务顺序、失败／软告警／不完整验收拒绝与 168 月范围检查均通过，早期真实样本预检尚未执行。

**股票之后的多品种接续（2026-10-30 部署；当前进度见上述快照）**：两批股票（2010～2023、2024～2026-10-29）全部验收成功并退出后，按“8 只核心指数 → 沪深 ETF → 六所期货 → 八所期权”顺序执行，统一历史范围 2010-01-01～2026-10-29，各品种从实际上市／可用起点开始。指数白名单为 000001.SH、000016.SH、000300.SH、000905.SH、000852.SH、000688.SH、399001.SZ、399006.SZ；不扩成全市场指数。一次性后台接续任务已运行并等待股票，计划／状态为 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/plan.json` 与同目录 queue.json；分品种子目录保存 state.json／run.log。每月核对 raw 范围与哈希、全部 canonical 字段，首个有效月份另做重复导入和固定种子独立单位抽查；未审查的新软告警、缺数据、源码／DDL／lock／PG 目标变化或验证内存预算超限时停止，不放宽门禁。D-025 的 TAS 排除和 D-026 的 ETF 隔离／缺报价映射仍按既定规则记录明确告警。期权按交易所官方首个品种上市日期分别起抓（依据链接已记在 plan.json），只采 raw 并写独立 `getrich_options_validation_20100101_20261029` 验证库；正式工作库的四个期权 writer 保持关闭，历史参数和发布资格未开放。该验证库在期权阶段开始后才由当前 gr-db DDL 建立，本轮仅只读确认了建库权限，未创建验证库或采集新资产。期货 Tushare 阶段仅导入行情／已有档案，乘数及最小价位等 `meta.future_contracts` 参数仍按 D-027 留给米筐，未启用米筐。部署检查覆盖股票全区间完成／退出的顺序门禁、202 月日期范围、8 指数白名单、期权上市边界与隔离、首月验收及 raw 越界拒绝；安装目录依赖导入／检查均通过。这些是控制与部署验证，不代表其他品种的全历史真实数据已验收。

电源设置仍为 `sleep=1`、`disksleep=10`、`autorestart=0`。AutoStart 已开启也不能证明无人登录、外盘挂载、Docker 和 PG 的完整重启恢复链路通过；这些留到正式连续运行验收。

## 2. 现在先做：测试与 Tushare 受限下载

**2026-10-30：2024-01 同月 raw 与真实样本整月隔离 PG 验收已完成。** 这不是全历史回补或正式发布；工作库、正式环境文件和 DDL 均未改动，期权正式写入仍关闭。

本次验收根为 `/Volumes/neoimac/data/getrich-validation/tushare-etf-options-20261030/continued-month/`：`result.json` 记录 raw 结果，`price-preflight.json` 记录价格／单位预检，`pg-result.json` 记录两轮入库、全部 canonical 字段比对和从源值独立复算的结果；`source-pin.json` 固定本轮源码。执行脚本和汇总证据位于同级 `reproduce/` 与上级验证目录。

| 验收对象 | 实际范围与结果 |
| --- | --- |
| 日历 | 沪深及六所期货市场的八份 raw 日历复用原观察，覆盖该月；沪深日历导入隔离 PG，期货日历仅核对 raw 交易日，不伪造夜盘字段 |
| ETF 原始名单 | 六份沪深 L／D／P 响应共 1,909 行，完整保留；58 条 P 跳过，1 条 OF 冲突及 5 条 L 缺上市日隔离；身份／映射各写入 1,845 行 |
| 基金行情与因子 | 原 `fund_daily`／`fund_adj` 分别 28,151／29,620 行、22 日，收据与 SHA256 复核通过，未重新下载；识别出的 ETF 日线 19,661 行入库并核对同日因子 |
| 期权日线 | 八所各 22 个交易日、176 份原响应，共 365,508 行；均入隔离 PG，日期、市场、业务键及全部 canonical 字段核对通过 |
| 期权合约与标的 | 合约 19,236 个，与整月日线代码集合完全一致；复用已有 882 个合约，分三批新增 220＋220＋136＝576 次元数据请求。补齐的合约及映射均入库；277 个所需指数／期货标的使用已留存的真实基础资料，ETF 标的来自上述名单 |
| 幂等与独立核验 | 两轮导入的三张产物表内容哈希一致；另从原值独立核对全部行情价格、份额／手数、金额、因子、持仓与结算，以及合约参数和标的关联 |

用户已确认并实施的处理口径见 [D-026](../../.agents/brain/DECISIONS.md#d-026)：

- ETF 的 `158008.OF + SZ + L` 冲突以及 L 缺上市日（NULL／空字符串）完整留在 raw，跳过身份／映射／行情写入并记软告警，不改码、猜日期或改成 P。名单独立存在的合法 `158008.SZ` 正常登记。坏代码、错市场、非法日期和 D 缺上市日仍拒绝。
- `open=high=low=0, close>0` 的源占位保留 raw，ingest 将 OHL 映射为 NULL，保留 close 和其余字段。整月 DCE／GFEX 共 168,385 行，含非零成交量记录。
- CZCE／`.ZCE` 的 OHLC 全零且 settle>0 时，将 OHLC 映射为 NULL，不按量额判断是否缺报价；共 56,970 行，其中 33 行有成交量额，原量额／结算／持仓保留。2024-01-02 的 4,116 个合约与[郑商所官方日行情](https://www.czce.com.cn/cn/DFSStaticFiles/Option/2024/20240102/OptionDataDaily.txt)在 9 个共同字段上完全一致；1 月 3 日有成交但 OHLC 全零的样本也与[官方同日文件](https://www.czce.com.cn/cn/DFSStaticFiles/Option/2024/20240103/OptionDataDaily.txt)一致。
- CZCE／GFEX 的 OHLC／settle 全零在 raw 仅作候选留存。ingest 必须用真实 opt_basic 逐行验证 trade_date 等于 delist_date，才将 OHLC 映射为 NULL、保留真实 settle=0；缺证据或日期不匹配即拒绝。整月 267 行全部核对通过（CZCE 179、GFEX 88），其中 GFEX 25 行成交量非零，不能统称无成交。

价格、量额和持仓的负值、非有限值、精度或单位门禁保持有效，不用结算价或成交均价补造 OHLC。ETF 分类仍沿用已知不准确的旧规则，未执行分类更正或存量删除；少数源 L 记录的未来上市日／可空简称仍原样保留，未擅自修复状态。期权参数仍是当前快照，不具备历史参数发布资格。

**验证与复用边界**：ETF／期权回归 157 项通过，包含三类报价 PG 往返、到期证据缺失／不匹配拒绝、非法值及隔离边界；整月真实 PG 用例通过，Ruff／格式、默认 basedpyright 和差异检查通过。临时容器／卷由夹具清理。采集器按每批最多 220 次请求／15 分钟停止并保留响应后续跑；576 次是有缓存的本月实测，不是冷启动或全历史预算。

2026-10-29 的初轮部分失败证据、旧 `accepted-sample/` 的八所各一条抽样、完整 `diagnostics/full-month/` 原响应和 `zero-settlement-diagnosis.json` 到期核验均保留，未覆盖原观察。完整行情复用这些原响应，基金日线／因子与日历未重抓；没有将初轮 partial 或抽样结果当成整月完成。

| 顺序 | 当前状态／下一步 | 验收与边界 |
| --- | --- | --- |
| 1 | 已完成：核查并确认异常契约 | 原响应存证，按上述用户确认口径处理 |
| 2 | 已完成：补齐同月 raw 与合约资料 | ETF 名单、八所日线及 19,236 个合约齐备，原始值与哈希可追溯 |
| 3 | 已完成：真实样本整月隔离 PG 验收 | 标的、映射、raw 日历及观察前置核验，全部 canonical 字段、单位和重复导入通过；仍有明确软告警，不作正式发布 |
| 4 | 已完成两源字段互验与有界补充验证 | 结果及缺口见下文；P6 有限样本数值自洽不等于全区间校准。其他日期／全历史回补及源盘迁移仍先核对权限、预算和原账本；分类更正与正式写入不自动启用 |

### 字段互验与补充验证（2026-10-30）

审计根为 `/Volumes/neoimac/data/getrich-validation/source-field-audit-20261030/`。`report.html` 提供可搜索的双向字段表；`source-fields.json/.parquet` 列出每个源字段去向，`target-fields.json/.parquet` 列出每个数据库列的来源、默认值、生成规则或未写状态。官方网页、真实响应、代码哈希、真实 DDL 建库后的 catalog、测试及复现脚本均在同目录，不能只凭报告摘要宣称全历史验收。

- **Tushare 字段清单已核对，存在缺口**：18 个现行源接口加补充分类接口 `fund_basic`，共 217 条接口字段；32 张相关表共 316 列，其中包含 13 张风险表、3 张通用运维表和缺少 writer 的 `meta.future_contracts`。现行 Tushare 接口有 36 个官方字段未请求、30 个字段仅在 raw 保留；`fund_basic` 的 25 个字段目前完全不在正式采集链路。本轮审计样本不等于正式 raw 已补齐。
- **需要审核用途后再处理的字段**：`stock_basic` 的地区、行业、板块、名称、沪深股通和实控人等 9 字段未采集；`index_basic` 的基期、基点、权重规则、发布方和分类等 7 字段未采集；`fut_basic` 的单位、交易／交割说明等 8 字段未采集。日线另有涨跌额、AH 成交、持仓变化、交割结算等未请求字段，完整清单见矩阵。可推导或无当前用途的字段不因存在就自动扩列。
- **期货参数缺 writer**：`fut_basic.multiplier` 已在正式 raw 白名单且真实响应非空，但没有 Tushare writer 写 `meta.future_contracts`；隔离 PG 核验该表仍为空。不能认为乘数、最小价位、交割等静态参数已具备。需逐字段确认真源和业务用途，不猜测单位字段含义。
- **参考表的字段并不等于已填充**：`stock_daily_basic` 的多项旧 OHLC／均价／成交笔数列当前未写；估值／股本等 13 个字段保留在 `raw_payload`，其中 `pb/pe_ttm` 另有 `valuation_1d` 专列。`raw_payload` 不重复保存已提升的列，并非完整源行副本。`valuation_1d.available_at` 仍是事件日 17:00 的文档近似，不是实测供应商发布时间。
- **ETF 分类实证已完成，旧规则已证伪**：当前 `etf_basic` 1,910 条与场内基金 L/D/I 状态快照按完整代码连接，匹配 1,850 条，包括 62 条债券型、30 条货币型和 19 条“其他”；其中当前 L 的债券型 53 条、货币型 27 条。未匹配的 60 条是 59 条 P 和已隔离的 `158008.OF`，不把状态范围差异当源缺失。`511010.SH` 为债券型、`511880.SH` 为货币型，不能归 equity；`513100.SH` 为纳斯达克 100 QDII，不能统一归 cn_a；`518880.SH` 的源类型为“其他”，`fund_type` 单字段不足以确定商品／跨境市场。没有修改分类代码或存量，后续实施仍须确认映射。
- **米筐真实互验已完成有界样本**：用户恢复本机认证后，固定历史 100 股，`v1+sws_2021` 取 2026-10-14～16，v2／v2trd 各取 2026-10-16。原生响应与 raw 逐值一致，因子维度 42／48／52；142 个模型因子字段的原始位置、canonical 序号／类型均单列于 `ricequant-factor-fields.json/.parquet`。五件套及模型元数据在隔离 PG 两轮导入，全部源数值、因子轴、单位转换、σ 平方、上三角 DOUBLE、REAL 二进制值及实际观察时间一致，业务数据合计 1,510 行。固定验证观察不产生动态 coverage／binding／variant／receipt／checkpoint；这 5 张平台证据表的逐列语义、真实 DDL 及事务／约束／失败用例另行核对，不能冒充供应商返回字段。初轮认证失败证据保留，不再是当前阻塞。
- **米筐源单位已独立重测**：三个模型均使用 2026-04-20～10-16 完整 120 交易日的因子收益与固定 100 股特异收益，日期唯一、排序、因子／股票轴及有限性通过。协方差对角／因子收益方差的中位数分别约 197.24／193.32／193.21；特异标准差／特异收益标准差约 13.51／13.55／13.61，均通过现有单位门禁。另行 NumPy 复算一致，不把历史探针或单位量级通过当模型校准。
- **风险列的业务边界**：`model_run.estimated_at` 实际存 raw 观察时刻，`model_version` 是本地 run 版本；协方差及特异风险的 half_life/window_days 未填。平台身份、覆盖、收据与检查点无须 SDK 提供同名字段。字段互验不改变 `calibrated=false`，D-022 2b 仍待评审／实现。

**P6 收益分解诊断**：先保留未复权 `close/prev_close` 的简单价格收益与前日／同日暴露两项对照，前日暴露出现约 0.46 bp 公共偏移，同日暴露偏差更大，均未按原诊断容差通过。后续以独立的实际中债 3M 国债收益率曲线和米筐前复权收盘价核验，经验复现为：

```text
r_excess_pct(t) = 100 × [adjusted_close(t) / adjusted_close(prev_trading_day) - 1
                         - ((1 + government_3M_yield(t))^(1/252) - 1)]
r_excess_pct(t) = 100 × X(prev_trading_day) @ f_decimal(t) + u_pct(t)
```

三模型合计 500 个股日模型观测，最大绝对误差约 `2.27e-14` 个百分点；按已核准的 PG REAL 量化后，最大误差约 `3.43e-7` 个百分点，均在既定数值诊断容差内。同日暴露反例保留。未拟合截距，未放宽原 `1e-4` 个百分点（0.01 bp）的数值诊断容差，未混用复权 close 与未复权 prev_close。官方风险文档描述因子收益为超额收益，但未找到公开说明中的完整暴露日期／无风险期限和日化细则；**上述是独立真实数据在有限样本的经验复现，供应商约定和其他日期／全区间仍待确认**。不将其自动写成生产契约，也不标已校准或正式发布。原失败、两种暴露日期、原始／超额收益及逐股残差分别留在 `ricequant-numeric.json`、`p6-residuals.parquet`、`p6-excess-diagnostic.json` 和 `p6-excess-residuals.parquet`。

**本轮已执行的验证**：2024-01-02 的真实股票、指数、期货、复权、每日指标、估值、日历、官方代码别名和 17 条停复牌事件在一次性 PG 中两轮导入；全部 writer contract 字段、独立源量额换算／JSONB 去向及幂等通过。ETF／期权复用前述整月真实验收，未重复下载。另以当前完整 DDL、一个标的和一条超表行情完成 `pg_dump → timescaledb_pre_restore → pg_restore → timescaledb_post_restore`，恢复值核对通过；这不代表生产规模恢复时间或跨设备备份通过。Tushare／米筐真实往返及逻辑恢复三项隔离验证通过，相关风险／收据／失败续跑／停复牌／DDL／指数期货回归 626 项通过、4 项既有 strict xfail 保留。

**边界探针**：GFEX 2023-01-01～10 的 10 个自然日日历完整；`CU2402.SHF` 上市日 2023-02-16 有日线；SSE 指数清单 208 条中 8 条有 `exp_date`。它们只证明所测样本，不能证明所有期货上市当日覆盖或所有已停发指数均填终止日。后者仍需独立已停发名单。源盘复制／历史对账、冷启动／全历史预算、持续运行／断网与重启恢复、跨设备备份及一周观察尚未完成；本轮未改工作库、正式 raw、环境文件、DDL、调度或主机电源设置。

历史股票、指数／期货和米筐数据待源盘核验后复用，避免在缺少原账本和 raw 时重复下载已完成历史。后续迁移按第三节进行。

## 3. MBA 移动硬盘带回后：先复制文件，再从 raw 重建数据库

raw、Parquet、manifest、账本、配置模板和验收证据直接 `cp -a` 到新目录，本轮新样本保持独立、不覆盖合并。**工作库不恢复源 PG**：空库按当前 DDL 建表后从 raw 重新入库；源 PG 逻辑导出只恢复到隔离库作对账参照，不复制数据目录或 Docker.raw（原因见 [D-006](../../.agents/brain/DECISIONS.md#d-006)）。米筐 `run_id`、`available_at` 由 raw 确定，重导不变；`receipt_id` 随 importer 版本变化。

**重导带不回、暂不处理的内容**（不影响新库使用，开放发布前补齐）：

- 2024-12-11 旧 v2 run 的人工否决（源库 `check_id=37`）：开放风险读取前排除该观察或重新登记。
- importer 新版本：批次启动前登记到运行目录的 `version-policy.json`。
- 业务数据与旧 DataYes CNE6 历史：先在源库确认是否存在、是否保留。

| 顺序 | 动作 | 验收与边界 |
| --- | --- | --- |
| 5 | 冻结 MBA 源端并补齐清单 | 确认无采集／入库写任务或会重新触发它们的自动化，记录截止日期、raw／run／receipt／版本。核实源 PG 实际版本、规模与非 raw 来源的数据；旧“Docker 离线”记录不能当作源库现状 |
| 6 | 制作配套快照与复制清单 | 导出新的 PG 逻辑备份作对账参照，记录 raw／证据的相对路径、数量、大小和 SHA256。旧 2026-10-22 dump 早于米筐回补完成，不能作参照快照 |
| 7 | 将普通文件复制到 iMac 新目录 | 先确认目标位置、可用空间与卷挂载，复制 raw 和运行证据，保留层级、观察身份与原时间；逐项比对清单，不覆盖源盘，不因同名文件直接覆盖本轮样本 |
| 8 | 建立工作库并从 raw 重新入库 | 确认目标库为空后执行 `gr-db migrate --target pg`；先导入身份、映射与日历，再导入行情与米筐风险。各数据集按自身验收状态写入，不因迁移放宽门禁 |
| 9 | 与源库参照对账 | 在隔离库核对行数、日期范围、业务键、ownership、停复牌覆盖、因子顺序／维度及 run／observation／manifest 哈希／用途（不比 receipt_id）；否决、被取代观察和非 raw 数据单列差异，不在工作库手工补写 |

若届时目标库已产生需保留的数据，先做逻辑备份与冲突评估，不能直接清空重建。源盘保留到重导、对账及回滚窗口验收结束；清理源盘另行确认。

### 源盘待复制清单

下列为 2026-10-27 在 MBA 的历史盘点，不是本次重查；硬盘带回后复核容量与内容。路径以源盘根为基准。

| 内容 | 历史位置／证据 | 复制与恢复要求 |
| --- | --- | --- |
| 米筐 raw | `data/raw_parquet/ricequant`，约 53 GB | 整体复制，包括 validation、失败／被取代观察、manifest 和哈希；不只挑成功 Parquet |
| 米筐回补账本与终验 | `project/getrich-runs/ricequant-20240130-20261021`，约 69 MB | 保留 baseline、templates、ledger、version-policy、reports、acceptance 与 RUNBOOK；已完成执行器不重新启动 |
| Tushare 股票 raw | `data/raw_parquet/tushare`，约 413 MB | 连同 instruments、calendar、复权、涨跌停、停复牌覆盖 JSON 复制；月文件存在不代表完整或最新 |
| 指数／期货回补账本 | `data/tushare-backfill/20240101-20261023`，上级约 22 MB | 按账本定位其实际 raw，不能只复制股票根目录后宣称指数／期货历史齐全；正式 PG 入库仍待核验 |
| 指数／期货样本 | `data/tushare-smoke/2024-01-20261024` | 单独保留为验收证据，不冒充全历史正式行情 |
| ETF/期权诊断样本 | `data/tushare-etf-options-smoke` | 保留源异常、响应与报告；与本轮 2026-10-29 样本分开，不混入已验收发布 |
| PostgreSQL | 从源 PG 新做逻辑导出 | 只作对账参照，恢复到隔离库，不进入工作库；旧库风险证据仍在 `ops` 下，比对时按表名对应到 `factor`，质量否决等非 raw 记录单列 |
| 部署与环境 | `data/getrich-docker`、项目本地环境配置及采集模板 | 在 iMac 适配必要连接、目录、权限与资源；不整份覆盖本机 `.env`，凭据不进入仓库 |

历史证据仅确认米筐 **2024-01-02～2026-10-21**、三模型各 676 日；2020～2023 若确需迁移，先找到实际数据。`calibrated=false`、validation 用途及正式风险读取关闭状态不会因复制／重导改变；被否决旧 run 的否决记录不随 raw 迁移，见上文。具体依据见[米筐验证记录](../history/2026-10-23-rq-risk-validation.md)和 [REAL 修复验收](../history/2026-10-24-rq-real-recovery.md)。

## 4. 对账后：建立唯一正式采集与备份

| 顺序 | 动作 | 通过条件 |
| --- | --- | --- |
| 10 | 完善 iMac 正式配置与增量范围 | 正式 raw、验证 raw、部署、运行证据及备份目录分开；采集 checkout 固定已验证源码／lock，独立于日常开发。停用数据集与已完成历史回补不自动启用 |
| 11 | 验证持续运行，再启用唯一调度 | 核验睡眠／外盘／重启／登录／Docker／PG 顺序、断网恢复、配额暂停和告警；先确认 MBA 正式任务不会再触发。通用定时还需通过[可靠采集计划](gr-data-reliability-implementation-plan.md)的租约与提交防护，不能因实例启动就宣称无人值守可用 |
| 12 | 建立跨设备备份并演练恢复 | PG 做逻辑备份，raw 与运行证据另保留跨设备副本；同一 SSD 上 Docker、raw 和 dump 不是独立备份。按既定 RPO 24 小时、一期可用子集 RTO 4 小时目标实测，并连续观察至少一周再收敛源端副本 |

iMac 为唯一正式采集／入库主端；Air 用于远程开发及最小隔离样本，日本云服务器仍为后续服务候选。远程访问使用受控通道，数据库保持 loopback；不为了远程开发开放公共数据库端口。

## 5. 尚需现场确认

- 源盘实际 raw／账本位置、源 PG 可用性与最新逻辑备份；指数／期货历史及可能的米筐 2020～2023 数据。
- 正式目录、跨设备备份目的地、保留窗口与实际容量；本轮验证目录不自动成为正式根。
- MBA 到 iMac 的远程连接、源端所有调度入口、iMac 重启恢复链路，以及真实数据质量／发布能力。

此前隔离验证未修改工作库；2026-10-30 工作库准备已执行的迁移与主数据导入见第一节。本轮未修改电源设置、Docker 配置或正式环境文件，未启用定时调度或清理源盘；米筐源盘迁移留待后续；Tushare 股票首月已验收，历史回补状态见第一节及运行账本。
