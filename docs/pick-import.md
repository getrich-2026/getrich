# 选股标的池导入指南

本文讲怎么把基金经理在本地产出的**每日标的池**导进数据库。P0 阶段系统只做接收与展示，
**不校验选股逻辑本身**——池子对不对是策略的事，导入只负责「不让明显错的数据静默落库」。

设计依据：`getrich-design/strategy-signal/个股推荐_数据库设计_P0.md`。

> **术语澄清**：这里说的「信号」指选股策略产出的**每日标的池**（`pick.batch` / `pick.item`）。
> 择时策略的买卖信号（`app.signals`）目前**没有**导入 CLI，只能由 `gr-signal` 实时生产
> 或直接写 SQL。别把两者混为一谈。

---

## 1. 数据落在哪

| 表 | 内容 |
|---|---|
| `pick.batch` | 一次上传 = 一个批次，记 `trading_day` / `item_count` / `status` / `note` |
| `pick.item` | 该批次的每日**全量**快照，一行一只标的 |

`pick` schema **不在**连接池的 `search_path` 里，写 SQL 一律显式加前缀（`pick.item`）。

同一策略同一交易日只能有一个 `status='active'` 的批次（唯一索引 `uq_batch_active`）。
重传会把旧批次置 `superseded` 并**先删后插**——不是 UPSERT，因为重传的池子可能比原来少
几只，UPSERT 会把它们留成脏行。

## 2. 参考数据在哪

```
packages/gr-api/tests/fixtures/picks/strategy_picks_30d.csv        # 人可读，可直接丢给 CLI
packages/gr-api/tests/fixtures/picks/strategy_picks_30d.parquet    # 同样内容，走 Parquet 读取路径
packages/gr-api/tests/fixture_picks.py                             # 生成器，确定性可重跑
```

30 个交易日 × 20 只，代码是真实 A 股代码段格式，名称一律「模拟股 NN」，**不对应任何真实证券**。
数据形态刻意贴近真实上传习惯：首日给 `entry_date`（带入历史持仓）、之后留空让系统推算，
每天换 0–3 只制造出池／重新入池，`rank` 留几个空验证「系统不按行序推断排名」。

重新生成（同样的种子必然产出同样的字节）：

```bash
uv run python packages/gr-api/tests/fixture_picks.py
```

> **这两份是长表**：比导入契约多一列 `trading_day`，30 天的数据都在一个文件里。
> 直接丢给 CLI 会被当成同一天的 600 行，`symbol` 大面积重复而报错。用法见 §4.1。

## 3. 文件格式

`.csv` 或 `.parquet`，表头**必须**是下面 7 列中的若干个，多余列忽略并告警，列名大小写与
前后空格会被归一化。**只有 `symbol` 是必需的**。

| 列 | 必需 | 说明 |
|---|---|---|
| `symbol` | ✅ | 带后缀的完整代码，`^\d{6}\.(SH\|SZ\|BJ)$`，如 `600000.SH` |
| `symbol_name` | | 快照时点名称，超过 64 字符直接截断，不因名字太长让整批失败 |
| `entry_date` | | 入池日 `YYYY-MM-DD`。**留空则由系统推算**，见 §6 |
| `rank` | | 推荐排名，≥ 1。留空即 NULL，排序时落末尾；系统**不会**按行序补 |
| `score` | | 策略评分，量纲自定，跨策略不可比 |
| `suggest_weight` | | 建议权重，**小数不是百分数**：0.25 表示 25%，写 25 会被拒 |
| `reason_text` | | 入选理由，展示给订阅者 |

**文件一律按全列字符串读**，否则 `000001.SZ` 会被类型推断成整数、丢掉前导零。这是
`gr_tools.read_frame(all_string=True)` 保证的，自己写脚本生成文件时也要注意别让
Excel 把代码列转成数字。

入库时 `symbol` 会被拆开：`pick.item.symbol` 存**不带后缀**的裸代码（`600000`），
交易所存进 `exchange` 列且用 `SSE`/`SZSE`/`BSE`（**不是** `meta.*` 的 `XSHG`/`XSHE`/`XBSE`）。

## 4. 命令行导入

