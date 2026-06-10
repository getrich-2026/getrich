# 时区与时间语义

## 时区
- **所有市场数据时间一律 `Asia/Shanghai`。**
- 禁止混用 naive 与 tz-aware datetime。
- DDL 中分钟级/实时时间列为 `TIMESTAMPTZ`；日线 `dt` 为 `DATE`。

## 时间语义（列名要无歧义）
- **event time**：行情发生时间 → `dt`（bar）、`trading_day`（交易日）。
- **publish time**：供应商发布时间（如有）→ 显式命名，不与 event time 混用。
- **ingestion time**：写库时间 → `updated_at`（DB 维护）。

## 防止前视泄漏
当时间戳驱动下游 join 时，列名必须能区分上述三类时间。raw 层保留源时间字段原义，
ingest 层在 transform 中显式映射到 canonical 时间列，绝不静默改写。

## int8 日期
供应商（尤其银河）常用 int8 日期（`20240102`）。`common/retry.py` 提供
`to_int_date` / `int_to_date` / `today_int` / `chunk_date_range` 统一转换，
落库前转为 `date` / `timestamptz`。
