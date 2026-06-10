# Provider 归属规范（单表单一来源）

## 规则

**数据库内同一张目标表，只能由一个 provider 写入。** 行情表、元数据表、实时缓冲表同理。

理由：同一张表混入多个数据源会导致来源不一致、复权/口径冲突、难以追溯。强制单一来源后，
每张表的数据语义由其唯一 provider 决定，可追溯、可回放。

归属登记在 `ops.table_ownership`：

| 列 | 含义 |
|---|---|
| `target` | 目标表全名，如 `market.stock_bar_1d` |
| `provider` | 唯一写入方：`yinhe` / `ricequant` / `insight` |
| `channel` | 写入通道：`ingest`（批量入库）/ `stream`（实时） |
| `updated_at` | 最后变更时间 |

## 强制点

- **ingest**：每个 importer 在 `run()` 写库前调用 `OwnershipManager.claim(target, provider, channel='ingest')`。
  首次写入即登记；若该表已归属**另一** provider，抛 `OwnershipError`，拒绝写入。
- **stream**：handler 启动时调用 `claim_ownership()`（`channel='stream'`），同样的冲突校验。

## 操作方法

### 查看归属
```bash
getrich own list
```

### 转移归属（切换数据源）
切换某张表的数据源是**显式高风险操作**，两种方式：

```bash
# 1) 命令行直接登记（force）
getrich own set market.stock_bar_1d ricequant ingest

# 2) ingest 时带 --force-ownership（转移并立即写入）
getrich ingest ricequant --only stock_bar_1d --force-ownership
```

### 解除归属
```bash
getrich own release market.stock_bar_1d
```
解除后该表可被任意 provider 重新 claim（下次写入即重新登记）。

## 注意

- 转移归属**不会**自动清空旧数据。切换源前应确认是否需要 `TRUNCATE` 目标表，避免新旧来源数据混存。
- `meta.instruments` / `meta.symbol_map` 等元数据表也受归属约束。多 provider 并存时，
  通常指定一个**权威 provider** 负责元数据，其余 provider 只写各自的行情表，并通过
  `meta.symbol_map`（每个 provider 一行映射）解析 `instrument_id`。
- 归属变更会写 `updated_at`，并在日志中留痕。

## 相关代码

- `src/getrich_data/common/ownership.py` — `OwnershipManager`、`OwnershipError`
- `db/ddl/70_ownership.sql` — `ops.table_ownership` 表定义
