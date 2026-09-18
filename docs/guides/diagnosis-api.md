# 持仓诊断 API 调用指南

读者：接入诊断页面的前端开发者、接口使用者；Agent 修改接口时参考。
范围：当前调用流程与状态语义；请求／响应字段以运行应用的 `/openapi.json` 和后端响应模型为准。
代码核对：2026-09-08；本文不代表服务正在运行或数据库供数已达标。

统一前缀 `/v1/diagnosis`，成功响应仍使用项目的 `{code, message, data, timestamp, request_id}` 信封。
运行后可在 `/docs` 查看请求示例，在 `/openapi.json` 获取实际响应模型。

1. `POST /snapshots` 提交 `plans`，每项包含唯一 `plan_id` 与 `holdings: [{symbol, weight?}]`。
   权重要么全部提供，要么全部缺省；缺省时去重后等权。调仓意图须显式传入，
   两个及以上方案缺省为 `multi_portfolio`。
2. 使用返回的 `data.links.result` 读取数值、`data.links.report` 读取页面报告。
   处理中返回 `202` 与 `Retry-After: 1`；终态返回 `200`，业务失败由 `run_status` 表达。
3. `/report?user_level=retail|pro` 切换展示偏好，缺省 `retail`，不会重算。
   `/data-quality` 提供同一快照的方案级缺失原因与覆盖率。
4. `/stream` 提供可选 SSE。当前同步计算完成后订阅只发 `meta → complete`，
   `complete` 携带与 `/result` 相同的完整终态，收到后关闭连接。

每次新提交创建新快照；网络重试请复用 `Idempotency-Key: <UUIDv4>` 请求头。
同键异体返回 `409`。错误响应为 `{request_id, error: {code, message, retryable, issues}}`，
校验错误的 `issues[].path` 使用 JSON Pointer。`user_level` 和 `idempotency_key` 不放在 POST 请求体中。

A–D 在各方案的 `section_a`–`section_d`，E 在顶层 `comparison`；压力测试在方案顶层
`stress_scenarios`。区块状态为 `ready/unavailable/failed`，指标为 `ok/degraded/unavailable`，
不可用状态没有 `value`，不能当作数字 0。当前 A 使用已有计算，B/C/D、压力测试及多方案比较
明确返回未开放或口径未定的原因。报告提供有类型的指标卡、分布、输入持仓和文本组件，
数值保持机器可读，百分比用小数表示；前端按 `format`、`decimals` 展示。

## 实现与限制的入口

- 响应模型：`packages/gr-api/src/gr_api/schemas/diagnosis_response.py`。
- HTTP 行为：`packages/gr-api/src/gr_api/routers/diagnosis.py`。
- 报告组装：`packages/gr-api/src/gr_api/services/diagnosis_presentation.py`。
- 计算／幂等：`packages/gr-api/src/gr_api/services/diagnosis.py`。
- 尚未提供的计算与供数工作见 [待决问题](../plans/backlog.md)。
- 设计取舍见 [决策记录](../../.agents/brain/DECISIONS.md) D-010、D-017、D-018。