```bash
uv run gr-picks import --strategy <UUID 或 strategy_code> \
                       --trading-day YYYY-MM-DD \
                       --file <path.csv|path.parquet> \
                       [--dry-run] [--overwrite] [--allow-empty] \
                       [--uploaded-by <user UUID>] [--note "本期备注"] [-v]
```

| 参数 | 作用 |
|---|---|
| `--strategy` | 策略 UUID 或 `strategy_code`。策略必须已存在，且 `strategy_kind='pick'` 才会出现在选股接口里 |
| `--trading-day` | 池子归属的交易日 |
| `--file` | `.csv` 或 `.parquet` |
| `--dry-run` | 只预检不写库。**每次正式导入前先跑一遍** |
| `--overwrite` | 该交易日已有 active 批次时覆盖。不加就报 409——误选日期会不可逆地覆盖正确数据 |
| `--allow-empty` | 接受 0 行的池子，表示**确认当日空仓**。空文件更常见的原因是导错了，所以要显式声明 |
| `--uploaded-by` | 操作者 user UUID，可不填 |
| `--note` | 本期备注，会展示给前端 |
| `-v` | 打印 DEBUG 日志 |

退出码：`0` 成功（含 `--dry-run` 预检通过），`1` 有阻断错误或参数非法。

### 4.1 用参考数据跑一遍

长表要先切出某一天、去掉 `trading_day` 列：

```bash
uv run python -c "
import polars as pl
f = pl.read_parquet('packages/gr-api/tests/fixtures/picks/strategy_picks_30d.parquet')
f.filter(pl.col('trading_day') == '2026-08-11').drop('trading_day').write_csv('/tmp/picks_20260811.csv')
"

# 先预检
uv run gr-picks import --strategy STR_DEMO_STK_001 --trading-day 2026-08-11 \
    --file /tmp/picks_20260811.csv --dry-run

# 确认无误再写库
uv run gr-picks import --strategy STR_DEMO_STK_001 --trading-day 2026-08-11 \
    --file /tmp/picks_20260811.csv
```

成功输出长这样：

```
[validated] STR_DEMO_STK_001 2026-08-11 — 20 rows valid / 20 rows total (298ms)
  superseded an existing batch with 20 item(s)
```

状态有三种：`blocked` 有阻断错误未写库 / `validated` 预检通过但 `--dry-run` 未写库 /
`committed` 已落库。

### 4.2 空仓日

```bash
uv run gr-picks import --strategy STR_DEMO_STK_001 --trading-day 2026-08-12 \
    --file /tmp/empty.csv --allow-empty --note "本期无符合条件标的"
```

`item_count=0` 是合法状态，前端会显示成 `empty`，与「当天没上传」（`not_updated`）是
两种不同的空态，别混淆。

## 5. 函数接口

CLI 只是薄壳。脚本／notebook 里直接调：

```python
from gr_api.services.pick_import import import_picks_sync

result = import_picks_sync(
    strategy="STR_DEMO_STK_001",
    trading_day="2026-08-11",
    source=frame,          # .csv/.parquet 路径，或 polars / pandas DataFrame
    overwrite=False,
    allow_empty=False,
    dry_run=False,
)
print(result.status, result.batch_id, result.summary)
```

`import_picks_sync()` 自己开关连接池，**不要**在已经跑着事件循环的进程里调用它；
FastAPI 路由里请直接 `await import_picks(conn, ...)`（异步版，事务由调用方掌握）。

行级错误放在 `result.errors` 里返回而**不抛异常**，这样一次能把整份文件的问题都告诉用户；
结构性问题才抛（见 §7）。

## 6. 入池日是怎么定的

`entry_date` 那列留空时，系统按「连续在池」推算：

- 上一交易日的池子里**有**这只 → 继承它的 `entry_date`；
- 上一交易日**没有** → 今天就是新入池，取 `trading_day`；
- 上传方**显式给了** `entry_date` → 原样采用，`entry_date_source` 记 `provided`。

漏传某一天时（上一交易日没有 active 批次），系统**沿用**而不是重置——重置会静默破坏
历史且不可恢复。这种情况会往 `pick.batch.note` 追加一条系统提示，并在 CLI 输出里
打 WARN。

