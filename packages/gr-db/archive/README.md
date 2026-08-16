# 历史 SQL 存档 —— 不要执行

`legacy-sql/` 是 2026 年重构前的建库脚本，随 `getrich-database` 合并一并带入，
**只作历史参考，任何环境都不要执行**。

## 为什么不能执行

这些脚本建的是已经废弃的 `frontend` schema。当前的 schema 划分是
`app`（业务）+ `backtest`（回测产物），`frontend` 已不复存在
（见 `AGENTS.md` §2 与 `.agent/brain/DECISIONS.md` D-020）。在现有库上执行会
建出一套与应用完全对不上的影子表。

其中还包含 `14_mock_data.sql` 这类演示数据，误跑到真库上会污染业务表。

## 当前的真源在哪

| 内容 | 位置 |
|---|---|
| 全部 DDL | `packages/gr-db/src/gr_db/ddl/postgres/`、`ddl/clickhouse/` |
| 应用 DDL 的方式 | `uv run gr-db migrate --target all` |
| 旧库升级到新 schema | `ddl/upgrade/001_frontend_to_app_backtest.sql` |

保留而不删除，是因为里面的表设计意图（尤其 `openapi.yaml` 与
`API_TASKS.md`）对理解历史字段含义仍有价值。确认不再需要后可整体删除，
内容在 git 历史里可恢复。
