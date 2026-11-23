# 待决问题与后续工作

面向安排工作的项目维护者。本文只保留未关闭、可落实的实现缺口与待定口径，不是已批准的实施计划，不授权变更 API、schema、依赖或工作库。

基线核对：**2026-11-23**（同步多用户持仓诊断 V1 `diag-publication-v3` 后端加固与云端 `/srv/getrich` 追平状态；已完成的 Batch 2 申万一级行业、Batch 3 年度 ROE、`051` 迁移、`052` 账本对齐、Batch 4 两阶段日更及初次上云均已从本表移除）。当前运行状态见 [NOTES](../../.agents/brain/NOTES.md)，实现取舍见 [决策记录](../../.agents/brain/DECISIONS.md)，上线切换步骤见 [V1 发布切换指南](../guides/v1-release-cutover.md)。

---

## 1. V1 正式发布前运维切换项（`/srv/getrich`）

仓库侧 V1 后端代码、测试与 `diag-publication-v3` 数据（云端已追平至 `2026-11-20`，`5,224` 只沪深 A 股、7 项模型指标）已就绪；正式对外开放前须由用户在云端确认并完成以下仓外切换：

| 待切换项 | 完成条件与验收门禁 |
| --- | --- |
| **提升 `current/{app,etl}` 发布版本** | 云端冻结 ETL 仍停在旧 `9bf6a0e`，须从最新已推分支构建：`app` 使用 `--package gr-api --no-dev --no-editable`；`etl` **必须保留 `.git` 且使用 editable 安装**（满足 `risk_receipts.py` 干净源码树校验）。 |
| **拆分 `api-prod.env` 并移出 `maintenance-runtime.json`** | 新建 `0600` 的 `api-prod.env`（不含供应商密钥，显式设 `GETRICH_V1_DIAGNOSIS_ONLY=true`、`GETRICH_DIAG_PUBLICATIONS_ENABLED=true`、`BACKTEST_ARTIFACT_DIR=/srv/getrich/state/artifacts` 并提前创建该目录）；将 `api.env`/`api-prod.env` 移出 `maintenance-runtime.json` 字节哈希，避免修改 API 配置阻断日更与 `pg_dump` 备份。 |
| **日更定时器改至次日 `<15:00 Asia/Shanghai` 并启用 `--probe-upstream`** | 将 `getrich-v1-daily.timer` 从 `23:30` 改为 `09:00,12:30 Asia/Shanghai`，调用 `diagnosis-daily run --probe-upstream`，消除交易日当晚米筐 `v2` `exposure=None` 误触发 `daily-blocked.json` 及次日 `15:00` 后 `lag = 2` 的 `503` 窗口；同步对齐 `cloud_health.py` 的 `pending_upstream` 判定。 |
| **`getrich-api.service` 与反向代理边界加固** | 显式绑定 `127.0.0.1:8001`、设 `--timeout-graceful-shutdown 35` 与 `TimeoutStopSec=45s`；反向代理对外屏蔽 `/metrics`、配置认证与诊断写入限流；ICP 备案前保持 DNS 暂停与非 `80/443` 源 IP 白名单，备案后拆分根/`www` 与 `api.<domain>`。 |
| **供应商授权有效期与异机备份抽检** | 放通前核实米筐与 Tushare 剩余额度 `>= 10%`、授权有效期 `>= 30` 天；确认云端滚动 `.dump` 已定期拉回异机留存。 |

---

## 2. 持仓诊断 V1.1 / 二期 / V2 待决项

