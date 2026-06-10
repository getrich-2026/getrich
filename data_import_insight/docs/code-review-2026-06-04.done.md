# getrich_data_import 代码审查报告

- **审查日期**：2026-06-04
- **审查范围**：`getrich_data_import` 子工程全部源码（约 2226 行）+ `sql/init/backend/*.sql` + `tests/*.py`（546 行）
- **审查方式**：独立第三方视角（code-review agent），实际运行 `pytest` / `ruff` 验证
- **审查者**：code-review agent
- **更新记录**：2026-06-04 追加「附录 A：SQL Schema 设计专项评估」（字段完备性 + 分表设计）

---

## 结论先行

| 项 | 结论 |
|---|---|
| 整体成熟度 | **约 30%** |
| 风险等级 | 🔴 High |
| 是否可进入"打通真实数据导入"阶段 | **不建议**，需先修复 Critical #1、#2 |
| `pytest` 结果 | 32 passed（属实，但全为纯内存逻辑） |
| `ruff check` 结果 | clean（属实） |

一句话：核心管道存在事务边界 bug（失败的 job 记录永远不落库）、SQL 降级路径会二次失败、关键路径零测试覆盖，当前不可进入真实数据导入阶段。

**测试覆盖说明**：32 个测试全部测试"安全的纯内存逻辑"，核心导入路径（pipeline、upsert、adapter 数据读取）一个测试都没有。"32 passed"给出的安全感是虚假的。

---

## 🔴 Critical（必须修复 —— 正确性 / 数据 / 架构问题）

### 1. Pipeline 事务边界错误：失败的 job run 记录永远不持久化

- **位置**：`orchestration/pipeline.py:85-126`
- **现象**：`import_bars` 和 `load_metadata` 都用 `engine.begin()` 包裹整个工作单元。`finish_job_run(failed)` 写在 `except` 块中，但仍在 `engine.begin()` 的事务范围内。异常 re-raise 后 `engine.begin()` 的上下文管理器触发 **ROLLBACK**，`finish_job_run` 的写入随之回滚。
- **风险**：数据导入失败时，`ops.etl_job_run` 和 `ops.data_quality_check` 中不留任何记录，运维/审计完全失去失败历史。ops 看板永远只会显示 success 或者空。
- **修复方向**：拆分为两个事务：外层事务（独立连接）仅负责写 job_run 记录，内层事务负责数据写入。

```
with engine.begin() as audit_conn:
    run_id = insert_job_run(audit_conn, ...)
try:
    with engine.begin() as data_conn:
        ...data work...
    with engine.begin() as audit_conn:
        finish_job_run(audit_conn, run_id, "success", ...)
except Exception as exc:
    with engine.begin() as audit_conn:
        finish_job_run(audit_conn, run_id, "failed", error=str(exc))
    raise
```

### 2. 30_compress_ca.sql 的"降级"路径仍依赖 TimescaleDB 专属函数，会二次报错

- **位置**：`sql/init/backend/30_compress_ca.sql:61-143`
- **现象**：注释声称"Apache license 下 continuous aggregate 不可用，降级为普通 materialized view"。但降级路径中的 `first(open, dt)` 和 `last(close, dt)` 是 TimescaleDB 的 `first(value, time)` / `last(value, time)` 聚合函数，在纯 PostgreSQL 环境下同样不存在。当 continuous aggregate 失败（触发 EXCEPTION 块）时，备用 `CREATE MATERIALIZED VIEW` 里的 `first()`/`last()` 也会失败，且二次异常没有被捕获。
- **风险**：任何纯 PostgreSQL 或 TimescaleDB Apache 版本环境下，`30_compress_ca.sql` 执行会失败，迁移/初始化中断。声称的"降级"实际上是无效降级。
- **修复方向**：降级路径中的 `first(open, dt)` 改为 `(array_agg(open ORDER BY dt))[1]` 或 subquery 取 first row，`last` 同理，彻底去掉对 TimescaleDB 扩展函数的依赖。

### 3. InsightSource.instrument_frame() 裸吞所有异常

