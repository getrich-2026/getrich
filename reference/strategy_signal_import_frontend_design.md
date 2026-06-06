# 策略与信号导入前端架构设计

## [Agent: architect]

## 1. 目标

为 GetRich Web 前端新增一个后台导入页面，用于维护策略元信息，并导入策略日涨跌幅序列和历史信号。净值曲线、累计收益、回撤、月度收益等可由日涨跌幅计算得到的指标，由后端派生生成，不再要求重复导入。页面与数据库的交互统一通过后端 API 完成，不允许前端直连或直接写数据库。

## 2. 假设与约束

- 当前前端在 `web/`，使用 React 19、TypeScript、Vite、React Query、react-hook-form、zod、shadcn/ui。
- 当前后端在 `src/getrich/apps/web/`，FastAPI 路由统一挂在 `/v1` 下，通过 `psycopg3` 访问 PostgreSQL。
- 策略元数据、策略业绩、信号属于业务数据，按项目约束写入 PostgreSQL。
- 当前运行代码使用 `strategies.id` 作为 UUID，外部展示和路由使用 `strategy_code`；`signals.id` 为 UUID，外部展示和路由使用 `signal_code`。
- Uncertain：仓库中未找到正式迁移文件，实际数据库 DDL 需要在实现前用 PostgreSQL introspection 确认。
- 当前 `strategy_trades` 表未上线，`GET /strategies/{strategy_code}/trades` 仍返回空列表。若历史业绩要包含逐笔交易，需要先补交易表设计。
- 历史业绩默认通过日涨跌幅序列导入，收益聚合默认使用复利；前端可选择单利作为计算口径。

## 3. 核心决策

采用 API 导入，不采用前端直接写库。

原因：

- 前端直连数据库会暴露凭证和写权限，不可控。
- API 层可以做管理员鉴权、字段白名单、CSV 类型校验、幂等键、事务、回滚、审计和错误明细。
- 当前系统已有 FastAPI + PostgreSQL 连接池，新增导入服务能复用统一响应、异常和连接管理。
- 大 CSV 或未来 Parquet 导入可以在 API 层切到异步任务，前端无需感知数据库细节。

## 4. 页面设计

页面路由建议：`/#/admin/imports`

左侧为策略基础信息表单，右侧为 CSV 导入区和预检结果。

主要区域：

- `StrategyBasicForm`：填写策略和作者信息。
- `CsvTemplatePanel`：下载 CSV 模板。
- `CsvUploadPanel`：选择导入类型并上传文件。
- `ReturnCalcMethodControl`：导入类型为 `strategy_daily_returns` 时显示收益计算口径，使用单选或分段控件，默认选中复利。
- `ImportPreviewTable`：展示前 100 行解析结果、字段映射、错误列。
- `ValidationSummary`：展示总行数、有效行、错误行、重复行、将新增/更新的数量。
- `CommitBar`：预检通过后确认写入。
- `ImportHistoryTable`：展示最近导入作业、操作者、状态和错误报告。

前端文件建议：

- `web/src/pages/AdminImportsPage.tsx`
- `web/src/api/adminImports.ts`
- `web/src/types/adminImport.ts`
- `web/src/lib/importSchemas.ts`
- `web/public/templates/strategy_daily_returns_template.csv`
- `web/public/templates/strategy_signals_template.csv`

导航入口建议只对管理员显示，先隐藏在 `SideNav` 的后台入口中，避免普通用户误触。

收益计算口径前端交互：

- 控件位置：`CsvUploadPanel` 的导入配置区。
- 显示条件：仅当 `import_type = strategy_daily_returns` 时显示。
- 控件形式：`RadioGroup` 或 `Tabs/SegmentedControl`，两个选项为 `compound` 和 `simple`。
- 默认值：`compound`。
- 提交行为：点击“预检”时前端读取 CSV 文本，并随 JSON 请求一起提交 `return_calc_method`；预检通过后生成的 `job_id` 固定该口径，后续 `commit` 不允许再覆盖。
- 展示行为：`ValidationSummary` 和 `ImportHistoryTable` 显示口径标签，避免同一策略不同导入批次的月度收益口径混淆。

