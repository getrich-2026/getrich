# TODO

更新时间：2026-06-10

## P0

- 已完成本地 schema 初始化、迁移、基础检查和 P0 核心 smoke。后续只保留回归验证，不再新增 P0 范围。

## P1

- 更新 PostgreSQL 17 + TimescaleDB 环境后的 schema verification 记录；精确 TimescaleDB patch 版本待命令确认。
- ~~RiceQuant P0/P1 开发前先做 `rqdatac` 安装和初始化 smoke：确认 license 环境变量、`id_convert`、`all_instruments`、`get_trading_dates` 和小样本 `get_price` 可用性。~~ (已完成)
- ~~实现 RiceQuant provider adapter：metadata、symbol map、trading calendar/trading day、少量 1d/1m sample bars、Parquet staging。~~ (已完成)
- 增加 canonical source policy，避免 RiceQuant 自动覆盖已有 INSIGHT/Yinhe 同区间 canonical bars；差异先入 DuckDB/人工核对，最终只选一条入库。
- 补齐 INSIGHT 交易日历导入验证，尤其是期货交易所日历。当前分钟线可在 staged parquet 自带完整 `trading_day` 时落库，但生产环境仍应优先依赖权威交易日历处理夜盘归属。
- 继续确认 `etf_redemption` 的 INSIGHT 参数或权限；当前仍未标记为 ready。
- 明确 OTC 公募基金 NAV 代码规范：裸代码、带交易所后缀，还是 source-qualified symbol。
- 交叉验证复权价来源：`get_kline(fq=)`、`stock_daily_basic.backward_adjusted_closing_price`、`stock_valuation`、`stock_adj_factor`。
- 增加 DuckDB 验证/快照产物记录；临时分析数据放 DuckDB，不污染 PostgreSQL canonical 表。

## P2

- 扩展 money flow、trade distribution、chip distribution、margin data。
- 设计并实现 Barra 因子长表导入。
- 设计财务报表和公司事件 PIT schema。
- 为 ClickHouse 25 设计 tick、逐笔、委托等高频长期存储 schema。
- 设计 RiceQuant `get_auction_info`、`get_open_auction_info`、`get_yield_curve` 对应 schema。
- 评估是否需要 source-qualified 长期对比表，或继续用 DuckDB 保存多源差异明细。

## P3

- 定义 realtime source protocol。
- 设计 Redis 实时缓冲和 ClickHouse 高频长期存储协作方式。
- 增加实时 K 线、tick、逐笔和委托流导入路径。

## Code Review Findings

- 生产级交易日历仍需补齐；当前分钟线 `trading_day` fallback 只解决本地样本导入，不替代完整日历。
- `etf_redemption` 仍是 planned，需要确认 INSIGHT 权限或参数。
- 复权价多来源尚未形成唯一可信口径。
- ClickHouse 25 只有环境信息和目标定位，还没有 schema 和导入实现。
- RiceQuant 历史 tick 和实时接口权限未验证，不能假设可长期回补。
- RiceQuant 处于试用期，不能假设大范围历史行情权限；INSIGHT 仍是主要行情来源。
- RiceQuant 真实 license smoke 通过，但账号提示约 11 天后到期；后续测试若失败需先排查 license 到期或权限变化。

### RiceQuant 适配器审查（2026-06-10，code-review agent）

审查范围：`adapters/ricequant.py`（新增）+ `registry.py` / `config.py` / `pyproject.toml`。结论：已修复完毕并合并。

🔴 阻塞性（已修复）：
- [x] #1 `ricequant.py:266` 分钟线时区 crash：`tz_localize("Asia/Shanghai")` 对已带 tz 的戳抛 `TypeError`，被 `except: continue` 吞掉导致 1m 数据静默全量丢弃。修法：先判 `ts.dt.tz is None` 再选 `tz_localize` vs `tz_convert`，复用 Insight 的 `to_shanghai_timestamp_series`。
- [x] #2 `ricequant.py:258` `source_symbol` 静默污染：`order_book_id` 列缺失时整 chunk 全部行被赋为 `chunk[0]`，多标的被错标为单一标识落库。修法：列缺失时 `logger.warning + continue`，禁止静默回退。
- [x] #3 `ricequant.py:267` 夜盘 trading_day 错误：`trading_day = dt.date` 一刀切，未对期货/期权夜盘用 `trading_date`，与 INSIGHT join 错行（违反架构文档 §8）。修法：`asset in {future, option}` 且有 `trading_date` 列时优先用之。

