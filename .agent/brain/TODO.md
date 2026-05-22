# GetRich — TODO

## 当前状态
后端 22 个 endpoint 已实现并连接 PostgreSQL 真实数据库（`frontend` schema）。前端 StrategiesPage 已对接真实 API，其余页面仍使用硬编码 mock 数据。认证使用 X-User-Id mock 头。

---

## P0（上生产前必须做）

- [ ] 替换 mock 认证为真实 JWT（`deps.py` + `settings.py` 加 JWT_SECRET/JWT_TTL + `user_sessions` 表 + `/auth/login` `/auth/refresh` 接口；完成后删 `VITE_DEMO_USER_ID` mock 拦截）
- [ ] Webhook HMAC 验签强制启用
- [ ] 新建 `strategy_trades` 表并实现 `GET /v1/strategies/{code}/trades`
- [ ] 接入 access control（`services/access.py` 占位未实现）

## P1（联调过程中可能踩坑）

- [ ] 前端页面 mock 数据替换为真实 API 调用（SignalDetail→getSignalDetail, StrategyDetail→getStrategyDetail）
- [ ] 完善 `users` 表 `display_name/avatar_url/bio` 字段读取（影响策略详情页 creator 展示）
- [ ] 补充 endpoint 6 年度回测细分字段 `max_drawdown/sharpe/trades by year`（当前填 0 占位）
- [ ] Redis 缓存（观察 PG 负载后再决定，热点 key 见 NOTES.md）

## P2（未来扩展）

- [ ] WebSocket 实时信号推送
- [ ] 用户登录注册接口（手机号 / 邮箱 / 微信）
- [ ] 文章模块 API（`articles` 表已建）
- [ ] 市场速递页面（MarketPage）对接后端——需先实现新闻/事件 API
- [ ] 知识库页面（KnowledgePage）对接后端——需先实现文章 API
- [ ] 工具模块 API（`tools` 表已建）
- [ ] 限流（rate limit）
- [ ] Cron 离线任务（刷新 strategy_performance_snapshot / subscriber_count）
- [ ] 生产部署（gunicorn + nginx + systemd）