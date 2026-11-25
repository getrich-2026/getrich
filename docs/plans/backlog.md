# 待决问题与后续工作

面向安排工作的项目维护者。本文只保留未关闭、可落实的实现缺口与待定口径，不是已批准的实施计划，不授权变更 API、schema、依赖或工作库。

基线核对：**2026-11-24**（云端 `/srv/getrich` 已完成 V1 准生产环境切换、`ops/` 长期运维脚本收口与旧冻结目录清理；已完成项均从本表移除）。当前运行状态见 [NOTES](../../.agents/brain/NOTES.md)，实现取舍见 [决策记录](../../.agents/brain/DECISIONS.md)，运维操作见 [V1 发布切换指南](../guides/v1-release-cutover.md)。

---

## 1. V1 线上运行期持续关注项（`/srv/getrich`）

V1 后端代码、晨间 T+1 日更调度（`09:00/12:30/14:15`）、长期逻辑备份（`run-backup.py`）、全面健康巡检（`run-health.py`）与 Nginx 公网反向代理均已上线验收通过；当前仅保留以下运行期跟进项：

| 待跟进项 | 完成条件与验收门禁 |
| --- | --- |
| **米筐授权续期与异机备份定期拉回** | 米筐 `rqdatac` 授权剩余有效期约 17 天（低于 30 天预警线），须在到期前完成续期；云端 `/srv/getrich/state/backups/` 的最新滚动 `.dump` 需定期拉回异机留存独立副本。 |
| **域名备案后切换正式 `APP_ENV=prod` 与 HTTPS** | 当前联调期为 `APP_ENV=staging` + `STRICT_MODE=true` + HTTP `:8080`；境内域名 ICP 备案完成后，按 `api.<domain>` 签发自动续期 TLS 证书、收紧 `WEB_CORS_ORIGINS` 为正式 HTTPS 域名、切换 `APP_ENV=prod` 并按需屏蔽公网 `/docs` 与 `/openapi.json`。 |

---

## 2. 持仓诊断 V2 主线与二期待决项

> **V2 当前优先主线（2026-11-24 已确认，见 [D-032](../../.agents/brain/DECISIONS.md#d-032)）**：优先推进**持仓诊断深化**——① 组合历史回放与个股／组合 Beta（DS06～DS08）；② L4 风险源分解（含风格暴露／模型相关性复核）；③ 调仓前后显式对比。其余项按 V1 用户反馈与阶段排期跟进。

范围对照设计仓 [范围决策](../../../getrich-design/governance/scope.md)、[表与接口设计](../../../getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md) 与 [一期数据集清单](../../../getrich-design/data-platform/portfolio-diagnosis-phase1-datasets.md)。

| 未关闭问题 | 下一步与完成条件 |
| --- | --- |
| **L4、风格暴露与模型相关性主视图（批次 2A）** | 已完成全历史 3,592 个米筐 `v2` 交易日正交稳定性核验（`0/3592` 失败，最小特征值 `6.25e-3`，守恒误差 `<1.68e-14`），并在特性分支 `feat/v2-2a-l4-comparison` 落地 `057_diag_v4_model_metrics.sql`（12 项模型指标）及隔离库实测验收；待评审合入并在云端升级发布 `diag-publication-v4`。 |
| **米筐 P6 全区间校准（`calibrated=true`）待供应商约定** | 11,633 个模型日五表扫描已完成只读终验，但前日暴露 + 超额收益代理在历史个股日仍有未解残差（见 `NOTES` P6 记录）。须取得米筐关于暴露时点、复权与无风险利率的书面约定后再评定 `calibrated=true` 范围；在此之前全部保持 `calibrated=false`（`degraded / not_calibrated`）。 |
| **批次 2B 的发布范围与后续扩展** | 本地开发已接入 DS06 实施分红、DS07 退市截断、DS08 三条经核验的全收益基准，回放与 Beta 的测试数据和命令见[诊断指南](../guides/diagnosis-api.md#本地-v2-批次-2b-开发验证)。扩大股票覆盖前，须为新增标的核验分红全历史、停复牌与开盘限价证据、退市观察，并按发布版本固化。可靠退市终值仍缺来源，当前在受影响日截断。 |
| **`/report` 缺个股估值展示卡片** | `/result` 的 `instrument_facts` 已逐股返回总市值、PB、估值日期与年度 ROE，但设计稿 §7.3.4 尚未定义对应文字报告块类型，`/report` 暂不输出；需先补设计块定义再实现。 |
| **主前端 `apps/web` 解冻与 `v3`/`v4` 契约对齐** | `apps/web` 在 V1 冻结不部署；解冻前须补齐 `PortfolioDiagnosisPage.tsx` 对 `v3`/`v4` 风险指标、调仓对比及行业/市值/PB/ROE/相关性区块的展示、移除过时的“匿名模式”提示（现已强制登录 `401`）。 |
| **数据库维护边界与历史 PIT** | TimescaleDB 受保护表的 `DROP` / `drop_chunks` / retention 策略、诊断只读专用 DB 角色、通用全量代际发布以及历史任意交易日 PIT 诊断仍待后续阶段单独设计审阅。 |
| **V2：定性画像/盲点阈值、调仓意图核对与权重建议** | `rebalance_holding` / `rebalance_amount` 客观数值对比（`deltas`、`marginal_impact`、`overlap_with_new`）已在 2A 分支完成；`intent_effect_gap` 意图核对、定性画像与盲点阈值（M11）、用户记忆与行为画像、按风险偏好建议权重按后续阶段推进。 |

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
| **Tushare 停复牌空响应与日线重复键** | 区分当日尚未发布的 `suspend_d` 空响应与合法无停牌，明确同一证券同一交易日出现冲突日线时的处理规则。 |
| **无年报新股重复回查与旧列注释跟进** | `diagnosis_daily` 对尚无 `12-31` 年报记录的新股每日重复请求 `fina_indicator` 空结果，后续可加空观察缓存；`038_fundamental.sql` 与 `039_classify.sql` 的旧占位列注释待通过新注释迁移刷新（严禁改已记账 SQL）。 |
| **ETF 剩余 120 键 `fund_adj` 与填充值溯源** | 364 只 ETF 的 16,132 行米筐观察值已按 `provider_fill_possible=true` 准入，剩余 4 只 ETF 共 120 个交易日因 Tushare `fund_adj` 仍为空暂缓（不默认填 `1`）；ETF 专项研究前另行溯源。 |
| **北交所待核项与期货完整日历** | `ops.tushare_bj_pending` 存量待处理记录与六所期货完整交易日历写入方案留待对应品种开放前专项核实。 |
| **期权多方法表与 Greeks 精度扩展** | 期权正式发布继续关闭（[D-026](../../.agents/brain/DECISIONS.md#d-026)）；后续开放前需审定 `market.option_greeks_1d` 的 `theta`/`vega`/`rho` 扩 `NUMERIC(20,8)` 或新建多方法 `market.rq_option_greeks`、郑商所原生指标口径及 `opt_mins` 分钟权限。 |
| **米筐补充数据集 R1–R10 去重门槛** | `gr_data/config/ricequant.py` 仍要求 `datayes_overlap == 'distinct'`，启用补充 writer 前按 DP-02 同步配置与验收。 |
