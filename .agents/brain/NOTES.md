# GetRich 当前状态

读者：接续任务的 Claude/Codex/Antigravity；维护者也可用它快速定位工作。
最后整理：2026-11-04。只写现状与待办；已完成的工作留一行结论和证据位置，过程与测试数字不写入（可从 Git、代码和 docs/history 追溯）。

## 开始任务

1. 先读根 `AGENTS.md`，再读本文。
2. 按任务查 [待决问题](../../docs/plans/backlog.md) 和 [决策主题索引](DECISIONS.md)。
3. 使用说明从 [文档目录](../../docs/README.md) 定位；历史材料不作为现行指令。

## 当前方向与阻塞

- 郑商所期权官方年度字段覆盖已实施并续跑（2026-11-04 23:18 上海时间实查，D-012）：用户后续授权已解除暂停，原 2017-08-21 全日排除方案由官方年度覆盖取代。冻结批准源 `eea6871+czce-official-v1-40d8f49cc47c` 已登记，尚未 commit／push；仅覆盖授权的 CZCE 字段，其他价格与合约集合仍严格断言，Tushare raw 原值、表归属和 schema 保持。2017-04～07 已重导复验，其他交易所全部列不变；2017-08 整月验收及审计幂等通过，300 条特殊日记录完整保留。2026-11-05 接续实查：期权已验收到 2018-08，2018-09 因最后一次 SHFE 收据范围被误用于 CZCE 而停止；用户已授权按交易所记录独立 scope、补回归并修复后续跑，尚未实施该修复。此前监管器／锁及源码哈希验收为历史快照；D-026 仍仅 raw／隔离验证，正式期权日线为 0。opt_daily 现已接入共用历史开市日有界空响应重查，DCE 2017-05-26 和 CZCE 2022-06-10 的真实响应故障注入重放通过，共用接口间隔仍为 1.5 秒。年度原件、SHA 与逐行差异在 `/Volumes/myssd/data/raw_parquet/czce/option_official_annual`；全量复算、双版本测试、原子回滚、四月重导、八月验收及运行证据在 `/Volumes/myssd/data/getrich-validation/tushare-czce-official-v1-20261104T144525Z`，源码登记为任务根的 `czce-official-v1-source-registration-20261104.json`。复算纠正了“2020-09 后金额全相同”的初步结论，2021-01～04 另有金额差异，仍在授权范围内并留逐行证据；2026 明确标记未经官方年度核对。后续实时进度查 option/state.json 和 queue.json。

- 期权 2017-05 空响应中断已重启恢复（2026-11-04 17:49 上海时间实查）：期货已完整 202/202 月，指数／ETF 各 202/202 月。期权原在 2017-05-26／DCE／opt_daily 空表停止，独立双重查各 204 行逐值／哈希相同；用户授权重启后沿原 `eea6871` 冻结副本、校验及共用 1.5 秒限速整月重采。2017-05 raw／隔离库日线各 9,490 行，合约 1,356 条 canonical 通过；三市场各 20 交易日，故障日全部字段匹配双探针，价格／量额／持仓异常 0、400 项独立单位值和幂等通过，正式库期权日线仍 0 行。当前期权已验收 28 月、上市前 not_listed 61 月，2017-06 collecting；监管器 PPID=1、控制器／worker 存活持锁已实查。原 27 个期权月、61 个上市前记录、其他三类各 202 月及 raw／股票账本保持；5 月原 SSE 1,452 行部分 raw 和失败证据已备份。该次恢复未改源码／规则／commit；当时 opt_daily 空表仍直接门禁，现已由上方官方年度覆盖任务接入共用有界重查策略。期权继续仅 raw／隔离验证，正式发布未开放。恢复收据 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/option/empty-dce-20170526-recovery-20261104.json`；备份、验收及进程证据在 `/Volumes/myssd/data/getrich-validation/tushare-option-empty-dce-20170526-recovery-20261104T094533Z`，以后进度以 state／queue 为准。

- 数据库目录整理（2026-11-04）：PostgreSQL 实现集中到 `gr_data.db.postgres`，与 `clickhouse` 并列；`gr_data.db` 顶层导出常用接口并与 `postgres` 共用连接池；旧模块路径（pool／sync／copy／trading_status／risk_receipts）及 ClickHouse `query_sql` 已删除，调用方全部改用 `gr_data.db.postgres.<module>`，配置和 SQL 行为不变。仓库外冻结快照和运行目录脚本仍自带旧路径，下次从仓库取快照时一并迁移。风险收据源码位置校验及类型基线路径已同步；相关测试通过，当前环境跳过的真库集成验证尚未覆盖。

- HDB 配置已移除（2026-11-04）：删除 `HdbConfig`、导出及 `ENABLE_HDB` 示例和说明；保留其他供应商配置，PostgreSQL 默认值与 DSN 行为不变。

- 期货 2021-07 空响应中断已恢复（2026-11-04 09:51 上海时间核验）：原任务于 03:55 在 DCE／2021-07-23 连续空表、额外 3 次重查仍空后按门禁停止，2021-06 为原最后完成月。用户继续任务后两次独立重查各 261 行、逐值及文件哈希相同，底层供应商原因仍未知。原 launchd 服务已不在 gui／user 域加载、旧三 PID 不存在；按同字节原 Standard plist 重新 bootstrap，卸载原因未确定，未改启动配置。沿原 `eea6871` 审核副本、规则和共用 1.5 秒限速完整重采 2021-07，正式 18,373 行 canonical／价格／幂等及 400 项独立量额验证通过，故障日全字段匹配两份探针；五所交易日齐全，原 138 月记录／raw／参考快照及 ETF／指数／股票账本保持，日历／占位审计分别仍 580／2 且唯一。当前 139/202 月完成至 2021-07，2021-08 collecting；监管器 PPID=1、控制器／worker 存活持锁及封存已实查，期权尚未开始。本次未改生产源码或 commit。恢复收据 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/future/empty-dce-20210723-recovery-20261104.json`；重查、停点备份、整月验收、进程证据及恢复脚本在 `/Volumes/myssd/data/getrich-validation/tushare-future-empty-dce-20210723-20261104T014242Z`，后续实时进度仍查 state／queue。

