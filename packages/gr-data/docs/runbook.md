# 运行手册

## 首次建库
```bash
uv sync
cp config.example.yaml config.yaml      # 填 PG 连接 + provider 凭证（环境变量名）
export PGPASSWORD=... YINHE_USER=... YINHE_PASSWORD=...   # 按 config 里的 *_env
getrich db migrate
```

## 日常抓取 + 入库（以 yinhe 为例）
```bash
getrich raw yinhe --mode update     # 增量抓取落 /opt/raw_parquet/yinhe/
getrich ingest yinhe                # 归一化入库
```
建议 cron：raw update 后接 ingest。多 provider 各自一条链。

## 切换数据源
见 conventions/provider-ownership.md。简言之：
```bash
getrich ingest <new_provider> --only <table> --force-ownership
```
注意是否需要先清空目标表，避免新旧来源混存。

## 排障
- **OwnershipError**：目标表已归属其它 provider。`getrich own list` 查看；确需切换用 `--force-ownership`。
- **ingest 行数为 0**：检查 raw parquet 是否已落地（`/opt/raw_parquet/<provider>/`），
  以及 `meta.symbol_map` 是否已建立（bars 依赖它解析 instrument_id）。
- **DDL 重跑失败**：DDL 须可重入；改过的文件 checksum 变化会 reapplied。
- **质量告警**（etl_job_run.status=partial）：查 `ops.etl_job_run` 与日志的 warnings。

## 验证（Definition of Done）
- `uv run ruff check src/` 通过
- `uv run pytest tests/raw tests/common` 通过（离线）
- 有 docker 时 `uv run pytest`（含真实 PG 集成）通过
- 小范围 ingest 后核对行数 / 重复键 / source 列
