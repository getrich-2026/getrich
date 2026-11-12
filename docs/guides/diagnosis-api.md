# 持仓诊断 API 调用指南

面向后端接口使用者，说明独立于网页的调用方式、响应和启停。字段真源为 `/openapi.json`、[请求模型](../../packages/gr-api/src/gr_api/schemas/diagnosis.py)和[响应模型](../../packages/gr-api/src/gr_api/schemas/diagnosis_response.py)；设计 OpenAPI 不能替代实现。

历史数据验收状态（2026-11-10）：工作库定向055、新证券范围发布、新连接读回及真实TCP HTTP多用户验收通过。本轮交付仅后端API、迁移及数据发布；浏览器测试仅补充证据，现有apps/web改动保留待另审，未部署网页。用户已批准正式后端部署与启用；当前正式部署主机、服务进程和对外地址待明确，正式地址复验待此信息到位后执行，常规 `GETRICH_DIAG_PUBLICATIONS_ENABLED=false` 未改。

## 已验收范围

- 日期 **2026-11-05**，米筐v2，原run `da212baf-9bfc-5014-8bff-0b574e8e7b9b`；不回退日期或模型。
- 发布版本 `diag-v2-20261105-ashare5224-20261110-v1`，5224只沪深A股（上交所2318、深交所2906）。实际清单在 `/v1/diagnosis/options` 的 `data.publication_scope.security_ids`，应结合证券元数据解析；以发布清单为准，不把所有看似合法的代码自动纳入。
- 仅三项模型指标：`annual_variance`、`volatility.by_method.forward`（年化预测波动率）、`daily_prediction_volatility`。后两者都是小数，显示百分比时乘100；年化方差保持小数平方。
- `calibrated=false`，指标状态为 `degraded/not_calibrated`：指定单日证券清单及三指标的源值、单位和数值验收通过，全区间校准及P6尚未完成。不能解释为历史PIT或其他风险指标已验收。
- 清单内可自由组合与调权，无需逐组合发布。每个方案最多100原始行（含重复和零权重），每次1～5个独立方案。

## 认证和调用

所有诊断路径前缀为 `/v1/diagnosis`。成功信封是 `{code,message,data,timestamp,request_id}`。使用已有账号向 `POST /v1/auth/login` 提交 `email/password`，把返回的 `data.access_token` 作为 `Authorization: Bearer ...`。不同用户分别使用自己的token；正式使用保持 `GETRICH_ALLOW_MOCK_AUTH=false`。

续期调用 `POST /v1/auth/refresh`，JSON 请求为 `{"refresh_token":"YOUR_REFRESH_TOKEN"}`；
成功响应的 `data` 返回新的 `access_token`、轮换后的 `refresh_token`、`token_type` 和 `user`。
前端同时替换两个 token；无效或过期 refresh token 返回 401，重新登录。

下例需要curl和jq。把 `BASE_URL` 改为获准启用的服务地址，把 `TOKEN_A` 设为本人有效token。本轮临时验收地址127.0.0.1:18011已停止，不作为正式地址。

```bash
export BASE_URL='https://YOUR_API_HOST'
export TOKEN_A='YOUR_ACCESS_TOKEN'

cat > portfolio.json <<'JSON'
{
  "as_of_date": "2026-11-05",
  "plans": [{
    "plan_id": "regression",
    "holdings": [
      {"symbol": "600519.SH", "weight": "0.4"},
      {"symbol": "600036.SH", "weight": "0.35"},
      {"symbol": "000333.SZ", "weight": "0.25"}
    ]
  }]
}
JSON

curl --fail-with-body --silent --show-error \
  "$BASE_URL/v1/diagnosis/snapshots" \
  -H "Authorization: Bearer $TOKEN_A" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(python3 -c 'import uuid; print(uuid.uuid4())')" \
  --data-binary @portfolio.json > created.json

SNAPSHOT_ID=$(jq -r '.data.snapshot_id' created.json)
curl --fail-with-body --silent --show-error \
  "$BASE_URL/v1/diagnosis/snapshots/$SNAPSHOT_ID/result" \
  -H "Authorization: Bearer $TOKEN_A" > result.json

jq '.data | {as_of_date,data_fingerprint,publication,
  plans:[.plans[] | {plan_id,risk:.section_b.value}]}' result.json
```

