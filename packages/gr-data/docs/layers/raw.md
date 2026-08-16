# raw 层

## 职责
调供应商 SDK 抓取数据，**原样**落 parquet 到 `/opt/raw_parquet/<provider>/`，不做归一化。
归一化在 ingest 层。

## 结构
```
raw/<provider>/
  client.py        # SDK 封装 + 协议（依赖注入，测试可换 Fake）
  fetchers/        # 一个数据集一个 fetcher 类
    __init__.py    # REGISTRY: {dataset_name: FetcherClass}
```

## 基类
- `BaseFetcher`（`raw/base.py`）：`PROVIDER` / `DATASET` 类属性 + `fetch(mode)` 方法。
- 全量类（calendar/instruments/...）：每次覆盖。
- 增量类（kline）：从本地最新分区取水位，只拉之后数据，按 code+月去重追加。

## 新增 fetcher
1. 在 `client.py` 协议里加所需 SDK 方法（真实实现 + 注释真实调用）。
2. 在 `fetchers/` 新建类，继承 `BaseFetcher`，设 `PROVIDER`/`DATASET`，实现 `fetch()`。
3. 在 `fetchers/__init__.py` 的 `REGISTRY` 注册。
4. config `enabled.raw.<provider>` 加入数据集名。

## 运行
```bash
getrich raw <provider> --mode init|update [--only a,b]
```
`init` 全量、`update` 增量。限流/重试参数在 config `providers.<provider>.rate_limit`。