- 期货上市前连续合约占位规则已切换（2026-11-04 01:54 上海时间实查，D-025）：独立提交 `eea687190d5098bef5fdbbf9654854741e936743`、未 push；仅连续代码、七项源价格全缺失、量额仓精确零、同品种同所 raw 首个到期合约晚于该行四项齐备才认可原跳过行，其他 close／settle 均无效行仍停止；TL2306 不会误认成 T+L2306。主仓／冻结副本各 200 项回归及静态检查通过，真库注入失败已验证行情与审计同事务回滚。已在 2018-08 边界替换 2222afe 的冻结源，先重验 2018-07 的 13,890 行逐值／价格／幂等不变，再复用原哈希 raw 重验 2018-08：14,730 raw 行、14,728 正式行全部原值一致；TSL.CFX／TSL2.CFX 的 2018-08-14 两条依据 raw 到期合约首日 2018-08-17 留证，审计 2 条且重放不增，五所各 23 交易日，400 项独立量额值通过。原 103 月记录及 104 个 raw、ETF／指数各 202 月和股票账本均保持；日历审计仍 580。当前 104/202 月已验收，2018-09 collecting，监管器 PPID=1、控制器／worker／锁及封存均实查，共用 1.5 秒限速，后接期权 raw／隔离验证。月报 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/future/pre-listing-placeholder-months.json`；源码登记 `future-pre-listing-v1-source-registration-20261104.json` 位于同任务根；双月验收／原停点备份／原子回滚和运行证据在 `/Volumes/myssd/data/getrich-validation/tushare-future-pre-listing-v1-20261103T174721Z`。后续进度以 state／queue 为准。

- common 职责拆分（2026-11-03）：日期转换、分块与索引水位集中到 `gr_data.common.dates`，集合工具到 `iterables`，`retry` 仅保留重试；仓内引用和 AGENTS 已同步。日期分块拒绝非正步长；米筐模块边界及 Parquet 宽松读取语义未变更。

- 历史开市日空响应统一重查已切换（2026-11-03 21:33 上海时间实查）：2012-08-20 CFFEX双重查各9条且逐值/哈希一致，先按原02c3990恢复2012-08、7740条真库验收后干净暂停在2012-09边界。独立提交 `2222afe36bc1fe810b37c7a7a52c6e68b0c3f729`、未push，仅在原日历开市+历史日+完整query_all结果为空时额外查至多3次、退避5/15/45秒逐次WARNING，非空后继续原完整校验、耗尽仍停；统一fut_daily/fund_daily/fund_adj与daily/adj_factor/stk_limit/daily_basic，合法稀疏suspend_d及当天待发布语义保持。后台旧ETF空表包装已移除，避免与共用机制叠加；实际接口限速仍共用1.5秒。源码哈希在月份边界登记，切换后2012-08 canonical/价格/单位/幂等保持，原32个期货月及ETF/指数/股票账本和raw不重写；故障注入整月重放在第2次重查成功，整月raw字节保持，月报计1次成功/2次额外查询。新源首月2012-09已验收6740条，其真实重查成功数0、日期空；当前期货33/202月、活跃2012-10、状态collecting，监管器PPID=1/worker/锁实查，期权尚未开始。主仓检查通过；冻结运行副本有已在旧版本复现的临时文件处理旧基线失败，具体边界 `/Volumes/myssd/data/getrich-validation/tushare-empty-requery-v1-20261103T131925Z/validation-boundaries.json`，未带入其他Parquet/Yinhe/Insight源码变化。月度次数/日期/额外查询明细 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/future/empty-response-recovery-months.json`，切换登记 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/empty-requery-v1-source-registration-20261103.json`，切换重验/故障注入/运行验收 `/Volumes/myssd/data/getrich-validation/tushare-empty-requery-v1-20261103T131925Z`；以后进度以state/queue为准。

- 期货临时空响应恢复（2026-11-03 19:49 上海时间实查）：2010-08-09 CFFEX当次空表导致19:14停止，供应商底层原因未给出；故障日两次独立重查各9条、逐值/哈希一致，4个实际合约全部返回，前后交易日各9条。按原 `02c3990` 审核副本/规则/计划/共用1.5秒限速恢复原launchd任务，整月2010-08重采后6160条canonical/价格/单位/幂等通过，四所各22交易日，目标日9条与双探针逐值相同；未新增数据例外、改源码或commit。原7个期货月、202个ETF/指数月记录、原raw/主数据及股票账本保持，580条休市推导审计未重复计数；监管器PPID=1、进程与锁已实查，当前期货8/202月、活跃2010-09、状态collecting，期权尚未开始。停止证据/备份/恢复收据 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/future/empty-cffex-20100809-recovery-20261103.json`，双重查及整月验收 `/Volumes/myssd/data/getrich-validation/tushare-future-empty-20100809-20261103T114108Z`。此条为当时的恢复快照；该空表立即停止机制已由上方统一三次重查策略取代。

