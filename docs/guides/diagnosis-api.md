# 持仓诊断 API 调用指南

面向后端接口使用者，说明独立于网页的调用方式、响应和启停。字段真源为 `/openapi.json`、[请求模型](../../packages/gr-api/src/gr_api/schemas/diagnosis.py)和[响应模型](../../packages/gr-api/src/gr_api/schemas/diagnosis_response.py)；设计 OpenAPI 不能替代实现。

状态（2026-11-10）：工作库定向055、新证券范围发布、新连接读回及真实TCP HTTP多用户验收通过。本轮交付仅后端API、迁移及数据发布；浏览器测试仅补充证据，现有apps/web改动保留待另审，未部署网页。用户已批准正式后端部署与启用；当前正式部署主机、服务进程和对外地址待明确，正式地址复验待此信息到位后执行，常规 `GETRICH_DIAG_PUBLICATIONS_ENABLED=false` 未改。

## 已验收范围

- 日期 **2026-11-05**，米筐v2，原run `da212baf-9bfc-5014-8bff-0b574e8e7b9b`；不回退日期或模型。
- 发布版本 `diag-v2-20261105-ashare5224-20261110-v1`，5224只沪深A股（上交所2318、深交所2906）。实际清单在 `/v1/diagnosis/options` 的 `data.publication_scope.security_ids`，应结合证券元数据解析；以发布清单为准，不把所有看似合法的代码自动纳入。
- 仅三项模型指标：`annual_variance`、`volatility.by_method.forward`（年化预测波动率）、`daily_prediction_volatility`。后两者都是小数，显示百分比时乘100；年化方差保持小数平方。
- `calibrated=false`，指标状态为 `degraded/not_calibrated`：指定单日证券清单及三指标的源值、单位和数值验收通过，全区间校准及P6尚未完成。不能解释为历史PIT或其他风险指标已验收。
- 清单内可自由组合与调权，无需逐组合发布。每个方案最多100原始行（含重复和零权重），每次1～5个独立方案。

## 认证和调用

所有诊断路径前缀为 `/v1/diagnosis`。成功信封是 `{code,message,data,timestamp,request_id}`。使用已有账号向 `POST /v1/auth/login` 提交 `email/password`，把返回的 `data.access_token` 作为 `Authorization: Bearer ...`。不同用户分别使用自己的token；正式使用保持 `GETRICH_ALLOW_MOCK_AUTH=false`。

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
| 他人或匿名读取有归属的结果、报告、数据质量或重算 | 403；使用另一个token不能取得原快照 |
| 最新发布失效/无可用发布 | 新诊断503，不自动回退旧日期；历史产物仍可读，重算409 |

例如80%茅台加20%无法解析的888888.SH，实际返回 `model_coverage.covered_weight="0.8"`、`data_quality.plans[0].coverage_summary.risk_model=0.8`，缺失项 `{"symbol":"888888.SH","weight":"0.2","reason":"unresolved_symbol"}`，三项完整模型风险均不可用且无value。不能把该请求解读为茅台100%的风险。

区块状态与指标状态分别判断：`ready/unavailable/failed` 与 `ok/degraded/unavailable`。`run_status=partially_succeeded` 可由未开放的C区等产生，不表示已验收的三项风险计算失败；只消费本次准入的指标及其status，不把其他字段推断为新增准入。不可用指标没有value，不能显示为0。

## 正式启用与回退

工作库055及本版发布已验收，用户已批准仅后端正式部署与启用。当前正式服务目标未明确，发布候选准备完成但尚未部署/改开关，未部署网页。收到部署目标后按下列步骤直接继续，保留原授权。

正式部署时：

1. 发布仅已验收后端及依赖，包含注册必填列修复和gr-api显式依赖gr-signal的声明；后者在独立安装时验证为必需。使用锁定依赖的非editable安装（`uv sync --frozen --package gr-api --no-dev --no-editable`），不携带apps/web部署。先核对055唯一账本和新版本可用性，不再跑全目录迁移。
2. 在现有API运行环境设置 `GETRICH_DIAG_PUBLICATIONS_ENABLED=true`，保持 `GETRICH_ALLOW_MOCK_AUTH=false` 及既有JWT配置，优雅重启既有API进程。
3. 用真实登录账号读options，确认日期、版本、5224清单和三指标；调用三股样本复现1.3411841678%，验证不同用户的403及缺失持仓提示后再放通流量。
4. 运行中发布失效应返回503，先核查真实数据和收据，不为恢复出数而回退日期或放宽coverage。

回退：撤下诊断新请求入口，将 `GETRICH_DIAG_PUBLICATIONS_ENABLED=false` 并优雅重启；如需应用版本回退，选兼容现有schema的后端版本。保留055、全部账本、新旧publication/receipt、已保存报告和验收证据，不自动删表/逆改账本/恢复覆盖当前库。需要数据库恢复时，先从逻辑备份恢复全新隔离库核对，再另审切换方案。

实现入口：[HTTP](../../packages/gr-api/src/gr_api/routers/diagnosis.py)、[读取与幂等](../../packages/gr-api/src/gr_api/services/diagnosis.py)、[固定版本读取](../../packages/gr-api/src/gr_api/services/diagnosis_publication.py)、[范围门禁](../../packages/gr-api/src/gr_api/services/diagnosis_scope.py)、[发布与收据](../../packages/gr-data/src/gr_data/diagnostic_publication.py)。迁移和工作验收见[实施计划](../plans/gr-data-reliability-implementation-plan.md#多用户-v1证券清单准入与工作库执行门槛2026-11-10)。
