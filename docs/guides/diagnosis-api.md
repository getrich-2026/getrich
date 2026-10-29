# 持仓诊断 API 调用指南

面向诊断页面开发者与接口使用者，说明当前调用流程与状态。字段以 `/openapi.json` 和后端模型为准，交互文档见 `/docs`。

代码核对：2026-10-28，仅静态核对，未验证服务运行与数据库供数。新版设计尚未全部落地，差异见[待决问题](../plans/backlog.md)。

## 调用流程

统一前缀为 `/v1/diagnosis`，成功响应使用 `{code, message, data, timestamp, request_id}` 信封。

1. `POST /snapshots` 提交 `plans`，每项含唯一 `plan_id` 与 `holdings: [{symbol, weight?}]`。方案内权重须全填或全省略，省略时去重后等权。调仓须显式传入 `intent`；两个及以上方案默认 `multi_portfolio`。
2. 按 `data.links.result` 读取数值，按 `data.links.report` 读取报告。查询参数 `user_level=retail|pro` 控制展示，默认 `retail`，切换不重算。
3. 按 `data.links.data_quality` 查看方案级缺失原因与覆盖率。可选 SSE 使用 `data.links.stream`，当前只发 `meta → complete`；`complete` 携带与 `/result` 相同的完整终态，收到后关闭连接。

每次新提交创建新快照；网络重试复用 `Idempotency-Key: <UUIDv4>` 请求头，同键异体返回 `409`。`user_level` 和 `idempotency_key` 不放在请求体中。

## 状态与展示

| 场景 | HTTP 状态与处理 |
| --- | --- |
| 提交快照 | 当前同步计算，新建返回 `201`，幂等重放返回 `200` |
| 读取结果、报告或数据质量 | 处理中返回 `202` 与 `Retry-After: 1`；终态返回 `200`，计算失败由 `run_status` 表达 |
| 请求错误 | 返回 `{request_id, error: {code, message, retryable, issues}}`；校验错误的 `issues[].path` 使用 JSON Pointer |

- **结果位置**：A–D 在各方案的 `section_a`–`section_d`，E 在顶层 `comparison`，压力测试在各方案的 `stress_scenarios`。
- **可用性**：区块状态为 `ready/unavailable/failed`，指标状态为 `ok/degraded/unavailable`。不可用指标没有 `value`，不得按 0 展示。
- **当前范围**：A 已有计算；B、C、D、压力测试及多方案比较返回未开放或口径未定的原因。
- **报告渲染**：百分比以小数返回，前端按 `format`、`decimals` 展示。

## 实现与限制的入口

- [响应模型](../../packages/gr-api/src/gr_api/schemas/diagnosis_response.py)
- [HTTP 行为](../../packages/gr-api/src/gr_api/routers/diagnosis.py)
- [报告组装](../../packages/gr-api/src/gr_api/services/diagnosis_presentation.py)
- [计算与幂等](../../packages/gr-api/src/gr_api/services/diagnosis.py)

设计取舍见[决策记录](../../.agents/brain/DECISIONS.md)：D-010（因子口径）、D-017（缺数据处理）、D-018（幂等与缓存）。
