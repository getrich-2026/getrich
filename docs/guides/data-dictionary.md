# 数据字典与 DDL 注释指南

读者：查看数据结构的数据开发者、维护迁移的后端开发者；Agent 修改 DDL 时参考。
用途：从活库生成结构说明、检查契约漂移。表结构真源仍是 `packages/gr-db/src/gr_db/ddl/`，不在 Markdown 里复制字段目录。
以下命令从仓库根目录执行；需要相应数据库连接，真实凭证保存在仓库外或被忽略的本地配置中。

```bash
# 从活库生成 HTML / JSON；--target 可用 pg、ch、all
uv run gr-db docs --target pg --out /tmp/data-dictionary.html --fail-on-drift
uv run gr-db docs --target ch --format json --out - --fail-on-drift

# CI 中检查新增建表或新增字段是否有 COMMENT ON
uv run python scripts/lint_migrations.py --db pg --comments --base-ref origin/dev
```

## 如何理解结果

- PostgreSQL 字典从活库 catalog 反射，只覆盖 gr-db 明确管理的业务 schema，包含 `diag`，排除 TimescaleDB 内部 schema。
- `--fail-on-drift` 检查契约列与运行时表归属；多个 provider 声明接入能力不等于生产混写。
- `ch` 模式不连接 PostgreSQL，也不能替代 PostgreSQL 契约／归属验证。
- 注释门禁同时覆盖新增建表和 `ALTER TABLE ... ADD COLUMN`；豁免列与解析规则以 `gr_db/docs/ddl_lint.py` 为准。
- HTML／JSON 是生成产物，按需重建，不提交活库快照。访问地址、表行数和服务健康状态应在运行时确认。

实现：`packages/gr-db/src/gr_db/docs/`；CI：`.github/workflows/ci.yml`。
设计理由见 [决策记录](../../.agents/brain/DECISIONS.md) D-051、D-054、D-058。
实施过程仅在需要追溯时查 [历史计划](../history/data-dictionary-plan.md)。
