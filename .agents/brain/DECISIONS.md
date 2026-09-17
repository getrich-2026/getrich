# GetRich 有效决策与防错理由

读者：实现相关模块的 Agent、理解设计取舍的维护者。先按主题索引定位，不要求全文读取。
用途：保留不能仅从代码看出的理由、刻意偏离设计的选择与高风险陷阱；执行规则以根 AGENTS.md 为准。
整理日期：2026-09-08。编号稳定，删除项不重排；历史实测仅表示当时证据，不能据此断言当前数据库状态。

## 主题索引

- 项目结构与文档：[D-003](#d-003)、[D-004](#d-004)、[D-006](#d-006)、[D-008](#d-008)、[D-010](#d-010)、[D-018](#d-018)、[D-022](#d-022)、[D-025](#d-025)、[D-060](#d-060)、[D-061](#d-061)、[D-062](#d-062)。
- 部署、配置与数据库：[D-013](#d-013)、[D-014](#d-014)、[D-015](#d-015)、[D-016](#d-016)、[D-019](#d-019)、[D-020](#d-020)、[D-021](#d-021)、[D-023](#d-023)、[D-028](#d-028)、[D-029](#d-029)、[D-051](#d-051)、[D-054](#d-054)、[D-058](#d-058)。
- 选股与回测：[D-024](#d-024)、[D-026](#d-026)、[D-027](#d-027)。
- 前端：[D-031](#d-031)、[D-032](#d-032)、[D-033](#d-033)、[D-034](#d-034)。
- 数据接入与因子口径：[D-035](#d-035)、[D-036](#d-036)、[D-037](#d-037)、[D-038](#d-038)、[D-039](#d-039)、[D-040](#d-040)、[D-041](#d-041)、[D-042](#d-042)、[D-043](#d-043)、[D-044](#d-044)、[D-055](#d-055)、[D-056](#d-056)、[D-057](#d-057)。
- 持仓诊断与安全验证：[D-045](#d-045)、[D-046](#d-046)、[D-047](#d-047)、[D-049](#d-049)、[D-050](#d-050)、[D-059](#d-059)。

## 项目结构与文档

<a id="d-003"></a>

### D-003 项目根目录按 uv workspace 识别

单包 pyproject.toml 不能作为根标志，否则会漏读根 `.env`、把产物写到成员包。`find_project_root()` 查找 `[tool.uv.workspace]`；不硬编码父目录层数。修改配置加载须覆盖从子目录启动。

<a id="d-004"></a>

### D-004 日志与指标归属遵守包依赖方向

旧 gr-data 从回测命名空间导入日志，单包安装会失败。通用日志现在归 gr-tools（D-062），实盘指标归 gr-signal；不要为共享常量或日志反向 import。边界由静态测试守卫。

<a id="d-006"></a>

### D-006 替换既有行为测试后再移除旧测试

旧单体迁来的测试仍是行为基线；重构时先证明替代用例覆盖相同行为，不能因文件名称过时先删测试。

<a id="d-008"></a>

### D-008 路径过滤的 CI 不能直接设为必需检查

工作流未触发时必需检查可能一直 Pending。若要全仓强制门禁，先设计始终运行的汇总检查；当前是否设为 required 属于仓库设置，不能从 YAML 推断。

<a id="d-010"></a>

### D-010 归档代码删除必须单独授权

`archive/` 与 `packages/gr-db/archive/` 含历史脚手架／SQL。文档整理不构成删除归档代码的授权。

<a id="d-018"></a>

### D-018 包名与 import 一一对应，不共用 getrich 命名空间

多个发行包装进同一个 `getrich/` 曾导致覆盖与单包安装失败。发行名／目录用 gr-x，import 用 gr_x；包依赖单向，禁止回到命名空间混装。日志反向依赖的具体教训见 D-004。

<a id="d-022"></a>

### D-022 外部代码合并必须检查历史凭证

getrich-database 已合入 gr-data，旧仓只作历史来源。曾有供应商配置中的 license key 随 subtree 历史进入本仓；gitignore 只能挡未来提交，不能清除历史。合并外仓前检查凭证，发现泄漏需按实际状态处理，不把旧“已轮换”说明当当前安全证明。

<a id="d-025"></a>

### D-025 gr-tools 是无一方依赖的叶子包

文件、表格与格式化能力可供其他包使用；gr-tools 不依赖 gr-data，包括日志。内部用标准 logging，不能依赖用户目录的隐式全局配置；表格读取的 all_string 选项用于保留证券代码前导零。

<a id="d-060"></a>

### D-060 Codex 为主，兼容入口引用同一份规则

根 AGENTS.md 是唯一项目规则真源。Antigravity 通过 .agents/rules/project.md 引用，Claude Code 经 CLAUDE.md 导入，权限配置各归各工具。共享状态在 .agents/brain；旧 .agent 路径仅保留于不可为此改 checksum 的 SQL 历史字符串。

<a id="d-061"></a>

### D-061 文档按读者与生命周期组织，允许授权清理

**时间**：2026-09-08，用户明确授权本次分类与删除过期决定。

Agent 启动只读规则与短状态，按主题查决策；人从 README／docs 目录按操作目的进入。
指南放 docs/guides，未决问题放 docs/plans，已完成且值得追溯的材料放 docs/history；
包内手册和供应商资料留在模块旁。每份新文档先标读者、用途与状态，不机械创建计划和总结。

本次删除 D-002、D-005、D-007、D-009、D-011、D-012、D-017、D-030、D-048、D-052、D-053：
分别为已废弃切包／部署中间态、禁止 docs 的过期规则、包占位旧状态、旧目录约定、
已吸收的部署与配置修复、被 D-059 取代的幂等规则、通用 shell 提醒、被 D-058 取代的 schema 范围。
有效结论已归并到相关条目；不重排或复用编号。历史仍可从 Git 中追溯，不再复制一份完整旧清单。

日常更新优先追加新决定并标明取代关系；经用户授权可删除无用记录，同时修复引用。
运行状态与未决问题分别在 NOTES 和 backlog 维护；只有解释“为什么”的内容进入决策记录。

## 部署、配置与数据库

<a id="d-013"></a>

### D-013 Redis 混放锁与缓存时使用 noeviction

缓存、分布式锁和限流计数器共用实例，LRU 会淘汰锁并破坏互斥。设置容量上限并使用 `noeviction`，缓存靠 TTL 回收，写满显式失败。要启用淘汰须先隔离到独立实例；逻辑 DB 不隔离实例级淘汰策略。

<a id="d-014"></a>

### D-014 PostgreSQL 的机器调优与平台规范分层

`deploy/config/postgres/postgresql.conf` 先 include 数据目录内配置，再覆盖平台时区、日志等设置；内存／并行度由 tune 或部署侧明确配置。迁移机器或变更资源后检查调优结果，不能假定重建容器会重新 tune。

<a id="d-015"></a>

### D-015 bind 日志目录要验证容器用户写权限

Linux 的宿主日志目录属主与容器用户不符时，PG 可能直接启动失败；macOS 上正常不代表 Linux 权限正确。按实际镜像用户核验 UID/GID，不把旧机器的 uid 70 当跨镜像常量。数据目录仍使用 named volume。

<a id="d-016"></a>

### D-016 deploy 只存模板，实例在仓库外

仓库只维护 `deploy/docker-compose.yml`、`deploy/config/` 与示例配置。将 deploy **内容**平铺同步到外部部署根，不能多套一层 deploy；不得覆盖真实 `.env`、数据或主机配置。仓库内只做 compose 静态校验，不创建、停止或重启实例。此条吸收旧 D-005／D-012／D-017 的有效结论。

<a id="d-019"></a>

### D-019 PostgreSQL 是行情真源，ClickHouse 仅存因子输出

早期 PG 与 CH 并行存行情造成两套 schema 和冲突口径。行情与事务业务统一 PG／TimescaleDB；CH 的 factors_long 用于因子批量写入和分析，DuckDB 只作临时计算。新增持久化前按 AGENTS 的数据库职责归类。

<a id="d-020"></a>

### D-020 schema 与引用列类型以现行 DDL 为准

历史 frontend schema 与 app/backtest 并存，strategies 主键和引用列类型不一致，曾导致新库接口失败。业务使用 app，回测使用 backtest；新引用要核对当前被引用列类型，不照搬旧设计稿的 VARCHAR／UUID 假设。

<a id="d-021"></a>

### D-021 迁移按文件名与 checksum 记账

仅按前缀记账不能识别内容变化；当前 gr-db 按 file_name + checksum 记在 ops.schema_migrations。内容变化会重新应用，因此 DDL 必须幂等、schema 全限定，编号连续。CH 每次执行一条语句，不能把多语句文件直接交给 command。文档搬迁不应改变已记账 SQL 的历史引用字符串。

<a id="d-023"></a>

### D-023 真实环境变量优先于根 .env

CLI 与服务共用 gr_data.config.settings，环境变量覆盖本地 dotenv；不能让 `.env` 覆盖 CI 或命令行注入。config.yaml 只存结构化采集参数，不能另维护一份数据库连接。默认值与示例一致，不能写特定机器地址。raw 根优先 RAW_PARQUET_ROOT，再取采集配置默认值。

<a id="d-028"></a>

### D-028 ClickHouse 记账使用 insert 接口

旧 command 拼 INSERT 却没有占位符，参数未落入语句，出现执行正常但迁移账本无记录。记账使用 client.insert；验证必须检查账本实际新增与幂等，不仅看 DDL 无异常。

<a id="d-029"></a>

### D-029 数据库数据目录使用 named volume

macOS 文件共享层的 bind 数据目录曾出现文件／POSIX 语义异常导致 PG 不可用。PG、CH、Redis 数据使用 named volume；日志与配置可 bind。备份走 pg_dump、clickhouse-client、BGSAVE 等逻辑导出，不拷运行中数据目录。

<a id="d-051"></a>

### D-051 字典从活库生成，契约与归属由自动检查守卫

gr-db docs 反射受管 catalog，并对照 gr-data 契约、注册表和 ops.table_ownership。多个 provider 声明可选能力不是生产混写；漂移判断以目标列与实际归属为准。注释门禁只管相对基线新增／修改的迁移，不用存量欠账阻塞无关改动。

<a id="d-054"></a>

### D-054 DDL 注释门禁覆盖 ALTER 新增列

只检查 CREATE TABLE 会漏掉后续 ADD COLUMN。门禁检查一条 ALTER 内的多个新增列，并从迁移目录收集 COMMENT ON；豁免列按实现维护。CH-only 字典不做 PG 契约／归属校验，缺少比较基准不能当漂移。

<a id="d-058"></a>

### D-058 diag 已纳入 gr-db 受管 schema

040_diag.sql 已合入本仓，所以 diag 属于 gr-db 字典和注释范围；旧“diag 在仓外”决定已失效。只管理 DDL 明确声明的业务 schema，始终排除 TimescaleDB 内部 catalog。041／042 补齐注释；具体表数随 DDL 变化，不写成永久约束。

## 选股与回测

<a id="d-024"></a>

### D-024 选股信号（`pick` schema）落地：三处偏离设计文档的取舍

**时间**：2026-08-17

选股展示模块（`getrich-design/strategy-signal/`）的 P0 存储层落地为 `pick.batch` +
`pick.item` 两张表（迁移 `034_pick.sql`）。设计文档写于 introspect 实际库之前，
落地时有三处必须偏离，理由记在这里，免得后来者当成实现错误去「修正」：

1. **`strategy_id` 用 UUID 而不是 `VARCHAR(32)`。** 文档 §3 把这条列为阻塞项，
   要求落地前 introspect 确认 —— 实际 `app.strategies.id` 是 UUID（见
   `021_strategies.sql`），对外展示与路由用 `strategy_code`。这与 D-020 踩过的坑
   同源：引用别人主键时类型必须与被引用列一致，否则全新库上恒 500。
2. **`import_job_id` 保留列但不建外键，`chk_batch_job` 不建。** 文档假设复用
   `/v1/admin/imports` 的 `import_jobs` 表 —— 但**本仓根本没有那张表的 DDL**
   （`services/admin_import.py` 引用它，`gr-db/ddl/` 里一行都没有，全新库上那套接口
   必然报错）。P0 走函数 / CLI 导入，没有 job 可挂，硬建外键会让迁移直接失败。
3. **`uploaded_by` 可空。** 文档写 `NOT NULL VARCHAR(32)`，但 CLI 导入没有登录用户。
   改成可空 UUID 并外键到 `app.users(id)`。

**策略类型判别选了「加列」而不是「用分类」**（文档 §3.3 的方案 B）：
`app.strategies.strategy_kind`（`pick`/`timing`/`combo`，可空）。方案 A（用一个专门的
`strategy_categories` 分类）零改动，但会把「策略类型」和「业务分类」焊死，将来选股
再分子类（预增 / 双击）就打架。可空 + 选股接口只认 `strategy_kind='pick'`，
所以没回填的存量策略不会误入选股列表。

**两套交易所码是这块最容易静默出错的地方**：`pick.item.exchange` 存 `SSE/SZSE/BSE`
（前端接口契约 `PickItem.exchange` 枚举定死），数据层 `meta.*` 用 canonical 码
`XSHG/XSHE/XBSE`，且 `meta.instruments.symbol` 存的是**带后缀全码**（`600000.SH`）。
拿 `SSE` + 不带后缀的 `600000` 去查 `meta.instruments`，SQL 不报错、只是查不到，
表现为 `instrument_id` 整批 NULL、`holding_trading_days` 全部走自然日兜底。
转换集中在 `gr_api/services/pick_symbols.py`，别在别处再写一份。

**入池日推算的保守方向不可反转**：上一交易日没有 active 批次（漏传）或交易日历尚未
ingest 时，`entry_date` **沿用不重置**。反过来（重置成今天）会静默破坏历史且不可恢复；
沿用导致的偏差是「入池时间偏早」，可见、可解释、事后可修正。
`product_entry_date` 的兜底值取 `entry_date` 而非 `trading_day` —— 取后者会在
「首次入池 + 上传方给了更早的 entry_date」这个**每个基金经理首次接入的必经场景**下
违反 `chk_item_prod_entry`，整批插入失败（文档附录 A.6 第 1 条）。

<a id="d-026"></a>

### D-026 选股查询范围随本次业务收窄

连续导入优先读上一交易日 active 批次，避免每次扫描全历史；漏传或日历缺失才走历史回退。
个股反查的 latest CTE 只聚合命中策略的 batch，不能对全平台策略历史求最大日期。
保持 SQL 形状稳定以便复用查询计划；优化必须保留漏传／空仓／重新入池的日期语义，见 D-024。

<a id="d-027"></a>

### D-027 Black-Litterman：去掉不自洽的归一化，并记下两个待定的建模口径

**时间**：2026-08-17

`BlackLitterman._compute_posterior` 原来对先验和观点**分别**做归一化：

```python
pi_prior = pi_prior / pi_norm          # → L1 = 1，量级 O(1)
q_vec = mu_scores / q_norm * pi_norm   # → L1 = pi_norm，量级 O(1e-5)
```

两次归一化互不自洽 —— Π 被拉到 O(1)，Q 却被压回原始 `pi_norm`（日收益量级）。
后验里 `ts_inv @ Π` 因此恒定压过 `omega_inv @ Q` 约五个数量级，**观点的符号被
完全抹掉**：`score=-1` 的标的照样拿到正的后验收益，长短仓完全反向。

现在两者都保持各自的自然量纲，不做任何归一化。修完后验从 `[0.167, 0.167]`
（观点消失）变成 `[+1.00, -0.99]`（观点符号保留）。

**同时修掉的第二个缺陷**：`np.linalg.inv` 只在矩阵**恰好**奇异时抛
`LinAlgError`。两只标的行情完全同步时协方差的行列式是 1e-26 这种量级，不触发
异常，却让求逆结果变成纯数值噪声。伪逆也救不了 —— `pinv` 的输出恒落在协方差的
行空间里（秩 1 时是 `span{[1,1]}`），和观点完全无关，归一化后得到 `[0.5, 0.5]`，
两个方向相反的标的同号。所以判据改成**条件数**（`_MAX_COND = 1e12`，依据是
float64 的相对精度 2.2e-16），退化时直接退回「按方向等权」，不拿噪声冒充最优解。

**遗留两个待决口径，等定了方案再动**：

1. **`tau` 目前是无效参数**。后验里 `(τΣ)⁻¹` 和 `Ω⁻¹ = 1/(diag(Σ)·τ)` 同时以
   `1/τ` 缩放，τ 在 `(Σ⁻¹/τ + D/τ)⁻¹ (Σ⁻¹Π/τ + DQ/τ)` 里精确约掉，改两个数量级
   得到的后验逐位相同。要让 τ 重新起作用必须换 Ω 的取法（Idzorek 置信度是常见
   做法）。用例 `test_tau_currently_cancels_out` 钉住现状，改了 Ω 它会先失败。
2. **score 被直接当预期收益用**（Q = score）。量纲上 `score=1` 等于「预期日收益
   100%」，和 Π 的 O(1e-5) 差五个数量级，等于把观点的置信度隐式拉满。要不要在
   Q 前面加一个标定系数（比如按截面波动率缩放），属于策略口径，需要先定。

**测试层面的教训**：BL 原有 6 条用例**全部**用同一条价格序列喂两个标的，协方差
秩为 1，走的都是退化分支 —— 真正的后验路径一条都没覆盖，符号错了三个月没人发现。
新增 `test_view_sign_survives_posterior`（cond(Σ)≈1.7 的非退化数据）补上这条路径。
**造测试数据时，「两个标的」必须真的不一样**，否则测的是 fallback 不是算法。

## 前端

<a id="d-031"></a>

### D-031 Vite 主版本迁移同时检查构建与开发路径

apps/web 使用 Vite 8 的 Rolldown 构建，不再依赖 Rollup 插件假设。迁移时验证 dev／HMR／proxy 与生产构建；lint 通过不代表配置加载或运行时成功。旧构建错误的逐项修复日志不再作为当前状态保存。

<a id="d-032"></a>

### D-032 前端类型必须反映实际响应

旧 API 的 any 隐藏了页面读取不存在字段、把单笔成交当开平回合等错位。类型按后端实现／响应模型写，未知契约明确记录，不猜字段。编译期类型不能校验真实 JSON，枚举与空态还需接口样本或运行时契约验证。未决项见 docs/plans/backlog.md。

<a id="d-033"></a>

### D-033 Tailwind 4 主题与构建保持 CSS-first

主题在 src/index.css 的 @theme，构建用 @tailwindcss/vite。不要恢复 tailwind.config.js、postcss.config.js 或 autoprefixer。shadcn UI 由 CLI 管理；升级时既检查生成 CSS 也检查实际页面，不能只凭工具类存在断言视觉正确。

<a id="d-034"></a>

### D-034 前端只维护一套接口层

旧 lib/api.ts 漏认证头，旧 api 层签名又把已剥壳响应当 Axios 外壳；重复实现使错误长期隐藏。统一 src/api/client.ts 处理认证／401／code／信封，domain 函数返回 Promise<T>，组件通过 react-query 使用。视图形状转换留在组件，业务 code 错误必须抛出。

## 数据接入与因子口径

<a id="d-035"></a>

### D-035 `factor` schema 相对设计文档的四处刻意偏离

`getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md` §5.2 是 `factor`
schema 的原始设计草案；本仓现行 DDL 真源仍在 gr-db。`037_factor.sql` 有四处不照抄，**都是刻意的**，
看到差异不要当成实现错误去「订正」：

| 偏离 | 理由 |
|---|---|
| `covariance.cov_flat` 用 `DOUBLE PRECISION[]` 而非 `REAL[]` | 实测样本里最大值 723.695971 = 9 位有效数字，`REAL` 只有约 7 位，末两位会被**静默**截掉。矩阵求逆与半正定判定对精度敏感，而截断后的矩阵依然对称、依然正定，不会有任何报错 |
| `model_run` 加 `units JSONB NOT NULL DEFAULT '{}'` | `annualization_basis` 是单值 CHECK ∈ (daily, annual_252)，装不下「$F$/$D$ 年化 + $f$/$u$ 日频」这种**同一模型内部混着量纲**的事实。`annualization_basis` 保留填 `'annual_252'`，语义收窄为「风险类口径」 |
| `model_run` 加 `calibrated BOOLEAN NOT NULL DEFAULT false` | 量纲定标的依据是**单日**样例且属 SW14 期。全区间复核（P6）通过前，下游必须能读到「这批数是没复核过的」，否则会把 degraded 当成正常结果展示 |
| `model_run` 加 `factor_set_hash VARCHAR(32)` | 每日复核当日活跃因子集合，不符即中断。见 D-036 |

**下游必须知道的一条**：若 portfolio-analysis 按
`annualization_basis='annual_252'` 去读 `factor_return.ret_vector`，会混淆风险年化口径与收益频率
——`f` 是**日频小数**。口径以 `model_run.units` 为准，不以 `annualization_basis` 为准。

另有一条 ownership 粒度的边界：`factor.*` 目前**按表级**登记归属
（`OwnershipManager` 只支持表级）。一旦要用自研估计与采购数据并存地写
`factor.*`，必须先把 ownership 下沉到表 + run_id，否则两套估计会混在一张表里
且事后分辨不出哪行是谁写的。

<a id="d-036"></a>

### D-036 datayes 三张宽表的因子列顺序互不相同（静默算错的头号风险）

实测样本 `dy1d_*_20260829.csv` 逐列核对，**不是推测**：

```
exposure  : … COMPUTERS, CONGLOMERATES, CONSTRDECOR, DEFENSE, ELECTRICALEQUIP, ELECTRONICS …
covariance: … COMPUTERS, ELECTRONICS,   CONSTRDECOR, DEFENSE, ELECTRICALEQUIP, NONBANKFINAN …
```

三表都是 58 个因子列（20 风格 + 37 行业 + COUNTRY），**集合相同、顺序不同**，
且 CSV 列名全大写而协方差的 `factorName` 行标签是原大小写。

**按源列序 `df[cols].to_numpy()` 展平 = 每个因子都对应错**，而结果依然是合法的
52 维向量 / 对称正定矩阵，没有任何报错。这是本次接入唯一的「形状正确但数值全错」
高危点。四层防护：

1. `factors.reindex_wide(df, order)` 是**唯一允许把宽表变成数组的函数**，
   源列名经大小写归一后匹配，缺列 / 重复列一律抛错，**不 fillna 不容忍**。
   全仓禁止再出现按源列序取值的写法。
2. `factor_set_hash` 每日复核：当日活跃因子集合的哈希与 `model_run` 不符即中断，
   人工确认后开新 `model_version`。与 `factor_order_hash`（校验我们自己的常量
   没被改）分两列存。
3. 协方差硬校验：行标签集合 == 列名集合、对称性、对角元 > 0，任一不满足即中断；
   半正定只做软校验（告警）。
4. 行业哑变量每行恰有一个 1、`COUNTRY ≡ 1` —— 这两条同时是「列没错位」的最强
   证据，因此**不做「取最大值」兜底**：兜底正好会把错位掩盖过去。

配套的一条：活跃因子集合**从数据派生**而不是写死 52。SW14 期是 49 个、SW21 期
是 52 个，写死一个数字就等于在体系切换时静默算错。写死的只有 58 个的超集与它
的规范顺序（那份是文档明确给出的）。

**踩过的坑**：手上的样本 CSV 是 2020-12-31，属 SW14 期，9 个 SW21 新行业整列为
NaN，只有 49 个因子有值。**它不能直接当 52 因子路径的测试 fixture。**

<a id="d-037"></a>

### D-037 `meta.symbol_map` 是「单表单一来源」铁律的唯一例外

AGENTS.md §3.4 规定同一张目标表只能由一个 provider 写入。接入 datayes 时
`DatayesSymbolMapImporter` 撞上 `OwnershipError：表 meta.symbol_map 已归属
provider='tushare'`。

这不是实现 bug，是规则与这张表的用途本身冲突：**该表的主键就是
`(source, source_symbol)`，它存在的意义就是跨源对齐**。铁律要防的是「两家供应商
往同一批行里写不同口径的值」，而这里两个 source 写的是互不相交的行。

处理：`common/ownership.py` 加 `MULTI_SOURCE_TABLES = frozenset({"meta.symbol_map"})`，
`check()` 提前返回、`claim()` 不登记。

**往这个集合里加表的门槛（必须同时满足）**：主键里含 `source` 列，因此不同
provider 写的行物理上不可能相交。不满足就不能加 —— 加错了不会报错，只会让两家
供应商的数据互相覆盖。

<a id="d-038"></a>

### D-038 gr-data CLI 的 statement_timeout 放宽到 30 分钟

`PgConfig.statement_timeout_ms` 默认 60 s，那是给交互式短查询的。而一次 ingest
是「一个事务里 COPY 上百万行再 UPSERT」：实测 `daily_basic` 单次 1,433,283 行在
60 s 处被 `psycopg.errors.QueryCanceled` 打断，**已写入的部分整批回滚，重跑还是
同样的结果**，且报错信息（"canceling statement due to statement timeout"）看不出
是量太大还是库有问题。

`cli.py::_pg()` 显式传 `_INGEST_STATEMENT_TIMEOUT_MS`（默认 1800000，可用
`GR_DATA_STATEMENT_TIMEOUT_MS` 覆盖）。**只影响 gr-data CLI 这条批处理通路**，
服务侧的连接池与 `PgConfig` 的默认值都不变 —— 给 API 请求 30 分钟的超时是灾难。

<a id="d-039"></a>

### D-039 从 datayes 暴露表派生行业分类：五条必须显式披露的限制

G1（行业分类）的**正解**是 tushare 的 `index_classify` + `index_member_all`：
三级树、申万官方码、真实生效日期。但这两个接口在
`getrich-design/dataapi/tushare-api/tushare_api_design.md` 的 §2–§8（61 个小节，
已逐节核对）里**没有字段目录**，凭猜实现会写出一批看起来对、实际对不上申万发布
口径的数据。

折中：从通联 CNE6 exposure 的 31 个行业哑变量读出逐日归属，按变化点压成
`[in_date, out_date)` 区间。代价是五条限制，**全部写进 DDL 列注释 +
`ops.data_quality_check`，不假装不存在**：

1. 只覆盖 CNE6 收录的 A 股个股，不含 ETF / 指数 / 期货；
2. 只有一级，`scheme.available_level = 1`（**体系级声明，不得当逐标的判据**）；
3. `industry_code` 是通联的英文标识（`Banks` / `NonbankFinan`），不是申万官方码
   （`801780.SI` 那类）。`industry_node.external_code` **恒 NULL**，接到真源后
   回填 —— 猜一份映射会让下游误以为能直接对接申万发布的成分数据；
4. 没有真实 `in_date`，区间起点被导入窗口截短（记 `rule='classify_window_truncated'`）。
   方向是**保守**的：不会让历史看到未来的行业，只会看不到更早的历史；
5. 停牌日没有 exposure 行会打断区间，只对行业相同、间隔 ≤ 40 自然日的相邻段合并。
   停牌一年的票中间有没有被重分类，我们并不知道，接上就是替供应商编数据。

两个容易写错的实现细节：

- **`out_date` 取下一段的起点，不是本段最后一个交易日。** 后者会在两段之间漏掉
  一天，那一天查不到任何行业，而查询本身不报错，只是少了一只票。
- **资产类别（G5）只映射能确定的 stock / etf / fund。** future / option / index
  刻意不映射：CFFEX 同时挂股指期货（equity）与国债期货（fixed_income），交易所
  定不了类别。少一行只让下游标 degraded，写错一行让资产配置分解整块失真且不报错
  —— 两者代价不对称。

接到 tushare 真源后，`classify.instrument_industry` 走 `gr-data own release/set`
转移归属，**两个来源的分歧本身就是很强的质量信号**，值得保留交叉校验。

<a id="d-040"></a>

### D-040 `available_at` 只能有一个产地

新建 `ingest/pit.py`，三个函数按**可信度降序**：

| 函数 | 依据 | 可信度 |
|---|---|---|
| `from_vendor_timestamp(ts)` | 供应商的逐行时间戳（datayes `updateTime`） | 高：逐行精确，天然覆盖回算与重述 |
| `from_announce_date(ann, fallback)` | 公告日（财报的 `f_ann_date` / `ann_date`） | 中：日粒度 |
| `from_trading_day(day, publish_hour)` | 交易日 + 文档声明的发布小时 | 低：**文档值不是实测值** |

**绝对禁止用 `end_date` 兜底**：20241231 的年报次年 3–4 月才披露，按 `end_date`
对齐等于提前看到三四个月后的信息，且回测会「表现优异」——这类前视不会报错，
只会让结果好看。

时区一律 `Asia/Shanghai` 显式 localize。相关的测试写法坑：断言时区**不能断言
`utcoffset()`**，那只反映读取连接的会话时区，换个连接就变。要断言**瞬间**：
`SELECT available_at AT TIME ZONE 'UTC'`，17:00+08 必须等于 09:00 UTC。
漏了 `tz_localize` 时，CI 的 UTC 机器上会存成 17:00Z 而本地机器看着完全正常。

<a id="d-041"></a>

### D-041 `column_types` 声明的是**发送侧线格式**，不是目标列类型

`TableContract` 新增可选字段 `column_types`，`upsert_rows` 据它调
`cursor.copy().set_types(...)`，用来打通 JSONB 与数组列的 COPY 通路。

踩过的坑：`fundamental.valuation_1d.total_mv` 目标列是 `NUMERIC(24,4)`，
于是声明成 `("total_mv", "numeric")`，结果 psycopg 报
`TypeError: class NumericDumper cannot dump float` —— Python 侧给的是 `float`，
而 `numeric` 适配器不接受它。改声明 `float8` 后正常：float8 的文本表示能被
`NUMERIC` 原样解析。

规则：**填的是「我这边发的是什么 Python 类型」，不是「库里那列是什么类型」。**
另外 `set_types` 要么不填、要么填全，不能只填一部分。

顺带一条：`raw_payload` 这类 JSONB 列在 `to_dict("records")` 之前必须把 NaN 换成
None —— `json.dumps(float('nan'))` 产出 `NaN` 字面量，PG 的 jsonb 解析器**会拒绝**，
整批 COPY 失败（而不是那一行失败）。

<a id="d-042"></a>

### D-042 datayes 的区间查询必须用 `tradeDate` 多值，不是 `beginDate`/`endDate`

配好 token 后第一次跑 live 契约用例，10 条挂了 9 条，全部是 retCode=-2：

```
At least one of [secID,ticker,tradeDate] parameters must be provided   (exposure / srisk / specific_ret)
At least one of [factorName,tradeDate] parameters must be provided     (covariance)
```

五张表里**只有 factor_ret 接受纯 `beginDate`+`endDate`**，另外四张必须在
`tradeDate` 那一组里至少给一个。接口文档看不出这一点：它的「是否必须」一栏填的
是「多选多」（文档作者也在注里标了这栏可疑），实测语义是「这一组至少给一个」。

实测确认的三条语义：

- `tradeDate` 支持**逗号分隔多值**（空格分隔返回 0 行，不报错 —— 又一个静默失败）；
- 给了 `tradeDate` 之后，`beginDate`/`endDate` **被忽略**；
- 单日 exposure 约 5551 行，因此一次最多塞约 17 天就会逼近 10 万行上限。

改法：`client._query_span()` 把区间展开成**工作日列表**发 `tradeDate`，
`query_range` 的切分与折半逻辑不动。周末不发（接口对非交易日只返回空，带上它
只让 URL 长 30%）；法定节假日仍然发 —— 查日历会让 raw 层依赖数据库，而
`meta.trading_calendar` 本身也是抓来的，那是循环依赖，代价只是几行空返回。

**这条是「live 契约用例挡住了设计错误」的实例**：Fake 永远测不出来，因为 Fake 是
照我们自己的理解写的。单测已把契约钉死在 `tests/raw/test_datayes_client.py`。

<a id="d-043"></a>

### D-043 通联的北交所后缀是 `XBEI`，不是 canonical 的 `XBSE`

`ingest/datayes/symbols.py` 原来假设「通联用的本来就是 canonical 码」，
把 `DATAYES_SUFFIX_TO_EXCHANGE` 写成恒等映射。**实测证明北交所不是。**

2026-08-28 单日 exposure 的后缀分布：`XSHE` 2897 / `XSHG` 2315 / **`XBEI` 339**，
一条 `XBSE` 都没有。XBEI 那 339 只全在 920xxx 代码段，与 `meta.instruments` 里
341 只 920xxx（exchange=XBSE）交叉核对一致 —— 是实测结论，不是按名字猜的。

不改的后果：339 只北交所标的的 `secID` 解析不出交易所 → `to_tushare_symbol()`
返回 None → symbol_map 建不起来 → 这批标的的因子数据整批入不了库。
未解析比例 339/5551 ≈ 6.1%，会撞上 0.5% 的容忍上限直接中断，所以**这次不会静默**；
但如果哪天北交所只剩十几只，就会掉到容忍线以下变成静默丢数。

`XBSE` 仍保留在映射表里兜底，万一供应商改用 canonical 码不至于整批解析不了。

**这条同样是探针用例抓出来的**（`test_sec_id_suffixes_are_all_known`）：
它枚举真实返回的后缀，出现未登记的就失败。当初写它时标的是「未决项 U21」，
现在证明这个未决项确实存在，而且答案与推测相反。

<a id="d-044"></a>

### D-044 datayes 五表的真实数据起点是 2021-08-02

探针方法（避免踩到自己挖的坑）：

1. **先别用 `meta.trading_calendar` 做二分。** 第一次这么做，五张表都「探到」
   最早是 2025-08-01 —— 那是**日历表在本库里的下界**，不是接口的下界
   （tushare calendar 当时只灌了 1520 行）。二分只能证明「在候选集合内最早」，
   候选集合本身错了就毫无意义。
2. **按年粗探时别取月初工作日。** 第二次用「每年 1/4/7/10 月的前 5 个工作日」，
   得出「最早 2022 年」。错的：2021 年那批候选日里，10 月 1–7 日整周是国庆、
   1 月 1 日元旦、4 月 5 日清明 —— 几乎全是节假日。改用**月中**（每月 12 日起的
   4 个工作日）后，2021 年立刻有数据。

最终结论：五张表**一致**在 2021-08-02（2021 年 8 月第一个交易日）起有数据，
2021-07 整月为空，2020 及更早全空。`config.yaml` 的
`providers.datayes.start_date` 因此定为 `20210802`，再往前抓只会拿到空返回。

顺带一条：手上那份 2020-12-31 的样本 CSV **不是本账号权限内的数据**，
它是供应商的演示样本。别拿它当「历史能取到 2020 年」的证据。

<a id="d-055"></a>

### D-055 通联 CNE6 的行业体系在 2021-11 切换，`cne6-sw21` 的窗口只能从 2021-12 起

抓完全量后，`ModelRunImporter` 的逐月因子集校验当场报出：

```
2021-11 的活跃因子集合与 2021-08 不一致：
  多出 [BasicChemicals, BeautyCare, Coal, EnvironProtect, Petroleum,
        PowerEquip, RetailTrade, SocialServices, TextileApparel]
  缺少 [Chemicals, Commerce, ElectricalEquip, Leisure, Mining, TextileGarment]
```

逐月统计（61 个月）：**2021-08/09/10 是申万 2014（49 因子），2021-11 起是申万
2021（52 因子）**，只切换一次。注意接口路径叫 `...CNE6SW21`，但它对切换前的日期
返回的仍是旧体系 —— **端点名不能当作口径保证**。

更细的一层：切换在五张表之间**不是同一天发生的**。逐日核对 2021-11：

| 表 | 2021-11-01 |
|---|---|
| exposure | 已是申万 2021（4527 行全部落在新行业列） |
| factor_ret / covariance | **仍是申万 2014**（协方差当月 1141 行 = 49 + 21×52） |
| srisk / specific_ret | 无因子列，不受影响 |

所以 2021-11 是个混合月。五张表必须在同一个 `model_run` 内**逐日一致**（同一天
要能同时取到 X、F、D、f），因此 `cne6-sw21` 的窗口起点定为 **2021-12-01**，
实际入库 57 个月（2021-12 → 2026-08）。

**为什么不给申万 2014 那段单独开一个 run**：`factor.definition` 的主键是
`(model_id, factor_code)`、并且有 `UNIQUE (model_id, ordinal)`，是**按 model_id**
而不是按 model_version 建的。两套体系里同名因子的 ordinal 不同，塞进同一个
`model_id` 会直接撞唯一约束。要支持双体系，得先决定是拆 `model_id`
（`barra_cne6_sw14` / `barra_cne6_sw21`）还是把 `definition` 下沉到 model_version
—— 那是 `持仓诊断_表与接口设计.md` §5.2 的设计范围，**不在数据接入层单方面改**。
代价是 2021-08~11 共 4 个月（约 5% 的可取区间）暂时进不了库。

顺带一条**方法论**：这个错误是「逐月比对」抓出来的。原实现是先把 61 个月
`concat` 成一个大 DataFrame 再算 `active_factors`，那样得到的是两套体系的**并集
58 个**，既不等于 49 也不等于 52，会被当成「超集全都活跃」而静默混用两套下标。
改成逐月比对不只是为了省内存，它本身就是更强的校验。

<a id="d-056"></a>

### D-056 大批量入库分批，但跨月语义必须保留

历史全量导入曾出现无输出、无新增行的异常终止，怀疑峰值内存不足；没有内核日志时不能
仅凭现象确认 OOM。运行验收应检查退出状态、作业记录与实际落库，不能把“没有异常”当成功。

`IngestContext.months` 与 `gr-data ingest --months` 支持按月选择输入；处理大表时使用有界批次。
DatayesSymbolMapImporter／ModelRunImporter 逐月读取后归约，避免先拼全历史再计算；
活跃因子集合必须逐月比较，直接取全历史并集会掩盖 SW14／SW21 切换。

InstrumentIndustryImporter 的区间压缩需要全历史，不能把每个月独立导入；
先逐月降到必要列，再做跨月区间处理。批处理超时单独配置，不放宽 API 超时（D-038）。

<a id="d-057"></a>

### D-057 通联大响应需控制分片与总耗时

历史 exposure 请求曾在响应体中途断连；将时间分片从 10 天缩到 4 天后，当时的断连减少。
这不是供应商永久限制：响应大小与延迟需要按当前接口重测。更小的分片会增加请求次数和总耗时。

读超时不等于整次请求的总时限，慢速持续返回仍可能拖长任务；应分别考虑重试、任务耗时与取消。
曾用一次性并发脚本缩短回补时间，但没有据此批准常规并发实现。若要引入，先确认供应商配额、
限流策略、独立分片可重试及数据完整性，不能把旧低请求率当当前限流许可。

## 持仓诊断与安全验证

<a id="d-045"></a>

### D-045 `diag` 的用户列用 UUID，不是设计文档写的 BIGINT

`持仓诊断_表与接口设计.md` §5.5 把 `portfolio_snapshot.user_id` 与
`share_token.created_by` 都写成 `BIGINT`，但本仓 `app.users.id` 是 **UUID**。
`040_diag.sql` 直接对齐真实主键类型，没有照抄文档。

理由是 D-020 已经踩过一次同型的坑：`strategies.id` 是 VARCHAR 而引用方按 UUID
建，结果整个策略／信号接口在全新库上恒 500。**引用列与被引用主键类型不一致，
建表时不报错，报错要等到第一次 join**，所以这类偏差必须在建表当下就纠正，
不能留给"以后再说"。

同类提醒：设计文档给的是产品口径，不是本仓的 schema 现状。落地前逐个外键核对
被引用列的真实类型，比通读文档更有效。

<a id="d-046"></a>

### D-046 泛型判别联合在 3.11 下保留 `TypeAliasType`，裸 `Annotated` 别名会 TypeError

`MetricValue[T]`（`OkMetric[T] | DegradedMetric[T] | UnavailableMetric`，按
`status` 判别）第一版写成：

```python
MetricValue = Annotated[OkMetric[T] | DegradedMetric[T] | UnavailableMetric,
                        Field(discriminator="status")]
```

导入即炸：`TypeError: typing.Annotated[...] is not a generic class`。
`Annotated[...]` 的赋值别名**不是** generic class，不能再下标。

PEP 695 的 `type MetricValue[T] = ...` 能解决，但那是 **3.12 语法**，本仓下限
3.11。可用的写法是 `typing_extensions.TypeAliasType`：

```python
MetricValue = TypeAliasType(
    "MetricValue",
    Annotated[OkMetric[T] | DegradedMetric[T] | UnavailableMetric,
              Field(discriminator="status")],
    type_params=(T,),
)
```

Pydantic v2 原生支持它做判别联合，`MetricValue[float]` 正常工作。

2026-09-17：用户决定停止支持 Python 3.10，最低版本统一为 3.11，CI 保留
3.11／3.12；诊断模型可直接使用标准库 `StrEnum`。提高 Ruff 目标版本时暂不
强制 UP017／UP041／UP042 的风格迁移，尤其不能将现有 `str, Enum` 机械替换
为 `StrEnum` 而改变字符串转换行为。PEP 695 语法仍需 3.12，因此保留上述写法。

<a id="d-047"></a>

### D-047 「不得静默估算」靠**字段缺失**落实，不靠字段可空

`UnavailableMetric` **没有** `value` 字段（而不是 `value: T | None`）。差别在于：
可空版本里 `{"status": "unavailable", "value": 0.0}` 是可构造的，前端也能把它
渲染成数字 0；字段缺失版本里这个组合在类型层面就不存在。

同一条原则的三个推论，实现时都踩到过：

1. 分布类指标没有数据时返回 `unavailable`，**不返回空字典** —— `{}` 会被前端
   渲染成「一个没有任何行业的组合」，看上去像已经算过了。
2. 覆盖不全时在**有数据的子集内**归一化并标 `degraded`，把缺失权重当 0 会让
   分布凑成看似完整的 100%。
3. 依赖未启用模块的盲点检测器必须显式返回 `triggered=false` + `reason_code`，
   而不是干脆不返回那一项 —— 省略等于告诉用户「查过了，没问题」。

<a id="d-049"></a>

### D-049 安全头测试不能拿「让它 500」来验

给新路由补安全头用例时，第一版故意打一个缺 DB 连接的端点，断言 4 个头 —— 失败。
原因：未捕获异常由 Starlette 最外层的 `ServerErrorMiddleware` 处理，**那一层在
用户中间件之外**，`SecurityHeadersMiddleware` 根本没机会执行。

正确做法是 `app.dependency_overrides[get_db]` 覆盖依赖，让端点走**正常 200
响应**这条路径再断言。既有的 `test_middleware.py` 用 `/boom` 能测出头，是因为
它抛的是 `HTTPException`，由内层的 `ExceptionMiddleware` 处理，仍在中间件栈内 ——
两者不是一回事，照抄会得出错误结论。

<a id="d-050"></a>

### D-050 PG 集成测试的连接失败 traceback 也可能泄漏凭证

测试代码若把包含密码的 PostgreSQL DSN 直接传给 `psycopg.connect()`，连接失败时
pytest 会展开 psycopg 栈帧与局部变量，DSN 可能随测试日志进入终端或 CI artifact。
这不是业务日志泄漏，常规的「不要记录密码」检查挡不住。

门控 PG 测试必须在连接 helper 内捕获 `OperationalError`，用不含 DSN 的固定消息
终止测试并关闭 traceback 展开；失败信息不得拼接原异常或连接字符串。测试成功路径
仍用真实连接，不能因此把连接失败静默 skip。

<a id="d-059"></a>

### D-059 诊断的幂等、纯计算缓存与展示状态分离

新提交创建新 snapshot；只有同一 UUIDv4 Idempotency-Key 重放同一资源，同键异体返回 409。
`request_hash` 保存幂等键的命名空间散列，原始请求体单独比较；不能恢复旧“相同请求体永久复用快照”的规则。

`calculation_hash` 仍按单 plan 的纯计算输入构造：解析后的标的与权重按稳定顺序规范化，
不含 plan_id、label、plan_index、intent 等展示字段。规范化 JSON 与量化权重保证稳定性；
请求字段、覆盖率画像和盲点不能写进跨用户共享缓存。更改计算载体时更新版本，避免复用旧形状。

A–E 通过有类型区块区分 ready／unavailable／failed；旧缓存的裸 null 不能直接作为网页响应。
报告与数值从同一组固定运行结果组装。失败方案保留输入与安全错误，新快照重试不改旧终态。
零权重校验必须先于可解析子集过滤；保留完整输入回显，避免零权重持仓影响有效数量。


<a id="d-062"></a>

### D-062 日志配置下沉公共工具，环境配置不重复存储

**时间**：2026-09-08，用户授权日志改造、配置边界整理与仅 PostgreSQL 的默认 CI。

公共 LoggingConfig 在 gr_tools.config，JSON／handler 配置在 gr_tools.logging，无领域依赖。
现有 gr_data.config.Settings 保留组装入口及兼容导出，数据库／供应商模型不在本次整体迁移；
不把所有配置搬入工具包，也不在仓库根新增不可独立安装的 config Python 模块。
模块只取得 stdlib logger，不隐式初始化。旧 gr_data.logging 保留兼容函数／Logger 类但不自动配置。

CLI、API lifespan、Celery 日志启动信号显式配置；LOG_FILE 的完整文件名和 LOG_FMT 必须生效。
重复配置只关闭本工具管理的 handler，不清掉 pytest／框架已有输出。
request_id 的 filter 必须挂在输出 handler：root logger 上的 filter 不处理子 logger 的传播记录。
Celery exec 会替换进程，在旧进程配置日志不会传到 worker；必须在新进程的启动信号处理。
回归测试应断言输出与资源关闭，不假设 root.handlers 只有本项目 handler，也不依赖测试导入顺序。

环境变量／.env 保存环境差异、凭证、连接和日志选项；Python 模型做校验与默认值；YAML 保留结构化采集参数。
默认 inproc 仅依赖 PG；CI 仅启动 PG，手动 extra_services 才启动 CH／Redis 并执行 CH 冒烟，离线检查不删。
