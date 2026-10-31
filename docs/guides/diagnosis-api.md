# 持仓诊断 API 调用指南

面向诊断页面开发者与接口使用者，说明当前调用流程与状态。字段以 `/openapi.json` 和后端模型为准，交互文档见 `/docs`；`packages/gr-api/diagnosis-design.openapi.json` 是设计契约，不是实现导出。

代码核对：2026-10-31，单元、契约与一次性 PG18 集成测试通过；工作库只做过只读取数冒烟，未在工作库执行迁移 051 或启动服务。尚未落地的设计差异见[待决问题](../plans/backlog.md)。

## 调用流程

统一前缀为 `/v1/diagnosis`，成功响应使用 `{code, message, data, timestamp, request_id}` 信封。

1. `POST /snapshots` 提交 `plans`（1～5 个，每个最多 100 行原始输入），每项含唯一 `plan_id` 与 `holdings: [{symbol, weight?}]`。方案内权重须全填或全省略，省略时去重后等权。可选 `options` 选择行业体系、基准与统计区间，缺省取口径版本默认值。
2. 按 `data.links.result` 读取数值，按 `data.links.report` 读取报告。查询参数 `user_level=retail|pro` 控制展示，默认 `retail`，切换不重算。
3. 按 `data.links.data_quality` 查看方案级缺失原因与覆盖率。可选 SSE 使用 `data.links.stream`，当前只发 `meta → complete`；`complete` 携带与 `/result` 相同的完整终态，收到后关闭连接。
4. `POST /snapshots/{id}/recompute` 以 `{options, reset_to_default}` 基于原快照创建新快照，原快照不变。当前原数据版本无法证明未被修订，固定返回 `409 BASE_DATA_VERSION_UNAVAILABLE`（`retryable=false`），见下文限制。

每次新提交创建新快照；网络重试复用 `Idempotency-Key: <UUIDv4>` 请求头，同键异体返回 `409`。`user_level` 和 `idempotency_key` 不放在请求体中。

## 输入校验

| 情形 | 处理 |
| --- | --- |
| 已识别的北交所、已退市股票及 ETF 等非个股 | `422`，`issues[].path` 指向 `/plans/{i}/holdings/{j}/symbol`，`code=unsupported_asset`，需移除或修正 |
| 无法识别的代码 | 保留原始份额并计入覆盖率；方案没有可计算的已识别正权重标的时 `422` |
| 历史代码 | 当前代码查不到时按 `meta.symbol_map` 解析；新旧代码同时输入视为重复并合并 |
| 零权重或量化到 8 位小数后为 0 | 回显 `zero_weight`，不计入名义持仓数，也不参与计算 |
| `as_of_date` 早于最新发布数据日 | `422 feature_not_available`；晚于发布日时取最新发布日并回显 |
| `intent` 为 `rebalance_amount`／`rebalance_holding` | `422 feature_not_available`（调仓比较第二期开放） |
| `options` 选择未验证的行业体系或基准、选择回放起点或回放统计区间、区间晚于诊断日 | `422`，路径为 `/options/<字段>` |

## 状态与展示

| 场景 | HTTP 状态与处理 |
| --- | --- |
| 提交快照或重算 | 当前同步计算，新建返回 `201`，幂等重放返回 `200` |
| 读取结果、报告或数据质量 | 处理中返回 `202` 与 `Retry-After: 1`；终态返回 `200`，计算失败由 `run_status` 表达 |
| 请求错误 | 返回 `{request_id, error: {code, message, retryable, issues}}`；校验错误的 `issues[].path` 使用 JSON Pointer |

- **结果位置**：A–D 在各方案的 `section_a`–`section_d`，E 在顶层 `comparison`，压力测试在各方案的 `stress_scenarios`；实际使用的计算参数在顶层 `options`。
- **可用性**：区块状态为 `ready/unavailable/failed`，指标状态为 `ok/degraded/unavailable`。不可用指标没有 `value`，不得按 0 展示。
- **当前范围**：A 区出数；B、C、D 与压力测试为 `feature_not_available`；画像为 `spec_not_defined`，盲点均为「未能判断」。因此终态为 `partially_succeeded`。
- **A 区口径**：TopN 返回 Top1／Top3／Top5，以完整输入份额为分母；HHI、L1、L2 在已识别部分计算并按覆盖率降级（低于 0.95 降级、低于 0.80 不可用）。行业、市值、PB 分布保留 `unclassified`／`missing_or_invalid`／`non_positive` 档，只降级不判不可用。行业体系未验证时行业分布与最大行业为 `data_not_validated`；ROE 单位未核验，逐股为 `data_not_validated`。
- **报告渲染**：百分比以小数返回，前端按 `format`、`decimals` 展示。逐股估值（`instrument_facts`）目前只在 `/result` 中。

## 已知限制

- 诊断日期取 `diag.data_version` 最新一行的发布日；该表尚无自动发布流程（D-022），需人工推进。
- `diag.data_version.available_options` 尚无写入流程，行业体系与基准默认都按未验证处理。
- 重算在 D-022 2b 发布清单落地前一律拒绝。
- 部署前须执行迁移 051；它依赖 050，二者须一并提交。

## 实现与限制的入口

- [请求模型](../../packages/gr-api/src/gr_api/schemas/diagnosis.py)、[响应模型](../../packages/gr-api/src/gr_api/schemas/diagnosis_response.py)
- [HTTP 行为](../../packages/gr-api/src/gr_api/routers/diagnosis.py)
- [报告组装](../../packages/gr-api/src/gr_api/services/diagnosis_presentation.py)
- [取数、解析与幂等](../../packages/gr-api/src/gr_api/services/diagnosis.py)
- [纯计算模块](../../packages/gr-api/src/gr_api/diagnosis_calc/)

设计取舍见[决策记录](../../.agents/brain/DECISIONS.md)：D-010（因子口径）、D-017（缺数据处理）、D-018（幂等与缓存）、D-021（纯计算模块）。
