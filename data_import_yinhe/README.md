# GetRich Data Import

这个目录负责把 `yinhe_data_fetcher/data/` 下的 parquet 原始数据清洗后导入
`sql_script_sample/` 定义的 PostgreSQL 表。

## 框架设计

入口在 `import_script/`，核心分层如下：

- `config.py`: 读取数据库、raw data 目录、批大小、SQL 文件顺序。
- `raw_store.py`: 统一封装 parquet 路径、代码列表、复权因子矩阵索引。
- `importer.py`: importer 基类，负责判定 `full` / `incremental`、事务和批量写入。
- `db.py`: PostgreSQL schema 初始化、目标表检查、临时表 upsert。
- `importers/`: 每张目标表一个 importer，后续新增表只需要新增类并注册。

当前已支持：

| importer | 目标表 | raw 来源 | 导入策略 |
| --- | --- | --- | --- |
| `calendar` | `re.calendar` | `calendar/*.parquet` | 全量覆盖 |
| `symbol_mapping` | `re.symbol_mapping` | `hist_code_list/*.parquet` | 全量覆盖 |
| `rq_instruments_cs` | `rq.instruments_cs` | 股票代码列表 | 全量覆盖 |
| `rq_instruments_etf` | `rq.instruments_etf` | ETF 代码列表 | 全量覆盖 |
| `rq_instruments_indx` | `rq.instruments_indx` | 指数代码列表 | 全量覆盖 |
| `bars_1d` | `md.bars_1d` | `kline_day` + `backward_factor` + `hist_code_list` | 自动增量 |

`bars_1d` 是多 raw 表 join 的示例：日线提供 OHLCV，复权因子矩阵提供
`adj_factor`，历史代码表提供 `type`，并按单代码日线计算 `pre_close`、收益率、
对数收益率和振幅。

## 使用

在 `getrich_database/data_import` 目录下：

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml 的 database_url
python -m import_script scan
python -m import_script -c config.yaml init-schema
python -m import_script -c config.yaml plan
python -m import_script -c config.yaml run
```

也可以不写配置文件，直接使用环境变量：

```bash
export DATABASE_URL='postgresql+psycopg://user:password@127.0.0.1:5432/getrich'
python -m import_script run --mode auto
```

常用命令：

```bash
python -m import_script scan
python -m import_script -c config.yaml plan --mode auto
python -m import_script -c config.yaml run --only bars_1d
python -m import_script -c config.yaml run --mode full --only calendar
python -m import_script -c config.yaml run --dry-run --only bars_1d
```

## 全量 / 增量判定

`--mode auto` 是默认行为：

- full-replace importer 永远走全量覆盖，适合日历、代码映射、基础标的信息。
- incremental importer 如果目标表为空，自动走全量；否则按 watermark 走增量。
- `bars_1d` 的 watermark 是 `md.bars_1d.dt`，只导入 `dt > max(dt)` 的数据。

也可以强制指定：

- `--mode full`: 重新扫描 raw 数据并 upsert 全部记录。
- `--mode incremental`: 强制只按目标表 watermark 导入新增记录。

`full` 模式会先清空当前 importer 的目标表，再重新导入，避免 raw 中已经消失的记录残留。

## 新增 importer

1. 在 `import_script/importers/` 新建一个类，继承 `BaseImporter`。
2. 声明 `name`、`target_table`、`primary_keys`，有增量字段时声明 `watermark_column`。
3. 实现 `stream_frames(ctx, mode, since)`，分批 `yield pandas.DataFrame`。
4. 在 `import_script/importers/__init__.py` 的 `IMPORTERS` 里注册。

写库逻辑会自动把 DataFrame 列与目标表列对齐，并通过 PostgreSQL 临时表执行
`INSERT ... ON CONFLICT ... DO UPDATE`。
