# raw parquet 布局与原子写

## 根目录
`/opt/raw_parquet`（可在 config `paths.raw_root` 改）。仓库内**不存任何数据**（.gitignore 已忽略）。

## 布局：`<raw_root>/<provider>/<dataset>/...`

```
yinhe/calendar/calendar_<market>.parquet
yinhe/hist_code_list/<security_type>.parquet
yinhe/backward_factor/<security_type>.parquet
yinhe/kline_day/<code>/<YYYY-MM>.parquet        # 按 code + 月分区
yinhe/kline_min1/<code>/<YYYY-MM>.parquet
ricequant/instruments/<asset>.parquet
ricequant/calendar/<market>.parquet
ricequant/bars_1d/<asset>/<code>.parquet
insight/basic_info/<security_type>.parquet
insight/trading_days/<exchange>.parquet
insight/kline_day/<code>/<YYYY-MM>.parquet
```

路径解析统一走 `common/paths.py::RawPaths`，禁止散落硬编码。

## 写入规则
- 一律 **zstd** 压缩。
- **原子写**：先写 `*.tmp-<uuid>.parquet`，再 `os.replace()`。
- **追加去重**：K 线按时间索引追加，与已有文件按索引合并去重（pandas，`keep='last'` 新数据胜出），
  实现见 `common/parquet.py::write_parquet(append=True)`。月分区单文件很小，无需额外引擎。
- 绝不提交 > 100K 行的 CSV；landing 一律 parquet。