## 5. API 设计

新增路由模块：

- `src/getrich/apps/web/routers/admin_imports.py`
- `src/getrich/apps/web/services/admin_import.py`
- `src/getrich/apps/web/schemas/admin_import.py`

统一前缀：`/v1/admin/imports`

### 5.1 管理员鉴权

新增依赖：

```python
async def require_admin(user_id: str = Depends(require_user)) -> str:
    ...
```

规则：

- 开发期可以先通过 `users.role = 'admin'` 或配置白名单判断。
- 生产期必须接 JWT 权限，不允许只靠 `X-User-Id`。
- 所有导入 API 必须使用 `require_admin`。

### 5.2 策略基础信息保存

`POST /v1/admin/imports/strategies/upsert`

用途：创建或更新策略基础信息。

请求体：

```json
{
  "strategy_code": "STR_FUT_001",
  "name": "Index Futures Trend",
  "summary": "Medium frequency trend strategy",
  "description": "Full strategy description",
  "detail_html": "<p>...</p>",
  "category_id": "future",
  "asset_class": "future",
  "market": "cn",
  "risk_level": "medium",
  "run_status": "paper",
  "pub_status": "draft",
  "author_id": "USER_ADMIN_001",
  "subscription_monthly": "99.00",
  "subscription_yearly": "999.00",
  "backtest_start": "2026-01-01",
  "backtest_end": "2026-05-31",
  "tags": ["trend", "future"]
}
```

写入规则：

- `strategy_code` 作为外部幂等键。
- 金额字段后端使用 `Decimal`，前端以字符串提交。
- `pub_status` 默认为 `draft`，导入完成并人工检查后再发布。
- 不允许表单直接修改 `subscriber_count`、`total_signal_count` 这类统计冗余字段。

### 5.3 CSV 预检

`POST /v1/admin/imports/preview`

JSON 请求体：

- `import_type`: `strategy_daily_returns | strategy_signals`
- `strategy_code`: 可选；信号 CSV 允许每行带 `strategy_code`，业绩类建议统一传。
- `file_name`: CSV 文件名。
- `csv_text`: 前端从 CSV 文件读取出的文本内容。
- `mode`: `upsert | insert_only`
- `return_calc_method`: `compound | simple`，仅对 `strategy_daily_returns` 生效，由前端勾选/单选后传入；未传时后端默认 `compound`。
- `initial_nav`: 可选，默认 `1.0`。
- `trading_days_per_year`: 可选，默认 `252`，用于年化收益和年化波动率。
- `risk_free_rate`: 可选，默认 `0`，用于 Sharpe 等风险调整指标。

响应：

```json
{
  "job_id": "IMPORT_20260604_001",
  "status": "validated",
  "summary": {
    "total_rows": 1200,
    "valid_rows": 1198,
    "error_rows": 2,
    "duplicate_rows": 3,
    "will_insert": 900,
    "will_update": 298,
    "return_calc_method": "compound"
  },
  "preview_rows": [],
  "errors": [
    {
      "row_number": 18,
      "column": "trade_date",
      "message": "invalid date, expected YYYY-MM-DD"
    }
  ]
}
```

预检只解析和校验，不写业务主表。

日涨跌幅预检除字段合法性外，还需要模拟计算派生结果：

- `strategy_equity_curve`：由日涨跌幅计算 `nav`、`cumulative_return`、`drawdown`、`benchmark_nav`。
- `strategy_monthly_returns`：按自然月从日涨跌幅聚合生成。
- `strategy_performance_snapshot`：按导入序列末日生成或更新基础绩效快照。

派生计算口径：

- 复利，默认：`period_return = product(1 + daily_return) - 1`。
- 单利，可选：`period_return = sum(daily_return)`。
- 复利净值：`nav_t = initial_nav * product(1 + daily_return_i)`。
- 单利净值：`nav_t = initial_nav * (1 + sum(daily_return_i))`。
- 回撤：`drawdown_t = nav_t / max(nav_1..nav_t) - 1`。

### 5.4 确认写入

`POST /v1/admin/imports/{job_id}/commit`

