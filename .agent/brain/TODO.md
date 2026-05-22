# GetRich — TODO

## 当前状态
MVP Web API 22 个 endpoint 已实现，mock 认证（X-User-Id 头），待替换为 JWT。

---

## P0（上生产前必须做）

- [ ] 替换 mock 认证为真实 JWT（`deps.py` + `settings.py` 加 JWT_SECRET/JWT_TTL + `user_sessions` 表 + `/auth/login` `/auth/refresh` 接口；完成后删 `VITE_DEMO_USER_ID` mock 拦截）
- [ ] Webhook HMAC 验签强制启用（`services/payment.py`；prod 环境未配置 `PAYMENT_WEBHOOK_SECRET` 应启动报错）
- [ ] 新建 `strategy_trades` 表并实现 `GET /v1/strategies/{code}/trades`（参考前端 `TradeRecord` 字段：entry/exit_signal_id, symbol, direction, entry/exit_price, pnl 等）
- [ ] 接入 access control（`services/access.py` 占位未实现；PG 中 `can_access_content()` / `can_access_strategies_bulk()` 已存在，JWT 落地后立即跟进，否则付费内容全裸露）

## P1（联调过程中可能踩坑）

- [ ] 确认 `user_sessions` 表在 goldmine 库中是否存在（JWT 实现前需核对）
- [ ] 完善 `users` 表 `display_name/avatar_url/bio` 字段读取（影响策略详情页 creator 展示，字段已在 schema，只是 service 层没 SELECT）
- [ ] 补充 endpoint 6 年度回测细分字段 `max_drawdown/sharpe/trades by year`（当前填 0 占位）
- [ ] Redis 缓存（观察 PG 负载后再决定，热点 key 见 NOTES.md）

## P2（未来扩展）

- [ ] WebSocket 实时信号推送
- [ ] 用户登录注册接口（手机号 / 邮箱 / 微信）
- [ ] 文章模块 API（`articles` 表已建）
- [ ] 工具模块 API（`tools` 表已建）
- [ ] 限流（rate limit）
- [ ] Cron 离线任务（刷新 strategy_performance_snapshot / subscriber_count）
- [ ] 生产部署（gunicorn + nginx + systemd）
