# 后端 API 批次任务拆解

> 技术栈：FastAPI (Python 3.10+) · PostgreSQL 16 · Redis · Pydantic v2  
> 前提：数据库已按 `00_extensions.sql` → `13_indexes.sql` 顺序初始化完毕

---

## Batch 0 — 基础骨架（1-2 天）

> 所有后续 Batch 均依赖此批次，优先完成。

| 任务 | 内容 |
|------|------|
| **T0.1** 项目骨架 | 目录结构 `app/{routers,services,schemas,deps,core}`；`main.py` 注册路由；`config.py` 读取环境变量（DB_URL、REDIS_URL、SECRET_KEY 等） |
| **T0.2** 统一响应格式 | Pydantic 封装 `ApiResponse[T]`：`{"code":0,"data":...,"msg":"ok"}`；全局异常 handler 统一返回格式 |
| **T0.3** Auth 中间件 | JWT 解析 → `current_user: User \| None`；`require_auth` 依赖项；会话从 `user_sessions` 验证，revoked/expired 均 401 |
| **T0.4** AccessService | 封装 `can_access_content(user_id, tier, delay_free, published_at, strategy_id=None)` → 调用 PG 函数；Redis 缓存键 `access:{user_id}:{strategy_id}`，TTL 300s；批量版 `can_access_strategies_bulk()` 供列表页使用 |
| **T0.5** 分页工具 | `PageParams(page, page_size)`；`PagedData[T](items, total, page, page_size)` |
| **T0.6** 限流中间件 | Redis 滑动窗口；接口默认 60 req/min；支付回调接口 10 req/min |
| **T0.7** Code↔UUID 解析器 | `resolve_strategy(code_or_uuid)` → `UUID`；`resolve_signal(code_or_uuid)` → `UUID`；结果 Redis 缓存 `str:id:{code}`，TTL 3600s |

---

## Batch 1 — 策略只读接口（2-3 天，可与 Batch 2 并行）

> 全部为 GET，无写操作，可独立部署验证。

| 任务 | 接口 | 关键点 |
|------|------|--------|
| **T1.1** 分类列表 | `GET /strategies/categories` | 查 `strategy_categories`，按 `sort_order`；结果 Redis 缓存 `str:cats`，TTL 3600s |
| **T1.2** 策略列表 | `GET /strategies` | 过滤：`category_id, type, asset_class, risk_level, market, keyword`；排序：`order.field`（sharpe/annual_return/follower_count/published_at）+ `order.direction`；调 `can_access_strategies_bulk()`；Redis 缓存摘要 `str:summary:{id}`，TTL 60s |
| **T1.3** 策略详情 | `GET /strategies/{code_or_id}` | 调 `resolve_strategy()`；`can_access_content()` 控制 `detail_html` 字段是否返回；缓存 `str:detail:{id}`，TTL 30s |
| **T1.4** 净值曲线 | `GET /strategies/{id}/equity-curve` | 查 `strategy_equity_curve`；支持 `start_date/end_date` 过滤；按 `trade_date ASC` 返回 |
| **T1.5** 月度收益 | `GET /strategies/{id}/monthly-returns` | 查 `strategy_monthly_returns`；按 `year DESC, month DESC`；返回 `[[year, month, return], ...]` |
| **T1.6** 绩效快照 | `GET /strategies/{id}/performance` | 取 `strategy_performance_snapshot` 最新一条（`snapshot_date DESC LIMIT 1`）|
| **T1.7** 信号历史列表 | `GET /strategies/{id}/signals` | 分页；`type/action/status` 过滤；访问控制按 `signals.access_tier`；登录用户附带 `is_read/is_executed` |

---

## Batch 2 — 信号 & 用户状态接口（2-3 天）

| 任务 | 接口 | 关键点 |
|------|------|--------|
| **T2.1** 信号详情 | `GET /signals/{code_or_id}` | `can_access_content()`；返回 `signal_market_snapshot`；附 `is_read/is_executed` |
| **T2.2** 标记已读 | `POST /signals/{id}/read` | `INSERT INTO user_signal_reads ... ON CONFLICT DO NOTHING`；失效 Redis `sig:unread:{user_id}` |
| **T2.3** 标记执行 | `POST /signals/{id}/execute` | `INSERT ... ON CONFLICT DO UPDATE`；更新 `executed_price, executed_qty, executed_at, note` |
| **T2.4** 未读统计 | `GET /signals/unread-summary` | 按 `strategy_id` 分组统计未读数；结果 Redis 缓存 `sig:unread:{user_id}`，TTL 60s |
| **T2.5** 全局推送设置 | `GET/PUT /user/signal-settings` | 读写 `user_signal_settings`；`channels JSONB`，`urgency_filter TEXT[]`，`quiet_hours JSONB` |
| **T2.6** 策略推送覆盖 | `GET/PUT /strategies/{id}/signal-settings` | 读写 `user_strategy_signal_settings`；`enabled/channels/urgency_filter` 覆盖全局设置 |
| **T2.7** 信号全局列表 | `GET /signals` | 跨策略；`strategy_id[]` 过滤；分页；权限过滤 `access_tier` |

---

## Batch 3 — 订阅 & 支付接口（3-5 天）

> 含幂等回调，需重点测试。

