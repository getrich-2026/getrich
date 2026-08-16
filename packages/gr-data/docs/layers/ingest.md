# ingest 层

## 职责
读 raw parquet（或直连 SDK）→ 归一化为 canonical → 写 PostgreSQL。一个 importer = 一张目标表。

## 结构
```
ingest/<provider>/
  adapter.py       # 读 /opt/raw_parquet/<provider>/ parquet
  symbols.py       # 代码归一化（symbol/exchange）
  importers/
    __init__.py    # REGISTRY + GROUPS（如 bars_1d -> 三个 asset importer）
```

## 基类 `BaseImporter`（ingest/base.py）
`run()` 流程（单事务）：
1. `OwnershipManager.claim(target, provider, channel='ingest')` — 单表单一来源校验。
2. `build()` — 子类实现：读 raw + 归一化为 canonical DataFrame（列对齐 `contract.columns`）。
3. quality 校验（空集/缺列/重复键/null）。
4. `upsert_rows` — 临时表 + COPY + `ON CONFLICT` upsert。
5. 写 `ops.etl_job_run` 流水，commit。

## 依赖顺序
`instruments → symbol_map → calendar → bars_*`。bars importer 通过 `symbol_map` 解析 `instrument_id`。

## 新增 importer
1. 在 `adapter.py` 加读取方法。
2. 在 `importers/` 新建类，继承 `BaseImporter`，设 `PROVIDER`/`DATASET`/`CONTRACT`，实现 `build()`。
3. 注册到 `REGISTRY`（必要时加 `GROUPS` 别名）。
4. config `enabled.ingest.<provider>` 加入。

## 运行
```bash
getrich ingest <provider> [--only a,b] [--force-ownership]
```