POST新建返回201和 `data.links.result/report/data_quality`。按返回的links读取结果、报告或缺失原因；结果已经同步计算。下列是本次三股工作库GET响应的字段摘录，保留实际层级，省略其他诊断字段：

```json
{
  "code": 0,
  "data": {
    "as_of_date": "2026-11-05",
    "data_fingerprint": "diag-v2-20261105-ashare5224-20261110-v1",
    "publication": {
      "scope_type": "security_universe",
      "status": "available",
      "recomputable": true,
      "model_run_id": "da212baf-9bfc-5014-8bff-0b574e8e7b9b",
      "calibrated": false
    },
    "plans": [{
      "plan_id": "regression",
      "section_b": {
        "status": "ready",
        "value": {
          "annual_variance": {"status":"degraded","value":0.04532912929206873,"reason_code":"not_calibrated"},
          "volatility": {"by_method":{"forward":{"status":"degraded","value":0.21290638621720281,"reason_code":"not_calibrated"}}},
          "daily_prediction_volatility": {"status":"degraded","value":0.01341184167781401,"reason_code":"not_calibrated"},
          "model_id": "rq_423b18dfe38ab26a51659adc19796",
          "model_date": "2026-11-05",
          "model_run_id": "da212baf-9bfc-5014-8bff-0b574e8e7b9b",
          "calibrated": false,
          "model_coverage": {"status":"complete","total_count":3,"covered_count":3,"total_weight":"1","covered_weight":"1","missing":[]}
        }
      }
    }]
  }
}
```

对应年化预测波动率21.2906386217%，单日预测波动率1.3411841678%。用独立资产协方差路线复算，rtol=1e-12/atol=1e-15通过。最终F和特异方差从库内pct2_annual各除10000恢复年化小数方差，再仅除252一次取得日方差；不再次平方特异方差。

## 修改权重、多个方案与重算

修改股票或权重后，向同一个 `POST /snapshots` 提交新的**完整组合**及新的Idempotency-Key。例如三股改为20%/30%/50%，三项实际结果为0.0410145604591487、0.20252051861267958和0.012757593515166138。

需要同一版本的两套权重时，在一个请求的 `plans` 中提交两个不同plan_id的完整方案；一次请求固定同一发布版本，各方案独立返回结果。不同时间的两个POST可能遇到版本更新，应核对返回的data_fingerprint。V1不输出调仓建议或自动建议权重。

`POST /snapshots/{id}/recompute` 仅复制原快照组合并按新options创建新快照，不能用于替换持仓。版本有效且归属匹配时201；原版本失效时409 `BASE_DATA_VERSION_UNAVAILABLE`，旧报告仍可读取，不能用最新数据冒充原版本。

幂等键须为UUIDv4：同用户、同键、同体重放200并返回原snapshot；同键异体409。新的计算或调权使用新键；纯计算缓存不改变快照归属。GET报告可带 `user_level=retail|pro`，不影响计算或权限。

## 缺失数据与状态

| 情况 | 契约 |
| --- | --- |
| 负权重、非有限数、全零、部分填写、超过100行/5方案 | 422，按issues定位；全部省略时对唯一标的等权，重复项合并 |
| 已识别的ETF、北交所、退市或其他范围外资产 | 422，要求修正后提交，不静默删除 |
| 日期与发布日不同或请求越界指标 | 422，不回退；请求 `metrics` 只能选annual_variance/volatility/daily_prediction_volatility |
| 正权重证券无法解析、未在清单或缺同run风险输入 | 保留证券、原份额及原因，完整组合三项模型风险unavailable；不对覆盖子集重新归一化。没有可解析正权重标的时输入422 |
| 无凭证、无效或过期凭证访问私有诊断接口 | 401 unauthorized，使用标准诊断错误结构 |
| 已登录用户读取他人结果、报告、数据质量或重算 | 403 forbidden |
| 最新发布失效/无可用发布 | 新诊断503，不自动回退旧日期；历史产物仍可读，重算409 |

例如80%茅台加20%无法解析的888888.SH，实际返回 `model_coverage.covered_weight="0.8"`、`data_quality.plans[0].coverage_summary.risk_model=0.8`，缺失项 `{"symbol":"888888.SH","weight":"0.2","reason":"unresolved_symbol"}`，三项完整模型风险均不可用且无value。不能把该请求解读为茅台100%的风险。