- **位置**：`adapters/insight.py:94-95`
- **现象**：`try: raw = api.get_all_basic_info(...) except Exception: continue` 捕获全部异常后 `continue`，没有任何日志。
- **风险**：如果 index/future/option 任意一类数据获取出错，该类数据被静默跳过，`instrument_frame()` 返回部分或空的 DataFrame，下游 `symbol_map` 不完整，后续 `import_bars` 时 `attach_instrument_ids` 抛 `LookupError`——但此时报的是"symbol not in map"，掩盖了真正根因。
- **修复方向**：至少 `except Exception as exc: logger.warning(...); continue`。`frames` 列表为空时应抛异常或明确警告，而不是悄悄返回空 DataFrame。

### 4. 整个工程无结构化 logger，全部用 print()

- **位置**：`cli.py:66-122`（及 pipeline/adapter/service 层无任何日志）
- **现象**：CLAUDE.md 铁律明文禁止 `print()` 用于运维日志。cli.py 所有输出（含错误 `print(f"ERROR: {exc}", file=sys.stderr)`）全用 `print()`。
- **风险**：无法在生产/调度环境做日志聚合、告警过滤、级别控制。真实导入出问题时除 traceback 外无任何可观测性。违反项目架构规范。
- **修复方向**：在 `common/` 创建 `logger.py`，用标准 `logging`。pipeline 层在 job 开始/结束/每批写入发 INFO，adapter 层在跳过/异常发 WARNING。

### 5. _request_start / _request_end 生成 naive datetime 传给外部 API

- **位置**：`adapters/insight.py:320-328`
- **现象**：`datetime.combine(day, time(hour=9))` 无 tzinfo，传给 Insight SDK 的 `get_kline(time=[...])` 是 naive datetime。
- **风险**：若 SDK 将 naive datetime 解释为 UTC，请求时间段偏移 8 小时，早盘数据被截断（UTC 09:00 = 上海 17:00）。典型时区隐患，违反"禁止 naive/aware 混用"。
- **修复方向**：`.replace(tzinfo=ZoneInfo("Asia/Shanghai"))`。Insight SDK 时间参数语义需明确文档化。

---

## 🟠 Major（应当修复 —— 健壮性 / 性能 / 数据完整性）

### 6. 质量检查：NaN 值不触发 OHLC 规则

- **位置**：`quality/rules.py:33-39`
- **现象**：`df["high"] < df[["open","close","low"]].max(axis=1)` 在 `high` 为 NaN 时比较结果为 `False`，不会被标记为 bad_ohlc。实测确认。
- **风险**：带 NaN 的价格不会被质量规则捕获，会静默写入数据库（列允许 NULL），下游因子/策略产生无效值。
- **修复方向**：OHLC 检查前增加 `null_price = df[["open","high","low","close"]].isna().any(axis=1)` 单独上报，或归一化后 `dropna` 并记录丢弃数量。

### 7. factor_series 对每个 symbol 扫描所有 backward_factor Parquet 文件

- **位置**：`adapters/yinhe_parquet.py:204-212`
- **现象**：每次调用都遍历 `backward_factor/` 全部文件，逐一读 schema 找列，无缓存。`_normalize_bar_frame` 每处理一个 kline 文件就调一次。
- **风险**：12 个月度文件 × 5000 支股票 = 6 万次 Parquet schema 读取，全量导入 I/O 爆炸。
- **修复方向**：`__init__` 阶段一次性构建 `_factor_cache: dict[str, pd.Series]`（`@cached_property` 或懒加载），或按文件批量读取所有 symbols。

### 8. _upsert_symbol_map 使用固定临时表名

- **位置**：`orchestration/pipeline.py:133`
- **现象**：`tmp_name = "getrich_symbol_map_stage"` 固定名称（而 `upsert_dataframe` 已用 UUID）。
- **风险**：当前依赖 `pg_temp` 的 session 隔离侥幸安全，但若未来复用 connection/session 就会冲突。
- **修复方向**：改成 UUID 命名，与 `upsert_dataframe` 一致。

### 9. upsert_dataframe 返回值不准确

- **位置**：`load/postgres.py:65`
- **现象**：返回 `len(df)`（输入行数）而非实际写入行数。`ON CONFLICT DO NOTHING` 时仍返回 `len(df)`，虚报写入数。
- **风险**：`ops.etl_job_run.rows_written` 虚报，监控无法区分"全量新增"和"大量重复写入"。
- **修复方向**：使用 `conn.execute(...).rowcount`。

### 10. attach_instrument_ids 依赖数据库但放在 transform 层

