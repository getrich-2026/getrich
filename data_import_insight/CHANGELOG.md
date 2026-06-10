# CHANGELOG

## v0.1.8 - 2026-06-10

- 补齐 RiceQuant `rqdatac` adapter API：`id_convert` 封装、`get_trading_periods` 交易时段帧、market 参数传递。
- 增加 RiceQuant 配置模板和环境变量覆盖：`env_file`、`license_env`、`init_mode`、`login_required`、`market`、symbols、默认日期等。
- 支持 RiceQuant `tcp_license` 初始化，并完成真实 license smoke：symbol 转换、metadata、calendar、股票日线样本和交易时段样本均通过。
- 增加 RiceQuant API 单元测试，覆盖 symbol 转换、market 传参、交易时段 schema 归一化和既有分钟线回归。
- 同步 README、ARCHITECTURE 和 brain 文档中的 RiceQuant 实现状态。

## v0.1.6 - 2026-06-09

- 整理文档结构：`.agent/brain/PROGRESS.md` 作为 AI 首读入口，`INFO.md` 记录稳定事实，`TODO.md` 记录 P0-P3 和 code-review findings。
- 将版本日志移到根目录 `CHANGELOG.md`。
- 记录当前数据库环境主版本：PostgreSQL 17 + TimescaleDB，ClickHouse 25。
- 新增项目级 `docs/PRD.md` 和 `docs/ARCHITECTURE.md` 入口文档。
- 新增 `docs/ricequant_import_architecture.md`，设计 RiceQuant provider、`rqdatac` smoke、Parquet staging、canonical source policy 和后续任务。
- README 增加 AI 工作记忆入口。

## v0.1.5 - 2026-06-08

- 启用 INSIGHT `stock_adj_factor` canonical transform 和 ready 状态。
- 修复 P1 区间数据过滤逻辑：`begin_date` 优先于 `end_date`，避免复权因子最后一期被错误过滤。
- 分钟线导入在交易日历缺失但 staged parquet 已有完整 `trading_day` 时，保留源交易日。
- 使用 `uv` 增加 `polars` 依赖。
- 完成 INSIGHT ETF、期货、期权小样本导入验证。