写入规则：

- 一个导入作业一个事务，失败则回滚。
- 通过 `ON CONFLICT DO UPDATE` 实现幂等。
- 只允许提交 `validated` 状态的作业。
- 提交后记录 `committed_by`、`committed_at`、`affected_rows`。

### 5.5 导入状态与错误报告

- `GET /v1/admin/imports/{job_id}`
- `GET /v1/admin/imports/{job_id}/errors`
- `GET /v1/admin/imports/history?page=1&page_size=20`

## 6. 导入作业表设计

建议新增 PostgreSQL 表保存审计和错误明细。

```sql
CREATE TABLE import_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_code        VARCHAR(64) NOT NULL UNIQUE,
    import_type     VARCHAR(64) NOT NULL,
    strategy_id     UUID REFERENCES strategies(id),
    file_name       VARCHAR(256) NOT NULL,
    file_sha256     CHAR(64) NOT NULL,
    mode            VARCHAR(16) NOT NULL,
    status          VARCHAR(16) NOT NULL,
    summary         JSONB NOT NULL DEFAULT '{}',
    preview_rows    JSONB NOT NULL DEFAULT '[]',
    created_by      UUID NOT NULL REFERENCES users(id),
    committed_by    UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    committed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE import_job_errors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    row_number      INTEGER NOT NULL,
    column_name     VARCHAR(128),
    error_code      VARCHAR(64) NOT NULL,
    message         TEXT NOT NULL,
    raw_row         JSONB NOT NULL DEFAULT '{}'
);
```

CSV 原文件不建议直接长期存库。可选方案：

- 小文件：只保留 `file_sha256`、预览行和错误行。
- 大文件：保存到受控对象存储或本地非公开目录，DB 仅记录路径和哈希。

## 7. CSV 模板

模板设计原则：

- 日期统一 `YYYY-MM-DD`。
- 时间统一 ISO 8601，带时区；未带时区时后端按 `Asia/Shanghai` 处理并记录告警。
- 百分比字段使用小数，例如 `0.1234` 表示 `12.34%`。
- 空值保留为空字符串，不使用 `N/A`、`--`。
- 金额和价格字段后端转 `Decimal`。

已提供设计模板：

- `reference/csv_templates/strategy_daily_returns_template.csv`
- `reference/csv_templates/strategy_signals_template.csv`

后续实现下载时，将这些文件复制到 `web/public/templates/`，前端使用静态链接下载。

## 8. 字段校验规则

策略基础信息：

- `strategy_code` 必填，唯一，格式建议 `^STR_[A-Z0-9_]{3,32}$`。
- `risk_level` 仅允许 `low | medium | high`。
- `asset_class` 仅允许 `stock | future | option | multi_asset`，最终枚举以数据库为准。
- `market` 仅允许 `cn | hk | us | global`，最终枚举以数据库为准。
- `subscription_monthly`、`subscription_yearly` 必须大于等于 0。

日涨跌幅序列：

- 幂等键：`strategy_id + trade_date`。
- `daily_return` 必填，必须为有限数值，禁止 `NaN`、`Inf`。
- `benchmark_daily_return` 可为空；非空必须为有限数值。
- `position_ratio` 可为空；非空必须在 `[0, 1]`。
- `trade_date` 不允许重复；同一策略同一日期重复行在预检阶段标红。
- 导入后由后端派生写入 `strategy_equity_curve`、`strategy_monthly_returns` 和基础 `strategy_performance_snapshot`。

派生净值曲线：

- 幂等键：`strategy_id + trade_date`。
- `nav` 必须大于 0。
- `daily_return`、`cumulative_return`、`drawdown` 必须为有限数值。
- `position_ratio` 必须在 `[0, 1]`。

派生月度收益：

- 幂等键：`strategy_id + year + month`。
- `month` 必须在 `1..12`。
- `monthly_return` 必须为有限数值。
- 默认复利计算；用户选择单利时按单利计算，并在导入作业 `summary.return_calc_method` 中记录。

派生业绩快照：

