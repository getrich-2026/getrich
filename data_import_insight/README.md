# getrich-data-import

设计版 GetRich 数据导入工程。它只负责把上游数据源归一化并写入 PostgreSQL/TimescaleDB 权威库，不依赖旧 `data_import` 或 `import_data`。

## 文档入口

- AI 工作记忆首读：`.agent/brain/PROGRESS.md`
- 稳定事实：`.agent/brain/INFO.md`
- 后续任务：`.agent/brain/TODO.md`
- 版本日志：`CHANGELOG.md`
- 项目 PRD：`docs/PRD.md`
- 项目架构：`docs/ARCHITECTURE.md`
- RiceQuant 导入架构：`docs/ricequant_import_architecture.md`

当前上游适配器：

- `yinhe`：读取 `yinhe_data_fetcher` 生成的 Parquet。`yinhe_data_fetcher` 继续作为独立下载项目存在，本工程通过目录和字段约定消费其输出。默认数据目录为 `/data`。
- `insight`：可选直接调用当前环境里的 Insight SDK，使用 `get_all_basic_info`、`get_trading_days`、`get_kline`。未选择该 provider 时不会加载 Insight SDK。
- `ricequant`：已注册 `rqdatac` provider，覆盖 metadata、symbol map、trading calendar、future/option contract、1d/1m bar、`id_convert` 和 `get_trading_periods` API 封装；source policy 仍待在 canonical load 层实现，INSIGHT 仍是主要行情来源。

## 已实现范围

- 设计版 backend DDL：`meta`、`market`、`realtime`、`ops` schema。
- 元数据导入：交易日历、标的、数据源代码映射。
- 行情导入：`kline_day` -> `market.{asset}_bar_1d`，`kline_min1` -> `market.{asset}_bar_1m`。
- 写入留痕：`ops.etl_job_run`。
- 质量校验：OHLC 关系、非负数、复权因子正数；`error` 级阻断并写 `ops.data_quality_check`。
- 幂等写入：基于目标表主键 `ON CONFLICT DO UPDATE`。

## 使用

```bash
cd getrich_data_import
uv sync

cp config/defaults.example.toml /etc/getrich/getrich-data-import.toml
# 编辑 database_url；yinhe 默认读取 /data

uv run getrich-import --config /etc/getrich/getrich-data-import.toml init-schema
uv run getrich-import --config /etc/getrich/getrich-data-import.toml migrate-schema
uv run getrich-import --config /etc/getrich/getrich-data-import.toml check-db
uv run getrich-import --config /etc/getrich/getrich-data-import.toml --provider yinhe scan
uv run getrich-import --config /etc/getrich/getrich-data-import.toml --provider yinhe load-metadata
uv run getrich-import --config /etc/getrich/getrich-data-import.toml --provider yinhe import-bars --asset index --freq 1d
uv run getrich-import --config /etc/getrich/getrich-data-import.toml --provider yinhe import-bars --asset index --freq 1m
```

环境变量 `GETRICH_IMPORT__DATABASE_URL`、`GETRICH_IMPORT__YINHE_DATA_DIR`、`GETRICH_IMPORT__INSIGHT_RUNTIME_PATH`、`GETRICH_IMPORT__INSIGHT_SYMBOLS`、`GETRICH_IMPORT__RICEQUANT_SYMBOLS`、`GETRICH_IMPORT__RICEQUANT_MARKET`、`GETRICH_IMPORT__PARQUET_EXPORT_DIR` 可覆盖配置文件。

Insight 示例：

```bash
uv run getrich-import --config /etc/getrich/getrich-data-import.toml \
  --provider insight load-metadata

uv run getrich-import --config /etc/getrich/getrich-data-import.toml \
  --provider insight fetch-dataset \
  --dataset stock_bar_1d \
  --start-date 2026-05-19 --end-date 2026-05-19 \
  --symbol 000001.SZ

uv run getrich-import --config /etc/getrich/getrich-data-import.toml \
  --provider insight load-dataset \
  --dataset stock_bar_1d \
  --start-date 2026-05-19 --end-date 2026-05-19 \
  --symbol 000001.SZ

uv run getrich-import --config /etc/getrich/getrich-data-import.toml \
  --provider insight import-bars \
  --asset future --freq 1m \
  --start-date 2026-05-19 --end-date 2026-05-19 \
  --symbol IF2406.CCFX
```

Insight 需要配置：

```toml
[insight]
runtime_paths = []
env_file = ""
staging_dir = "~/data/insight"
username_env = "INSIGHT_USER"
password_env = "INSIGHT_PASSWORD"
login_required = true
batch_size = 300
default_start_date = "2026-05-19"
default_end_date = "2026-05-19"
symbols = ["IF2406.CCFX", "000300.XSHG"]
```

RiceQuant 示例：

```toml
[ricequant]
staging_dir = "~/data/ricequant"
env_file = "../.env"
license_env = "RQDATAC_LICENSE"
init_mode = "tcp_license"
username_env = "RQDATAC_USER"
password_env = "RQDATAC_PASSWORD"
login_required = true
market = "cn"
batch_size = 300
default_start_date = "2026-05-19"
default_end_date = "2026-05-19"
symbols = ["000001.XSHE", "IF2406"]
```

## 边界

`yinhe_data_fetcher` 只负责下载 Parquet；本工程只负责导入数据库。旧 `data_import` 和 `import_data` 保持不动，不作为运行依赖。
