# Context

## 边界

- `getrich_data_import` 是新的数据导入工程。
- `yinhe_data_fetcher` 只负责下载 parquet；旧 `data_import`、`import_data` 不作为运行依赖。
- 默认 yinhe 数据目录：`/data`；当前已有测试数据在 `/home/quant/data`，通过 env 覆盖使用。
- `/home/quant/data` 暂无 `kline_min1`。

## 常用命令

```bash
cd getrich_data_import
.venv/bin/python -m pytest tests
.venv/bin/ruff check src tests
GETRICH_IMPORT__DATABASE_URL='postgresql+psycopg://quant:***@127.0.0.1:5432/getrich?connect_timeout=10' \
  .venv/bin/getrich-import verify-schema
```

## 当前 Review

- `docs/code-review-2026-06-04.done.md` 已完成。
- 附录 A 通过 `60_review_appendix_a.sql` 实施，本地 DB 已应用。
