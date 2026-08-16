# 架构

## 五层

| 层 | 职责 | 输入 → 输出 | 是否归一化 |
|---|---|---|---|
| `common` | 共享内核 | — | — |
| `raw` | 下载 | 供应商 SDK → `/opt/raw_parquet` parquet | 否（保留源语义） |
| `ingest` | 入库 | parquet → 归一化 → PostgreSQL | 是（canonical） |
| `stream` | 实时 | 行情流 → `realtime.tick_buffer` | 是 |
| `db` | 库管理 | DDL / 迁移 / 归档 | — |

**层优先、源其次**：顶层按职责分层，每层内部再按 provider（yinhe/ricequant/insight/tushare）切分。
新增数据源 = 在 raw/ingest 各加一个纵切片；改某层逻辑 = 只动一个横切片。

## 数据流

```
AmazingData(银河)  → raw/yinhe     → /opt/raw_parquet/yinhe/*     → ingest/yinhe     → PostgreSQL
rqdatac(米筐)      → raw/ricequant → /opt/raw_parquet/ricequant/* → ingest/ricequant → PostgreSQL
INSIGHT(华泰)      → raw/insight   → /opt/raw_parquet/insight/*   → ingest/insight   → PostgreSQL
Tushare Pro       → raw/tushare   → /opt/raw_parquet/tushare/*   → ingest/tushare   → PostgreSQL
INSIGHT/银河 实时   → stream/<provider> ───────────────────────────────────────────→ realtime.tick_buffer
```

raw 与 ingest 解耦：raw 只负责把数据原样落地，ingest 只消费 parquet。某些 provider 也支持
ingest 直连 SDK（跳过 raw），但默认走两段式以便回放与审计。

## 边界（铁律）

本仓库只做数据接入：provider 适配、抓取、归一化、质量校验、入库。
**不含**因子、回测、策略、交易决策。这些属于主 `getrich` 工程。

## 关键不变量

- 单表单一来源（见 conventions/provider-ownership.md）。
- 所有市场时间为 `Asia/Shanghai`（见 conventions/timezone.md）。
- raw 不改变源数据单位/口径；归一化规则在 ingest 显式实现。
- canonical 列定义集中在 `common/contracts`，与 `db/ddl` 严格对齐。