范围对照设计仓 [范围决策](../../../getrich-design/governance/scope.md)、[表与接口设计](../../../getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md) 与 [一期数据集清单](../../../getrich-design/data-platform/portfolio-diagnosis-phase1-datasets.md)。

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| **L4、风格暴露与模型相关性主视图未准入** | V1 `v3` 已开放方差、年化/单日预测波动率、RC、RC 占比、MRC、L3 七项；`l4_effective_count`、`l4_market_source_share`、`l4_largest_source`、风格暴露及 `correlation.by_method.forward` 需先在真实全市场样本上复核最小扭转正交化的方差守恒与近奇异阈值后再发布新口径版本。 |
| **米筐 P6 全区间校准（`calibrated=true`）待供应商约定** | 11,633 个模型日五表扫描已完成只读终验，但前日暴露 + 超额收益代理在历史个股日仍有未解残差（见 `NOTES` P6 记录）。须取得米筐关于暴露时点、复权与无风险利率的书面约定后再评定 `calibrated=true` 范围；在此之前全部保持 `calibrated=false`（`degraded / not_calibrated`）。 |
| **组合回放与个股/组合 Beta 缺 DS06～DS08** | 完成 DS06 分红送转（`finance.dividend`）、DS07 退市终止价值依据与 DS08 全收益基准（如沪深 300 全收益）的来源核验与建表入库；严禁用价格指数替代全收益基准或静默填补缺失分红。组合回放按 [D-021](../../.agents/brain/DECISIONS.md#d-021) 独立实现，不复用 `gr-backtest`。 |
| **`/report` 缺个股估值展示卡片** | `/result` 的 `instrument_facts` 已逐股返回总市值、PB、估值日期与年度 ROE，但设计稿 §7.3.4 尚未定义对应文字报告块类型，`/report` 暂不输出；需先补设计块定义再实现。 |
| **主前端 `apps/web` 解冻与 `v3` 契约对齐** | `apps/web` 在 V1 冻结不部署；解冻前须补齐 `PortfolioDiagnosisPage.tsx` 对 `v3` 新增四项风险指标及行业/市值/PB/ROE/相关性区块的展示、移除过时的“匿名模式”提示（现已强制登录 `401`），并将 `apps/web/.env.example` 端口对齐至 `8001`。 |
| **数据库维护边界与历史 PIT** | TimescaleDB 受保护表的 `DROP` / `drop_chunks` / retention 策略、诊断只读专用 DB 角色、通用全量代际发布以及历史任意交易日 PIT 诊断仍待后续阶段单独设计审阅。 |
| **V2：按风险偏好建议权重与二期调仓对比/记忆** | 二期显式 Before/After 调仓对比、定性画像与盲点阈值（M11）、用户记忆与行为画像、V2 按风险偏好建议权重均按阶段规划推进，不在 V1 开放。 |

---

## 3. 其他模块待决项

### 3.1 回测引擎与作业接口（`gr-backtest` / `gr-api`）

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| **Black-Litterman 量纲与后验退化** | 按 [D-009](../../.agents/brain/DECISIONS.md#d-009) 确定 `Q` 与 `Ω` 标定口径；补非退化协方差的后验与观点符号回归。 |
| **`PgBarLoader` 未完整适配真库** | `PgBarLoader` 仍拒绝 `oi`、未映射 `trading_status`、未接入公司行为表；完成适配前不将真库回测视为已验收（V1 通过 `GETRICH_V1_DIAGNOSIS_ONLY=true` 不对外挂载 `/v1/backtest-*`）。 |
| **撮合顺序与涨停买入边界偏差** | `api.py` 先撮合后处理公司行为且 `_load_corp_actions()` 吞异常；`execution.py` 允许买价等于涨停价。按明确撮合规则修复并补可核算回归。 |

### 3.2 策略／信号与选股模块（`gr-api` / `gr-picks`）

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| **管理导入通道缺 `import_jobs` DDL** | `services/admin_import.py` 引用的 `import_jobs` / `import_job_errors` 在 `gr-db` DDL 中未定义（`upsert_strategy` 的 HTML 清洗与长度上限已补齐）；对外开放管理导入前须先定去留并补齐 DDL 与端到端测试。 |
| **信号执行写全局成交流水与枚举不一致** | `POST /v1/signals/{code}/execute` 当前会写入公共 `strategy_trades` 表，需明确个人跟单记录与策略作者公共交易流水的权限边界；同时对齐 `signal.py` 的 `type`/`urgency` 枚举及 `SignalDetail.tsx` 占位字段。 |
| **选股导入历史代码别名回填** | `gr-picks` 当前仅查 `meta.instruments.symbol`，尚未像诊断一样串联 `meta.symbol_map` 合并新旧代码并幂等回填历史 `pick.item.instrument_id`。 |

### 3.3 数据平台与非诊断品种（`gr-data` / `gr-db`）

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| **全供应商通用可靠采集协议** | 按 [可靠采集实施计划](gr-data-reliability-implementation-plan.md) 推进通用状态机、quarantine、不可变观察与收据闭环（诊断 V1 与米筐风险已先行建立专用闭环）。 |
| **停复牌空响应语义与 Tushare 4 项 `xfail`** | 区分当日尚未发布的 `suspend_d` 空响应与合法无停牌；修复 [`test_tushare_review_findings.py`](../../packages/gr-data/tests/test_tushare_review_findings.py) 中 `#4`/`#5`/`#26`/`#37` 四项 strict `xfail` 及日线重复键冲突口径。 |
| **无年报新股重复回查与旧列注释跟进** | `diagnosis_daily` 对尚无 `12-31` 年报记录的新股每日重复请求 `fina_indicator` 空结果，后续可加空观察缓存；`038_fundamental.sql` 与 `039_classify.sql` 的旧占位列注释待通过新注释迁移刷新（严禁改已记账 SQL）。 |
| **ETF 剩余 120 键 `fund_adj` 与填充值溯源** | 364 只 ETF 的 16,132 行米筐观察值已按 `provider_fill_possible=true` 准入，剩余 4 只 ETF 共 120 个交易日因 Tushare `fund_adj` 仍为空暂缓（不默认填 `1`）；ETF 专项研究前另行溯源。 |
| **北交所待核项与期货完整日历** | `ops.tushare_bj_pending` 存量待处理记录与六所期货完整交易日历写入方案留待对应品种开放前专项核实。 |
| **期权多方法表与 Greeks 精度扩展** | 期权正式发布继续关闭（[D-026](../../.agents/brain/DECISIONS.md#d-026)）；后续开放前需审定 `market.option_greeks_1d` 的 `theta`/`vega`/`rho` 扩 `NUMERIC(20,8)` 或新建多方法 `market.rq_option_greeks`、郑商所原生指标口径及 `opt_mins` 分钟权限。 |
| **米筐补充数据集 R1–R10 去重门槛** | `gr_data/config/ricequant.py` 仍要求 `datayes_overlap == 'distinct'`，启用补充 writer 前按 DP-02 同步配置与验收。 |
