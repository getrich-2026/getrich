# CI 工作流

!!! info "Phase 2 文档"
    本页尚未编写（计划在 Phase 2 补完）。

## 计划内容

- GitHub Actions 4 个 job：
  1. `backend-lint` — ruff check / format
  2. `backend-test` — pytest + find_silent_fails
  3. `frontend-build` — npm lint + test + build
  4. `docs-build` — mkdocs build --strict
- 缓存策略：`uv cache` / `node_modules` / `pip cache`
- Python 版本矩阵：3.10 / 3.11 / 3.12 / 3.13
- Node 版本：22 LTS
- services: PostgreSQL 16 / ClickHouse 24 / Redis 7
