# 选股标的池导入指南

面向每日标的池的策略维护者与数据开发者。本文说明当前 `gr-picks` CLI 与函数接口；所有命令从仓库根目录执行。

代码核对：2026-10-28，已核对源码、DDL 与测试并离线验证样例，未连接数据库。系统接收每日全量快照，不校验选股逻辑；写入 `pick.batch`／`pick.item`，与择时买卖信号 `app.signals` 分开。

## 1. 导入前准备

- 安装 workspace 依赖：`uv sync --frozen --all-packages`；根 `.env` 配好 `PG_*`，环境变量优先于文件。
- 确认目标库已执行 `uv run gr-db migrate --target pg`，策略已存在；示例中的 `STR_STK_001` 须替换为实际策略 UUID 或 `strategy_code`。
- 策略进入选股列表需 `strategy_kind='pick'`、`pub_status='published'`；默认列表还筛选 `run_status` 为 `paper`、`live` 或 NULL。导入器本身只检查策略存在，不强制这些展示条件。
- `meta.trading_calendar` 应覆盖对应区间，使用 `exchange='XSHG'`；缺日历会影响入池日推算，见第 4 节。
- `meta.instruments` 应登记完整代码与 canonical 交易所码；映射失败仅告警，`instrument_id` 留 NULL，不阻断导入。历史别名解析与关联回填仍有缺口，见[待决问题](../plans/backlog.md)。

## 2. 文件契约

支持 `.csv`、`.parquet`、`.xlsx`、`.xls`，**一个文件对应一个策略、一个日期的全量池子**。列名会去除首尾空格并转小写；未知列忽略并告警，只有 `symbol` 必填。

| 列 | 说明 |
| --- | --- |
| `symbol` | 6 位代码加 `.SH`、`.SZ` 或 `.BJ`，如 `600000.SH`；首尾空格和后缀大小写会归一化，不接受重复代码 |
| `symbol_name` | 快照名称，超 64 字符截断；留空时尝试用 `meta.instruments.name` 补齐 |
| `entry_date` | 入池日，建议 `YYYY-MM-DD`，不得晚于导入日；留空按第 4 节推算 |
| `rank` | 整数且 ≥ 1；留空为 NULL、排序时置后，不按文件行序补排名 |
| `score` | 有限数值，量纲由策略定义，跨策略不可比 |
| `suggest_weight` | `[0, 1]` 内的小数：`0.25` 表示 25%，不接受 `25` 或文本 `25%`；不校验全池权重之和 |
| `reason_text` | 入选理由 |

`score` 和 `suggest_weight` 会存库，当前选股展示接口不返回这两个字段。

### 读取注意事项

- CSV／Excel 在读取时按字符串解析；代码仍须存为文本，已丢失的前导零不会补回。
- Excel 必须恰有一个工作表，第一行是表头。日期单元格接受无时区的午夜值，如 `2026-10-26 00:00:00`；非零时间、时区或日期序号（如 `46321`）会报错。百分比单元格的底层值仍须为 `0.25`。
- Parquet 保留类型，筛选已知列后转字符串；已知列不接受 List／Struct 等嵌套数据，未知嵌套列仍忽略并告警。
- 超过 100,000 行使用 Parquet，不存普通 CSV。

入库后，`pick.item.symbol` 为裸代码（`600000`），`exchange` 为 `SSE/SZSE/BSE`，与 `meta.*` 的 `XSHG/XSHE/XBSE` 分开。当前解析器统一写 `asset_class='stock'`，不据代码判定真实资产类别，也不支持期货／期权代码。

## 3. 命令行导入

先预检，核对策略、日期、行数和告警，再去掉 `--dry-run` 正式写入。样例文件切片见第 8 节：

```bash
uv run gr-picks import --strategy STR_STK_001 --trading-day 2026-08-11 \
    --file /tmp/picks_20260811.csv --dry-run

uv run gr-picks import --strategy STR_STK_001 --trading-day 2026-08-11 \
    --file /tmp/picks_20260811.csv
```