- **位置**：`transform/bars.py:26`
- **现象**：接收 `Connection` 参数并查询 `meta.symbol_map`，属于 load 层操作，却放在 transform 模块。
- **风险**：违反 extraction → normalization → storage 分离原则，使 transform 层无法脱库测试。
- **修复方向**：移至 `load/postgres.py` 或 `orchestration/pipeline.py`，transform 层只做纯数据变换。

### 11. insight.py 的 adj_factor=1.0 对所有 1d bar 无差别赋值

- **位置**：`adapters/insight.py:283`
- **现象**：`out["adj_factor"] = 1.0 if freq == "1d" else None`。对期货、期权日线 bar 也赋 1.0，语义误导。
- **风险**：下游可能因 `adj_factor` 非 NULL 误以为已复权，错误使用。
- **修复方向**：仅对 stock/etf 赋 1.0，future/option/index 设为 None；或字段命名加注释说明"1.0 表示无复权调整"。

---

## 🟡 Minor（建议修复 —— 风格 / 维护性 / 隐患）

### 12. config/defaults.toml 未加入 .gitignore

- **位置**：`config/defaults.toml`
- **现象**：当前未提交，但 `.gitignore` 无对应规则。文件含默认凭据 `postgresql+psycopg://getrich:getrich@...`。
- **风险**：`git add .` 会把含凭据的配置提交进仓库历史。
- **修复方向**：`.gitignore` 加 `config/defaults.toml`，改用 `.example` 示例文件；或凭据行留空，强制 env var 覆盖。

### 13. yinhe_parquet.py 存在拼写错误键 EXTRA_IDNEX_A_SH_SZ

- **位置**：`adapters/yinhe_parquet.py:16`
- **现象**：`EXTRA_IDNEX_A_SH_SZ`（IDNEX）和 `EXTRA_INDEX_A_SH_SZ` 同时存在，均映射 `asset="index"`。
- **风险**：暗示上游文件名含拼写错误但未文档化；若上游修复则该条目变死代码、静默漏读。
- **修复方向**：加注释说明上游拼写错误；`_hist_path` 在目录不存在时发明确警告。

### 14. trading_calendar.py 对周末时间戳的错误信息无指导性

- **位置**：`services/trading_calendar.py:128-158`
- **现象**：`assign_trading_day` 在 `local_day` 是周末（不在 calendar 表）时直接抛 `TradingCalendarMissingError`，信息指向"missing row"而非"weekend timestamp"。
- **风险**：夜盘时间归属时若收到非交易日时间戳，错误信息对排障无帮助。
- **修复方向**：增加快速 fallback 路径，或异常信息说明"非交易日（如周末）也需在 meta.trading_calendar 中填充以支持夜盘归属"。

### 15. migrations.py 与 50_ops.sql 双重定义 ops.schema_migrations

- **位置**：`db/migrations.py` vs `sql/init/backend/50_ops.sql`
- **现象**：`_ensure_table()` 建最简表，`50_ops.sql` 建带索引/约束的完整版，二者都用 `IF NOT EXISTS`。
- **风险**：若 `migrate-schema` 先运行建了最简表，后续 `50_ops.sql` 因 IF NOT EXISTS 跳过，完整约束丢失。
- **修复方向**：`_ensure_table()` 与 `50_ops.sql` 表结构保持一致，或引导表只在 SQL 中处理。

---

## ✅ 做得好的地方

- **质量规则架构清晰**：`validate_bars` 返回 `list[QualityIssue]` 与副作用分离，`fail_on_error` 可配置。
- **BarsExtractionRequest 防御完整**：`__post_init__` 全字段规范化+边界检查，`frozen=True` 防突变，是全项目最健壮的模块。
- **SymbolMapService 批量查询**：`resolve_many` 用 `ANY(:source_symbols)` 一次查询，无 N+1。
- **TradingCalendarService 时区严格**：强制 aware timestamp，拒绝 naive，符合规范。
- **临时表 UUID 命名**：`upsert_dataframe` 用 `tmp_getrich_{uuid}`，防多进程冲突（`_upsert_symbol_map` 除外）。
- **SQL 参数化完整**：列名用 `qident` 包装，`comparator`/`ordering` 来自内部白名单枚举，无注入风险。

---

## 测试补充建议

32 个测试全是纯内存逻辑，未覆盖数据库交互和数据流通路径。建议补充：

