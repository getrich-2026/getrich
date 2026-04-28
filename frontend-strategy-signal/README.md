# GetRich 前端业务数据库 — 初始化 SQL

面向前端"策略 + 信号"模块的全量 PostgreSQL 初始化脚本。按文件名数字前缀的顺序执行即可，所有业务对象会创建在 `frontend` schema 下。

## 执行顺序

```bash
# 假设数据库名为 getrich
for f in $(ls *.sql | sort); do
  echo "==> $f"
  psql -U postgres -d getrich -f "$f"
done
```

或按顺序：

| 顺序 | 文件 | 内容 |
|------|------|------|
| 00 | `00_extensions.sql` | `frontend` schema、`pgcrypto`（UUID）、`pg_trgm`（模糊搜索） |
| 01 | `01_users.sql` | 用户、认证、微信、会话、验证码 |
| 02 | `02_tags.sql` | 统一标签表（策略/文章共用） |
| 03 | `03_membership.sql` | 会员套餐 + 用户会员记录 |
| 04 | `04_strategies.sql` | 策略分类、策略主表、策略标签、关注 |
| 05 | `05_strategy_timeseries.sql` | 净值曲线、绩效快照、月度收益 |
| 06 | `06_signals.sql` | 信号批次、信号、信号行情快照 |
| 07 | `07_signal_user_state.sql` | 信号已读/执行、推送设置（全局 + 策略覆盖） |
| 08 | `08_orders.sql` | 订单、订单行项目 |
| 09 | `09_subscriptions_access.sql` | PayG 授权、策略周期订阅 |
| 10 | `10_articles.sql` | 文章、评论、点赞 |
| 11 | `11_tools.sql` | 工具、工具使用日志 |
| 12 | `12_functions.sql` | `can_access_content` 访问控制函数 + 批量版 |
| 13 | `13_indexes.sql` | 全部非主键索引 |

## 核心设计点

### 1. ID 策略
- **主键一律 UUID**（安全、唯一、无猜测风险）
- 对外展示的可读 ID 作为第二列：`strategies.strategy_code`（如 `STR_FUT_001`）、`signals.signal_code`（如 `SIG_20260415_001`）
- API 层可通过 `code` 或 `id` 任一查询，内部关联使用 UUID

### 2. 访问控制：三条并存路径
由 `frontend.can_access_content()` 函数统一判断，任一成立即可访问：

1. **内容公开**：`access_tier = 0`
2. **延迟免费到期**：发布 N 小时后对所有人开放
3. **用户会员 tier 足够**：`user.tier >= resource.access_tier`
4. **PayG 一次性授权**：`strategy_access_grants`（由订单触发）
5. **周期订阅有效**：`user_strategy_subscriptions`（monthly/yearly，对应前端 4.8）

列表场景请用 `frontend.can_access_strategies_bulk()` 批量版，避免在循环里一条条调。

### 3. 订阅模型
系统同时支持三种付费形态，互不冲突：
- **全站会员**（`user_memberships`）：tier 1/2/3，解锁对应 tier 的全部内容
- **策略买断**（`strategy_access_grants`）：一次付费、永久或限时
- **策略订阅**（`user_strategy_subscriptions`）：月/年自动续费

前端 `POST /strategies/{id}/subscribe` 应落在第三种，订单落在 `orders + order_items(item_type='strategy_subscription')`。

### 4. 时序数据全部在 PostgreSQL
原本设计稿里 ClickHouse 负责的时序表（净值曲线、绩效快照、月度收益、行情快照）现全部用 PostgreSQL：
- 量级上，单策略日度 × 10 年 = 2500 行，100 个策略 = 25 万行，PG B-Tree 完全够用
- 单表合理分区可选（按 `trade_date` 做 RANGE 分区），当前量级不急
- 所有表都有 `(strategy_id, date DESC)` 的聚簇索引

### 5. 已修复的老 SQL 问题
- `user_auth.user_id` 等从 `BIGINT` 改为 `UUID`（匹配 `users.id`）
- `tags.group` → `tag_group`（避开 SQL 保留字）
- 删除了 `strategies.backtest_report JSONB`，改用独立时序表
- 信号 `confidence` 从 `SMALLINT 1-5` 改为 `NUMERIC(3,2) 0.00-1.00`

### 6. 需要配套的离线任务（不在本 SQL 范围）
- 每日凌晨刷新 `strategy_performance_snapshot`（从 `strategy_equity_curve` 算出）
- 每月初刷新 `strategy_monthly_returns`
- 每日刷新 `strategies.subscriber_count/follower_count/signal_count`
- 订阅到期前 3 天扫 `user_strategy_subscriptions.expire_date` 做续费扣款

## 回滚

```sql
-- 按相反顺序 DROP（注意 CASCADE）
DROP TABLE IF EXISTS frontend.tool_usage_logs, frontend.tools,
  frontend.comment_likes, frontend.article_comments, frontend.article_likes, frontend.article_tags, frontend.articles,
  frontend.user_strategy_subscriptions, frontend.strategy_access_grants,
  frontend.order_items, frontend.orders,
  frontend.user_strategy_signal_settings, frontend.user_signal_settings, frontend.user_signal_reads,
  frontend.signal_market_snapshot, frontend.signals, frontend.signal_batches,
  frontend.strategy_monthly_returns, frontend.strategy_performance_snapshot, frontend.strategy_equity_curve,
  frontend.strategy_follows, frontend.strategy_tags, frontend.strategies, frontend.strategy_categories,
  frontend.user_memberships, frontend.membership_plans,
  frontend.tags,
  frontend.user_sessions, frontend.user_wechat, frontend.verification_codes, frontend.user_auth, frontend.users
  CASCADE;
DROP FUNCTION IF EXISTS
  frontend.can_access_content(UUID, SMALLINT, INT, TIMESTAMPTZ, UUID),
  frontend.can_access_strategies_bulk(UUID, UUID[]);
DROP SCHEMA IF EXISTS frontend;
```