- 期货缺失休市日四证据规则已实施（2026-11-03 19:03 上海时间实查，D-025）：供应商确实缺行、SSE明确休市、该所现有fut_daily raw无行、原始日历前后最近开市日pretrade_date衔接四项全满足才推导is_open=false/has_night=false；原始日历不回写，供应商已有行不覆盖，不推断开市日夜盘。采集阶段校验完整请求区间并汇总不可推导缺口，行情采集复用同一内存补全规则。仅580个推导休市行已写既有日历表，并与逐行四证据审计同事务、按规则/交易所/日期去重；其中CFFEX577、DCE/CZCE/SHFE各1，分区未生成的无行情证据明确标注，不冒充整月已采完。独立提交 `02c39909fe996e3233943db3a3d09da4344e7700`、未push、未带入其他修改；针对性回归、冻结副本及真库事务回滚/审计去重通过，2010-01～03旧版逐值/canonical/价格/单位/幂等不变，原3个月记录不重写。2010-04已验收5790条、其中CFFEX推导休市4天；该次启动时为期货4/202月、活跃2010-05、状态collecting（历史快照，后续进度以上方恢复条目及运行账本为准）；launchd监管器PPID=1、控制器/worker与锁已核验，共用1.5秒限速，之后仍接期权raw/隔离验证。ETF及指数各202/202已完成、所有月记录保持，股票账本和原raw保持；米筐未操作。验收 `/Volumes/myssd/data/getrich-validation/tushare-future-closed-calendar-20261103T105230Z/acceptance.json`，审核/源登记 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/future-calendar-closed-source-registration-20261103.json`，月度按交易所列天数 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/future/calendar-inference-months.json`，进程/封存验收 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/future/calendar-closed-control-20261103/startup-acceptance.json`；后续实时进度查state/queue。

- ETF 统一身份 v1 已完成本轮202/202月（2026-11-03 17:33完成）：四只transformation登记及159908迁移已按提交 `1de544c2fed42f216cc2c1a6500561608da29f89` 验收；2013-12与2018-02正式重验通过。冻结快照128只D状态已退市ETF全部包含于1845只筛查，无新增转型候选；退市覆盖 `/Volumes/myssd/data/getrich-runs/tushare-etf-identity-screen-20261103/delisted-coverage-acceptance-20261103.json`，验收 `/Volumes/myssd/data/getrich-validation/tushare-etf-identity-v1-20261103T072818Z/`，登记 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/etf-identity-v1-source-registration-20261103.json`。旧raw-only任务已在2018-02月边界交接正式队列，不应重启其旧保护账本计划。

- 米筐调度排查已结束（2026-11-03 21:31 上海时间验收）：旧任务实际为Background(5)、worker/supervisor PRI4；已在v2/2023-11-28验收边界安全退出、经原监管器留退出/中断审计，bootout/bootstrap后实际为Standard对应daemon(3)、两进程PRI20。用户明确PRI约31仅作参考，PRI20且非background可接受；连续20个新取数日2023-11-30～12-27均80次数据请求，按原pre_launchd_59_requests基线，取数0.330539秒/请求（1.095798倍，门槛0.361970）、验收6.613秒/日（1.185550倍，门槛6.6936），两项均通过，Standard定为正式配置并继续原raw顺序。取数阶段含逐响应落盘/校验及额度检查；最终五件套写入发布均值0.5598秒，IPO后继取数等待单列；验收阶段为取得所需证据后的墙钟时间，不是纯CPU计时。20日13例IPO缺失全部由次日manifest解释，0拒绝。独立50次get_quota热查询均值0.034014秒，按80次数据请求对应85次额度查询折算2.8912秒/日，低于5秒，不改额度检查。采集源码5598ed2、原政策/门禁哈希不变；仅raw、v2→v2trd→v1、保留10%及首次额度耗尽后次日确认门禁不变，不写工作库、不切Interactive。结论/逐日数据/哈希/launchctl与PRI快照在 `/Volumes/myssd/data/getrich-runs/ricequant-history-20100104-20231231-20261102/launchd-control/scheduling-standard-20261103/` 的timings.json、performance-decision.json和acceptance.json；实时进度仍查运行账本。

- 米筐独立运行恢复（2026-11-03 00:16 上海时间验收）：旧 PID 6391 无退出码/信号记录，历史父进程链未捕获，确切退出原因未确定；系统 Codex assertion 超时及新进程时间线仅作相关证据，不作为因果结论。已由恢复工具检测失效 PID，把残留 running 转为 interrupted 并存原账本/末次验收2019-11-20审计。现经用户授权改用 launchd 用户任务，监管器PPID=1，caffeinate -i已生效；原5598ed2副本/门禁/业务写入权限不变，外置哈希封存的适配器仅把日启动及逐请求保留提高到10%。续跑首日v2/2019-11-21已验收：唯一完整raw原样复用（新增文件0），3728/3730完整，两IPO均由11-22同variant manifest确认恢复、不可解释缺失0；11-22未发布暂存已按中断归入_failed，原响应及原receipt哈希留存。每分钟独立健康检查、每15分钟生成报告，PID不存在或恢复宽限后10分钟日志/验收无推进报停滞；原聊天heartbeat已补规则，实际自动投递仍未核实。恢复长核验期间已真实触发停滞告警，首验后health恢复running；当时曾做taskpolicy临调并将磁盘plist改为Standard，但2026-11-03实查仍为Background/PRI4；实际重载及耗时验收见上方调度排查条目。首验和进程/额度/原观察复用的完整核对为该目录`resume-acceptance.json`，34项回归通过。证据和脚本在 `/Volumes/myssd/data/getrich-runs/ricequant-history-20100104-20231231-20261102/launchd-control/`；myssd Owners Disabled及launchd打开外盘stdout受限，所以加载用plist和启动器自身日志位于用户 `Library/Application Support/GetRich/runs/ricequant-history-20100104-20231231-20261102/launchd/`，原目录保留同字节plist，未改整卷设置；采集日志/账本/raw仍留原处。

