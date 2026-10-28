# 米筐风险模型验证与 production 首批验收（2026-10-22～23）

读者：追溯米筐风险数据来源、单位依据与 variant 身份的维护者。
状态：历史快照，2026-10-27 从 `.agents/brain/NOTES.md` 原样迁出，仅调整相对链接；不作为当前指令。
后续：三个 production 模型 2024-01-02～2026-10-21 已于 2026-10-26 全部回补完成，当前状态见 [NOTES](../../.agents/brain/NOTES.md)。

数据库 `factor.model_run.units` 里的 units_evidence 原文引用 `.agents/brain/NOTES.md#rq-three-model-history-20261022`，该章节现位于本文 [同名锚点](#rq-three-model-history-20261022)。已入库的证据字符串不改写。

<a id="rq-dynamic-stage1-20261023"></a>
### 2026-10-23 米筐动态名单第一阶段（单日样本完成，保留覆盖降级）

- 用户已确认设计并明确两阶段边界。动代码前已将当时 7 个文档文件单独提交为 `ac7543b`（未推送）；后续代码与文档仍未提交。固定名单 v1 raw 身份和既有历史观察保持兼容。
- 已实现：只读一致性事务冻结 PG 身份／别名；结合米筐上市含首日、退市不含当日的明确参考边界生成每日沪深 A 股名单；保留边界未知与 SDK 过滤，B 股明确排除留证；300114 与 302132 通过已验证整码别名关联同一证券。v2 variant 包含名单策略／映射版本／validation 用途，不包含每日变化名单；每日原始请求、完整响应、名单快照及覆盖 hash 不可变保留，reader 重算名单与三表交集。未知新 SDK 代码没有已核实别名时仍拒绝入库，不猜身份。
- 新 `factor.model_run_coverage` 与五件套、模型元数据、映射和成功 ETL 同日事务提交；失败流水独立记录。覆盖降级保留 ETL 告警及完整候选，纯覆盖降级可成功；数值质量告警仍遵循既有复核语义。空完整集、数值／轴／身份异常阻断，不放宽 R1／R2。v2 run 的 units 明确 purpose=validation、日期及名单／覆盖身份，calibrated=false，available_at 为实际观察时间。
- 首版 DDL（已被下方修订取代）：`048_factor_model_run_coverage.sql`，SHA256 `89f5cafb6ff506422d8ad9ff850493ef82b9092c99dca52d78cbee62f2cbee1a`。一次性 TimescaleDB 2.30.1-pg18 先应用基线 000～047，再 dry-run 确认仅 048，正式应用和重放成功；4 个合法用例通过、21 个非法数组／状态／JSON／主外键用例被拒绝。用户要求工作库执行前看 DDL，已展示并发出批准问题，**尚未获得本次工作库迁移确认，未执行工作库迁移或采样**。
- 全仓验证命令：`GETRICH_TEST_PG=1 GETRICH_WORKER_BACKEND=inproc PG_HOST=127.0.0.1 PG_PORT=55439 PG_USER=postgres PG_PASSWORD=test PG_DB=getrich TUSHARE_TOKEN='' RICEQUANT_API_KEY='' RICEQUANT_ENABLED=false COVERAGE_FILE=/tmp/getrich-rq-stage1.coverage UV_CACHE_DIR=/tmp/getrich-uv-cache uv run --frozen pytest --cov --cov-report=term-missing --cov-report=xml:/tmp/getrich-rq-stage1-coverage.xml --cov-fail-under=75`。全部 DB 测试指向一次性容器；3029 passed、22 skipped（21 个真实供应商测试、1 个 Windows 专属）、8 个既有 xfail，覆盖率 85.5%，退出 0。新增真实 PG 用例验证 partial bundle／JSONB 与数组 COPY／重复导入／coverage 写失败整日回滚／300114 别名冲突。独立审查无阻断项；其建议的“SDK 接受新代码但未核实 alias”回归补充运行 1 passed。
- 静态验证：`uv run --frozen ruff check packages/ scripts/`、`ruff format --check packages/ scripts/`、`python scripts/lint_migrations.py`、`uv lock --check`、`git diff --check` 通过。本任务一次性测试容器与 named volume 已清理；gr-data 集成 fixture 的容器亦已自行清理。日志 `/tmp/getrich-rq-stage1-full-tests.log` 及临时覆盖率文件仅为本机验证附件；以上摘要为可持久追溯记录。未调用真实供应商进行本阶段采样，未启动正式风险读取。
- 样本准备：只读核验 2026-10-21 为沪市开市日且有 Tushare 日线，三个模型的四项源单位及证据沿用各自已验收历史 run 原文，配置不含凭据。v1/v2/v2trd 的 v2 raw variant 已预登记在 [设计表](../plans/ricequant-historical-universe.md#验证-run-与正式读取隔离)。实际候选、完整、未返回、异常数与流量尚无本轮实测值，**不得以固定 100 股结果或预登记冒充全市场采样结果**。工作库迁移批准后，先核对 dry-run 仅 048，再应用、核对 owner，顺序各采一天并按 2026-10 入库；质量异常先检查。
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

后续进展：以下首轮“待确认／待授权”已由用户授权的 [120 日单位探针](2026-10-22-rq-risk-units-probe.md) 及下文三天样本验收取代；本段仅保留首轮历史证据。

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

- 2026-10-22 单位探针方法、比值分布与100只名单已归档：[米筐风险单位探针](2026-10-22-rq-risk-units-probe.md)。

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
- 2026-10-23 用户已认可[全市场动态名单与逐股覆盖设计](../plans/ricequant-historical-universe.md)方向。本版补充：下限 2024-01-01，更早需先列 Tushare 补齐范围；正式读取仅走 D-022 钉住的 run，发布排除验证用途且禁止 latest 回退；诊断按 D-017 保留缺覆盖持仓及权重，相关指标不可用、不估算；三模型配额粗估 4～5 日并列明依据。本轮仅修订文档，DDL／代码等用户复核确认后再做；正式覆盖阈值等独立全市场样本后再定。固定 100 股验证已完成，不重复采集。D-022 及校准仍未完成，不能放行正式全市场读取。

<a id="rq-boundaries-20261023"></a>

### 2026-10-23 换码／摘牌边界修复与新 variant 全市场样本（完成，验证用途）

- D-012 已记录触发原因：动态历史名单必须按交易日选当时有效代码。最小规则 `cn_stock_code_intervals_v1` 仅含 300114.SZ → 302132.SZ；[公司公告](https://static.cninfo.com.cn/finalpage/2025-02-15/1222544408.PDF) 确认 2025-02-17 开市生效。上市区间、代码区间、停牌分别处理，同一证券身份不拆分，不覆盖北交所，不建设通用公告核定系统。
- 先执行 `uv run --frozen gr-data raw tushare --only instruments --mode update`，再 `uv run --frozen gr-data ingest tushare --only instruments,symbol_map`，均退出 0（12:05～12:06）。Tushare 已自行补齐 000016.SZ 的 delist_date=2026-10-23，未做人工数据覆盖。其最后行情日是 2026-09-03，9 月 4 日至 10 月 22 日有 29 个 S 事件；10 月 21、22 日在市且停牌，23 日摘牌排除。
- 统一上市区间为 `list_date <= day < delist_date`。真实核验范围是 2024-01-01～2026-10-23 摘牌的沪深 A 股 103 只：两源退市日期 103/103 一致；100 只在库内有行情，摘牌当日／之后行情均为 0。002898、000004、002808 等最后行情紧邻摘牌，000016、601059、601198 等存在停牌间隔，因此退市日不能代替最后行情日。000046、002776、600290 在本库 2024 年后无行情，不作为行情边界正证据。已退市而缺结束日仍降级，不以当前 active 状态过滤历史；普通未退市证券空结束日开放。当前人工核定例外清单：**0 条**。未来仅对有公告依据的源冲突逐条登记，超过 5 条停止确认。
- 边界小探针：三模型分别请求 2025-02-14 的 300114.XSHE、2025-02-17 的 302132.XSHE、2026-10-21／22 的 000016.XSHE，共 12 个股票日模型组合，五件套全部完整，数值门禁通过。摘牌日 2026-10-23 由新规则和参考日期验证排除，不发送个股请求，也不采未结束交易日。探针账户计数窗口增加 3,351,938 字节，不能视为逐请求精确计费。
- 新策略 `listed_cn_a_v2 / alias_v2`，规则正文冻结在 raw，版本／哈希纳入新 variant，逐股只给受影响证券存换码证据；共用规则摘要进 run／ETL。旧 `listed_cn_a_v1`、旧 raw、旧降级 run 原样保留，三个旧 raw 只读重放／PG 逐值验收通过。048 磁盘及工作库 checksum 仍为 `0488aa6eac51`，9 张 factor 表归属未变。
- 全仓测试和独立代码审查通过后，重采并用 `ingest ricequant --only rq_risk_model --months 2026-10` 导入三个新 variant 的 **2026-10-21 单日全市场**；每个模型 20,898 行（含覆盖表），各 1 条 success ETL、0 failed、0 warning。用途仍是 validation、calibrated=false；新 variant 已登记在[设计文档验证表](../plans/ricequant-historical-universe.md)。旧样本每模型 2 个 unknown、99.9617% 完整率及原流量结论继续保留，未追溯修改。

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