1. **Pipeline 事务回滚测试**：模拟 import 失败，验证 `etl_job_run` 记录是否持久化（当前实现下不持久化，修复后应持久化）。
2. **upsert_dataframe 功能测试**：验证 INSERT、ON CONFLICT UPDATE、missing PK 列抛 ValueError。
3. **YinheParquetSource.bar_frames + calendar_frames**：用 `tmp_path` 构造最小 Parquet，验证时区、adj_factor、symbol 过滤。
4. **quality/rules.write_quality_issues**：验证 issues 正确写入 DB，`has_error` 逻辑。
5. **migrations.apply_migrations 幂等性 + checksum mismatch**：验证重跑不报错，SQL 改变后抛 ValueError。

---

## 验证命令

```bash
cd /home/quant/project/getrich-database/getrich_data_import

# 验证测试与 lint（已核实）
uv run pytest tests/ -v
uv run ruff check src tests

# 验证 30_compress_ca.sql fallback 使用了 TimescaleDB 专属函数
grep -n "first(\|last(" sql/init/backend/30_compress_ca.sql

# 验证 pipeline 事务边界问题
grep -n "engine.begin\|finish_job_run\|raise" src/getrich_data_import/orchestration/pipeline.py

# 验证 defaults.toml 未被 gitignore
git check-ignore -v config/defaults.toml
```

---

## 整体评价

**成熟度**：约 30%。骨架清晰，抽象层次设计合理（adapter/extract/transform/load/quality 分离方向正确），但 3 个核心风险未解决。

**最大的 3 个风险**：

1. **事务边界 bug（pipeline.py）** —— 任何导入作业失败都不会在数据库留下失败记录，运维完全失明。第一个要修。
2. **30_compress_ca.sql 的假降级** —— 声称能在 Apache License 环境降级，实际降级路径同样依赖 TimescaleDB 函数；真实 DB 上跑 `init-schema`/`migrate-schema` 高概率失败。
3. **关键路径零测试** —— pipeline、upsert、adapter 读数、transform 全无测试，"32 passed"是虚假安全感。

**是否可进入"打通真实数据导入"阶段**：不建议。至少先修复第 1、2 条 Critical，再做一次有真实 DB 的 smoke test（`init-schema` + `load-metadata` + 单个小数据集 `import-bars`），否则上线后第一次遇错就会丢失全部审计记录，且 schema 初始化本身就可能在非 TimescaleDB-Enterprise 环境失败。

---

# 附录 A：SQL Schema 设计专项评估

- **评估日期**：2026-06-04
- **评估对象**：`getrich_data_import/sql/init/backend/20_market.sql`（市场行情表）
- **对比基线**：`getrich-database/sql/legacy/backend/04_md_tables.sql`（legacy 统一 `md.bars_1m` / `md.bars_1d`）、`10_meta.sql`（元数据层）
- **回答的两个问题**：① 字段是否完备（尤其 `*_bar_1m`）；② "按标的分 bars_1m" 的设计是否好且必要

## A.1 现状事实

现有 `market` 层共 **6 张 bar 表 + 1 张希腊值表**：

```
market.index_bar_1d   market.index_bar_1m
market.future_bar_1d  market.future_bar_1m
market.option_bar_1d  market.option_bar_1m
market.option_greeks_1d
```

**完全没有 stock / etf 的 bar 表**，尽管 `meta.instruments` 的 CHECK 约束允许 `asset IN ('index','future','option','stock','etf')`。

设计形态：**按品类（asset class）分表**，表内用 TimescaleDB hypertable 按 `dt` 分 chunk、`instrument_id` 作复合主键一部分。**不是**"一合约一张物理表"。

---

## A.2 问题①：字段完备性

**总结：结构性"瘦身"是对的，但漏了几个"源头原始字段"，这是真问题。**

### A.2.1 正确砍掉的字段（赞同，勿加回）

| legacy 字段 | 新设计处理 | 评价 |
|---|---|---|
| `raw_symbol` | 归一到 `meta.symbol_map(source, source_symbol)` | ✅ 正确，符合 3NF，避免每行冗余 |
| `type` | 归一到 `instrument_id → meta.instruments.asset` | ✅ 正确 |
| `pct_chg` / `pct_chg_log` / `amplitude` | 删除 | ✅ **正确**。派生字段，按"数据层不嵌入计算/因子"边界本就不该落库 |

### A.2.2 漏掉的"源头原始字段"（建议补，按优先级）

均为数据源直接提供的 raw 字段、非派生量，缺失会导致下游无法还原或绕路：

