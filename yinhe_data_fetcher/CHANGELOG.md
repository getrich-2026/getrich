# CHANGELOG

## [2026-05-14] - 性能与可靠性优化 (Performance & Reliability Optimization)

### 核心改进 (Core Improvements)

- **DuckDB 合并写入 (Phase 3)**: 引入 DuckDB 引擎处理 Parquet 合并。通过 SQL `UNION BY NAME` 与 `ROW_NUMBER` 窗口函数实现高效去重，避免了 Pandas 全量加载大文件产生的内存峰值。
- **按月分区存储 (Phase 5)**: 将 K 线存储布局从 `data/<NAME>/<code>.parquet` 优化为 `data/<NAME>/<code>/<yyyy-mm>.parquet`。
    - 显著提升分钟线等大数据量文件的追加性能。
    - 实现冷热数据分离，单分区文件保持在数 MB 级别。
- **水位线系统 (Phase 4)**: 引入 `_sync_status.json` 追踪每个 fetcher 的全局同步进度。减少了重复检查本地文件索引的开销，确保跨会话的同步连续性。
- **原子化写入保护 (Phase 2)**: 写入过程中先生成 UUID 临时文件，成功后再通过 `os.replace` 原子替换。有效防止进程意外中断导致的数据文件损坏。

### 功能修复与完善 (Fixes & Refinement)

- **K 线去重逻辑修复**: 弃用 SDK 返回的无意义 `RangeIndex`，强制使用 `kline_time` (DatetimeIndex) 作为唯一索引。彻底解决了多次追加任务可能导致的数据误删或索引混乱问题。
- **轻量索引读取**: 优化 `read_parquet_index`，仅加载元数据或空列，极大降低了在检查“最后同步日期”时的磁盘 I/O。

### 运维建议 (Operational Notes)

- **并发策略**: 经评估 (Phase 6)，由于 AmazingData SDK 的单连接限制及回调阻塞模型，当前保持串行抓取以确保稳定性。
- **数据迁移**: Phase 5 引入了新布局，旧的单文件数据无需手动迁移（抓取器会自动开启新分区），但下游读取代码建议适配目录加载方式（如 `pd.read_parquet("path/to/code_dir/")`）。
