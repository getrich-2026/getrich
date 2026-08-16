# 命名规范

## Python
- 包/模块：小写下划线（`raw`, `ingest`, `yinhe`, `bars`）。
- 类：`PascalCase`，fetcher 以 `Fetcher` 结尾，importer 以 `Importer` 结尾。
- provider 名固定小写：`yinhe` / `ricequant` / `insight`。

## raw 数据集名
- 与落盘目录一致：`calendar` / `hist_code_list` / `kline_day` / `kline_min1` / `instruments` / `bars_1d` ...
- 注册键 = 数据集名 = config `enabled.raw.<provider>` 列表项。

## 数据库
- schema：`meta`（元数据）、`market`（行情）、`realtime`（实时缓冲）、`ops`（运维/归属/审计）、`staging`。
- 行情表：`<asset>_bar_<freq>`，asset ∈ {stock, etf, index, future, option}，freq ∈ {1d, 1m}。
- 列：小写下划线。时间列 `dt`（bar 时间）、`trading_day`（交易日）。来源列统一 `source`。

## canonical 契约
- 规范列定义在 `common/contracts`，**唯一真相源**。DDL 变更必须同步 contracts，反之亦然。