区块状态与指标状态分别判断：`ready/unavailable/failed` 与 `ok/degraded/unavailable`。`run_status=partially_succeeded` 可由未开放的C区等产生，不表示已验收的三项风险计算失败；只消费本次准入的指标及其status，不把其他字段推断为新增准入。不可用指标没有value，不能显示为0。

## 正式启用与回退

工作库055及本版发布已验收，用户已批准仅后端正式部署与启用。后续部署须先完成已批准的本地批次及审核；真实目标与上线状态在仓外维护。下列为已有版本的部署参考，不代表已部署。

正式部署时：

1. 发布仅已验收后端及依赖，包含注册必填列修复和gr-api显式依赖gr-signal的声明；后者在独立安装时验证为必需。使用锁定依赖的非editable安装（`uv sync --frozen --package gr-api --no-dev --no-editable`），不携带apps/web部署。先核对055唯一账本和新版本可用性，不再跑全目录迁移。
2. 在现有API运行环境设置 `GETRICH_DIAG_PUBLICATIONS_ENABLED=true`，保持 `GETRICH_ALLOW_MOCK_AUTH=false` 及既有JWT配置，优雅重启既有API进程。
3. 用真实登录账号读options，确认日期、版本、5224清单和三指标；调用三股样本复现1.3411841678%，验证不同用户的403及缺失持仓提示后再放通流量。
4. 运行中发布失效应返回503，先核查真实数据和收据，不为恢复出数而回退日期或放宽coverage。

回退：撤下诊断新请求入口，将 `GETRICH_DIAG_PUBLICATIONS_ENABLED=false` 并优雅重启；如需应用版本回退，选兼容现有schema的后端版本。保留055、全部账本、新旧publication/receipt、已保存报告和验收证据，不自动删表/逆改账本/恢复覆盖当前库。需要数据库恢复时，先从逻辑备份恢复全新隔离库核对，再另审切换方案。

