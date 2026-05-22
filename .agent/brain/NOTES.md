# GetRich — 开发笔记

## 最近变更
- 2026-05-22: `reference/getrich_strategy_signal_design.md` v1.2 — 以 `reference/getrich.openapi.json` 为准，同步修复以下差异：
  - 数据流图 CH+PG → PG only（对齐"CH 只存行情"铁律）
  - 新增 6 个缺失端点（策略级信号列表、订阅状态查询、策略级推送设置 CRUD、用户订单、支付回调）
  - 修复章节编号：5.4 缺口、WebSocket 子节 6.x→7.x、前端页面 7.x→8.x
  - 更新技术栈：React 18→19、Zustand→移除、Redis 标记为 P1
  - 补充认证状态说明（JWT 定义但未强制）
  - 修剪超配响应字段（spread_std、basis、related_signals 等）
  - 附录 K 扩展为 22 个端点

## 关键决策
- 数据库 ETL（导入、清洗、网关接口等）部分彻底迁移至 `getrich-database/import_data` 项目，getrich 项目中完全删除 `apps/data` 目录及相关测试 `tests/test_export.py`, `tests/test_import.py`, `tests/test_rq.py`，使主业务与数据处理彻底解耦 — 2026-05
- 主业务库改为 PostgreSQL（goldmine），ClickHouse 仅保留时间序列行情数据 — 2026-04
- 不用 ORM，手写 SQL（直接调 PG 函数 / UPSERT / JSONB，少一层抽象）— 2026-04
- 响应包装用全局 dict + register_exception_handlers，不用 Pydantic response_model（字段量大且 schema 跟 SQL 紧耦合）— 2026-04
- 认证当前为 X-User-Id mock，`client.ts` 已准备 `Authorization: Bearer` 拦截器，JWT 落地后直接启用 — 2026-04

## 已知问题 / 技术债
- `apps/strategy/__init_.py` 文件名拼写错误（缺一个下划线），影响：strategy 模块 import 异常
- `GET /v1/strategies/{code}/trades` 返回空列表占位，`strategy_trades` 表未建
- access control 未接入，当前所有付费内容直接返回（JWT 落地前的临时状态）

---

## Web API 端点速查

| # | Method | Path | 认证 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/v1/strategies/categories` | 公开 | 分类列表 + strategy_count |
| 2 | GET | `/v1/strategies` | 可选 | 列表（filter+sort+page），登录后填 is_subscribed |
| 3 | GET | `/v1/strategies/{code}` | 可选 | 详情，登录后填 subscription_info |
| 4 | GET | `/v1/strategies/{code}/equity-curve` | 公开 | period=1m/3m/6m/1y/3y/all |
| 5 | GET | `/v1/strategies/{code}/monthly-returns` | 公开 | year×month[12] 矩阵 |
| 6 | GET | `/v1/strategies/{code}/backtest-report` | 公开 | summary/risk/trade/annual 四段 |
| 7 | GET | `/v1/strategies/{code}/trades` | 公开 | **占位**：表未建，恒返回空列表 |
| 8 | GET | `/v1/strategies/{code}/signals` | 公开 | 按 strategy 过滤的信号 |
| 9 | GET | `/v1/signals` | 可选 | 跨策略信号流 |
| 10 | GET | `/v1/signals/unread-summary` | 可选 | by_strategy + by_urgency |
| 11 | GET | `/v1/signals/{code}` | 可选 | 含 market_snapshot + historical_performance + user_state |
| 12 | POST | `/v1/signals/{code}/read` | 必须 | UPSERT user_signal_reads |
| 13 | POST | `/v1/signals/{code}/execute` | 必须 | 写 executed_price/qty/at/note，返回滑点 |
| 14 | POST | `/v1/strategies/{code}/subscribe` | 必须 | 创建 order + items + subscription(pending_payment) |
| 15 | POST | `/v1/strategies/{code}/unsubscribe` | 必须 | status→cancelled，access_until 持续到 expire_date |
| 16 | GET | `/v1/strategies/{code}/subscription` | 可选 | 订阅状态 + 定价 |
| 17 | GET | `/v1/user/signal-settings` | 必须 | 全局推送设置 + 策略覆盖列表 |
| 18 | PUT | `/v1/user/signal-settings` | 必须 | PATCH 语义，深合并 channels/quiet_hours |
| 19 | GET | `/v1/strategies/{code}/signal-settings` | 必须 | 策略级，未配置时继承全局 |
| 20 | PUT | `/v1/strategies/{code}/signal-settings` | 必须 | UPSERT user_strategy_signal_settings |
| 21 | GET | `/v1/user/orders` | 必须 | 订单列表 + 嵌入 items |
| 22 | POST | `/v1/webhooks/payment` | 无 | 以 payment_ref 幂等；success→激活订阅，refunded→取消 |

