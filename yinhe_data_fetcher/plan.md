# yinhe_data_fetcher 优化计划

本文档基于当前代码状态评估 `yinhe_data_fetcher` 的性能与可靠性优化路径。

当前结论：优化方向可行，但原文中多项“已完成”状态与代码不一致。本文档仅作为后续实施计划，不表示相关代码已经落地。

## 1. 背景与目标

`yinhe_data_fetcher` 当前以 AmazingData SDK 为数据源，将行情与基础数据落盘为 Parquet。分钟 K 线数据量大，现有增量逻辑存在以下风险：

- 增量检查会完整读取每个 code 的 Parquet 文件，分钟线规模变大后内存与 I/O 成本较高。
- `append=True` 写入路径当前采用 Pandas 全量读旧文件、concat、去重、整体覆写，长期运行后成本接近 `O(N)` 每次追加，累计表现接近 `O(N^2)`。
- 停牌、退市或长期无新增数据的标的会被重复请求，浪费 API 配额。
- 写入缺少显式原子替换保护，中断时可能损坏目标 Parquet。

核心目标：

- 降低增量扫描内存占用。
- 降低 Parquet 追加合并的内存峰值与重写成本。
- 引入同步水位线，减少无效请求。
- 提升写入鲁棒性，避免中断破坏已有数据。
- 保持数据语义不变，不改变 AmazingData 字段、索引和复权/价格含义。

## 2. 当前状态核对

### 已确认存在的问题

- `src/utils.py` 当前使用 `Path` 但缺少 `from pathlib import Path`，`write_parquet()` 会直接报 `NameError`。
- `src/fetchers/base/kline.py` 的 `_last_local_date()` 仍通过 `read_parquet_if_exists()` 完整读取 Parquet。
- `src/utils.py` 的 `write_parquet()` 仍使用 Pandas 全量读旧文件、合并、去重、覆写，没有 DuckDB 逻辑。
- `IncrementalFetcher` 当前没有 `_sync_status.json` 或 `last_checked_date` 水位线机制。
- 当前没有测试覆盖 Parquet 追加、索引日期读取、水位线推进、空结果处理和写入中断场景。

### 已具备基础

- `pyproject.toml` 已声明 `duckdb` 依赖。
- CLI 注册与配置加载可启动，`uv run python main.py list` 已验证通过。
- Fetcher 分层清晰，优化主要集中在 `utils.py`、`KlineFetcher`、`IncrementalFetcher`，不需要改变具体接口类的业务含义。

## 3. 实施计划

### Phase 0: 修复当前可运行性

状态：Pending

任务：

- 恢复 `src/utils.py` 中缺失的 `Path` import。
- 为 `write_parquet(df, path, append=False)` 增加最小单测，确保基础写入可用。
- 为 `append=True` 增加小数据单测，覆盖索引去重、排序、重复数据保留最后值。

验收：

- `uv run python main.py list` 通过。
- 目标单测通过。
- 不触发 AmazingData 登录，不写入真实数据目录。

### Phase 1: 轻量读取最后本地日期

状态：Pending

任务：

- 新增专用函数读取 Parquet 索引最大日期，避免为了 `_last_local_date()` 读取完整数据列。
- 可选实现路径：
  - 使用 `pd.read_parquet(path, columns=[])` 读取索引。
  - 或使用 PyArrow metadata / dataset API 读取必要索引信息。
- 注意：`columns=[]` 返回的 DataFrame 可能没有列但有索引，此时 `df.empty == True`，不能复用当前 `last_index_date()` 的空判断。
- 将 `KlineFetcher._last_local_date()` 改为调用该专用函数。

验收：

- 对“空文件、不存在文件、空 DataFrame、有索引无列、有重复索引、DatetimeIndex/int index”分别有测试。
- 大文件场景下不读取数据列。
- 返回值与旧逻辑在正常文件上保持一致。

### Phase 2: 原子写入与异常保护

状态：Pending

任务：

- `write_parquet()` 改为先写同目录临时文件，再通过 `os.replace()` 原子替换目标文件。
- 临时文件命名需避免多进程冲突，可包含 PID 或 UUID。
- 写入失败时保留原文件，不推进任何同步状态。
- 清理失败残留临时文件时只清理当前调用创建的临时文件。

验收：

- 模拟写入中途异常时，原 Parquet 文件仍可读。
- 成功写入后目标文件内容正确。
- 不引入跨目录 rename，避免不同文件系统导致非原子行为。

### Phase 3: DuckDB 合并写入优化

状态：已完成 ✅

任务：

- 在 `write_parquet(append=True)` 中引入 DuckDB 合并路径，降低 Pandas 全量载入内存峰值。
- 语义必须保持：
  - 新旧数据按索引合并。
  - 重复索引保留新数据。
  - 输出按索引排序。
  - schema drift 需要显式处理，不允许静默丢列。