- ETF 转型单代码范围（历史快照，已由2026-11-03统一v1登记取代；2026-11-02 23:50 上海时间实查，D-026）：仅159908.SZ在2018-12-10之前的fund_daily/fund_adj标为“基金转型前，不在范围内”，raw、list_date及当前跟踪指数不改；月账本按dataset记录代码/日期/行数/两份公告，其他代码早于上市日仍停止。独立提交 `92bfc206d25f43e8322fa5d871c4660ec23e319c`，未push；主仓与冻结候选各163项回归通过/3项真库测试环境跳过，另用真实工作PG重验2011-07：日线/因子各排除13条，其他525条与旧版本独立构建逐值一致，canonical/价格量额/幂等通过。新审核 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/approved-source-change-etf-transition-159908-20261102.json`，登记 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/etf-transition-159908-source-registration-20261102.json`，运行源 `/Volumes/myssd/data/getrich-validation/tushare-etf-transition-20261102T154101Z/runtime-source`；原18个ETF月记录、202个指数月记录、股票账本和已留证raw保持，7月只将实际已重验的失败月留证验收，未重采。后台running，ETFcollecting、已验收20/202月、当前2011-09，控制器/worker进程及锁已核对。范围估算复用19个raw月并花15次全市场年末截面请求，发现159908.SZ、510680.SH、512990.SH、511220.SH共4个候选；后三只未授权，不自动加入。该估算是下界，可能漏年内转型/抽样日停牌，不能断言总数≤5；逐码完整筛查还需约1841次查询（失败重试另计）。名单/日期/调用收据 `/Volumes/myssd/data/getrich-validation/tushare-etf-transition-20261102T154101Z/scope-estimate.json`；验收 `/Volumes/myssd/data/getrich-validation/tushare-etf-transition-20261102T154101Z/july-201107-acceptance.json`；逐月范围外汇总 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/etf/pre-transition-scope-months.json`。后续ETF→期货→期权，期权仅raw/隔离验证；米筐历史任务本轮未操作。

- ETF 临时空响应恢复（2026-11-02 22:54 上海时间核对）：2011-05-30 fund_daily 空响应曾触发停止；两次独立重查各149条、逐值和文件SHA一致，原版本完整重采后2011-05共469条canonical读回及价格量额/因子检查通过，当日raw全部约定字段等于重查。ETF已验收18/202月，当前2011-07，控制器/worker持锁继续，后续期货→期权（仅raw/隔离）。原16个ETF月记录和两批股票账本保持；原控制器刷新已完成指数顶层时间戳，指数202月仍全验收、恢复前163月记录未变。源码/计划/规则不变；收据 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/etf-empty-response-recovery-20261102.json`，双重查证据 `/Volumes/myssd/data/getrich-validation/tushare-etf-empty-20110530-20261102T145122Z/checks.json`。BJ待处理仍须独立核实，实时进度以state/queue为准。

