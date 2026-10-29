# gr-data — 数据层

配置、数据库连接，以及外部行情数据的接入（下载 → 归一化 → 入库）。

import 名 `gr_data`，命令行 `gr-data`。**建库与迁移不在本包**，DDL 的唯一真源是
`gr-db`（`gr-db migrate`）。

---

## 分层

| 层 | 职责 | 输入 → 输出 | 是否归一化 |
|---|---|---|---|
| `config` | env 型配置（`settings`）+ 采集矩阵（`pipeline`） | — | — |
| `db` | PostgreSQL／ClickHouse／DuckDB 连接与批量写 | — | — |
| `raw` | 下载 | 供应商 SDK → `$RAW_PARQUET_ROOT` 的 parquet | 否（保留源语义） |
| `ingest` | 入库 | parquet → 归一化 → PostgreSQL | 是（canonical） |
| `stream` | 实时 | 行情流 → `realtime.tick_buffer` | 是 |

**层优先、源其次**：顶层按职责分层，每层内部再按 provider 切分。新增数据源 =
在 `raw`／`ingest` 各加一个纵切片；改某层逻辑 = 只动一个横切片。

```
AmazingData(银河)  → raw/yinhe     → parquet → ingest/yinhe     → PostgreSQL
Tushare Pro        → raw/tushare   → parquet → ingest/tushare   → PostgreSQL
rqdatac(米筐)      → raw/ricequant → parquet → ingest/ricequant → PostgreSQL
INSIGHT(华泰)      → raw/insight   → parquet → ingest/insight   → PostgreSQL
银河／INSIGHT 实时  → stream/<provider> ───────────────────→ realtime.tick_buffer
```

`raw` 与 `ingest` 解耦：`raw` 只把数据原样落地，`ingest` 只消费 parquet，
便于回放与审计。

**边界**：本包只做数据接入。因子、回测、策略、交易决策分别属于 `gr-factor`、
`gr-backtest`、`gr-signal`。

---

## 跑起来

```bash
# 1. 配置：凭证只写环境变量名，明文不落配置文件
cp .env.example .env                                   # 仓库根，填 PG 与各 provider 凭证
cp packages/gr-data/config.example.yaml config.yaml    # 填抓取范围与限频

# 2. 建库（DDL 归 gr-db）
uv run gr-db migrate --target pg

# 3. 抓取 + 入库（以 tushare 为例）
uv run gr-data raw tushare --mode update    # 增量抓取落 parquet
uv run gr-data ingest tushare               # 归一化入库
```

`raw update` 之后接 `ingest`，多 provider 各自一条链，适合放进 cron。

### Tushare 已实现范围与导入顺序

默认范围覆盖 12 个接口：`stock_basic`、`index_basic`、`fut_basic`、`trade_cal`、`fut_trade_cal`、
`daily`、`adj_factor`、`stk_limit`、`suspend_d`、`index_daily`、`daily_basic`、`fut_daily`。
财报、宏观不在这批接口范围内。ETF／期权新增接口须显式启用，见下节；
未配置任务、旧 `all`／`reference`／`bars_1d` 均保持原范围。