| 参数 | 作用 |
| --- | --- |
| `--strategy` | 必填，策略 UUID 或 `strategy_code` |
| `--trading-day` | 必填，归属日期 `YYYY-MM-DD`；多日文件须先按日拆分，按日期升序导入 |
| `--file` | 必填，单日文件路径 |
| `--dry-run` | 连接数据库预检、推算入池日，但不写批次与条目；不是离线校验，也不保证后续写入必定成功 |
| `--overwrite` | 允许替换同日 active 批次；不能绕过历史日期限制 |
| `--allow-empty` | 接受有表头、0 行的池子，表示确认空仓；不等于接受无法解析的空白文件 |
| `--uploaded-by` | 可选，操作者用户 UUID |
| `--note` | 本期备注，供接口展示 |
| `-v`／`--verbose` | 启用 DEBUG 日志 |

### 结果与覆盖语义

| 状态 | 含义 |
| --- | --- |
| `validated` | 预检通过，未写入 |
| `committed` | 已提交入库，返回 `batch_id` |
| `blocked` | 有行级错误，整批不写入 |

正常退出码为 `0`；导入阻断或已捕获的文件／业务错误为 `1`；缺必填参数、未知选项等 argparse 参数错误为 `2`。结构性失败输出 `[failed]`，不返回上述结果状态。

同策略同日最多一个 active 批次。**小于最新 active 日期的导入一律拒绝，包括 `--overwrite`**。覆盖时在同一事务内将旧批次置 `superseded`、创建新批次、删除同日旧条目并插入全量新池；旧批次只保留元数据，不能从它恢复旧持仓。覆盖预检也须带 `--overwrite`；日志中的覆盖提示不代表已写入，以结果状态为准。

### 空仓日

```bash
printf 'symbol\n' > /tmp/picks_empty.csv
uv run gr-picks import --strategy STR_STK_001 --trading-day 2026-08-12 \
    --file /tmp/picks_empty.csv --allow-empty --dry-run
```

确认后去掉 `--dry-run`。`item_count=0` 对应 `empty`（确认空仓），没有对应批次才是 `not_updated`，两者不可混用。

## 4. 入池日推算

显式提供 `entry_date` 时采用该值，标记 `entry_date_source='provided'`；留空时标记 `derived`，按下表处理：

| 条件 | 处理 |
| --- | --- |
| 上一交易日有 active 批次，且标的在池 | 继承上一期入池日 |
| 上一交易日有 active 批次，但标的不在池（含确认空仓） | 取本次 `trading_day`，视为重新入池 |
| 上一交易日没有 active 批次，或无法确定上一交易日 | 查本期之前该标的最近一条历史记录，沿用入池日；没有历史则取本次日期 |

日历先查 `prev_trading_day`，缺失时改查日历中小于本期日期的最大开市日；两者都找不到才进入无法确定上一交易日的分支并告警。实际发生历史沿用时，CLI 输出 WARN，并将沿用提示追加到批次 `note`。

