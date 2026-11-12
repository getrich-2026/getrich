# 持仓诊断 API 调用指南

面向后端接口使用者，说明独立于网页的调用方式、响应和启停。字段真源为 `/openapi.json`、[请求模型](../../packages/gr-api/src/gr_api/schemas/diagnosis.py)和[响应模型](../../packages/gr-api/src/gr_api/schemas/diagnosis_response.py)；设计 OpenAPI 不能替代实现。

状态（2026-11-12，Batch 3 本地增强批次）：新增056并按v3协议发布年度ROE及七项模型风险指标，日期仍为2026-11-05。仅后端与数据验收，常规诊断开关仍false；未部署远端、未修改前端。历史批次的说明以下文标注的协议边界为准。

## 已验收范围

- 日期 **2026-11-05**，米筐v2，原run `da212baf-9bfc-5014-8bff-0b574e8e7b9b`；不回退日期或模型。
- 发布版本 `diag-v3-20261105-enhanced-20261112-v1`，5224只沪深A股（上交所2318、深交所2906）。实际清单在 `/v1/diagnosis/options` 的 `data.publication_scope.security_ids`，应结合证券元数据解析；以发布清单为准，不把所有看似合法的代码自动纳入。
- 三项基础模型指标：`annual_variance`、`volatility.by_method.forward`（年化预测波动率）、`daily_prediction_volatility`。后两者都是小数，显示百分比时乘100；年化方差保持小数平方。
- v3另准入 `risk_contribution`、`risk_contribution_ratio`、`marginal_risk_contribution`、`l3_effective_count`。L4、模型相关性、风格暴露和回放仍不可用。年度ROE为个股辅助字段，不是模型风险指标。
- `calibrated=false`，指标状态为 `degraded/not_calibrated`：指定单日证券清单及准入指标的源值、单位和数值验收通过，全区间校准及P6尚未完成。不能解释为历史PIT或未准入风险指标已验收。
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
  "message": "success",
  "data": {
    "as_of_date": "2026-11-05",
    "data_fingerprint": "diag-v3-20261105-enhanced-20261112-v1",
    "publication": {
      "scope_type": "security_universe",
      "status": "available",
      "recomputable": true,
      "declared_metrics": [
        "annual_variance",
        "daily_prediction_volatility",
        "l3_effective_count",
        "marginal_risk_contribution",
        "risk_contribution",
        "risk_contribution_ratio",
        "volatility"
      ],
      "calibrated": false
    },
    "plans": [
      {
        "plan_id": "regression",
        "section_a": {
          "status": "ready",
          "value": {
            "industry_labels": {
              "801110.SI": "家用电器",
              "801120.SI": "食品饮料",
              "801780.SI": "银行"
            },
            "instrument_facts": {
              "status": "ok",
              "method": "exact",
              "value": {
                "30322": {
                  "industry_code": "801120.SI",
                  "industry_name": "食品饮料",
                  "roe": {
                    "status": "ok",
                    "value": 0.3253,
                    "method": "annual_roe_waa",
                    "confidence": "high"
                  },
                  "roe_report_year": 2025,
                  "roe_ann_date": "2026-04-17"
                },
                "30670": {
                  "industry_code": "801780.SI",
                  "industry_name": "银行",
                  "roe": {
                    "status": "ok",
                    "value": 0.1344,
                    "method": "annual_roe_waa",
                    "confidence": "high"
                  },
                  "roe_report_year": 2025,
                  "roe_ann_date": "2026-03-28"
                },
                "33509": {
                  "industry_code": "801110.SI",
                  "industry_name": "家用电器",
                  "roe": {
                    "status": "ok",
                    "value": 0.197,
                    "method": "annual_roe_waa",
                    "confidence": "high"
                  },
                  "roe_report_year": 2025,
                  "roe_ann_date": "2026-03-31"
                }
              }
            }
          }
        },
        "section_b": {
          "status": "ready",
          "value": {
            "annual_variance": {
              "status": "degraded",
              "value": 0.04532912929206873,
              "method": "forward",
              "reason_code": "not_calibrated",
              "reason": "本次单日范围与指标已准入；全区间未校准。",
              "confidence": "medium"
            },
            "volatility": {
              "primary": "forward",
              "by_method": {
                "forward": {
                  "status": "degraded",
                  "value": 0.21290638621720281,
                  "method": "forward",
                  "reason_code": "not_calibrated",
                  "reason": "本次单日范围与指标已准入；全区间未校准。",
                  "confidence": "medium"
                }
              }
            },
            "daily_prediction_volatility": {
              "status": "degraded",
              "value": 0.01341184167781401,
              "method": "forward",
              "reason_code": "not_calibrated",
              "reason": "本次单日范围与指标已准入；全区间未校准。",
              "confidence": "medium"
            },
            "risk_contribution": {
              "status": "degraded",
              "value": {
                "30322": 0.10786460518566776,
                "30670": 0.06255495706476022,
                "33509": 0.04248682396677483
              },
              "method": "forward",
              "reason_code": "not_calibrated",
              "reason": "本次单日增强指标已准入；全区间未校准。",
              "confidence": "medium"
            },
            "risk_contribution_ratio": {
              "status": "degraded",
              "value": {
                "30322": 0.5066292613488186,
                "30670": 0.2938143762439465,
                "33509": 0.1995563624072348
              },
              "method": "forward",
              "reason_code": "not_calibrated",
              "reason": "本次单日增强指标已准入；全区间未校准。",
              "confidence": "medium"
            },
            "marginal_risk_contribution": {
              "status": "degraded",
              "value": {
                "30322": 0.2696615129641694,
                "30670": 0.17872844875645777,
                "33509": 0.1699472958670993
              },
              "method": "forward",
              "reason_code": "not_calibrated",
              "reason": "本次单日增强指标已准入；全区间未校准。",
              "confidence": "medium"
            },
            "l3_effective_count": {
              "status": "degraded",
              "value": 2.6121743557259216,
              "method": "forward",
              "reason_code": "not_calibrated",
              "reason": "本次单日增强指标已准入；全区间未校准。",
              "confidence": "medium"
            },
            "model_date": "2026-11-05",
            "calibrated": false
          }
        }
      }
    ]
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
| 日期与发布日不同或请求越界指标 | 422，不回退；请求 `metrics` 必须属于当前 `/options` 的 declared_metrics；旧v1/v2仅三项，v3为七项 |
| 正权重证券无法解析、未在清单或缺同run风险输入 | 保留证券、原份额及原因，完整组合本次准入模型风险unavailable；不对覆盖子集重新归一化。没有可解析正权重标的时输入422 |
| 无凭证、无效或过期凭证访问私有诊断接口 | 401 unauthorized，使用标准诊断错误结构 |
| 已登录用户读取他人结果、报告、数据质量或重算 | 403 forbidden |
| 最新发布失效/无可用发布 | 新诊断503，不自动回退旧日期；历史产物仍可读，重算409 |

例如80%茅台加20%无法解析的888888.SH，实际返回 `model_coverage.covered_weight="0.8"`、`data_quality.plans[0].coverage_summary.risk_model=0.8`，缺失项 `{"symbol":"888888.SH","weight":"0.2","reason":"unresolved_symbol"}`，本次准入的完整模型风险均不可用且无value。不能把该请求解读为茅台100%的风险。

区块状态与指标状态分别判断：`ready/unavailable/failed` 与 `ok/degraded/unavailable`。`run_status=partially_succeeded` 可由未开放的C区等产生，不表示本次已准入的风险计算失败；只消费本次准入的指标及其status，不把其他字段推断为新增准入。不可用指标没有value，不能显示为0。

## 正式启用与回退

工作库055及本版发布已验收，用户已批准仅后端正式部署与启用。后续部署须先完成已批准的本地批次及审核；真实目标与上线状态在仓外维护。下列为已有版本的部署参考，不代表已部署。

正式部署时：

1. 发布仅已验收后端及依赖，包含注册必填列修复和gr-api显式依赖gr-signal的声明；后者在独立安装时验证为必需。使用锁定依赖的非editable安装（`uv sync --frozen --package gr-api --no-dev --no-editable`），不携带apps/web部署。先核对056唯一账本和新v3版本可用性，不再跑全目录迁移。
2. 在现有API运行环境设置 `GETRICH_DIAG_PUBLICATIONS_ENABLED=true`，保持 `GETRICH_ALLOW_MOCK_AUTH=false` 及既有JWT配置，优雅重启既有API进程。
3. 用真实登录账号读options，确认最新日期、版本、动态证券清单和declared_metrics（v3七项）；调用三股样本复现1.3411841678%，验证不同用户的403及缺失持仓提示后再放通流量。
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
漏配即拒绝加载配置；各源必须为带hostname的http/https origin，prod拒绝包含任何本地源（localhost、127.0.0.1、::1），staging允许本地联调。mock认证仅允许dev。部署流程须检查 APP_ENV，库仍保留本地 dev 默认值。
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
| `A.instrument_facts.value.<id>.roe` | MetricValue，小数 | v3读取最近完整年度加权平均 ROE；报告年份 roe_report_year、公告日期 roe_ann_date；源缺失时不可用 |
| `B.annual_variance` | MetricValue，年化小数方差 | 不作为百分比转换 |
| `B.volatility.by_method.forward` / `daily_prediction_volatility` | MetricValue，小数波动率 | 前瞻年化 / 单日预测；百分比展示乘 100，年化天数见 annualization_days |
| `B.instrument_betas.value[]` | instrument_id 与指标对象数组 | historical_volatility 为逐股历史年化小数波动率；beta 和 benchmark_correlation 当前不可用 |
| `B.risk_contribution` / `risk_contribution_ratio` / `marginal_risk_contribution` | MetricValue，按 instrument_id 的字典 | v3已准入；分别为年化波动率贡献、贡献份额、边际贡献；前两项展示为百分点、百分比时乘 100 |
| `B.l3_effective_count` | MetricValue，数值 | v3已准入；存在负贡献时不能直读为独立股票数 |
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


## v3 增强协议与财务口径（Batch 3，2026-11-12）

056仅新增协议和保护能力，迁移本身不改变旧发布的有效性。v1/v2仍按原三指标与基础组成校验；
v3新增 `fundamental.indicator_q` 组成，风险准入按同run、同证券清单、协议版本独立登记。
写入新数据和新增准入后，旧版本按现有机制失效，历史计算产物仍可读，不改写旧快照。

年报数据取 Tushare `fina_indicator_vip`，与 `fina_indicator.roe_waa` 同字段语义，
按年度100行分页保留原始公告及修订。入库唯一将源百分数除100，保留真实零值及负值，缺失不补零。
单位核验对应[公司2024年年报摘要](https://www.moutai.com.cn/mtgf/articleFileDir/2025-04/08/a8931897311b4d4097b7c0b2bf3207d1.pdf)的加权平均ROE百分数表。
只取完整年度12月31日、公告日不晚于诊断日期且观察时间不晚于发布时刻的记录；
按报告期降序、同报告期公告日降序选择。当前接纳2025/2024年度，未提供可用值时明确不可用，
不回退单季度、TTM或年化ROE，不计算组合平均ROE。source_revision保留供应商update_flag，
不将其冒充独立的历史可得时间；本次观察不能认证历史PIT。

设 `Σ` 为同模型同日期年化小数协方差，`σ=sqrt(wᵀΣw)`：

- `risk_contribution[i] = w[i] * (Σw)[i] / σ`，合计为σ；显示波动率百分点时乘100。
- `risk_contribution_ratio[i] = risk_contribution[i] / σ`，非零波动时合计为1。
- `marginal_risk_contribution[i] = (Σw)[i] / σ`，单位为每一单位权重的年化小数波动率变化。
- `l3_effective_count = 1 / sum(risk_contribution_ratio[i]^2)`。

RC合计不是annual_variance；负贡献保留，存在负贡献时L3不能直接解读为独立股票数。
本批独立复算采用 rtol=1e-12、atol=1e-15；REAL风险列按二进制读取，避免文本往返改变精度。
零波动时RC、占比、MRC、L3不可用；缺任一正权重证券的模型输入时不对子集重新归一化。
RC/L3准入路径跳过L4正交化计算，未开放能力不增加请求耗时。

行业日更写入会先用已校验源闭区间收口旧行，再写新有效区间；源区间本身重叠则拒绝。
无实质变化的成员行不更新available_at和updated_at；未收到可靠调出日期时不猜测收口。
本批仅修复并验证该写入能力，未启用定时采集或日更调度。


## 两阶段日更（运维入口）

适用已完成初始验收的沪深 A 股诊断库。使用 `gr-data diagnosis-daily` 前台执行有限日期范围，
调度及真实连接配置放仓外；不需要额外队列、服务或新迁移。常规 API 发布开关默认仍为 false。

```bash
# 阶段A：供应商采集、归一化及预检，仅只读访问PG
uv run gr-data diagnosis-daily prepare --day 2026-11-06 --artifact <ARTIFACT_DIR>
# 阶段B：只读取固定产物，一次事务完成入库、12项基础收据、风险准入和v3发布
uv run gr-data diagnosis-daily apply --artifact <ARTIFACT_DIR>
# 自动逐个交易日推进；缺数或失败即停止后续日期
uv run gr-data diagnosis-daily run --start 2026-11-06 --end 2026-11-12
uv run gr-data diagnosis-daily status
```

产物默认位于 `$RAW_PARQUET_ROOT/diagnosis/daily/<日期>`；单日命令可显式指定仓外目录。
`prepared.json` 固定源码提交、原件和canonical哈希、上一发布、输入指纹及归属；`status.json`
记录失败阶段和原因。生产导入要求源码及DDL已提交；源码变更后未发布产物必须重新准备，不复用旧进程身份；已发布且有效的固定产物可零写重放。
跨隔离库验证可用 `prepare --reuse-raw <RAW_DIR>` 复制原件，但必须重新取得目标库基线。
风险原件全部候选的内部ID（含被排除项）必须与目标库一致；精简副本ID不同则拒绝复用，
应使用仅含Tushare原件的目录，让仓内入口为目标库独立采集风险观察。原件副本互不改写。

阶段A校验日历、日线/复权/估值、停复牌覆盖、SW2021来源区间、公告日财务增量及米筐v2命名轴、
单位、存储精度和覆盖门槛。缺日线须有同日全天停牌证据；未知行业缺行不能替代旧区间收口。
财务按明确 `ann_date` 查询，源 `start_date/end_date` 是报告期；空响应仍封存凭据。
ROE缺失不填零，现有年度数据与增量合并，公告日与实际观察时间分别保留。
新在市证券没有年度基线时，按证券定向补最近两年完整年报；同样过滤公告日，
不因公告早于上市日而遗漏年度ROE，也不将空响应当成零。

阶段B先核对基线，再在同一连接、同一外层事务和排他发布屏障内执行；已有导入器仅使用保存点，
不独立提交。事务内失败整笔回滚，旧发布保持有效。提交响应丢失时可再次apply核对固定发布，
不猜测提交结果。合法重复apply直接返回原发布，业务零写入。
新上市身份在只读阶段冻结候选ID，写入阶段锁定身份表并校验；新增ID序列允许失败留下空洞，
不得以连续ID作为业务语义。所有历史窗口及来源观察均随收据留证，不认证历史PIT或全区间校准。

当日风险run满足既有99.9%覆盖门槛且无未知边界/未映射证券时，自动准入完整五件套的在市证券；
个别缺暴露/特异风险的标的保留排除证据。持仓命中缺项时保留原权重，完整模型风险不可用。
新诊断最多允许滞后一个已完成交易日；过期、最新发布失效或日历不完整返回503，不回退旧版本。
历史快照保留产物并标记invalidated；依赖失效基础版本的重算返回409。

所有v3七项风险指标仍为 `calibrated=false`，`/result`、`/report`及`/data-quality`
按各自快照实际 `declared_metrics` 同步披露。旧三项快照保持原边界。风险贡献采用波动率贡献，
满足 `sum(RC)=sqrt(annual_variance)`；不是方差贡献。L4、回放、Beta等仍未准入。
