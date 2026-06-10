# db 层

## 结构
```
db/
  ddl/        建库 DDL，按文件名顺序执行（00_extensions → 70_ownership）
  migrations/ 增量迁移（同样按名排序，在 ddl 之后执行）
  archive/    历史 SQL（旧 frontend / legacy 后端 ClickHouse），只读留档，不执行
```

## schema
- `meta`：instruments, symbol_map, trading_calendar, future/option_contracts
- `market`：`<asset>_bar_1d` / `_1m`（TimescaleDB 超表）、adj_factor、daily_basic、valuation 等
- `realtime`：tick_buffer（短保留超表 + 压缩）
- `ops`：users, api_keys, etl_job_run, data_quality_check, schema_migrations,
  dataset_catalog, import_checkpoint, **table_ownership**
- `staging`：parquet_file 清单

## 迁移
```bash
getrich db migrate    # 应用未应用/已变更的 SQL，记账到 ops.schema_migrations（含 checksum）
getrich db status     # 查看 applied / pending / changed
```
幂等：每个文件用 `IF NOT EXISTS` / `DO $$ ... EXCEPTION` 包裹，可重复执行。
checksum 变化的文件会重跑（reapplied），故修改 DDL 须保证可重入。

## 改 schema 注意（铁律）
改 PG schema / 保留策略前需确认 blast radius 与回滚方式。canonical 列变更须同步
`src/getrich_data/common/contracts`。