| 缺失字段 | 缺在哪 | 严重度 | 为什么要 |
|---|---|---|---|
| `trading_status`（停牌标记 NORMAL/HALTED） | 所有 1d | 🔴 | 无法区分"停牌"与"成交量为 0 的正常日"，下游对齐/填充会出错 |
| `limit_up` / `limit_down`（涨跌停价） | 所有 1d（尤其 stock/index） | 🔴 | A 股 raw 提供；判断一字板、可否成交的关键，事后无法可靠重算 |
| `pre_close` / `pre_settle`（前收/前结算） | 所有 1d、1m | 🟠 | 可由上一交易日推，但跨除权/长假/首日上市易错；显式存为锚点更稳 |
| `adj_factor` | **所有 1m 表完全没有** | 🟠 | 1d 表有、1m 表无。分钟线后复权需 join 当日 1d 因子——可接受，但**必须在表注释写明该 join 路径**，否则是隐性陷阱 |
| stock / etf 的 bar 表 | 整个 market 层 | 🔴 | instruments 允许但无对应表。需明确决策：补 `stock_bar_1d/1m`，或文档写明"股票走 ClickHouse / 不入此库"。现为**静默缺口** |

### A.2.3 新增的好字段（赞同）

`trading_day`（显式交易日归属，夜盘必需）、`is_dominant`（主力标记）、`option_greeks_1d`（希腊值表）——legacy 没有的合理增强。

### A.2.4 类型选择

legacy 用 `DOUBLE PRECISION`，新设计改 `NUMERIC(20,6)`。**正确升级**——价格用定点数避免浮点漂移，代价是存储/计算稍重，对行情数据值得。

---

## A.3 问题②："按标的分 bars_1m" 的设计评估

**先澄清误读**：现有设计**不是**"每个合约一张表"，而是**按品类分 3 张表**（index/future/option），表内 TimescaleDB hypertable 按 `dt` 分 chunk、`instrument_id` 进复合主键。全市场几千合约共享一张表，**不是几千张表**。

### A.3.1 按品类分表 —— 好，且必要 ✅

| 理由 | 说明 |
|---|---|
| 列异构 | fut/opt 需 `open_interest`/`settle`，future 还要 `is_dominant`，index 都不需要。统一表会逼出大量"对 index 永远 NULL"的列 |
| 约束差异 | OI 非负约束只对 fut/opt 有意义，分表后约束更干净 |
| 查询局部性 | 实际查询几乎不会同时扫 index+future+option，分表避免跨品类扫描 |
| 分区/留存独立 | 每张 hypertable 可独立设 chunk interval、retention |
| 元数据对齐 | 天然对应 `future_contracts`/`option_contracts` 扩展表 |

代价仅 DDL 重复、跨品类查询要 UNION（极少）、ETL 按品类路由。**收益远大于成本，非过度设计。**

### A.3.2 ⚠️ 但"每个合约一张物理表"——坚决反对

若字面意图是 `rb2501_bar_1m`、`rb2505_bar_1m` 这种一合约一表，是**反模式**：

- 期货+期权合约成千上万 → 上万张表，catalog 膨胀、查询规划变慢；
- 无法做横截面查询（同一时刻全市场快照）；
- TimescaleDB 的价值正是让你无需这么做——hypertable 已在物理层按时间 chunk 切分，`instrument_id` 进主键后单合约查询有局部性，等于"逻辑一张表、物理自动分区"。

**现有设计正确地走了 hypertable 路线，保持现状即可。**

### A.3.3 可选小优化

1m 表主键 `(instrument_id, dt)`，但 hypertable 默认只按 `dt` 分 chunk。"单合约跨长区间"查询会扫多个 chunk。若此类查询频繁，可考虑加 `instrument_id` 的 space partitioning（hash 维度）或建 `(instrument_id, dt)` 覆盖索引。**非必须，看实际查询画像再定。**

---

## A.4 SQL 设计结论

1. **字段**：归一化和砍派生字段做得对；但漏了 `trading_status`、`limit_up/down`（🔴）、`pre_close/pre_settle`、1m 的 `adj_factor` join 路径（🟠），以及 **stock/etf bar 表整体缺失**（🔴 需明确决策）。
2. **分表**：按品类分 3 张表是好设计、必要且非过度设计；底层 hypertable + `instrument_id` 主键已实现"逻辑一表、物理分区"。**唯一要警惕的是别滑向"一合约一表"**，那才是错的。