| 任务 | 接口 | 关键点 |
|------|------|--------|
| **T3.1** 发起订阅 | `POST /strategies/{id}/subscribe` | 请求体：`plan_type(monthly/yearly)`, `payment_source(wechat/alipay/bank)`；创建 `orders + order_items(item_type='strategy_subscription')`；同时在 `user_strategy_subscriptions` 插入 `status='pending_payment'`；返回 `order_id + payment_source`（不返回 `payment_url`）|
| **T3.2** 取消订阅 | `POST /strategies/{id}/unsubscribe` | 更新 `user_strategy_subscriptions.status='cancelled'`, `cancel_reason`；不退款，当期可继续访问至 `expire_date` |
| **T3.3** 支付回调 | `POST /webhooks/payment` | 幂等：以 `payment_ref` 去重（`orders.payment_ref UNIQUE`）；成功后：`orders.status='paid'`；`user_strategy_subscriptions.status='active'`，计算 `expire_date`；失效 Redis `access:{user_id}:{strategy_id}` |
| **T3.4** 订阅状态查询 | `GET /strategies/{id}/subscription` | 返回当前有效订阅：`status, expire_date, auto_renew, plan_type` |
| **T3.5** 订单列表 | `GET /user/orders` | 分页；`status` 过滤；返回 `orders + order_items` JOIN |

---

## Batch 4 — WebSocket 信号推送（2-3 天）

| 任务 | 内容 |
|------|------|
| **T4.1** WS 连接管理 | `GET /ws/signals`；JWT 鉴权；连接注册到 `ConnectionManager`；会话元数据存 Redis Hash `ws:session:{user_id}:{conn_id}` |
| **T4.2** Redis Streams 消费 | 后台 Task 订阅 Redis Stream `signal:new`；反序列化消息，查询接收者列表 |
| **T4.3** 权限过滤广播 | 广播前调 `AccessService.can_access()`；仅向有权限用户推送完整内容；无权限用户推送摘要 + 解锁提示 |
| **T4.4** 心跳 & 重连 | 服务端每 30s 发 `{"type":"ping"}`；客户端应回 `{"type":"pong"}`；超时 90s 断开 |
| **T4.5** 信号发布触发 | 策略发布新信号时（管理后台接口或 cron 任务）写入 Redis Stream；WS 消费者广播 |

---

## 配套离线任务（D 系列）

| 任务 | 触发方式 | 内容 |
|------|----------|------|
| **D1** 绩效快照刷新 | 每日凌晨 02:00 Cron | 从 `strategy_equity_curve` 计算 sharpe/年化/最大回撤等，INSERT INTO `strategy_performance_snapshot` |
| **D2** 月度收益刷新 | 每月 1 日 01:00 Cron | 按月聚合 `strategy_equity_curve`，UPSERT `strategy_monthly_returns` |
| **D3** 统计计数刷新 | 每日凌晨 03:00 Cron | 刷新 `strategies.subscriber_count / follower_count / signal_count`（避免列表页 COUNT 聚合） |
| **D4** 过期订阅扫描 | 每日 00:30 Cron | 扫 `user_strategy_subscriptions.expire_date <= CURRENT_DATE AND status='active'`；`auto_renew=TRUE` 触发扣款；否则置 `expired` |
| **D5** 待支付订单清理 | 每小时 Cron | `orders.status='pending' AND expire_at < NOW()` → `status='cancelled'`；同步取消对应 `pending_payment` 订阅 |
| **D6** 会员到期扫描 | 每日 00:10 Cron | `user_memberships.expires_at < NOW() AND status='active'` → `status='expired'`；`auto_renew=TRUE` 触发续费 |

---

## 参考执行时间线

| 天数 | 工作 |
|------|------|
| Day 1-2 | Batch 0（骨架 + 基础设施） |
| Day 3-5 | Batch 1（策略只读接口） |
| Day 3-6 | Batch 2（信号 & 用户状态，与 Batch 1 并行） |
| Day 7-11 | Batch 3（订阅 & 支付） |
| Day 12-14 | Batch 4（WebSocket） |
| Day 15-16 | D 系列 Cron 任务 |
| Day 17 | 集成测试、性能测试（strategy 列表 bulk access check）、文档 |

---

## Redis 键速查

| 键 | 内容 | TTL |
|----|------|-----|
| `access:{user_id}:{strategy_id}` | 访问权限布尔 | 300s |
| `str:summary:{strategy_id}` | 策略摘要 JSON | 60s |
| `str:detail:{strategy_id}` | 策略详情 JSON | 30s |
| `str:cats` | 分类列表 JSON | 3600s |
| `str:id:{code}` | code → UUID 映射 | 3600s |
| `sig:unread:{user_id}` | 未读统计 JSON | 60s |
| `ws:session:{user_id}:{conn_id}` | WS 连接元数据 | 会话生命周期 |

---

## 接口鉴权一览

| 类型 | 接口示例 | 鉴权要求 |
|------|----------|----------|
| 公开只读 | `GET /strategies/categories` | 无需登录 |
| 可匿名 | `GET /strategies`, `GET /strategies/{id}` | 匿名返回受限字段，登录后返回完整字段 |
| 必须登录 | `POST /signals/{id}/read`, `GET /user/signal-settings` | 401 if not authenticated |
| 必须登录 + 有权限 | `GET /strategies/{id}/equity-curve` | 401 / 403 |
| 支付回调 | `POST /webhooks/payment` | HMAC 签名验证（非 JWT） |
| WebSocket | `GET /ws/signals` | JWT query param `?token=...` |