实现入口：[HTTP](../../packages/gr-api/src/gr_api/routers/diagnosis.py)、[读取与幂等](../../packages/gr-api/src/gr_api/services/diagnosis.py)、[固定版本读取](../../packages/gr-api/src/gr_api/services/diagnosis_publication.py)、[范围门禁](../../packages/gr-api/src/gr_api/services/diagnosis_scope.py)、[发布与收据](../../packages/gr-data/src/gr_data/diagnostic_publication.py)。迁移和工作验收见[实施计划](../plans/gr-data-reliability-implementation-plan.md#多用户-v1证券清单准入与工作库执行门槛2026-11-10)。


## Batch 1 接口契约（2026-11-12）

前端主页面消费 `/result` 与 `/data-quality`；`/report` 用于文字报告及分享报告。
前端只格式化和展示，不重复计算指标。实际路径统一为 `/v1/diagnosis`，无 `/api` 段。
本批只更新代码契约，不执行数据导入、迁移或发布；行业数据接入由后续批次完成。

### 认证与启动

除 `GET /share/{token}/report` 仍按分享 token 校验外，全部诊断端点必须登录，
包括 options、spec-versions、提交、重算、结果、报告、数据质量、stream 和创建分享。
匿名不再创建快照或读取选项；跨用户访问仍为 403。分享管理与流式展示不属于首批联调要求。

非开发服务显式设置 `APP_ENV=staging` 或 `prod`，不得使用默认开发环境。
这两种环境必须提供非默认、非空 `JWT_SECRET` 和非空、非通配的 `WEB_CORS_ORIGINS`，
漏配即拒绝加载配置；mock 认证仅允许 dev。部署流程须检查 APP_ENV，库仍保留本地 dev 默认值。
支付不作为诊断启动依赖，但任何环境下缺少支付验签密钥均返回 503，绝不跳过验签。
以上错误与正常响应均保留 CSP、X-Frame-Options、X-Content-Type-Options、Referrer-Policy。

### 返回字段及单位

以下路径相对成功信封的 `data`。完整字段、可空性与枚举以响应模型及生成的 OpenAPI 为准；
表中 `A`、`B`、`D` 分别表示 `plans[].section_a.value`、`section_b.value`、`section_d.value`。
本表覆盖计划指标的路径，并不表示这些指标当前已经完成数据准入。

| 路径 | 类型及单位 | 口径与展示 |
| --- | --- | --- |
| `plans[].input.holdings` / `calculation_holdings` | 持仓数组；权重见模型定义 | 原始输入与解析后的计算持仓分开，不用计算权重覆盖原份额 |
| `A.topn` | MetricValue，value 为 n/actual_count/weight 数组 | Top1/3/5；weight 为小数份额，展示百分比乘 100 |
| `A.hhi` / `l1_count` / `l2_effective_count` | MetricValue，数值 | HHI、持仓数、资金有效持仓数 |
| `A.industry_distribution` / `max_industry` | MetricValue，行业权重分布 / 最大行业对象 | 按输入覆盖规则汇总；unclassified 为未分类 |
| `A.industry_labels` | `dict[str,str]` | 行业代码到中文名；体系不可用时为空对象 |
| `A.market_distribution` / `asset_category_distribution` | MetricValue，权重字典 | 市场与资产类别构成 |
| `A.mktcap_distribution` / `pb_distribution` | MetricValue，权重字典 | 档位以 spec params 为准；缺失/异常单列，非正 PB 不代表便宜 |
| `A.lookthrough_coverage` | MetricValue，小数份额 | 当前个股输入的穿透覆盖 |
| `A.instrument_facts.value.<id>.industry_code` / `industry_name` | string 或 null | 逐股归属；未分类或体系不可用时均为 null |
| `A.instrument_facts.value.<id>.total_mv_yi` / `pb` | MetricValue，亿元 / 倍数 | 总市值已换算亿元，禁止再次换算；估值日期在 valuation_date |
| `A.instrument_facts.value.<id>.roe` | MetricValue，小数 | 后续接入最近完整年度加权平均 ROE；报告年份 roe_report_year、公告日期 roe_ann_date；当前不可用 |
| `B.annual_variance` | MetricValue，年化小数方差 | 不作为百分比转换 |
| `B.volatility.by_method.forward` / `daily_prediction_volatility` | MetricValue，小数波动率 | 前瞻年化 / 单日预测；百分比展示乘 100，年化天数见 annualization_days |
| `B.instrument_betas.value[]` | instrument_id 与指标对象数组 | historical_volatility 为逐股历史年化小数波动率；beta 和 benchmark_correlation 当前不可用 |
| `B.risk_contribution` / `risk_contribution_ratio` / `marginal_risk_contribution` | MetricValue，按 instrument_id 的字典 | 后续准入；分别为年化波动率贡献、贡献份额、边际贡献；前两项展示为百分点、百分比时乘 100 |
| `B.l3_effective_count` | MetricValue，数值 | 后续准入；存在负贡献时不能直读为独立股票数 |
| `D.correlation.by_method.historical` | MetricValue，instrument_ids 与 matrix | 矩阵轴按 instrument_ids 对齐；系数不做百分比转换 |
| `D.avg_pairwise_correlation.by_method.historical` / `high_correlation_pairs.by_method.historical` | MetricValue，数值 / 股票对数组 | 与历史相关矩阵同口径，阈值以 spec 为准 |
| `publication.declared_metrics` / `B.model_coverage` | 指标数组 / 覆盖对象 | 只开放该快照实际准入指标；模型卡片按 declared_metrics 裁剪 |
| `data_quality.plans[]` | issues、coverage_summary、forced_disclosures | `/data-quality` 的明细，覆盖率为小数；issues.paths 指向结果 JSON 路径 |

快照的 `as_of_date` 是诊断日期；`data_fingerprint` 固定数据版本，估值可有更早的逐股日期。
历史指标通过 `method`、`window_target`、`window_actual`、`sample_count` 回显方法、窗口与有效样本；
相关性和逐股波动率样本分别计算。`cov` 与 `options` 记录模型和区间选择，不用浏览器当前日期代替。
L4、模型相关性、风格暴露等未准入字段继续不可用，文字报告不输出未准入的模型卡片及相应说明。

载体缓存版本从 7.1 升为 7.2；新增行业字段不改写旧快照，旧载体经响应模型补空字典/null。
这些缺省值表示旧结果未提供信息，不应显示为真实行业归属。

### 状态与响应样例

当前同步执行：POST 新建返回 **201**，幂等重放返回 **200**；GET 返回 **200**。
同步响应已经是终态，不需要先轮询。不能承诺所有规模均为毫秒级，应按实际规模测量耗时。
`run_status=partially_succeeded` 也是终态，表示有区块尚不可用，不应无限重试。
下列 JSON 为契约摘录，省略的字段按 OpenAPI 返回，不能作为完整响应 fixture。

正常可用的指标（成功响应 data 内）：

```json
{"plans":[{"section_a":{"status":"ready","value":{"hhi":{"status":"ok","value":0.345,"method":"exact"}}}}]}
```

部分不可用：区块 ready 只说明组装完成，应逐项检查指标状态；unavailable 无 value，严禁显示为 0。

```json
{"plans":[{"section_a":{"status":"ready","value":{"industry_distribution":{"status":"unavailable","reason_code":"data_not_validated","reason":"行业数据尚未完成验证。"}}}}]}
```

仅供未来异步化的合成示例：**202** + `Retry-After: 1`，当前真实计算链路不触发。
前端只有遇到 pending/running 才按 links 查询；遇到 succeeded/partially_succeeded/failed 停止轮询。

```json
{"code":0,"message":"success","data":{"run_status":"running","snapshot_id":"11111111-1111-4111-8111-111111111111"},"timestamp":0,"request_id":"synthetic-example"}
```

整单错误与成功信封不同，例如未登录 **401**：

```json
{"request_id":"synthetic-example","error":{"code":"unauthorized","message":"auth required: please log in","retryable":false,"issues":[]}}
```

参数错误为 422，`issues[].path` 是 JSON Pointer；同幂等键异体为 409。
单方案失败时在成功信封中保留 plan 的 failed 状态与 error，不删除该方案；
发布不可用时整单 503，不伪装成全零报告。所有示例均不含真实账号、联调地址或持仓。

重算仅复制原持仓并修改 options，不支持替换持仓；调整股票或权重应创建新快照。
原数据版本失效或无法取得时返回 409 `BASE_DATA_VERSION_UNAVAILABLE`，不使用最新版本替代。

## 行业与核心数据更新（Batch 2，2026-11-12）

本批接入 Tushare `index_classify(level=L1, src=SW2021)` 与 `index_member_all`。
后者单页最多 2000 行，按一级行业及 `is_new=Y/N` 分片分页，原件保留全部返回历史。
canonical 本次只接纳覆盖诊断日期的归属区间，保留来源 `in_date/out_date`，
按 `in_date <= as_of_date < out_date` 读取，空 out_date 表示未剔除。
不使用最新归属倒填其他日期；数据观察时间单列，不宣称具备历史 PIT 认证。

行业采集与归一化入口分别是 `raw.tushare.fetchers.industry.fetch_industry` 和
`ingest.tushare.industry.normalize_industry`；它们不写业务库。
`write_industry_snapshot` 要求调用方已开启发布事务，按预期归属比较后写入，不自行提交。
三张行业表的 ownership 变动会全局标脏，因此必须在同一事务重签全部基础组成及风险头、发布新版本；
不能将行业写入与发布拆成独立提交。发布重放应在写入前检查原版本与清单一致性，避免触发无谓失效。

| 核心输入 | 本批核查范围 | 可用边界 |
| --- | --- | --- |
| 申万一级行业 | 2026-11-05 已准入证券清单；31 个行业、5224 个目标日归属 | 全清单目标日无分类缺项；其他日期需重新验证 |
| 主数据、日历、日线与复权、停复牌、估值及资产分类 | 重用已有窗口验收证据，并重新核对范围指纹 | 停牌、缺价、上市不足或滞后估值继续逐项披露，不填值 |
| 历史波动率与相关性 | 三股回归组合各 252 个有效收益；独立标准差及相关矩阵复算 | 不代表任意组合都满足共同样本数门槛 |
| 米筐 v2 三项预测风险 | rqdatac 3.8.1 单日五件套与旧原件比较，轴显式对齐 | 行业哑变量 dtype 可随样本推断为整数；列顺序不能当作固定因子轴 |
| ROE、风险贡献与 L3 | 后续批次 | 本批不新增准入 |
| Beta、L4、模型相关性、风格暴露与回放 | 尚未开放 | 保持 unavailable，不由行业接入自动开放 |

本批新发布仍为 2026-11-05 数据，追平和日更属于后续批次。正式可用日期始终以 `/options` 为准。
更新后旧发布可因输入修订失效，但历史快照的计算产物保留，不能把其结果日期自动替换为新版本日期。