- 多品种数据库中断恢复（2026-11-02 21:58 上海时间核对）：指数在2023-08因本地PG连接拒绝停止，当次核查时PG已恢复健康；2023-07完整canonical与原账本一致，2023-08既有raw184条和接口重查一致，按原源码/计划恢复后8核心指数202/202月、30136条均已验收完成，全部月raw SHA核对通过。原163月记录和两批股票账本未改。ETF已接续，当前2010-09、已验收8/202月；首月2010-01共140条，canonical/幂等/280项独立单位值和四价量额通过。参考快照55条待上市、11条未核实身份沿既有D-026留证，不是首月行情排除数。控制器和ETF worker持锁运行，仍固定 `/Volumes/myssd/data/getrich-validation/tushare-sh-exact-sentinel-source-20261102T062404Z`，未改源码/规则或重启DB；恢复/备份/验收收据 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/index-pg-recovery-20261102.json`，连通性及接口核对 `/Volumes/myssd/data/getrich-validation/tushare-index-pg-recovery-20261102T133715Z/checks.json`。后续ETF→期货→期权，期权仅raw/隔离验证；实时进度以state/queue为准。

- 股票终态审计（2026-11-02 20:55核对既有最终汇总）：历史168月与近期34月均complete；`/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/alias-rule-summary.json` 的final=true，包含各规则已提交审计、唯一命中、拒绝尝试和代码/日期分布。当前上市前隔离0条、分布为空；BJ待处理91177条/241码，仍须独立核实，不能把主表验收等同BJ待处理已解决。复权舍入唯一命中130交易日，其他各规则次数见该汇总。

- 指数缺口恢复（2026-11-02 20:55 上海时间实查）：8核心指数已验收122/202月至2020-02，后台当前2020-03。原2017-11/000016.SH整月22交易日缺口，两次独立重查各22条、逐值及文件SHA一致；原fetcher按完整白名单重采后全月154条canonical/四价与量额通过，目标22条逐值等于重查。原94月账本和raw、两批股票账本保持；不改规则、范围、计划或运行源码，仍固定 `/Volumes/myssd/data/getrich-validation/tushare-sh-exact-sentinel-source-20261102T062404Z`。恢复/备份收据为运行目录 `index-gap-resume-201711-20261102.json`，双重查证据 `/Volumes/myssd/data/getrich-validation/tushare-index-gap-201711-20261102T124632Z/probe.json`。后续仍按指数→ETF→期货→期权接续，期权只raw/隔离验证；后续实时进度以state/queue为准。

- 米筐代码归档（2026-11-02）：已按用户批准的文档方案将 rq-history 的六个原提交合入本地 dev；保留 D-012／D-030／D-031 详细证据与最新状态，未 push。后台采集仍使用原冻结副本 5598ed2，未切换运行源码；历史风险写工作库仍需另行授权。组合验证证据在 `/Volumes/myssd/data/getrich-validation/data-commit-20261102/`。

- 四价限价复核（2026-11-02，提交前独立审查补漏）：股票 open／high／low／close 分别与源上下限核对，任一越界沿既有口径保留行情原值、限价置 NULL、状态 UNKNOWN 并告警；精确等于边界仍 LIMITED，哨兵／B 股规则不变。仅修开发主仓，后台继续固定来源副本，未切换运行源码。

- Tushare 导入归档（2026-11-02 16:14 上海时间实查）：本轮将已授权且已用于回补的复权舍入例外、上市首日缺限价及对应测试/文档归档到本地 dev；提交候选的全部 gr-data/gr-tools/gr-db 生产 Python 逐文件匹配已审核运行快照，不切换运行源码或重写完成账本。2010～2023 已 complete、168/168 月；2024～2026-10-29 已 complete、34/34 月。多品种控制器当前 running、阶段 index；按原顺序接续8核心指数→ETF→期货→期权，期权仍只raw/隔离验证。米筐及诊断未提交工作保留，实时后续进度以运行账本为准。

- 沪市双精确哨兵（2026-11-02，用户授权，D-024）：以沪市六位 .SH、源上限精确10000、下限精确0.001或0.01取代原单一组合，原≥99999阈值不变；深市/BJ的10000在BJ行级分流前整批停止，未知/近似/单侧组合不类推。规则独立提交 `0acd712453d1ef44c5dd74ae0b102cd3b060b0d4`，未 push，其他原有修改保留；公告原件及原值库盘点在 `/Volumes/myssd/data/getrich-validation/tushare-sh-exact-sentinel-evidence-20261102/`。2020-08四表canonical/价格/幂等及所有业务值不变、90条创业板原哨兵全保留；2022-03四表重验通过，仅600145.SH/03-30 UNKNOWN→NO_LIMIT，03-03～29共19交易日HALTED且无补造bar，03-30/31 NORMAL、03-31限价0.31/0.25。月报逐条列代码日期、原值、处理规则、公告及重放事件，兼容旧审计但不重写历史。原146月（含2020-08）及近期34月账本保持，现147/168月至2022-03、从2022-04续跑；后续品种等全部股票。审核 `approved-source-change-sh-exact-sentinel-20261102.json`，双月验收 `sh-exact-sentinel-reacceptance-20261102.json`，注册/备份 `sh-exact-sentinel-source-registration-20261102.json`，启动 `sh-exact-sentinel-background-process-20261102.json`，运行源 `/Volumes/myssd/data/getrich-validation/tushare-sh-exact-sentinel-source-20261102T062404Z`。 隔离预检首次SZSE只返5000行已被完整性门禁拦截；失败响应/队列保存在 `sh-exact-sentinel-calendar-first-launch-20261102/`，一次重试完整通过，正式日历与包源码未改；若再现需按短日期窗口修复供应商采集，不可跳过日历完整性检查。

- 招港 B 范围单例（2026-11-02，用户授权，D-029）：仅 `201872.SZ` 在当前 Tushare 来源映射不存在时登记范围外；已有映射／查询失败／相邻未登记代码仍停止，原 200xxx.SZ／900xxx.SH 不变，不建证券、不映射 A 股。已扫描 raw 库存 235565 文件，候选及动态暂存边界见 `/Volumes/myssd/data/getrich-validation/tushare-b-share-201872-source-20261102T024722Z/runtime-snapshot.json` 所引扫描报告；没有自动增加其他代码；另有 `990018.XSHG` 仅见米筐供应商快照元数据，身份未确证，不按 B 股处理、不新增映射，补证为同证据目录 `990018-review.json`。两份官方公告、原件及 SHA 在 `/Volumes/myssd/data/getrich-validation/tushare-b-share-201872-evidence-20261102/evidence.json`。独立提交 `45a68ff8254a25b2348aa78ba46c1912a8dd1014`，未 push；必要 B 股基础接入一并纳入，其他已有改动保留。2020-09 canonical／价格／两轮幂等通过，09-18 的 38 只 B 股缺失估值观察全部事务留证（volume_ratio 有源值），无 B→A 映射；月明细 `b-share-scope-months.json`。原 128 月与近期 34 月账本及 raw 保持，已从 2020-10 续跑；审核 `approved-source-change-b-share-201872-20261102.json`、验收 `b-share-201872-september-acceptance-20261102.json`、启动 `b-share-201872-background-process-20261102.json`，运行源 `/Volumes/myssd/data/getrich-validation/tushare-b-share-201872-source-20261102T024722Z`，后续品种仍等待全部股票。

- 原单一精确哨兵（2026-11-02历史验收，规则已由上方沪市双精确哨兵取代，D-024）：仅新增源数值双侧精确 `(10000.0, 0.001)` 为 NO_LIMIT／NULL，原阈值不降，单侧／近似／其他未知组合仍停报；逐代码日期事务审计和月报已接入。规则独立提交 `7361d30f0ed26ac7aab1aee3eef0ecf541b2fee9`，未 push，其他原有改动保留。308 项组合回归、独立 HEAD 加该提交的 48 项回归、改动文件类型／Ruff／格式及部署门禁通过。2020-08 canonical／价格／两轮幂等验收通过：LIMITED=82102、NO_LIMIT=194、UNKNOWN=0；创业板 1e6/0.01 的 90 条全部 NO_LIMIT，唯一状态变化为 600610.SH／2020-08-17 UNKNOWN→NO_LIMIT，其余业务值不变。新精确值对命中 1 个代码日期，两次导入 2 个审计事件；月明细为 exact-no-limit-sentinel-months.json 及 state.json 各月 exact_no_limit_sentinels。原 127 月、近期 34 月完成账本与 raw 均未改；新审核 approved-source-change-exact-sentinel-20261102.json，验收 exact-sentinel-august-acceptance-20261102.json，运行源固定到 /Volumes/myssd/data/getrich-validation/tushare-exact-sentinel-source-20261102T000359Z，启动收据 exact-sentinel-background-process-20261102.json。从 2020-09 后台续跑，后续品种继续等待全部股票完成。两份原公告及 SHA 在 `/Volumes/myssd/data/getrich-validation/tushare-exact-sentinel-announcements-20261102/evidence.json`。每15分钟只读进度报告配置为本机 automation id=getrich-tushare-progress-15m、当前对话 heartbeat，状态文件 ACTIVE；首次实际触发仍待确认，不能把配置验证当投递已验证。

- 上市首日涨跌停缺行（2026-11-01，用户授权，D-024）：仅交易日等于持久化 list_date 且整条 stk_limit 缺失时记 UNKNOWN／NULL 并事务审计，不推断 NO_LIMIT，不补限价；其他缺失／非法限价与 OHLC 矛盾仍触发复核。688033.SH 的 list_date=2019-07-22 已核实，2019-07 科创板样本复核通过。该条供应商漏行的人工审核结论已写入 2019-07 reviewed_warnings；四 writer canonical／价格／幂等通过，输出与原待审月逐字段相同，原 114 月及近期 34 月账本不改。月度代码／日期明细在 state.json 各月的 listing_day_missing_limits 和运行目录 listing-day-missing-limit-months.json；284 项相关回归、改动文件类型／Ruff／格式及部署门禁通过。新审核 approved-source-change-listing-limit-20261101.json，验收 listing-day-july-acceptance-20261101.json、启动 listing-limit-background-process-20261101.json；仅 market.py 更新到只读快照 /Volumes/myssd/data/getrich-validation/tushare-listing-limit-source-20261101T145927Z，保留并行米筐工作。等待既有米筐互斥锁释放后完成重验，当前从 2019-08 后台续跑；后续品种仍等待全部股票完成。

- 复权舍入例外（2026-11-01 用户授权，D-012）：仅 `000043.SZ → 001914.SZ` 的 `adj_factor` 允许有限值绝对差 ≤0.001 用新值，方向性缺失处理沿用授权规则；其他换码对和字段不扩展。交易性覆盖审计及最终唯一命中日汇总已接入两张行情表。225 项相关回归、改动文件类型／Ruff／格式检查及接续部署门禁通过；全仓类型检查另有 16 项并行米筐测试错误，未改。真实 2019-06 四 writer canonical／价格／幂等通过，16 个唯一日期、首轮 32 个审计事件、重放后 64 个事件；2019-12-13／16／17 的新代码因子均为 8.334，源重叠差异为 2019-06-06～12-13 全部 130 个交易日。新审核为运行目录 `approved-source-change-adj-factor-20261101.json`，单月验收 `adj-factor-june-acceptance-20261101.json`、注册收据 `adj-factor-source-registration-20261101.json`，原 113 月与近期 34 月账本及 raw 不改。运行源固定为 `/Volumes/myssd/data/getrich-validation/tushare-factor-source-20261101T120901Z`，仅两份授权源码更新，保留并行米筐工作区改动；后台从 2019-07 续跑，进程收据 `adj-factor-background-process-20261101.json`。

- 米筐跨库重放（2026-11-01，工作库全量导入已验收）：D-030 冻结映射覆盖 2,028 个观察、5,326 对身份；原 raw／名单／源账本未改，源库不可独立访问及 `301139.SZ` 日期差异已审计。固定独立副本 `/Volumes/myssd/data/getrich-validation/ricequant-replay-checkout-20261101`、提交 `f2dddc944116c803eab3fd42cfb49334de5924af`（未 push）；隔离库真实提交版本的数值／覆盖／幂等／回滚复验通过。已登记 13 张 ricequant 风险表归属，保留旧 v2 run 的 publishable=false，正式风险读取关闭。两次锁超时已由 PG 日志定位为 Tushare 月度事务的归属 RowExclusiveLock 与米筐全表 ShareRowExclusiveLock 冲突；本轮 `serial_replay_supervisor.py` 通过既有 Tushare queue／run 锁互斥完成，未杀会话或修改 Tushare／已绑定 importer；已成功退出并释放，Tushare 状态文件前后哈希一致。运行目录 `/Volumes/neoimac/data/getrich-runs/ricequant-replay-20261101`：实时进度 `state.json`、互斥 PID `serial-replay-supervisor.json`、逐日审计 `days/`、日志 `run.log`，锁证据为 `ownership-lock-*`。`full-replay-file-acceptance.json` 与独立只读 `full-replay-acceptance.json` 已产出，原账本逐观察、各表总行数、收据／绑定／检查点及禁用观察均通过；三模型各 676 日，未新增工作库别名，calibrated=false。准备证据／备份恢复演练仍在 `/Volumes/myssd/data/getrich-validation/`。恢复前核对同任务与 Tushare 任务锁，不能无选择重导 raw、切换已绑定 importer 或重新采集。

- 米筐 2024 年前历史 raw（2026-11-02 02:22 上海时间验证，逐月验证已全过、正式 raw 采集中；此条时间为原验证时点）：用户已批准上药实际请求码与普天单例边界，D-012／D-031；独立源码 `/Volumes/myssd/data/getrich-validation/ricequant-history-approved-checkout-20261102` 固定提交 `5598ed28c4b84ba50a42cd1d74e3c3cc2eb3979a`、新 `cn_stock_code_intervals_v3`／新 variant，干净未 push，主工作区 Tushare 不动。旧 v1/v2 规则哈希、原 92 观察、旧停止／验收账本均保留。新运行根 `/Volumes/myssd/data/getrich-runs/ricequant-history-20100104-20231231-20261102`：`gate.json`／`user-approval.json` 固定授权及源输入，`background-process.json` 定位 PID，`state.json`／`run.log` 给阶段与逐日进度，`decisions/` 是不可变验收收据、`assessments/` 是最新视图、`capture-audits/` 给每段 hash／覆盖及实际 quota；独立库仍为 `getrich_rq_history_probe_20261101`，只 capture、不写风险业务。

  七个旧身份待审目标已在新 variant 真实重验全部通过，逐接口共同实际返回值一致；旧未请求上药／普天列为新增观察，不填旧值、不改原观察标签。结果 `seven-reassessment.json`。v1 的 2010-01-04 为 1,696/1,696；2014-01-06 三模型均完整；2017-01-04 三模型 IPO 两只用 2017-01-05 同新 variant manifest 确认恢复。v2trd 的候选起点 2011-04-28 已补五件套，4 IPO 由 04-29 确认恢复。现在按 v2／v2trd 分别验证 2011-04～2023-12 每月一实际交易日（各153个月）；任何模型／接口缺口或行业因子轴变化即停，不自动后移起点。所有条件通过后由 `production-raw-admission.json` 放行，已获用户授权自动按 v2→v2trd→v1 正式只采 raw：v2/v2trd 从2011-04-28、v1从2010-01-04，目标至2023年底。2024-01-02 仅允许作为末端恢复helper，不能成为历史目标。**历史入工作库需另行授权**，各月仍等 Tushare 股票历史及单位／数值验收。

  每日首采实查额度并保留10%（2026-11-02用户调整），日启动另留32MiB缓冲；仅实际确认quota触线可次日重查续跑。首次次日完成一个目标日即先落确认屏障，再保存 `first-next-day-resume.json`（前后额度／原暂停证据／manifest与验收SHA），暂停等待用户确认；额度不可读、网络、身份、质量等其他失败不自动恢复。当前尚未发生首次耗尽／跨日续跑。新源不改 `.env` 或 Tushare；工作库原2024+2,028观察已完整验收，正式风险读取仍关闭。

  行业事实与回测解读见 D-011：三个旧探测窗口51模型日行业轴相同31个，未见切换，但未证明是当时分类，可能用2021版申万回套；不能称PIT已证。原2024+2,028模型日/690IPO缺失新规则重判0停止，原四IPO的次日hash等证据在 `/Volumes/myssd/data/getrich-validation/rq-history-delayed-reassessment-20261102/`。退市分布169实体168同日仅普天+1，不泛化；普天公告PDF重试仍返回HTML验证页，已存上交所公司页／公告列表页、官方13条列表JSON、检索记录及hash在 `/Volumes/myssd/data/getrich-validation/rq-history-identity-approved-evidence-20261102/` 的 `archive-index.json`。原上药临2010-017有效PDF与双码实测见此前identity-review／identity-probe证据目录。

- B 股范围（2026-11-01 用户确认，D-029）：`900xxx.SH`／`200xxx.SZ` 登记为范围外，raw 原样保留，不写正式表、不映射 A 股；审计在 `ops.data_quality_check` 的 `tushare_b_share_out_of_scope`，按目标／批次／源观察去重且与正式写入同事务。范围内沪深与 BJ 原规则不变。规则及事务回归已验证；2018-08 四 writer 全字段读回与真实复权幂等验收通过，原 103 月账本及 raw 不改，已从 2018-09 恢复后台回补。历史股票新审核为运行目录 `approved-source-change-b-share-20261101.json`，验收为 `b-share-august-acceptance-20261101.json`，详情见迁移盘点。

- raw 存储切换（2026-11-01）：根 `.env` 已改为 `/Volumes/myssd/data/raw_parquet`，最新 Tushare 834 文件逐一 SHA-256 校验一致，neoimac 原件与 myssd 旧副本归档均保留；米筐 raw、数据库配置及数据卷未改。历史股票／多品种脚本已同步 raw 路径，运行账本／日志仍留 `/Volumes/neoimac/data/getrich-runs`；完成批次账本不改写。路径切换时未重启采集，随后按 B 股范围决策恢复；路径收据及回滚备份见该目录 `raw-storage-cutover-20261101T002853Z/`，规则见 [D-028](DECISIONS.md#d-028)。

- BJ 待处理项，后续单独核实：最新已完成 2023-12，本月 0 条／0 个代码；本回补累计 91177 条／241 个代码。仅 .BJ 行级失败暂存 `ops.tushare_bj_pending`，合格记录照常入库，沪深失败仍停止；逐月明细见 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/bj-pending-months.json`，后续单独核实原始值与历史口径。