认证级别：**公开** 不传也能调；**可选** 传了返回个性化字段；**必须** 缺认证返回 `{code: 4010}`

---

## 启动 / 联调

### 后端

```bash
uv venv --python 3.12 .venv && uv pip install -e .
.venv/bin/uvicorn getrich.apps.web.main:app --reload --host 0.0.0.0 --port 8000
# Swagger: http://localhost:8000/docs
```

关键 `.env` 键：`PG_HOST` / `PG_USER` / `PG_PASSWORD` / `PG_DB=goldmine` / `WEB_CORS_ORIGINS=http://localhost:5173`

### 前端

```bash
npm install && npm run dev   # :5173
# VITE_API_BASE_URL=http://localhost:8000/v1
# VITE_DEMO_USER_ID=11111111-1111-1111-1111-111111111111
```

### 测试速查

```bash
BASE=http://localhost:8000/v1
UID="X-User-Id: 11111111-1111-1111-1111-111111111111"

curl $BASE/strategies/categories
curl "$BASE/strategies?page=1&page_size=5&sort=sharpe"
curl $BASE/strategies/STR_FUT_001/backtest-report
curl $BASE/user/orders -H "$UID"
curl -X POST $BASE/strategies/STR_FUT_001/subscribe -H "$UID" \
  -H 'Content-Type: application/json' -d '{"plan_type":"yearly","payment_source":"wechat"}'
```

---

## Redis 缓存规划（P1，未实现）

| Key | TTL | 命中点 |
|---|---|---|
| `str:cats` | 3600s | endpoint 1 |
| `str:summary:{strategy_id}` | 60s | endpoint 2 列表项 |
| `str:detail:{strategy_id}` | 30s | endpoint 3 |
| `str:id:{code}` | 3600s | resolver.code_to_uuid（高频热点） |
| `access:{user_id}:{strategy_id}` | 300s | access control |
| `sig:unread:{user_id}` | 60s | endpoint 10 |

---

## 关键文件索引

| 文件 | 说明 |
|---|---|
| `src/getrich/apps/web/main.py` | FastAPI 应用工厂 + lifespan |
| `src/getrich/apps/web/deps.py` | get_db / get_current_user / require_user / page_dep |
| `src/getrich/apps/web/response.py` | ApiResponse 包装 + 全局异常 handler |
| `src/getrich/apps/web/routers/` | 6 个 router，22 个 endpoints |
| `src/getrich/apps/web/services/` | 8 个 service 文件 |
| `src/getrich/libs/postgres/pool.py` | PG 异步连接池（psycopg3） |
| `src/getrich/config/settings.py` | PostgresConfig + WebConfig |
| `src/api/client.ts` | Axios 单例 + VITE_DEMO_USER_ID 拦截器 |

---

## shadcn/ui 组件清单

> 以下为 shadcn/ui CLI 初始化时的记录，用于参考组件清单和导入路径。

**环境：** Node.js 20, Tailwind CSS v3.4.19, Vite v7.2.4

**组件（40+）：**
accordion, alert-dialog, alert, aspect-ratio, avatar, badge, breadcrumb,
button-group, button, calendar, card, carousel, chart, checkbox, collapsible,
command, context-menu, dialog, drawer, dropdown-menu, empty, field, form,
hover-card, input-group, input-otp, input, item, kbd, label, menubar,
navigation-menu, pagination, popover, progress, radio-group, resizable,
scroll-area, select, separator, sheet, sidebar, skeleton, slider, sonner,
spinner, switch, table, tabs, textarea, toggle-group, toggle, tooltip

**导入示例：**
```ts
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
```