推算依赖 `meta.trading_calendar`（交易所用 `XSHG`）。日历缺当天的上一交易日时会退到
「扫全量历史找最近一条」，同时打 WARN——**看到这条 WARN 说明日历没灌全，要补**。

## 7. 校验规则与常见报错

只保留「不做就会 DB 抛异常」或「不做会静默产生错误数据」的检查。是否为合法交易日、
标的是否停牌退市、`rank` 是否连续、`symbol_name` 是否与代码匹配——**有意不查**，
出错后前端一眼可见。

**行级**（报错带 CSV 物理行号，表头是第 1 行，数据从第 2 行起）：

| 错误码 | 触发条件 |
|---|---|
| `required` | `symbol` 为空 |
| `invalid_symbol` | 不匹配 `^\d{6}\.(SH\|SZ\|BJ)$` |
| `duplicate` | 同一文件里 `symbol` 重复 |
| `out_of_range` | `entry_date > trading_day` / `suggest_weight` 不在 [0,1] / `rank < 1` |

**批次级**（直接失败，退出码 1）：

```
# 补传历史日期——会让后续所有日期的 entry_date 推算错乱，且从数据本身看不出来
[failed] out-of-order upload: strategy already has data up to 2026-08-11, refusing to import 2026-07-14

# 该交易日已有生效批次
[failed] an active batch already exists for 2026-08-11 with 20 item(s); pass overwrite=True to supersede it

# 长表没切片就直接导：trading_day 被当成未知列忽略，600 行里 symbol 大面积重复
[blocked] STR_DEMO_STK_001 2026-08-11 — 52 rows valid / 600 rows total
  WARN  ignored unknown column(s): trading_day
  ERROR row 22 [symbol] duplicate: duplicate symbol in this file
```

其它结构性失败：缺 `symbol` 列、空文件未加 `--allow-empty`、策略不存在。

## 8. 导入后怎么验

```bash
# 批次概览
psql -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" -c "
SELECT b.trading_day, b.status, b.item_count, COALESCE(b.note,'') AS note
FROM pick.batch b JOIN app.strategies s ON s.id = b.strategy_id
WHERE s.strategy_code = 'STR_DEMO_STK_001' ORDER BY b.trading_day DESC LIMIT 10"

# 某天的池子
psql -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" -c "
SELECT i.rank, i.symbol, i.symbol_name, i.score, i.entry_date, i.entry_date_source
FROM pick.item i JOIN app.strategies s ON s.id = i.strategy_id
WHERE s.strategy_code = 'STR_DEMO_STK_001' AND i.trading_day = '2026-08-11'
ORDER BY i.rank NULLS LAST"
```

或者直接打接口（前端看到的就是这个）：

```bash
curl -s "http://127.0.0.1:8001/v1/pick-strategies/STR_DEMO_STK_001/picks" | jq '.data.batch'
curl -s "http://127.0.0.1:8001/v1/pick-strategies/STR_DEMO_STK_001/trading-days" | jq '.data.list[:5]'
```

## 9. 前置条件清单

导入前确认这几件事，否则要么报错要么数据不完整：

1. **库已建**：`uv run gr-db migrate --target pg`（`pick` schema 来自 `034_pick.sql`）。
2. **策略已存在**且 `strategy_kind='pick'`——没回填这一列的策略不会出现在选股接口里。
3. **`meta.trading_calendar` 已灌**对应区间（`exchange='XSHG'`），否则入池日推算走退化路径。
4. **`meta.instruments` 已登记**这些代码，否则 `pick.item.instrument_id` 整批为 NULL。
   P0 允许为 NULL 不阻断，但效果跟踪上线前必须补。
5. `.env` 里的 PG 连接信息可用。

## 10. 相关文档与测试

前端怎么起见 [`frontend-dev.md`](./frontend-dev.md)。


```bash
# 假游标用例（不需要数据库）
uv run pytest packages/gr-api/tests/test_pick_import.py packages/gr-api/tests/test_picks_cli.py -v

# 打真库的端到端：用 30 天参考数据跑「导入 → 读接口」，跑完自己清理
GETRICH_TEST_PG=1 uv run pytest packages/gr-api/tests/test_pick_pg_integration.py -v
```