- iMac 准备（2026-10-31）：工作库迁移、主数据及 2024-01-01～2026-10-29 股票 34 个月全部验收完成，逐月 canonical 字段、价格及首月幂等／独立单位检查通过，原始完成账本和源码指纹保留。正式 raw 已于 2026-11-01 切换为 `/Volumes/myssd/data/raw_parquet`（D-028），数据库与状态／证据继续留在 neoimac；状态／证据在 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20240101-20261029/`。myssd 原有米筐 raw 未改，米筐入库与定时调度未启用，日常 config.yaml 起点未扩展。详情见[迁移盘点](../../docs/plans/imac-collector-migration.md)。
- Tushare 早期股票续接（2026-10-31 BJ 策略调整后已恢复）：从 2010-04 续跑，该月四 writer 全部 canonical 读回／价格／幂等验收通过，股票日线与估值各 35,763 行、复权 37,721 行、停复牌 1,460 条；2 条／1 个 BJ 代码写入待处理，重复导入仍为 2 条，raw 未改。2010-01～03 已用新源码重验且原月账本不改；2024-01～2026-10-29 的 34 月完成账本未改。2026-11-02 已验收 168/168 月至 2023-12，历史股票批次 complete；原 B 股复权记录按 D-029 仅登记范围外，不补映射。2018-11 空响应已恢复；2019-06 复权舍入冲突按 D-012 显式例外重验通过，2019-07 上市首日缺限价的原告警已人工审核并按 D-024 重验通过，2020-08 恢复上市精确哨兵已按 D-024 授权重验通过，2020-09 招港 B 单例已按 D-029 授权重验通过，2022-03沪市精确哨兵已按D-024授权重验通过，该批已完成，运行源及恢复证据见上方沪市双精确哨兵条；全部逐月及结束汇总见运行账本。当前进度以 `/Volumes/neoimac/data/getrich-runs/tushare-stock-20100101-20231231/state.json`／queue.json 为准，后续品种控制器已恢复等待。规则见 D-023，待处理与主表同事务；沪深及共享设施失败仍停止。证据同目录 `bj-pending-april-acceptance.json`／`approved-source-change-bj-pending-20261031.json`。
- 股票之后的多品种接续（2026-10-31）：用户确认股票两批全验收并退出后，按 8 只核心指数 → ETF → 六所期货 → 八所期权接续，范围 2010-01-01～2026-10-29。已按已审查的换码／极端值审计／BJ 分流源码及迁移 050／052 修订计划并归档原计划，截至2026-11-02 16:14上海时间，股票两批已完成，控制器为 `running`、当前 `index` 阶段。计划／状态为 `/Volumes/neoimac/data/getrich-runs/tushare-assets-20100101-20261029/plan.json`／queue.json。期权只采 raw 和独立验证库，正式 writer 及历史参数发布仍关闭；期货合约乘数／最小价位留给米筐。源码、DDL、lock、目标与质量异常门禁保持，详情见迁移盘点。
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
- 2026-11-01 模型口径风险纯计算已合入 dev（`42f2451`）：合成协方差、模型波动率、风险贡献／占比／MRC、L3、最小扭转 L4 及市场源与最大风险源占比、模型相关性、风格暴露，PA-13 缺数与未识别份额阻断；对照计算指标清单 §4 模拟案例复现（单股 1.724、100 只等权 1.05、91% 集中 1.82）。取数入口 `services/diagnosis.py::_load_risk_model` 固定返回 None，模型口径对外仍不可用；接数据时须完成 v2 入库、D-022 2b 发布读取、特异波动率平方与期限／年化换算，并用真实数据复核近奇异容差（`diagnosis_calc/model_risk.py` 的 `*_TOL` 只是数值可算性判定）。
- 2026-10-31 历史统计已合入 dev（`aac8275`）：D 区历史相关性（PA-09）与 B 区个股历史年化波动率（PA-20）在 2024 年以来真实日线上出数（只读冒烟：默认 252 日窗口，6 只股票 0.03s、100 只 0.13s，仅为计时不作性能验收）；日内停牌计入样本（用户确认，见 D-021）。模型风险、Beta、回放仍不可用；gr-api 显式声明 numpy。下一步候选：模型风险纯计算（B 区，待米筐 v2 入库与 D-022 2b）。
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
- raw 根与原子写残留（2026-11-03）：`Config.raw_root` 只取 `RAW_PARQUET_ROOT` 或本机 `config.yaml` 的 `paths.raw_root`，都未配置时抛 `SettingsError`，不再退回 `/opt/raw_parquet`（`DEFAULT_RAW_ROOT` 与 example 中的路径已删，D-028）；没有 `.env` 的入口（新机器、未加载 `.env` 的定时任务）会直接报错。`gr-db docs` 缺 raw 根时只跳过 raw 统计并告警。`write_parquet` 临时名改为 `<name>.tmp-<hex>`，硬杀残留不再被 `*.parquet` glob 命中；yinhe／insight 读取与水位只认 `YYYY-MM.parquet`、`<st>_chunk<NNNN>.parquet`。待办：datayes `list_months`、ricequant `list_bar_codes` 仍不过滤旧名残留；同日扫描正式 raw 根、neoimac 原 raw 及两个验证根均无 `*.tmp-*`。
- 默认 worker backend 为 inproc；CI 默认仅 PG，手动 `extra_services` 可启用 CH／Redis。本地 `.env` 只存连接与凭证，未迁入源码或 YAML。
- Python 最低 3.11，开发默认 3.12；CI 跑 3.11／3.12，3.12 开启选股／诊断 PG 集成测试与 75% 覆盖率检查。
- CI 提速（2026-11-02 已推送 dev；`2cdedeb` 收紧 baseline 后运行 `41454578872` 全绿，总耗时 141 秒，该次改动不涉及前端，Web 已跳过）：`web.yml` 并入 `ci.yml`，3.12 拆 3 片、3.11 拆 2 片并用 pytest-xdist 并行，配对实测 306 秒降到 125 秒；`CI OK` 汇总全部 job，已设为 dev 必需检查（不要求分支最新，admin 可绕过），纯文档提交不跑测试。新增共用真库的用例必须标 `xdist_group("shared_pg")`。
- 类型检查用 basedpyright（standard，全仓唯一，配置在根 pyproject）；存量错误记在 `.basedpyright/baseline.json`，CI 只拦新增。本地默认 auto 模式会自动改写 baseline，CI 是 lock 模式，baseline 过期（错误减少）也会失败，提交前用 `CI=true uv run --frozen basedpyright` 验证并带上 baseline 变化。gr-tools 是否启用 strict 待定。
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
