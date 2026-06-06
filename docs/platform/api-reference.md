# Web API 参考

> **本页由 Redoc 从 OpenAPI 规范自动渲染**。OpenAPI JSON 位于 [`reference/getrich.openapi.json`](https://github.com/getrich/getrich/blob/main/reference/getrich.openapi.json)（v1.1）。

## 交互式 API 浏览器

<iframe
  src="https://redocly.github.io/redoc/?url=https://raw.githubusercontent.com/getrich/getrich/main/reference/getrich.openapi.json"
  width="100%"
  height="900"
  frameborder="0"
  style="border: 1px solid var(--md-default-fg-color--lightest); border-radius: 0.5rem;"
></iframe>

> **如果 iframe 加载失败**：直接打开 <https://redocly.github.io/redoc/>，然后在 URL 字段粘贴 `https://raw.githubusercontent.com/getrich/getrich/main/reference/getrich.openapi.json`。

## 下载 OpenAPI 规范

- [JSON 源文件](https://github.com/getrich/getrich/blob/main/reference/getrich.openapi.json)
- [本地路径：`reference/getrich.openapi.json`](https://github.com/getrich/getrich/blob/main/reference/getrich.openapi.json)

## 基础信息

| 字段 | 值 |
|---|---|
| OpenAPI 版本 | 3.1 |
| 规范版本 | 1.1 |
| 基础 URL | `https://api.getrich.millerquant.com/v1` |
| 鉴权 | JWT Bearer（24h 有效）+ Refresh Token（7d 有效） |
| 时间戳格式 | ISO 8601，UTC+8（Asia/Shanghai） |
| 金额格式 | Decimal 字符串，4 位小数 |

## 端点分组

API 端点按职责分为 12 组：

| 分组 | 前缀 | 数量 | 说明 |
|---|---|---|---|
| 认证 | `/auth/*` | 4 | 登录、注册、刷新、登出 |
| 用户 | `/user/*` | 5 | 资料、订单、设置 |
| 策略 | `/strategies/*` | 8 | 列表、详情、订阅、归因 |
| 信号 | `/signals/*` / `/strategies/*/signals` | 6 | 列表、详情、执行 |
| 通知设置 | `/user/signal-settings/*` | 3 | 全局 + per-strategy |
| 订阅 | `/strategies/*/subscribe` 等 | 4 | 订阅、取消、支付 |
| 支付 | `/payments/*` | 3 | 订单、回调、对账 |
| 回测 | `/backtests/*` | 9 | 列表、创建、结果 |
| Sweep | `/sweeps/*` | 6 | 列表、创建、结果 |
| Walk-Forward | `/walk-forwards/*` | 6 | 列表、创建、结果 |
| Job | `/backtest-jobs/*` | 5 | 列表、详情、取消、SSE |
| 内容 | `/content/*` | 3 | artifact 下载 |

> 详细字段定义见 [OpenAPI 规范](https://github.com/getrich/getrich/blob/main/reference/getrich.openapi.json)（下载后用 Swagger Editor 打开）。

## SSE 实时事件

3 个 SSE 端点用于实时推送：

| 端点 | 用途 |
|---|---|
| `GET /backtest-jobs/{job_id}/events` | 推送某个 backtest job 的进度更新 |
| `GET /sweeps/{sweep_id}/events` | 推送 sweep 状态 |
| `GET /walk-forwards/{wf_id}/events` | 推送 walk-forward 状态 |

事件帧格式：

```
event: update
data: {"status": "running", "progress": 0.42, "updated_at": "2024-..."}
```

后端通过 PostgreSQL `LISTEN backtest_job_changed` 监听 DB 变更（见 [运维 / 监控](../operations/monitoring.md)，Phase 2 文档），延迟 < 10ms。

## 鉴权

所有受保护端点需要 `Authorization: Bearer <access_token>` 头。

- **Access Token**：24 小时有效
- **Refresh Token**：7 天有效，可刷新 Access Token
- **401 响应**：access token 过期，客户端自动调用 `/auth/refresh`，重试原请求

详细流程见 [Web 前端](../platform/web-ui.md)（Phase 2 文档）。