先应用迁移 046（允许同一来源的多个旧代码关联同一证券，保留来源代码唯一约束）。
股票清单含北交所标的时，`instruments` 还采集 `bse_mapping`，原样保存至
`instruments/bse_mapping.parquet`。`symbol_map` 将其中的旧代码关联到新代码的
同一股票 ID；`300114.SZ → 302132.SZ` 另依
[公司换码实施公告](https://static.cninfo.com.cn/finalpage/2025-02-15/1222544408.PDF)
登记。原始行情和事件代码不改写，不另建旧代码标的；缺目标或已有映射冲突时拒绝导入。
这是证券身份别名，不是历史代码有效期或历史可得性证明；历史名称与代码时点回放另行处理。
北交所对照字段依据 [Tushare 官方文档](https://tushare.pro/document/2?doc_id=375)，
不能按 `920` 前缀或末三位猜测对应关系。
若同日同时返回新旧代码，映射后仅在全部数值一致时合并，优先保留 canonical
代码观察；任何核心字段冲突均硬失败。唯一已核验例外是中航成飞的
`daily_basic.limit_status`：旧代码历史值固定为 0，新代码与日线涨跌方向一致，
按新代码保留并记录差异计数。原始两份观察仍完整留在 raw 中。

| ingest 组别 | importer → 目标表 |
|---|---|
| `reference` | `instruments` → `meta.instruments`；`symbol_map` → `meta.symbol_map`；`calendar` → `meta.trading_calendar` |
| `events` | `suspend_d` → `market.stock_suspend_event`、`market.stock_suspend_coverage` |
| `bars_1d` | `stock_bar_1d`／`index_bar_1d`／`future_bar_1d` → 对应 `market.*_bar_1d` |
| `market_ext` | `daily_basic` → `market.stock_daily_basic`；`adj_factor_ts` → `market.adj_factor_ts` |
| `fundamental` | `valuation_1d` → `fundamental.valuation_1d` |
| `classify` | `instrument_category` → `classify.instrument_category` |

raw 先抓标的和日历。股票按 `trade_date` 逐日请求全市场；指数按白名单逐代码整段请求，
期货按白名单交易所逐日请求，均按自然月落盘。
每页请求（包含末尾空页探测与失败后的重试）都遵守
`providers.tushare.rate_limit.sleep_between_requests_sec`；遇到 offset 硬上限直接失败，
不把同一超大查询重试数遍。

`update` 补缺失月份并重抓最新已有月份。`start_date` 落在月中时，重抓保留月内
未请求日期，只替换本次已请求的日期。空 `suspend_d` 响应会清除对应日期的旧事件；
其他逐日数据集若在已有数据的日期返回空响应，会拒绝覆盖，避免把历史行情擦掉；
旧分区里没有的日期也一样：今天以前的交易日返回空响应即拒绝写出该月（缺一天的
分区在不再是最新月后不会被重抓）。今天的空响应视为尚未发布，只记 info，下次
`update` 重抓最新月时补齐。任意一天请求失败时不替换该月文件。

月内合并时，`trade_date` 的整数／字符串表示统一保存为 `YYYYMMDD` 字符串，
日期含义与行情单位保持不变。损坏的月文件可通过覆盖完整自然月的 `--mode init`
重建；该月起点须为月初，且已到月末。非稀疏数据存在空响应时不以不完整结果
重建损坏文件。月中起抓、尚未到月末或 `update` 仍需读出旧文件，读取失败时
明确报错并保留原文件，以免丢掉未请求日期。
按白名单采集的 `index_daily`／`fut_daily` 例外：整月 `init` 也要读出旧文件以保留范围外的行，
旧文件损坏时同样报错；需要重建时先把损坏文件移出分区目录，并确认范围外数据可另行补回。

```bash
uv run gr-data raw tushare --only instruments,calendar --mode update
uv run gr-data raw tushare --only future_calendar --mode update  # 启用期货时必需
uv run gr-data raw tushare --only daily,adj_factor,stk_limit,suspend_d,index_daily,daily_basic,fut_daily --mode update
uv run gr-data own list
uv run gr-data ingest tushare --only reference
uv run gr-data ingest tushare --only events,bars_1d,market_ext,fundamental,classify --months 2024-01
```

选中的数据集按依赖顺序执行，即使 `--only` 顺序相反也先处理依赖；未选中的依赖
不会自动启用。历史数据建议逐月导入，避免一次加载全部月份。
`daily_basic` 和 `valuation_1d` 共用原始文件，各自在目标金额列做万元→元转换；
未提升字段在 `raw_payload` 中保持供应商原单位。缺复权因子或股票 OHLC 会中断；
个别代码缺涨跌停价保留 NULL 并记软告警。股票辅助表关联前统一 int8／字符串日期
及代码首尾空格，再按键去重；期货成交量与持仓量保持「手」。

### ETF 与三类期权（2026-10-26，代码与测试阶段）

实现范围为沪深 ETF、ETF 期权、股指期权和商品期权日线；
使用 [专用配置样例](config.tushare-etf-options.example.yaml) 显式选择。
本节说明代码行为，不代表真实样本、历史完整性、正式发布或全量回补已经验收。
设计依据见相邻设计仓 `data-platform/proposals/tushare-etf-options-ingestion.md`。

| 阶段 | 显式任务／组 | 结果与依赖 |
|---|---|---|
| raw | `etf_instruments` | `etf_basic` 的沪深 L／D／P 清单 → `instruments/etf.parquet`；P 表示待上市 |
| raw | `calendar`、`option_calendar` | 沪深日历，以及 `option_exchanges` 选中期货市场的逐所日历 |
| raw | `fund_daily`、`fund_adj` | 逐日分页、月分区，源基金记录保留；因子页长 2000，日线 5000 |
| raw | `opt_daily` | 八所逐所逐日取数，页长 15000 → `opt_daily/YYYY-MM.parquet` |
| raw | `option_instruments` | 从所选日期、市场的 opt_daily 发现代码，按 opt_code 分页查 opt_basic；未知标的先精确引导，缺失代码精确回退；必须在日线之后运行 |
| ingest | `etf_reference` | `etf_instruments` → `etf_symbol_map`，分别写 meta.instruments／symbol_map |
| ingest | `etf_bars_1d` | 只导 ETF 清单内记录；源基金因子按代码、日期精确配对 → market.etf_bar_1d |
| ingest | `option_reference` | `option_instruments` → `option_symbol_map` → `option_contracts`；标的身份和 source 映射须预先具备 |
| ingest | `option_bars_1d` | 未复权源报价、结算价及手数 → market.option_bar_1d；默认有验证门禁 |

ETF 期权标的必须是 ETF，股指期权标的是指数，商品期权标的是具体期货合约。
现有标的参考信息可以复用，但必须先核对来源、哈希、映射和表归属；不会自动抓取所有标的的行情。
`AP405C8000.ZCE` 这类郑商所期权代码原样保留，标的从显式 `opt_code` 解析；不扩写期权代码年份。
元数据覆盖范围是“目标行情出现的代码”，不能据此声称已取得无行情合约在内的完整挂牌全集。
`init` 重新观察范围内全部目标代码；`update` 只重查新增、缺可靠观察日、
缺最后交易日，或最近观察日不晚于最后交易日的合约。
到期后已观察过的合约复用原记录；全跳过时返回 0，不发布新观察。
观察日独立保存在观察目录的 `observation_dates.parquet`，哈希写入清单和收据；
缺失、损坏或哈希不匹配时退回重查，不给源列添加内部日期。
查询优先复用已有元数据的显式 `opt_code`。冷启动时从尚未覆盖的代码中选一个精确查询，
获得其 `opt_code` 后按标的批量补齐，不从期权代码猜标的或年份。
通常每标的一次引导即可覆盖同组代码；若批量漏码，尚未建立映射的代码仍可能需要额外精确引导。
标的响应全量校验 `opt_code`、市场、代码后缀与分页键，不能先过滤再掩盖错市场／错标的。
批量缺失的目标代码回退到精确查询，记 WARNING 和条数；引导响应可复用，不重复请求同一代码。
若标的下所有目标代码都已在到期后观察过，则不请求该标的；同一标的响应中的已跳过合约也不覆盖原记录。
兼容元数据文件只更新本轮需要的代码，完整的批量／精确源响应另存观察目录的 `responses/`，
清单记录各文件行数、哈希，保留超出目标范围的源行。响应分批暂存，内存按单标的响应加目标行控制，
仍受客户端 offset 上限和重复页守卫保护。日志／收据分别记录 `underlying_queries`、
`bootstrap_queries`、`fallback_queries`、`fallback_rows`；查询计数为逻辑查询，分页的实际请求数另测。

| 字段 | ETF | 期权 |
|---|---|---|
| OHLC／前收 | 未复权源价格，不乘因子 | 保持报价尺度，不乘合约乘数变成现金金额 |
| volume | 源 vol ×100，精确转为基金份额整数 | 保持手数，拒绝小数手数 |
| amount | 千元 → 元，Decimal ×1000 | 万元 → 元，Decimal ×10000 |
| 因子 | 同日 fund_adj，必须有限且 >0；缺失不填 1／不前后填充 | 不复权；不把 ETF 因子套到调整期权 |
| 持仓量／结算 | 不适用 | oi → 既有列 open_interest，手数；合法 NULL 保留，零成交不等于缺失 |

期权额外接受精确的缺失占位模式：`open=high=low=0` 且 `close>0`，不按交易所或成交量限制。
raw 源值不变，收据 `scope.ohl_zero_placeholder_rows` 按交易所记录条数、非零成交量条数，
以及各最多 5 个键样本。ingest 仅把这些行的 OHL 显式映射为 NULL，
保留 close／settle／成交量／成交额／OI，并按交易所记软告警和同样的计数／样本。
只有部分 OHL 为零、OHL 全零而 close 不大于零、high<low 或正常价格中的 close 越界仍失败；
ETF 的价格包络校验不变。此口径不代表期权正式写入已开放。

`fund_daily`／`fund_adj` 的源代码统一只要求非空、无首尾空白的字符串；
七位代码或带 `!` 的非标准代码保留在 raw，不改码、不删行。
收据 `scope.nonstandard_code_rows` 记录条数和最多 5 个代码样本；
fund_daily 的 closed-market 检查只作用于六位 `.SH/.SZ` 代码。
ETF 入库仍只选严格 ETF 名单内的代码，日志另记被排除记录中的非标准代码数。

ETF 的 L／D 名单仍要求六位交易代码、市场一致及有效上市日。
P 名单允许非交易代码（如 `.OF`）、空上市日和空简称；raw 保留全部记录，
收据 `scope.pending_rows` 记录 P 总数、非标准代码数和缺上市日数。
**本实现选择全部跳过 P 的身份及 symbol_map 写入**，包括字段完整的 P 行，并记条数和最多 5 个样本的软告警。
后续变为 L 时再登记，不自动把 `.OF` 改为 `.SH`，不因待上市元数据不完整阻断已有 L／D 记录。

新增任务要求显式 `start_date`，按配置区间重核月份；`init`／`update` 都保护范围外日期和交易所。
这与旧股票“只刷新最新月”的策略不同：只应配置当前需要处理的月，不要把长期区间用于高频 update。
已过去的开市日空响应、错日期／市场、冲突键、非法值、目标精度溢出均失败；不会把负期权价当 SCTAS 价差放行。
当天尚未发布的空响应按数据集／交易所记 WARNING 和 `scope.pending_days`，
不算采集失败，也不删除旧文件里当天已有的行；pending 不代表当天数据已齐备。
当天 ETF 日线已发布而因子未发布时，入库仍因缺因子失败，不填充因子。
历史回补须根据各所期权正式上市范围收窄 `option_exchanges`；不能把上市前的
开市日空响应当作合法数据，也不能凭记忆填写上市日期。

新资产文件带同名 `.json` 收据，记录哈希、上海观察时间、范围及脱敏只读请求。
`tushare/observations/<dataset>/<observation_id>/` 保存本轮数据、清单及被替换的旧文件／旧清单。
消费端校验文件与收据哈希；缺收据或不匹配时拒绝入库。
采集侧仅在当前文件能匹配本数据集的完整观察清单、数据副本及前版关联时，
恢复“文件已替换、收据未替换”的中断发布，记 WARNING 后继续；校验先于创建新观察目录。
首次发布崩溃而缺收据时，仅当文件与本数据集的首次观察清单和数据副本哈希一致，
且该观察没有任何后继，才补写收据恢复；已有后继的旧观察不可借此回滚。
其余缺收据，或文件与全部合法观察均不匹配时仍拒绝覆盖，不能靠手工改文件绕过门禁。
源列与原单位留在 raw，机器根路径只取 `RAW_PARQUET_ROOT`，不新增共享默认数据目录。

**期权正式写入仍关闭。** `opt_basic` 给出的调整后行权价和乘数没有历史生效区间，
`meta.option_contracts` 只能承载当前观察。本轮不新增历史参数表，也不允许把该快照当作历史参数。
默认在连接数据库前拒绝包含 `option_instruments`／`option_symbol_map`／
`option_contracts`／`option_bar_1d` 任一期权 writer 的 CLI 计划；
库调用 `.run()` 也在 claim／写入前检查。只有在隔离验证库上显式设置
`TUSHARE_OPTION_VALIDATION_ONLY=1`（库调用 `validation_only=True`）才能验证，
且 `APP_ENV=prod` 拒绝该开关。该开关不验证连接是否为临时库，执行者必须先核对 PG_*；
验证写入明确记录软告警，CLI 返回 3，不可当作已发布成功。

ETF／期权日线一次只导入一个月，防止隐式拼接全历史。未来样本审核获准后，
确认独立 raw 根、临时 PG 环境及依赖齐备，再执行下面的样本命令；本文未执行这些真实采集命令：

```bash
uv run gr-data --config packages/gr-data/config.tushare-etf-options.example.yaml raw tushare --mode init
uv run gr-data --config packages/gr-data/config.tushare-etf-options.example.yaml ingest tushare --only etf_reference,etf_bars_1d --months 2024-01
# 只对临时验证库，并先准备所需的标的参考信息和映射；预期退出码 3，表示未发布：
TUSHARE_OPTION_VALIDATION_ONLY=1 uv run gr-data --config packages/gr-data/config.tushare-etf-options.example.yaml ingest tushare --only option_reference,option_bars_1d --months 2024-01
```

ETF 分类暂时沿用旧规则：一律 `equity`／`cn_a`，已知不准确（缺口 G4），本轮恢复为基线行为。
目标口径在后续独立任务中改为 Tushare `fund_basic.fund_type` 单一来源，
显式维护映射，未映射或混合型保持未分类。存量错误分类以“删除后按上市日重写”更正，
不用 `out_date` 关闭；真实采样、分类实现、数据删除和 DDL 注释迁移本轮均不执行。
`meta.instruments.status=pending` 仍可表示其他来源的待上市身份；本实现不登记 Tushare ETF 的 P 行。
单表单一 provider 保持不变，所有新 writer 仍校验 ownership，不自动 force 或切源。

**真实回补前待验收（本轮未执行）**：另行授权后，在独立 raw 根只启用
`calendar`、`option_calendar`、`opt_daily` 取得一个月；先不启用 `option_instruments`。
预算按需要重查的 `(exchange, opt_code)` 去重数估算，温缓存、每标的一页且无回退时，
请求数约等于标的数；冷启动另加未知标的引导数，实际总数为各标的页数之和＋引导页数＋回退页数＋重试。
乘以配置间隔估算限流等待量，另计网络耗时；不能只用标的数宣称实际请求数。
每日增量先排除到期后已观察的合约；全历史按去重标的／代码集合及分页规模测量，不能把月度去重数相加当精确预算。
2026-10-26 修复前真实 1 月样本为 19,236 个代码，逐代码约 8 小时；此为旧方案历史证据，
新方案未重新实取，不给出未经测量的标的数或耗时。本轮仅执行 A1–A5 离线修复；B 部分真实复验等待用户确认，
不调用真实 Tushare、不连接任何 PG，也不启动全量回补。
后续 ETF 分类任务在本分支合入后从 dev 另开分支，依赖 ETF symbol_map；
先验证 fund_basic.fund_type 枚举，存量更正前只读计数、备份，工作库删除另行授权。

**2026-10-26 实测进度：预算已测，真实样本验收未通过。** 代码已合入 dev `588a2c5`；
使用独立 worktree 的已提交采集器 `537592d`，已核对相关 raw／ingest 源码及 DDL 与 dev 一致，
采集后源码哈希未变。2024 年 1 月八所各 22 个交易日，共 365,508 条日线、19,236 个代码；
当前逐代码 `opt_basic` 方案首次约需 19,236 次请求，按 1.5 秒间隔约 8 小时，未计重试和额外分页。
1 月 31 日 16,840 个代码只是观察数量，不能当作当前增量请求数；全历史去重请求预算尚未测得。
另做每所一个历史代码的精确元数据探针，8/8 成功，不证明历史调整参数可得。

实取阻塞：DCE 130,118 行、GFEX 38,267 行 OHL=0、close=settle>0，触发高低价校验；
其中分别 79／84 行成交量非零，不能统一按无成交放行。ETF SH／P 名单含 `515470.OF`，
`fund_daily` 的 2024-01-30 含七位代码 `1610221.SZ`，均不符合现有代码契约。
原值、原始响应及失败证据保留，未改码、删行或放宽门禁。ETF 名单和日线未发布；
仅 `fund_adj` 完成 22 日、29,620 行的独立样本发布。总计 252 次请求全部成功，
无 SDK 异常；未进入临时 PG 验收、未连接工作库、未启动全量回补或 ETF 分类更正。
后续先核对上述源口径并完成修复／复验，再做临时库往返与幂等验收。
机器路径和详细请求日志在本机 NOTES 所指的仓库外验收目录，不写入配置默认值。

### 指数与期货日线（2026-10-24，代码审核阶段）

本轮只修代码并用模拟供应商及一次性 PostgreSQL 验证，**真实回补等待用户完成代码审核**。
可审查配置见 [config.tushare-markets.example.yaml](config.tushare-markets.example.yaml)：
起点为 2024-01-01，终点显式固定为 2026-10-23。`end_date` 只限定日线取数，
参考日历仍多取一年缓冲；未配置时沿用当天上限，配置未来日期也不会请求未来日线。

| 环节 | 修复前 | 修复后 |
|---|---|---|
| 普通指数请求 | 仅传交易日 | 按 `index_codes`／`index_markets` 白名单选代码，每个代码一次请求整段区间，再按月落盘 |
| 期货分页 | 按 5000 行判断末页，可能截断 | 按官方 2000 行上限翻页，整页后继续探测 |
| 期货交易日 | 使用沪市日历 | `future_exchanges` 白名单内各所的 `future_calendar/<exchange>.parquet`，逐所检查自然日覆盖后再取开市日 |
| 入库业务键 | 去重后才清理代码 | 先统一代码空白和日期表示，再按代码与交易日保留最后一行 |
| 丢弃不可用行情 | 仅运行日志 | 纳入软告警、ETL `partial` 与 CLI 退出码 3 |

指数接口契约依据 [index_daily](https://tushare.pro/document/2?doc_id=95)。
本机 2026-10-24 的 `index_basic` 落盘有 9,746 个非申万指数（CSI 9,053），逐代码逐月全量约 33 万次请求，
因此 `index_daily` **必须**配置 `providers.tushare.index_codes` 或 `index_markets`（取并集），
未配置即拒绝运行；未知代码、申万代码同样在请求前拒绝。请求次数等于代码数 × 连续月份段数，
与月份数无关（`update` 补缺失旧月加重抓最新月时分段请求，不跨越中间已完整的月份）。
**迁移提示**：已有机器配置若启用了 `index_daily` 却未配范围，升级后该数据集会直接报错，
同一次 `gr-data raw tushare` 里排在其后的数据集也不会执行；先补 `index_codes`。
该接口不覆盖申万，`.SI`／`market=SW` 明确排除；不调用申万或中信专用行情接口。
指数 `list_date` 是发布日期，只限定完整性检查，不删除供应商提供的发布前回溯值；
这类回溯值不是历史时点可得性证明。发布至终止区间内，任一代码过去开市日缺记录即拒绝本次全部落盘，
报错汇总所有缺数据的代码（代码:缺失天数:首个缺失日），便于一次修正白名单；今天尚未发布可留待更新。
`index_markets` 没有排除单个代码的办法：按市场选取时任一代码缺数据，整次运行都不落盘，
且整段行情同时留在内存。CSI 这类大市场未经实测前不要用 `index_markets`，改为逐个列出 `index_codes`。
账户权限、真实覆盖和跨市场指数的日历适用性仍须审核后小样本实取核验，
不能用 mock 通过宣称供应商数据已验收。

期货依据 [fut_daily](https://tushare.pro/document/2?doc_id=138) 与
[fut_trade_cal](https://tushare.pro/document/2?doc_id=467)。仅采集基础合约清单中出现的交易所，
每个开市日必须有该所响应；缺日历、日历日期缺口、非法开市标志、错交易所、错日期、重复响应键
均拒绝写出该月。[fut_trade_cal 文档](https://tushare.pro/document/2?doc_id=467) 只列
CFFEX／DCE／CZCE／SHFE／INE，GFEX 由 2026-10-24 的 live 用例实测确认（2024 全年日历逐日完整，日线只返回 `.GFE` 合约），因此 `providers.tushare.future_exchanges` 默认六所全取，可显式收窄；日历与日线都只取白名单，基础合约中白名单外的交易所记 WARNING 后整所跳过。复核命令：设置 `TUSHARE_TOKEN` 后运行
`uv run pytest packages/gr-data/tests/live/test_tushare_live.py -k "future_calendar_exchange_supported or gfex"`。白名单内的交易所缺日历时明确失败，
不回退使用沪市或其他交易所的日历。
各所的检查起点取 `start_date` 与基础合约清单中该所最早 `list_date` 的较晚者（如 GFEX 20221222、INE 20180326），
开业前不要求日历、不请求日线，也不因缺该所后缀把旧月份判为需重抓；日志 `Future exchange scope starts at first listing` 记录实际起点。
清单里该所没有任何上市日时不放宽，仍按 `start_date` 严格检查。

**扩大范围后的回补**：`update` 原本只补缺失月并重抓最新月。现在还会读取已有分区，
某月缺少当前白名单里的指数代码（该代码在当月应有过去开市日）或交易所（如新加入的 GFEX）时，
该月也会重抓并替换，不会静默留下历史缺口；日志 `Refetching partitions missing current scope` 列出这些月份。
**收窄范围不删旧数据**：`update` 与整月 `init` 重抓某月时，都只替换当前白名单内代码（指数）或交易所（期货）在请求日期上的行；
白名单外的旧行（包括升级前按交易日取得的全量指数）原样保留，日志 `Kept out-of-scope raw rows` 记录行数。
期货还要求日期不早于该所有效起点：清单缺老合约导致起点推后时，起点前的旧行同样保留，不随同日其他所的重抓被删。

日线 `dt/trading_day` 保留供应商交易日，
不从夜盘自然日期推导，也不构造分钟时间戳。`future_calendar` 只用于 raw 调度，不把缺少夜盘信息的
日历写成 `meta.trading_calendar.has_night=false`。

指数成交量按手→股、成交额按千元→元；期货成交量／持仓量保持手、成交额按万元→元。
金额以 `Decimal` 换算。已有的非数值、非有限或负成交量／成交额／持仓量拒绝；缺失仍保留 NULL，
期货手数不允许小数。只发布收盘点位的指数、只有结算价的期货仍保留，不能补造 OHLC。
各月逐份检查必需列，避免其他月份补齐列名掩盖缺列文件。

**原油 TAS 价差（2026-10-25 实测）**：`SCTAS` 月合约及主力／连续序列的 `open/high/low/close/pre_close` 是结算价偏移量，`settle/pre_settle` 仍是绝对结算价。依据[能源中心通知](https://www.ine.com.cn/eng/circularnews/circular/202303/t20230329_822378.html)，2023-04-11 交易日起该偏移量可在 [-2, 2] 元/桶内，因此 -0.1 是合法价差。独立 raw 回补执行器调用 `raw/tushare/quote_rules.py`：只对代码与基础信息 `exchange=INE, fut_code=SCTAS` 均确认的 TAS 价差字段应用对应边界；普通合约、所有结算价、成交量／金额／持仓量仍非负，已有非数值或非有限值拒绝。源 NULL 和负价差原样保留，不补零、不取绝对值、不加结算价重造 OHLC。**普通 `future_bar_1d` 没有 TAS 价差语义：importer 按代码形态（`SCTAS????.INE`／`SCTASL.INE`／`SCTAS.INE`）整行排除 TAS 行，计软告警（ETL `partial`、CLI 退出码 3），raw 不变；单独的存储与消费语义定案前，这些合约不进入 `market.future_bar_1d`。**

审核后的运行顺序为 `instruments → calendar/future_calendar → index_daily/fut_daily`，
再导入 `instruments,symbol_map,calendar`，最后逐月导入 `index_bar_1d,future_bar_1d`。
先核对工作库表归属、真实小样本、日期覆盖、单位和行数，再批准历史回补；不使用包含股票的
`bars_1d`／`all` 组名，也不自动转移表归属。独立 worktree、独立虚拟环境和明确的配置路径
应保留至本轮验收，不合并或修改米筐正在使用的工作目录。

### 导入门禁与退出码（Tushare）

Tushare importer 严格校验，下列情况**硬失败**：本 importer 不写库并回滚，
`ops.etl_job_run` 记一条 `failed`（`error` 只含错误类别、数据集、月份、计数与少量样例代码），
其后的 importer 不再执行；之前已提交的 importer 保留。

| 硬失败 | 说明 |
|---|---|
| raw Parquet 存在但不可读 | 报 `Corrupt raw parquet: <数据集>/<文件>`，不删除、不覆盖该文件 |
| 所选月份缺必需分区 | `--months` 指定的月份或主数据集现有月份缺分区；`stock_bar_1d` 还要求同月的 `adj_factor`、`stk_limit` |
| 未知代码 | 不在 `meta.symbol_map` 的行整批拒绝，不丢行；先跑 `instruments`、`symbol_map` |
| 质量问题 | 空数据集、缺必需列、主键重复、必需列为空；股票日线成交量／成交额缺失、非数值或非有限；`daily_basic`／`valuation_1d` 缺目标列对应的源字段（缺列会让整列 NULL 经 UPSERT 覆盖已有值） |
| 股票标的或沪深日历缺失 | `instruments[stock]`、`calendar[SSE]`、`calendar[SZSE]` |
| 停复牌 raw 与库不一致 | raw `suspend_d` 有有效凭据，但库内缺这些日期的覆盖或哈希不同，说明未重导停复牌，先跑 `suspend_d` |
| 表归属冲突 | 目标表已归属其他 provider；记 `failed`，退出码 1（此前为 2） |

配置里写了不存在的 importer 名属于配置问题：在连接数据库之前报错，退出码 2，不写流水。

**软告警**照常写库，运行记为 `partial`：个别代码缺涨跌停价、`pre_close` 不一致
导致丢弃涨跌停价、非法涨跌停价、残留 `*.tmp-*` 文件（不读入）、指数或期货标的缺失。
首日上市无前收盘、因而无涨跌停价的行不算软告警，只记 info 与 `ops.data_quality_check`；
供应商哨兵值表示的「当日不设涨跌幅」也不算软告警（见下节）。

### 涨跌停状态（045，D-024）

`stock_bar_1d.price_limit_status` 区分「当日不设涨跌幅」与「涨跌停价未知」，组合回放据此
判断开盘是否达到涨停价。先执行 `uv run gr-db migrate --target pg` 应用 045，再重导受影响月份。

| 状态 | 判定（Tushare `stk_limit`） | `limit_up`／`limit_down` | 软告警 |
|---|---|---|---|
| `LIMITED` | 两侧涨跌停价有效；`stk_limit` 带 `pre_close` 时还须与日线一致（缺该值则不比较） | 原值 | 否 |
| `NO_LIMIT` | 哨兵值：`up_limit ≥ 99999` **且** `0 ≤ down_limit ≤ 0.01` | NULL | 否（记 info 与 `ops.data_quality_check`） |
| `UNKNOWN` | 缺行、非法值（含只有一边像哨兵、无穷值）、`pre_close` 不一致 | NULL，单边缺失时保留另一边 | 是；首日无前收盘且只是缺可用涨跌停价的行不计，非法值仍计 |
| NULL | 未评估：045 之前写入，或其他供应商写入 | 不约束 | — |

哨兵取值依据 2026-09 真实样本 63 行（北交所 `99999.99/0.0`，沪市 `99999.999/0.01`，
深市 `999999.999/0.01`）；历史回补时须复核更早年份。首日无 `stk_limit` 行时记 `UNKNOWN`，
不按上市规则推断为 `NO_LIMIT`。数据库约束保证 `LIMITED` 两侧有值、`NO_LIMIT` 两侧为 NULL。

| 退出码 | 含义 |
|---|---|
| 0 | 全部成功 |
| 1 | 有 importer 硬失败；stderr 列出已提交与未执行的 importer |
| 2 | 配置问题（缺凭证、缺 SDK、未知 importer 名等） |
| 3 | 完成但有软告警，stderr 列出需复核的表 |

预期内的失败（门禁、坏文件、归属冲突）日志只记摘要；其他异常多为程序缺陷，日志保留完整堆栈。

指数／期货标的缺失只是软告警，但此时 `index_bar_1d`／`future_bar_1d` 的行情代码全部未知，
会按未知代码硬失败并停止其后的 importer。一期不需要指数与期货时，不要把它们列入 ingest 名单
（不要用 `bars_1d`、`all` 组名）。

其他供应商（银河、米筐旧链路、DataYes、INSIGHT）一期不使用，仍为旧的「记警告后写入」，
启用前须先接入同样的门禁。

### 停复牌事件与逐日状态（D-023）

先执行 `uv run gr-db migrate --target pg` 应用 044，再重抓没有覆盖凭据的旧
`suspend_d`：`uv run gr-data raw tushare --only suspend_d --mode init`。
该命令仍按配置起点抓到今天；分月导入用
`uv run gr-data ingest tushare --only suspend_d --months 2026-09`。
本机配置的 ingest 列表须包含 `suspend_d`（或 `events`／`all`）；注册表使它先于股票行情执行。

每个停复牌月分区配有 `.coverage.json`，记录实际成功请求日期（含空响应）、
Parquet 哈希及分区观察时间。缺凭据须重抓，哈希不符拒绝导入；它是当前 raw
覆盖证据，不是 D-022 发布版本，也不能证明历史时点已经获知这些事件。
事件与覆盖按已证实日期在一个事务内替换，同时刷新已有日线的状态；有效空响应
可以撤销旧事件，失败回滚。其他月份和价格列不动，未知标的直接拒绝。

| 当天证据（须有成功采集覆盖） | 状态 |
|---|---|
| 有 bar，无停牌 S（可以有 R） | `NORMAL` |
| 无 bar，只有无时段 S | `HALTED` |
| 有 bar，S 提供日内时段；同日 R 不抹掉该事件 | `INTRADAY_HALTED` |
| 缺覆盖、既无 bar 也无事件、无时段 S/R 同日、其他冲突 | `UNKNOWN` |

全天停牌通常没有 bar，不插入无价格行。使用
`gr_data.db.trading_status.load_stock_trading_status(conn, instrument_ids, start, end)`
结合标的上市区间及开市日历读取完整日级状态；缺日历时报错，不将沪深日历套用于北交所。
该函数和行情派生列共用状态规则，不跨日填充，不以日级状态推断开盘可买性。
股票行情的 `trading_status` 只从库内事件与覆盖表推导（不再读 raw）。raw 有有效凭据时，
库内缺这些日期的覆盖或哈希不同即硬失败，须先跑 `suspend_d`；raw 缺分区或没有凭据时不比较，
库内无覆盖的日期写 `UNKNOWN`。
抓取端遇到与分区不符的凭据（例如写完分区、未写凭据即中断）时记 WARNING，并按本次请求的
日期重建该月分区与凭据，无需手工删除凭据；读取端仍拒绝不符的凭据。
这些状态仍需接入具体回测／诊断调用方，不代表已发布诊断数据版本。

### 米筐风险模型五件套

DataYes 试用到期后的接替入口为 `rq_risk_model`，独立于 R1–R10 补充数据。
支持米筐标准 `v1/v2/v2trd`、`sws_2021/citics_2019`，期限固定 `daily`，
因子收益固定 `whole_market + implicit`。SDK 按日取暴露、因子收益、协方差、
特异收益和特异波动率；不需要额外 SDK，写库前需应用迁移 047（见下）。

先填写 `providers.ricequant.risk_model`：显式起止日期、沪深股票代码清单、
模型／行业体系、确认的模块权限及四项源单位和核对依据，再设置 `selected: true`。
本地官方文档未明确全部数值单位，因此样例保持空值，不能照抄其他供应商的系数。
`order_book_ids` 是本次完整采集范围；不会用当前股票名单回填历史，不自动跳过
尚未上市、停牌或模型不覆盖的股票。范围内任一股票缺失时整日失败，应核对覆盖后
分段配置。北交所、港股与需要额外包的定制风险模型暂不支持。
raw 需要 `RICEQUANT_ENABLED=true` 和 `RICEQUANT_API_KEY`；离线 ingest 不需要密钥。

写库前需应用迁移 047：`factor_order`、载荷、协方差、因子收益数组必须非空、一维、
长度与 `factor_count` 一致、元素非 NULL 且有限，由数据库约束拒绝。明细行的
`factor_count` 必须等于所属 `model_run` 的因子数，这条跨表规则由入库门禁检查，
不一致时整日回滚；通联的载荷、协方差、因子收益导入同样适用。

```bash
uv run gr-data --config /path/to/config.yaml raw ricequant --only rq_risk_model --mode init
uv run gr-data --config /path/to/config.yaml ingest ricequant --only rq_risk_model --months 2024-01
```

`init` 跳过已完整采集日，`update` 重抓显式日期范围。每轮保存恢复进度，失败后
同范围、同模式续跑只处理未完成日；日内尚未完成的批次重新请求。
请求按 `batch_size` 分批，配额触及共享 `supplements.quota_reserve_fraction`
（默认剩余 10%）时暂停。观察位于
`$RAW_PARQUET_ROOT/ricequant/rq_risk_model/v1/<variant>/<YYYY-MM-DD>/<observation_id>/`。
Parquet 使用 zstd，五份全部通过轴、完整性、有限值、行业哑变量、协方差对称与
严格正定检查后才发布 manifest；读取时复核哈希。R2 的相对非对称误差上限为
`1e-8`，按实际入库的上三角镜像矩阵检查正对角、Cholesky、正特征值和条件数，
不修补 raw 矩阵。条件数 `>1e6` 告警、`>=1e8` 拒收。未完成日不会入库。
新 manifest 保留采集前后的账户配额计数和观察时刻；计费更新可能延迟，零增量
不等于零流量，也不能将账户增量直接认作单次网络传输量。

ingest 依赖已存在的 canonical 股票 `meta.instruments`，按 `.XSHG→.SH`、
`.XSHE→.SZ` 严格关联并写入独立 `ricequant` 代码映射。五张数据表、模型元数据、
映射和成功 ETL 流水在同一日事务内提交；映射缺失或写入失败则该日全部回滚，
失败流水另开事务记录。ETL 包含交易日、请求范围、模型／run／观察身份、质量报告
和真实开始／结束时间；告警写入 warning_count，不因有业务行就隐去质量问题。
单位统一到现有契约：协方差与特异方差为年化 `%²`（日频按 252 换算，σ 先平方），
因子收益为日频小数，特异收益为日频百分比。源单位和依据保存在 `model_run.units`。
R1 在归一化后检查总年化波动率：截面中位数须在 `[5%,150%]`，个股在
`[1%,300%]` 外告警，超过 20% 个股越界则拒收。条件数和量级报告保存在 ETL request，
不改变既有不可变 model_run 的元数据。该工程阈值不表示风险模型已经校准。

历史批次还须在每月一个基准日用固定 30 股及全部因子的完整 120 交易日复核源单位：
年化小数口径下，协方差对角／因子收益样本方差的中位数应在 `[80,800]`，
特异标准差／特异收益样本标准差应在 `[5,50]`，任一组越界比例超过 20% 拒收。
计算函数是 `common.ricequant_risk_quality.validate_source_units`；日期完整性、排序、
股票与因子轴对齐由调用方先检查。**原生 raw／ingest CLI 不会自动下载这 120 日参考**；
本次历史验证由逐月运行编排先调用该门禁，保存参考 Parquet、哈希和报告，再调用 CLI。
缺历史不能默认通过。预测／过去实现波动率比值 `[0.5,2]` 外仅告警，不据此校准。
米筐使用独立模型身份；每次日度观察生成不可变 run，重复导入同一观察幂等。
`available_at` 使用实际采集时间，历史回填不会伪装为当时已可得；全区间校准前
始终 `calibrated=false`，不代表已经通过真实市场五表自洽验收。

切换到米筐前需显式处理以下 8 张表的归属：`factor.model`、`factor.definition`、
`factor.model_run`、`factor.exposure`、`factor.covariance`、`factor.factor_return`、
`factor.specific_risk`、`factor.specific_return`。先查看 `gr-data own list`，
确定切换后逐表执行 `gr-data own set <table> ricequant ingest`，并停止 DataYes 写入任务。
风险 importer 不接受 `--force-ownership`，也不自动转移或删除旧数据。
旧 CNE6 历史保留其 model/run 身份，下游需显式选择米筐模型，不能拼接为同一条模型历史。
真实样本验收及历史链路验证的日期、范围与限制见 [米筐验证记录](../../docs/history/2026-10-23-rq-risk-validation.md)，当前回补状态见 [NOTES](../../.agents/brain/NOTES.md)。
固定名单不等于全市场历史；动态名单与覆盖设计见
[分阶段实施方案](../../docs/plans/ricequant-historical-universe.md)。

新动态名单使用独立的 `universe_policy: listed_cn_a_v2`，不配置 `order_book_ids`，
研究样本显式标记 `purpose: validation`；production 的 2a 前置见下节。日期下限为 2024-01-01。旧固定名单继续使用
v1 raw 身份，动态名单使用 v2；每天的候选变化保存在带哈希的名单快照内，不改变
variant。动态 raw 额外只读 PostgreSQL 的证券身份和别名，再与米筐参考边界核对；
不按今天的 active、ST 或行业筛选历史股票。输入、SDK 解析后的请求及实际返回代码
分别留证，未知身份或映射冲突不能按六位数字猜测。
上市区间以 Tushare `list_date <= day < delist_date` 为准，停牌不提前结束上市区间。
版本化代码规则目前仅含 300114.SZ → 302132.SZ（2025-02-17 生效），按交易日选择请求代码。
规则版本与哈希进入新 variant，正文冻结在 raw；旧 `listed_cn_a_v1` 与旧 raw 保持原规则重放。

风险模型的 `start_date`／`end_date` 在 raw 和 ingest 阶段均为必填 ISO 日期，
终点必须早于运行当天；日常更新也不会自动推算最新交易日或从数据库续接。
每次按已核对的采集／入库账本确定待处理区间，并在执行前固定日期；
`--mode init` 跳过已有完整观察，适合补缺，`--mode update` 重抓指定区间并生成新观察，
失败后同区间、同模式续跑复用本轮进度。ingest 同样按配置日期过滤 raw，
`--months` 只进一步缩小范围，不替代起止日期。无人值守更新仍需后续调度层生成日期窗口。

动态 writer 还需要迁移 048 的 `factor.model_run_coverage`，归属同样为米筐。
成功请求中的单股未返回或部分接口缺失可保存为降级日；三张个股表使用同一完整交集，
覆盖表保留全部候选。数值异常、未知响应、全局接口失败及没有任何完整股票仍阻断。
覆盖表、五件套和成功 ETL 同日提交；原始响应保持原样，读取时重新核对覆盖证据。
`unmapped_symbol` 仅指身份已知但无请求代码；它与 `sdk_filtered`、
`universe_boundary_unknown` 都要求请求码为 NULL、三项返回状态全为 false。
数值异常、无法识别证券身份和范围外市场不写成覆盖表行。逐股 evidence 不重复保存
整日名单或参考快照，共用证据摘要在 run／ETL 中保留。全市场采样后另报每行及
evidence 的平均字节数；动态导入在同日事务中登记、检查覆盖表的 ricequant 归属。

第一阶段仅开放验证采集。D-022 发布清单与可靠性 B1／B2、诊断隔离读取需另行评审；
完成前不开放正式风险读取。`calibrated=false` 与验证用途是两个独立概念，不能用
最大采集时间或同模型最新 run 代替正式发布清单。全市场回补与覆盖阈值须依据独立样本
再次确认；当前没有自动批准全量回补。

### 米筐特色指数补充（R1–R3，待真实样本准入）

已实现 `rq_index_daily`、`rq_index_components`、`rq_index_weights` 的离线契约、
分片采集、观察版本存储和严格读取。它们是独立 `.RI` 数据集，保持原单位，不进入
普通指数行情表或 `meta.instruments`。当前只验证 Fake SDK 链路；**新的 PostgreSQL
表、代码映射及 importer 尚未实现**，补充 ingest 命令会在连接 PG 前明确拒绝。
正式启用按设计的 P0 逐项确认权限、与 Tushare／Datayes 的差异、样本形态及日期区间，
再推进对应 DDL／writer；R4–R10 保持未实现的条件候选。

示例配置的 `providers.ricequant.supplements.datasets` 全部 `selected: false`。
每个启用项要求 `tushare_overlap/datayes_overlap=distinct`、`rq_permission=confirmed`、
`contract_status=verified`、证据引用和核对日期，且显式填写起止日期和代码白名单。
这些值应来自实际核验，不能照抄测试 fixture。SDK 边界已按本地 3.2.5 核对，未升级依赖。
成员接口须显式填写经样本确认的 `enable_bjse`；同批任务该值须一致，不一致时分批运行。
raw 还要求入口环境快照中 `RICEQUANT_ENABLED=true` 和非空 `RICEQUANT_API_KEY`，
密钥不写 YAML 或 manifest。连接／请求超时默认 5／60 秒。

准入完成后只运行明确选中的补充数据，例如：

```bash
uv run gr-data --config /path/to/config.yaml raw ricequant --only rq_index_daily --mode init
# 三项分别选定且通过准入后才可用组名
uv run gr-data --config /path/to/config.yaml raw ricequant --only rq_indices --mode update
```

旧任务默认列表及 `all` 的范围保持不变。`--only ''` 或配置空列表执行零任务；
未知、未选定、未准入或尚未实现的名称令整批预检失败，不会偷偷回退到旧行情任务。
只做补充采集的配置可将 `enabled.raw.ricequant`、`enabled.ingest.ricequant` 都设为空，
使用显式 `--only`；不要为了启用补充任务转移普通行情表的 owner。

采集依赖现有 `tushare/calendar/SSE.parquet` 覆盖所选自然日区间，记录其哈希，不联网
另造交易日历。日值按代码批×自然月，成分／权重按单指数单交易日切片；VX 成员接口
标记不适用且不发请求。update 补缺片并回扫末月和最近 5 个交易日。请求重试后仍超时或响应超过内存预算时先二分日期、再二分代码；
单代码单日仍失败则保留失败状态。父片仅在所有子片完成后计为覆盖。

观察文件位于 `$RAW_PARQUET_ROOT/ricequant/<dataset>/v1/<variant>/<YYYY-MM>/<observation_id>/`，
对应计划和 manifest 放在同一 variant 下的 `observations/<YYYY-MM>/<observation_id>/`。
单主机文件锁保证一个 writer，Parquet 使用 zstd／原子发布，manifest 最后发布。
已完成观察不可覆盖，A→B→A 修订保留三次观察；崩溃遗留文件不作为成功覆盖。
配额触及 10% 安全余量时暂停并以非零码退出，保留计划和成功片。同范围续跑先补缺片，
沿用 `rounds/` 下原子保存的本轮计划，并按观察序号区分历史覆盖与本轮完成片；恢复
拆分任务时直接接续子片，成功片不重复下载。若在最后一片发布后暂停，下次运行仅
确认本轮完成；再下一次运行才开启新一轮回扫。默认有限重试只针对
暂态故障，认证／权限／契约错误不伪装成功。日值缺交易日、空响应、缺失收盘价
（含 nullable 数值类型）或异常价格均阻塞；
成分空列表只有带可信返回形态及 `create_tm` 才作为完整空快照。`create_tm` 保留原义，
PIT 状态为未核实；权重只记查询日，不猜生效日、不自动归一到 1。

`ingest.ricequant.supplement_adapter.iter_observations` 提供离线逐片读取和月份筛选，
先校验 manifest、文件哈希、schema 和当前证据，再复核返回契约；它不会初始化 SDK
或写库，不能替代尚待开发的 importer。

离线回归命令（不读取真实账号、不访问业务库）：

```bash
uv run pytest packages/gr-data/tests/ricequant -v
```

### 供应商 SDK

Tushare 与 rqdatac 已列入包依赖。银河和华泰的 SDK 按厂商方式安装：

| provider | 包名 | 凭证环境变量 |
|---|---|---|
| tushare | `tushare`（已随包安装） | `TUSHARE_TOKEN` |
| yinhe（银河） | `AmazingData`（厂商提供 wheel） | `YINHE_USER` / `YINHE_PASSWORD` / `YINHE_HOST` |
| ricequant（米筐） | `rqdatac`（已随包安装） | `RICEQUANT_API_KEY` |
| insight（华泰） | `insight_python` | `INSIGHT_USER` / `INSIGHT_PASSWORD` |

装好 SDK 且配好凭证后，用真实接口验证：

```bash
uv run gr-data raw tushare --only calendar     # 落 parquet
uv run gr-data ingest tushare --only calendar  # 写 meta.trading_calendar
uv run pytest packages/gr-data/tests/live -v   # 真实接口契约用例（无凭证时自动 skip）
```

缺凭证或缺 SDK 时命令会**立刻**失败并给出该设哪个变量，不重试、不静默降级。

---

## 表归属：单表单一来源

数据库里同一张目标表只能由一个 provider 写入，登记在 `ops.table_ownership`。
`ingest`／`stream` 写库前会校验，归属不符直接拒绝。

```bash
uv run gr-data own list                                  # 查看当前归属
uv run gr-data own set market.stock_bar_1d tushare ingest  # 转移归属
uv run gr-data own release market.stock_bar_1d           # 解除
```

**切主源是高风险操作**：不同源的单位口径、复权规则、停牌处理都可能不同，
混写会让同一张表里出现两套口径且事后无法分辨。转移前先逐表核对数据一致性。
示例配置已列出 Tushare 的六个 ingest 组别。启用列表只决定执行哪些 importer，
实际 owner 以 `gr-data own list` 为准；归属冲突时失败，不会自动切主源。
`meta.symbol_map` 是唯一例外：按包含 `source` 的主键隔离多源记录，见 D-012。

---

## 排障

| 现象 | 原因 |
|---|---|
| `缺少 Tushare token` | 没设 `TUSHARE_TOKEN`，或 `config.yaml` 的 `token_env` 指向了别的变量名 |
| `未安装 AmazingData SDK` | 银河 SDK 不在 PyPI，需厂商 wheel 手动安装 |
| `schema "meta" does not exist` | 没建库，先跑 `uv run gr-db migrate --target pg` |
| ingest 报归属冲突 | 目标表归属别的 provider，见上一节 |
| `Corrupt raw parquet` | 该分区文件损坏。先把坏文件手工移出该数据集目录（保留作证据），再 `raw … --mode update` 补抓缺失月份；抓取端在非整月或有空响应时也会读旧分区，坏文件留在原处会让重抓失败 |
| `missing raw partitions` | 所选月份缺分区；补抓该数据集，或调整 `--months` |
| `not in meta.symbol_map` | 先跑 `ingest tushare --only reference`；历史换码需先补映射 |
| `differs from the database; run the suspend_d importer` | raw 停复牌已更新但库内未重导，先跑 `--only suspend_d` |
| 退出码 3 | 有软告警，查看 stderr 的「需复核」行和 `ops.etl_job_run` 中的 `partial` 记录 |
| 读不到根 `.env` | 确认在 workspace 内运行；可用 `GETRICH_ROOT` 显式指定根目录 |

数据接入的口径约定（时区语义、symbol 归一化、parquet 布局、日志、命名）见
`AGENTS.md` §3.4；各供应商的接口设计文档在 `getrich-design/data-platform/`。


## 配置与日志

配置按使用者组装：数据连接与供应商模型在 `gr_data.config`，API／worker 模型在 `gr_api.config`；公共环境加载、路径与日志模型在 `gr_tools.config`。模型导入不加载 `.env`，不会创建用户目录配置文件。
日志输出工具在 `gr_tools.logging`；模块直接用标准库 logger，由启动入口调用 `gr_tools.config.setup_logging(logging_config)`。

| 来源 | 内容 | 示例 |
|---|---|---|
| 环境变量／本地 `.env` | 环境差异、连接、凭证、机器路径、输出选项 | PG_*、TUSHARE_TOKEN、RAW_PARQUET_ROOT、LOG_LEVEL／LOG_FMT／LOG_FILE／LOG_JSON |
| Python config | 类型、校验、默认值与应用组装 | LoggingConfig、PostgresConfig、ApiSettings／WorkerSettings |
| `config.yaml` | 结构化采集参数 | provider、dataset 启用列表、抓取范围、重试与限频 |

`load_environment()` 显式读取一个环境快照，默认不修改 `os.environ`。真实环境变量优先于文件；显式传 `env_file` 时只使用该文件，否则依次选择 workspace `.env`、`~/.config/getrich/.env`。自动候选都不存在时仅使用进程环境；显式文件不存在则报错，不自动创建文件。首次运行仍执行 `cp .env.example .env`。

布尔配置 `STRICT_MODE`、`RICEQUANT_ENABLED`、`ENABLE_HDB`、`ENABLE_INSIGHT`、`GETRICH_ALLOW_MOCK_AUTH` 和 `LOG_JSON` 统一接受 `true/1/yes/on` 与 `false/0/no/off`，不区分大小写；未设置或空串为 False，其他值抛出 `SettingsError`，错误消息不包含原值。`APP_ENV=prod` 启用严格模式的判断同样不区分大小写。

YAML 不复制数据库与日志配置；`load_config(environment=env)` 的占位符、`*_env` 凭证字段、raw 路径与连接配置共用同一快照。数据／信号 CLI 在启动时显式安装环境，兼容直接读进程环境的 SDK；模型和库导入不做此操作。

只加载当前命令需要的模型：raw 抓取不强制 PG，`gr-db status` 不校验连接，PG 命令不校验 CH／Web。默认使用 PostgreSQL 和 inproc 作业路径，
Redis 仅在 Celery 模式需要，ClickHouse 仅在使用因子输出相关能力时需要。

CLI／API／worker 启动入口统一配置日志，库模块导入不创建 handler 或日志文件。
LOG_FILE 使用完整文件名，先展开 `~`，相对路径以 workspace 根解析；LOG_JSON=true 输出单行 JSON，
否则使用 LOG_FMT。结构化字段使用 `extra` 或 `extra={"context": {...}}`，不得记录凭证或完整请求／供应商 payload。
CLI 的 `--verbose` 优先于 LOG_LEVEL，Celery 显式 `--loglevel`／`--logfile` 优先于环境选项。
重配只关闭本项目管理的 handler，保留测试／宿主框架的 handler；框架自身的访问日志配置仍由框架管理。

### Python 调用迁移

旧 `gr_data.config.Settings`、全量 `load_settings()`／`settings` 单例和 `gr_data.config.setup_logging` 已移除。数据模型与 `find_project_root` 仍可从 gr-data 配置入口导入；WebConfig、WorkerConfig、BacktestStorageConfig 改从 `gr_api.config` 导入。数据库连接池改为 `await pg_pool.init(postgres_config)`，ClickHouse 构造器可传 `config=clickhouse_config`。

直接调用公共布尔解析函数时，必须传配置键名：`parse_bool(value, name="FEATURE_FLAG")`。未知值会报错，不再静默解释为 False。

```python
from gr_data.config import load_postgres
from gr_data.config.pipeline import load_config
from gr_tools.config import LoggingConfig, load_environment, setup_logging

env = load_environment()  # 或显式指定 env_file
setup_logging(LoggingConfig.from_env(env.root, env.values))
pipeline = load_config(environment=env)
postgres = load_postgres(env)  # 只在需要 PG 的通路中调用
```

API 由 `load_api_settings(env)` 组装，`create_app(config)` 将配置绑定到应用实例；请求依赖与后台任务使用该配置。原 `uvicorn gr_api.main:app` 命令保持可用，默认应用在访问 ASGI 入口时创建，单独导入工厂不加载配置。Celery 工厂接收 `WorkerSettings`，CLI 入口加载一次并绑定到 Celery 应用；exec 后在新进程配置日志。

配置对象的 repr 隐藏凭证字段，旧全量 `to_dict()` 已删除；不要自行对环境快照或配置做全量序列化输出。


### 风险导入收据与用途（2a，需迁移 049）

动态风险导入需要 `ops.dataset_variant`、`ops.import_receipt`、
`factor.model_run_binding` 及扩展后的 `ops.import_checkpoint`。
`validation` 和 `production` 是不可变用途，production 只支持
`universe_policy: listed_cn_a_v2`；改变用途生成新 variant，不能给旧样本改标签。
五件套与覆盖表共用逻辑目标 `factor.risk_bundle`，不按物理表拆成六份独立收据。

生产 raw 命令在初始化 SDK 前检查迁移并登记用途；已发布 raw 才记 capture 检查点。
PG 失败时保留原观察与恢复计划，重试复用 raw。完整轮次的 init 回放可能重新查询
交易日历，但不会重新请求风险五接口或参考名单。动态 ingest 也可从校验过的 raw
重建 capture，再在同日事务中提交五件套、覆盖、receipt、binding、DB 检查点和 ETL。
重放已有收据时核对绑定和检查点，不重复 UPSERT 业务行；重放 ETL 标记 replay。

检查点按 `variant/day/observation` 隔离：只有 capture 时 DB 水位为空，成功提交后
一次推进到收据；不使用 MAX 日期代表区间完整，不承担 B2 当前版本选择。
`committed_at` 是事务内记录收据的时间，提交后才可见，不是服务器精确 commit 时刻。

production 的试行发布资格按整数检查 `complete * 1000 >= candidate * 999`
（candidate 必须为正），身份／上市边界未知为 0。覆盖不足但数值合法的整包可以
保留收据和降级覆盖，随后停止本批并报告不可发布；不会把已提交的成功 ETL 伪记为
failed。数值非法、身份冲突等原硬门禁仍回滚业务数据。研究 validation 的覆盖降级
保留原行为。production 仅表示用途，不能代表已发布；2b 清单和统一读取入口完成并
发布之前，正式风险读取继续关闭。

`importer_version` 取最近影响 gr-data 源码或 gr-db DDL 的完整 Git 提交号；
文档提交不改变版本。生产入口拒绝相关路径未提交的修改（含未跟踪源码），
Git 不可用或同一进程内源码提交变化也拒绝，后者须重启进程。
同一 raw 换 importer 版本不允许覆盖已有绑定 run，
需另行设计重处理身份后再升级。重放响应丢失依赖成功收据确认，不能仅以客户端
异常判断事务已回滚。

风险提交后停止有独立 CLI 状态：退出码 4 表示合法数据已保存，但发布资格不满足；
退出码 5 表示提交响应异常（消息区分收据已确认提交和提交结果未知）。这两种状态
停止后续日期及 importer，不追加普通 failed ETL 来暗示业务回滚。结果未知时按同一
raw 重放并查询收据；确认存在后不重复业务写入。普通确定性导入失败沿用原失败语义。

### 风险观察的显式选择与修复追溯

`gr-data ingest ricequant --only rq_risk_model --months 2024-12 --observation-id <32位小写十六进制ID>`
仅选择配置 variant、起止日期和月份范围内的一个已完整发布观察。不存在、跨范围、跨 variant
或 ID 在多个日期重复均报错；不自动选择最新观察。不传参数时仍按原规则遍历范围内的观察。
ETL request 保留 `selected_observation_id` 与实际 observation／run／收据关联。

选择器不改变 raw 身份或不可变绑定。同一 observation、同一 importer 的成功收据重放不写业务行；
同一 observation 换 importer 仍拒绝。修复已绑定数据须保留旧证据，另行批准新采集观察，
由新 importer 生成独立 run 和收据；不能重新绑定旧 observation。