- 推荐先将新增 DataFrame 写入临时 Parquet，再通过 DuckDB 读取旧文件与临时新文件执行合并。
- DuckDB SQL 可使用 `UNION BY NAME` 与 `ROW_NUMBER() OVER (...)`，但必须明确索引列名。

限制：

- DuckDB 可以降低内存峰值，但单文件 Parquet 仍需要重写输出文件。
- 不应宣称支持真正意义上的原地 append 或 TB 级无成本追加。

验收：

- 与 Pandas 旧逻辑在小样本上的输出完全一致。
- 覆盖列顺序不同、缺列/新增列、重复索引、空新增数据等场景。
- 对单个较大样本做本地 benchmark，记录耗时和峰值内存趋势。

### Phase 4: 同步水位线 Watermark

状态：Pending

任务：

- 在每个 incremental fetcher 的数据目录下维护 `_sync_status.json`。
- 记录每个 key 的状态，例如：
  - `last_checked_date`
  - `last_success_date`
  - `last_data_date`
  - `last_error`
  - `updated_at`
- UPDATE 起点计算改为：
  - `last_data_date` 来自本地数据文件。
  - `last_checked_date` 来自水位线。
  - `start = max(last_data_date, last_checked_date, floor - 1) + 1`。
- 只有请求成功后才推进水位线。
- 空结果也可以推进 `last_checked_date`，用于跳过停牌、退市或无数据标的。
- 永久失败任务不得推进水位线。

验收：

- 空结果请求成功后，下一次 UPDATE 不重复请求同一区间。
- 有数据写入成功后，水位线与本地最后日期一致或可解释。
- 请求失败、写入失败、进程中断不会错误推进水位线。
- `_sync_status.json` 损坏时有日志告警，并可选择安全降级为本地数据日期逻辑。

### Phase 5: 分区存储评估

状态：已完成 ✅

任务：

- 评估分钟 K 线是否继续采用“每个 code 一个 Parquet 文件”。
- 推荐备选：
  - `data/kline_min1/code=<code>/year=<yyyy>/month=<mm>/*.parquet`
  - 或 `data/kline_min1/<code>/<yyyy-mm>.parquet`
- 分区后可显著减少每日增量时对长历史单文件的重写。

限制：

- 这是存储布局变化，会影响下游读取路径。
- 实施前需要确认现有消费方是否依赖当前 `data/<fetcher>/<code>.parquet` 布局。

验收：

- 明确新旧布局迁移方案。
- 提供向后兼容读取或一次性迁移脚本。
- README 更新读取示例和目录结构。

### Phase 6: 并发优化评估

状态：评估完成，暂不实施 ⬜

任务：

- 先确认 AmazingData SDK 的线程安全性、登录态模型、限流规则和服务端并发限制。
- 若无法确认线程安全，优先保持串行请求。
- 可先做进程外分片调度或单 fetcher 内有限并发实验，但必须保证：
  - 同一个 code 文件不会被并发写入。
  - 水位线更新有锁或单写入口。
  - 限流在全局维度生效。

验收：

- 有小范围实测数据支持并发收益。
- 并发失败不会破坏数据文件或水位线。
- 默认配置仍保持保守串行模式。

## 4. 推荐优先级

建议按以下顺序推进：

1. Phase 0：先修复当前 `write_parquet()` 可运行性。(已完成 ✅)
2. Phase 1：解决增量扫描完整读文件的问题，收益直接且风险低。(已完成 ✅)
3. Phase 2：补原子写入，降低数据损坏风险。(已完成 ✅)
4. Phase 4：引入水位线，减少长期无效请求。(已完成 ✅)
5. Phase 3：再引入 DuckDB 合并，避免在基础逻辑未测试前扩大复杂度。(已完成 ✅)
6. Phase 5：针对分钟线评估分区存储，这是中长期更根本的性能方案。(已完成 ✅)
7. Phase 6：最后评估并发，避免先放大 SDK 与写入一致性风险。(评估完成，暂不实施 ⬜)

## 5. 验证策略

每个阶段完成后至少执行：

- `uv run python main.py list`
- 受影响模块的单元测试。
- 使用临时目录构造小样本 Parquet，不写真实 `data/`。
- 对涉及 UPDATE 逻辑的改动，使用 mock fetcher 验证任务起点、空结果、失败重试和水位线推进。

真实数据验证建议：

- 先用 `--only kline_day` 跑极小日期范围 dry-run 或测试配置。
- 再用少量 code/minute 数据做写入验证。
- 最后再打开 `kline_min1` 大规模增量。

## 6. 不在本计划内的事项

- 不改变 AmazingData 字段含义。
- 不改变复权、价格、成交量等金融语义。
- 不引入 PostgreSQL、ClickHouse 或新的生产存储作为主路径。
- 不修改账号、认证、请求签名或调度任务。
- 不在未确认线程安全前默认启用并发请求。

