# 文档索引

getrich-database 规范与设计文档集中地。

## 架构
- [architecture.md](architecture.md) — 分层架构、数据流、各层边界

## 规范（conventions/）
- [naming.md](conventions/naming.md) — 目录/模块/表/列命名
- [timezone.md](conventions/timezone.md) — 时区与时间语义（event/publish/ingest time）
- [symbol-mapping.md](conventions/symbol-mapping.md) — 代码归一化（symbol / exchange）
- [parquet-layout.md](conventions/parquet-layout.md) — `/opt/raw_parquet` 布局与原子写
- [logging.md](conventions/logging.md) — 结构化日志
- [provider-ownership.md](conventions/provider-ownership.md) — **单表单一来源**归属规则与操作

## 分层（layers/）
- [raw.md](layers/raw.md) — 下载层职责与新增 fetcher
- [ingest.md](layers/ingest.md) — 入库层职责与新增 importer
- [stream.md](layers/stream.md) — 实时层职责与接入
- [db.md](layers/db.md) — DDL / 迁移流程

## 数据源（providers/）
- [yinhe.md](providers/yinhe.md) — 银河 AmazingData
- [ricequant.md](providers/ricequant.md) — 米筐 rqdatac
- [insight.md](providers/insight.md) — 华泰 INSIGHT

## 运维
- [runbook.md](runbook.md) — init/update 怎么跑、排障