- 幂等键：`strategy_id + snapshot_date`。
- `snapshot_date` 使用导入日收益序列的最大 `trade_date`。
- 至少计算 `total_return`、`annualized_return`、`max_drawdown`、`annualized_volatility`、`sharpe_ratio`。
- `win_rate`、`total_trades`、`profit_factor` 等依赖交易明细的指标，在未导入交易明细前保持为空，不从日收益强行推断。

历史信号：

- 幂等键：优先 `signal_code`；若为空，由后端按 `strategy_code + published_at + symbol + type + action` 生成稳定编码。
- `type` 仅允许 `entry | exit | adjust | alert`。
- `action` 仅允许 `buy | sell | hold | close`。
- `direction` 仅允许 `long | short`，股票可默认 `long`。
- `confidence` 必须在 `[0, 1]`。
- `position_pct` 必须在 `[0, 1]`。
- `status` 仅允许 `active | expired | cancelled`。

## 9. 风险控制

写入风险：

- 预检阶段不写业务主表。
- 确认阶段使用单事务，失败回滚。
- 使用参数化 SQL，禁止拼接用户输入。
- 所有 upsert 使用明确冲突键，不允许无条件覆盖整行。
- 更新策略主表时只允许白名单字段，禁止更新订阅数、统计数、创建时间等系统字段。

权限风险：

- 仅管理员可访问导入页和导入 API。
- 导入作业记录操作者、文件哈希和提交时间。
- 生产环境禁用开发期 `X-User-Id` 管理员判定。

数据质量风险：

- 拒绝 `NaN`、`Inf`、空主键、非法枚举和越界百分比。
- 对超过 100,000 行 CSV 直接拒绝，提示使用 Parquet 或离线批处理。
- 预检报告必须展示错误行，错误未解决时不允许提交。
- 同一文件哈希重复导入时提示用户，默认不阻止，但必须二次确认。
- 日涨跌幅导入后自动重算相关派生表，禁止用户同时提交同一周期的月度收益覆盖派生结果。

量化风险：

- 导入历史信号时必须保留 `published_at`，避免事后信号和回测结果混淆。
- 导入历史业绩不得自动反推信号。
- 回测、信号生成时间和执行时间必须分字段保存，防止 look-ahead bias。
- 月度收益、净值和回撤的计算口径必须在导入作业中记录；默认复利，切换单利时前端必须展示口径标签。

## 10. 实施任务拆解

P0：

1. 确认 PostgreSQL 实际 DDL，尤其是 `strategies`、`signals`、`strategy_equity_curve`、`strategy_performance_snapshot`、`strategy_monthly_returns` 的字段类型和唯一约束。
2. 新增 `import_jobs`、`import_job_errors` 迁移设计。
3. 新增 `require_admin` 依赖。
4. 新增日涨跌幅 CSV 解析、复利/单利派生计算、zod/Pydantic 双端 schema、预检 API、提交 API。
5. 新增 `AdminImportsPage`，接入模板下载、表单、上传、预览、提交。
6. 将模板文件放到 `web/public/templates/`。

P1：

1. 导入历史作业列表和错误报告下载。
2. 大文件异步导入队列。
3. 支持 Parquet 导入，替代超过 100,000 行 CSV。
4. 补齐 `strategy_trades` 表和历史交易导入。
5. 发布工作流：导入完成后从 `draft` 人工切换到 `published`。
6. 高级覆盖导入：允许管理员手工导入业绩快照，但必须与日收益派生口径隔离并审计。

## 11. 验证计划

后端：

```bash
uv run ruff format src/getrich/
uv run ruff check src/getrich/ --fix
uv run pytest tests/ -v --durations=10
```

前端：

```bash
npm run lint
npm run build
```

重点测试：

- 无管理员权限访问导入 API 返回 403。
- CSV 缺必填列、非法枚举、非法日期、`NaN`、`Inf` 均被预检拦截。
- 同一日涨跌幅序列在复利和单利口径下生成不同月度收益，且导入作业正确记录口径。
- 同一 CSV 重复提交不产生重复业务记录。
- 提交中途失败后业务表无部分写入。
- 前端上传失败、预检失败、提交失败都有明确状态。