`product_entry_date` 以 `entry_date` 兜底；存在历史品种记录时取两者较早值，确保不晚于 `entry_date`。业务取舍见 [D-008](../../.agents/brain/DECISIONS.md#d-008)。

## 5. 函数接口

普通同步脚本可使用：

```python
from __future__ import annotations

from gr_api.services.pick_import import import_picks_sync

result = import_picks_sync(
    strategy="STR_STK_001",
    trading_day="2026-08-11",
    source="/tmp/picks_20260811.csv",
    dry_run=True,
)
print(result.status, result.batch_id, result.summary)
```

`source` 也接受 Polars／pandas DataFrame；`overwrite`、`allow_empty`、`uploaded_by`、`note` 与 CLI 对应。

`import_picks_sync()` 自行开关连接池，不能在已有事件循环中调用。FastAPI／异步 notebook 使用 `await import_picks(conn, ...)`；**异步版正式写入同样会调用 `conn.commit()`**，不要按“提交由调用方控制”使用，也不要混入无关的未提交操作。

行级错误保存在 `result.errors`；结构性问题抛异常。完整签名与行为见[导入实现](../../packages/gr-api/src/gr_api/services/pick_import.py)，参数解析与输出见 [CLI 实现](../../packages/gr-api/src/gr_api/picks_cli.py)。

## 6. 校验与排障

错误行号按解析后的记录计数，表头为第 1 行、数据从第 2 行开始；CSV 引号内的换行不增加记录行号，不能按文本物理行定位。

| 行级错误码 | 条件 |
| --- | --- |
| `required` | `symbol` 为空 |
| `invalid_symbol` | 代码格式不符 |
| `duplicate` | 归一化后的代码重复 |
| `invalid_date` | 日期无法解析，或带非零时间／时区 |
| `invalid_integer` | `rank` 无法解析为整数 |
| `invalid_number` | `score`／`suggest_weight` 不是有效数值，含 NaN／Inf |
| `out_of_range` | 入池日晚于导入日、权重超出 `[0, 1]` 或排名小于 1 |

结构性失败包括格式不支持、多工作表、已知列含嵌套数据、缺 `symbol` 列、未允许空池、策略不存在、乱序导入、同日已有批次却未允许覆盖。预检通过不替代正式写入时的数据库约束检查。

当前不校验是否开市、标的是否停牌／退市、排名是否连续或名称与代码是否匹配；导入成功不代表数据在业务上正确。

## 7. 导入后核验

在已配置连接的数据库客户端执行以下 SQL；根 `.env` 不会自动导出为 shell 变量。SQL 使用 schema 全限定名，`pick` 不在连接池默认 `search_path` 中。

```sql
-- 批次概览
SELECT b.trading_day, b.status, b.item_count, b.note
FROM pick.batch b
JOIN app.strategies s ON s.id = b.strategy_id
WHERE s.strategy_code = 'STR_STK_001'
ORDER BY b.trading_day DESC, b.batch_id DESC
LIMIT 10;

-- 单日池子；覆盖后仅保留当前条目
SELECT i.rank, i.symbol, i.exchange, i.symbol_name, i.instrument_id,
       i.score, i.entry_date, i.entry_date_source
FROM pick.item i
JOIN app.strategies s ON s.id = i.strategy_id
WHERE s.strategy_code = 'STR_STK_001' AND i.trading_day = DATE '2026-08-11'
ORDER BY i.rank NULLS LAST, i.symbol;
```

API 已启动时，可读取指定日期的池子与历史批次日期：

```bash
curl --fail --silent --show-error \
    'http://127.0.0.1:8001/v1/pick-strategies/STR_STK_001/picks?trading_day=2026-08-11' \
    | jq '.data.batch'
curl --fail --silent --show-error \
    'http://127.0.0.1:8001/v1/pick-strategies/STR_STK_001/trading-days' \
    | jq '.data.list[:5]'
```

`picks` 不传 `trading_day` 时取最新 active 批次；`trading-days` 只列有 active 批次的日期，不补出漏传日。

## 8. 模拟数据与测试

[参考 CSV](../../packages/gr-api/tests/fixtures/picks/strategy_picks_30d.csv) 与 [Parquet](../../packages/gr-api/tests/fixtures/picks/strategy_picks_30d.parquet) 均为 30 日 × 20 只的编造数据，日期只跳过周末，不代表真实交易日历；代码格式像 A 股，不代表真实证券。生成器见 [fixture_picks.py](../../packages/gr-api/tests/fixture_picks.py)，运行它会重写两份 fixture，不创建数据库策略。

**两份文件都是多日长表，不能直接作为单日池导入**：导入器会忽略 `trading_day` 列，将所有行按 CLI 指定日处理，最终因代码重复阻断。先切片，再按第 3 节预检：

```bash
uv run python - <<'PYCODE'
import polars as pl

frame = pl.read_parquet('packages/gr-api/tests/fixtures/picks/strategy_picks_30d.parquet')
frame.filter(pl.col('trading_day') == '2026-08-11').drop('trading_day').write_csv(
    '/tmp/picks_20260811.csv'
)
PYCODE
```

不连接数据库的导入／CLI 用例：

```bash
uv run pytest packages/gr-api/tests/test_pick_import.py packages/gr-api/tests/test_picks_cli.py -v
```

真库端到端测试仅在**隔离测试库**运行：先将 `PG_*` 指向该库并完成迁移，再显式开启。用例会写模拟策略和标的，且 UPSERT 交易日历；清理不恢复日历，不能在工作库执行。

```bash
GETRICH_TEST_PG=1 uv run pytest packages/gr-api/tests/test_pick_pg_integration.py -v
```

相关说明：[前端开发](frontend-dev.md)、[DDL 真源](../../packages/gr-db/src/gr_db/ddl/postgres/034_pick.sql)。
