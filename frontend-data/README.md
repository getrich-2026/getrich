# GetRich frontend_signal 数据整理模板

这些模板用于整理 `sql/init/frontend_signal/` 需要的前端业务数据。

本目录不包含日净值或日收益率序列模板。日度序列请单独整理，后续可用于生成：

- `frontend.strategy_equity_curve`
- `frontend.strategy_performance_snapshot`
- `frontend.strategy_monthly_returns`

## 建议填写顺序

1. `01_strategy_base.csv`
2. `02_author_users.csv`
3. `03_categories.csv`
4. `04_tags.csv`
5. `05_strategy_tags.csv`
6. `06_signals.csv`
7. `07_signal_market_snapshots.csv`
8. `08_user_signal_reads.csv`
9. `09_subscription_permissions.csv`
10. `10_push_settings.csv`
11. `11_performance_snapshot_optional.csv`
12. `12_monthly_returns_optional.csv`

## 最小闭环

只想先展示一个公开策略时，必填：

- `01_strategy_base.csv`
- `02_author_users.csv`
- `03_categories.csv`
- `04_tags.csv`
- `05_strategy_tags.csv`
- `06_signals.csv`

并把 `01_strategy_base.csv` 中的 `access_tier` 填为 `0`。

## 字段约束提醒

- `confidence`、`position_pct` 必须在 `0` 到 `1` 之间。
- 价格、数量、成交额、成交量不能为负。
- 未知值不要填 `0` 或空字符串，保留为空。
- 日期建议使用 `YYYY-MM-DD`。
- 时间建议使用 ISO 8601，如 `2026-04-15T09:31:00+08:00`。
- 枚举值必须使用模板中说明的取值。