🟡 建议修复（已修复）：
- [x] #4 `ricequant.py:80` `calendar_frames` 的 `exchange` 硬编码 `"CN"`、`has_night=False`，与 Insight 按交易所粒度 schema 不一致，期货日历错误。
- [x] #5 `ricequant.py:108/161/200` `instrument_frame` 用 `order_book_id.split(".")[1]` 解析 exchange，期货代码（`IF2406` 无点号）得空串。应直接用 `all_instruments` 的 `exchange` 列（架构文档 §6）。
- [x] #6 `ricequant.py:49-52` `_init_api` 缺凭据时静默 `rqdatac.init()`，报错不提示该设哪些环境变量。建议加 `login_required` 配置。
- [x] #7 `config.py:46` `staging_dir` 定义了但全程未使用（数据直接内存 yield，无 Parquet 暂存）。要么落地 zstd+原子写，要么 docstring 注明为预留字段。
- [x] #8 `ricequant.py:248-250` `except Exception: continue` 的 warning 不带上下文（chunk/asset/freq/时间范围），无法定位失败批次。
- [x] #9 `ricequant.py:109` `instrument_frame` 用 `raw["symbol"]`（实为中文简称）填 `name`，命名易混淆，需注释。
- [x] #10 零测试覆盖：RiceQuant 无对应 `test_*` 文件（Insight 有）。#1/#2/#3 都是测试本应拦住的场景，需补单测（MagicMock 模拟 rqdatac）。

🔵 可选优化（已优化）：
- [x] #11 `ricequant.py:133-209` `future/option_contract_frame` 与 `instrument_frame` 重复调用 `all_instruments`，可缓存。
- [x] #12 logger 改用 `extra={}` 结构化字段。
- [x] #13 `ricequant.py:290` `adj_factor=1.0` 加注释说明是"未复权"。

### RiceQuant 适配器复审（2026-06-10，第二轮，code-review agent）

针对上述 13 项修复的复审，发现修复过程引入的回归与遗漏，已全部修复。验证：`ruff` All checks passed；完整测试套件 `pytest` 109 passed。

🔴 阻塞性（已修复）：
- [x] R1 单标的拉取静默丢数据：修 #2 时一刀切禁止 `order_book_id` 回退，但 rqdatac 单标的 `get_price` 本就不返回该列，导致 `len(chunk)==1` 时数据全量静默丢弃。修法：缺列分支内先判 `len(chunk)==1`，单标的安全回填 `chunk[0]` 继续，多标的才 warning+continue。

🟡 应修复（已修复）：
- [x] R2 `config.py` `Settings.load()` 漏接 `login_required`：dataclass 定义了但构建时没读，配置文件设 `login_required=false` 无效。修法：补 `login_required=bool(ricequant_raw.get("login_required", True))`。
- [x] R3 `calendar_frames` 交易所列表含错误实体：CNI/CSI 是指数编制商非交易所、XINE（上期能源，有夜盘）缺失。修法：移除 CNI/CSI、补 XINE（含 has_night）、加近似说明注释。

🔵 可选（已修复）：
- [x] R4 `ricequant.py:17` `SHANGHAI_TZ` 常量定义后未使用，已删除及多余 `ZoneInfo` import。
- [x] R5 `tests/test_ricequant_adapter.py` `import sys` 未使用（ruff F401），已删除。
- [x] R6 测试 #2 只断言 `len(frames)==0` 未验证 warning，已补 `caplog` 断言；并新增 `test_ricequant_single_symbol_no_order_book_id_column` 覆盖 R1 回归场景。

## 工程化

- 增加调度、失败续跑和 checkpoint 策略的生产化配置。
- 给普通物化视图补 refresh 策略。
- 增加 API/SDK 读取层，让其他程序稳定调用 PostgreSQL/TimescaleDB、DuckDB、未来 ClickHouse 数据。
- 明确本地数据库可重建阶段结束点；之后 schema 变更改走 additive migrations。
- 评估 import job 的 chunk/commit 边界是否需要提升为显式配置，便于生产回放和失败续跑。
