# Frontend Signal 数据填充 TODO

## P0：最小展示闭环

- [ ] 整理一个策略的基础信息。
- [ ] 确认策略分类，如趋势、套利、均值回归、宏观配置。
- [ ] 准备一个策略作者用户。
- [ ] 整理策略标签。
- [ ] 整理策略日收益率或净值序列。
- [ ] 根据日收益率计算 `nav`、`cumulative_return`、`drawdown`。
- [ ] 聚合生成月度收益。
- [ ] 计算最新绩效快照的核心字段：
  - `total_return`
  - `annualized_return`
  - `max_drawdown`
  - `annualized_volatility`
  - `sharpe_ratio`
  - `win_rate`
  - `recent_1m_return`
  - `recent_3m_return`
  - `ytd_return`
- [ ] 整理信号触发记录。
- [ ] 将策略设置为公开策略：`access_tier = 0`。

## P1：信号详情与用户状态

- [ ] 为每条信号补充触发时刻行情快照。
- [ ] 为信号补充 `reason_detail` 指标快照。
- [ ] 创建测试用户。
- [ ] 创建用户已读记录。
- [ ] 创建用户执行反馈记录。
- [ ] 验证信号列表能返回 `is_read` 和 `is_executed`。

## P2：订阅与付费访问

- [ ] 定义会员套餐。
- [ ] 准备测试订单。
- [ ] 准备订单明细。
- [ ] 准备策略订阅记录。
- [ ] 准备一次性授权记录。
- [ ] 将策略改为非公开访问：`access_tier > 0`。
- [ ] 验证订阅用户可以访问策略和信号。
- [ ] 验证未订阅用户只能访问公开或延迟免费的内容。

## P3：推送配置与 WebSocket 过滤

- [ ] 准备用户全局推送设置。
- [ ] 准备策略级推送覆盖设置。
- [ ] 确认 `confidence_threshold` 范围在 0 到 1。
- [ ] 确认 `urgency_filter` 只包含 `normal`、`high`、`critical`、`low` 中的值。

## 数据导入注意事项

- [ ] 不要把未知值填成 `0` 或空字符串，优先保留 `NULL`。
- [ ] 价格、数量、成交额、成交量不能为负。
- [ ] `confidence` 和 `position_pct` 必须在 0 到 1 之间。
- [ ] 月份必须在 1 到 12 之间。
- [ ] 策略回测开始日期不能晚于结束日期。
- [ ] 订阅开始日期不能晚于到期日期。
- [ ] 信号类型、操作、方向、状态必须使用 schema 允许的枚举值。
