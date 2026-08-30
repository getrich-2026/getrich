# 持仓诊断 API — 代码审查交接单

> **状态**：已修复并验证（2026-08-30）。本文列出的 13 条发现来自对 commit `2089022` 的独立代码审查，
> 其中 4 条（#1 #2 #3 #5）已由第二人逐条对着源码复核确认成立，其余为审查结论、
> 未逐条复核但机制描述可信。
>
> **分支**：`worktree-feat-diagnosis-api`（worktree 位于
> `.claude/worktrees/feat-diagnosis-api`，基线是 `feat/data-ingest-tushare-datayes`，
> 均未合回 `dev`）。**所有命令从 worktree 目录跑，不要 cd 到主仓库。**
>
> **设计契约真源**：`/home/neo/project/getrich-design/portfolio-analysis/` 下的
> `持仓诊断_表与接口设计.md`（v0.2.2）与 `持仓诊断_架构设计.md`（v0.1.3）。
> 判断「哪个是对的」以设计文档为准，不以现有代码为准。

## 修复结论（2026-08-30）

修复提交为 `f57927c`，文档与验证基线分别见 `16c995c`、`35332cb`。三条护栏保持不变：
`calculation_hash` 仍不含请求级字段，`request_hash` 仍含 `label` 与 `plan_index`，
模块 B/C/D 仍按契约降级，不填估算值。

| 发现 | 处置 |
|---|---|
| #1 | 共享 run 只存纯计算子集；读取时从当前 `portfolio_plan` 重建 `plan_id`、`label`、覆盖率与请求级数据质量。 |
| #2 | SSE 发出 `complete` 后结束；在构造 `StreamingResponse` 前显式退出 PG 连接上下文。 |
| #3 / #9 | 标的查询限定 `stock` / `etf`、排序并显式拒绝歧义；重复持仓按规范化 `symbol_full` 合并。 |
| #4 / #8 | `/result` 选择每个 plan 的最新 run，并按 `diagnosis_run.status` 显式聚合全部状态。 |
| #5 | 可解析子集用户权重和为零时返回 422，不再静默改为等权。 |
| #6 | 新增 3 条 `GETRICH_TEST_PG=1` 门控集成用例，覆盖 SQL 全链路、幂等、跨用户复用隔离、`diag.` 前缀及 UUID 绑定。 |
| #7 / #10 | 新股窗口改为 365 个自然日；默认业务日期固定使用 `Asia/Shanghai`。 |
| #11 / #12 | snapshot 与 run 的冲突路径均使用 `ON CONFLICT` 回读并做空值防御。 |
| #13 | 8 个 JSON 端点均声明统一响应信封的 `response_model`；口径列表改为显式字段查询。 |

验证已完成：诊断单元测试 `51 passed`，真 PostgreSQL 集成测试 `3 passed`，全仓
`2435 passed / 38 skipped / 0 failed`；Ruff、格式、迁移静态检查与依赖锁检查均通过。
临时 `.env` 已删除。未执行手工并发 `curl` / `pg_stat_activity` 观测；SSE 的连接释放已
通过路由实现复核，分帧结束行为有单元覆盖。`data_fingerprint` 的每日维护任务仍是既有缺口，
不属于本轮修复。

## 被审代码（审查时快照）

| 文件 | 行数 | 内容 |
|---|---|---|
| `packages/gr-db/src/gr_db/ddl/postgres/040_diag.sql` | 283 | `diag` 的 7 张表 + bootstrap 种子 |
| `packages/gr-api/src/gr_api/schemas/diagnosis.py` | 458 | Pydantic 请求响应模型 |
| `packages/gr-api/src/gr_api/services/diagnosis.py` | 1477 | 服务层，问题集中在这里 |
| `packages/gr-api/src/gr_api/routers/diagnosis.py` | 284 | 9 个端点 + SSE |
| `packages/gr-api/tests/test_diagnosis.py` | 456 | 37 条测试（全是纯函数，不碰 SQL） |

---

# ⚠️ 动手前先读：三条不要「修错方向」的护栏

这三处是**刻意设计**，看起来像 bug 但不是。改错方向会毁掉设计意图且不会有任何报错。

**护栏 1：`_calculation_hash` 不含 `plan_id`/`label`/`plan_index`/`intent` 是对的。**
这是设计文档 T17 的明确决策（§7.8 对照表），目的是让「A 用户的独立组合」能命中
「B 用户 before/after 里的 before 方案」，是选 per-plan 粒度的**全部理由**。
#1 的正确修法是**不要把请求级数据写进共享的 payload**，
**绝不是**把 `plan_id` 加回哈希——那样做问题会消失，但跨用户复用同时也没了。

**护栏 2：`_request_hash` 含 `label` 与 `plan_index` 是对的。**
漏掉会让 before/after 互换命中同一个 snapshot，调仓结论直接反向。别为了「统一两套
哈希」把它们删掉。两套哈希粒度不同、时机不同、入参不同，这是设计要求，不是冗余。

**护栏 3：B/C/D 三节返回 `null` + `reason_code` 是对的。**
模块 B/D 需要历史协方差（架构篇 P0-b 的 L1 全市场日收益矩阵），模块 C 卡在缺口 G6
的产品决策。不要为了「让接口好看」给它们填估算值——设计文档 §7.6 和 D-047 明确
要求「不得静默估算」。

---

# HIGH：接前端之前必须修

## #1 跨用户缓存串数据 + 信息泄漏

**位置**：`packages/gr-api/src/gr_api/services/diagnosis.py:1010`（`_compute_plan` 构造 `plan_result`）

**机制**：`calculation_hash` 按设计不含 `plan_id`/`label`/未解析代码，所以两个**不同的
请求**可以命中同一行 `diag.diagnosis_run`。但 `payload` 里存了大量**请求级**数据：

- `plan_result.plan_id`、`plan_result.label`（1011–1012 行）
- `section_a` 的覆盖率字段族：`input_weight` / `resolved_weight` / `unresolved_weight` /
  `calculation_coverage_ratio`（由 `_build_exposure_section` 写入）
- 同行写入的 `data_quality`：`unresolved_symbols` / `duplicated_symbols` / `coverage_summary`

`_ensure_run` 命中哈希后直接复用整行，`get_result` 又直接把 `r["payload"]` 塞进响应。

**复现**：

1. 用户 A：`POST /v1/diagnosis/snapshots`，plan 为
   `{"plan_id":"before","label":"before","holdings":[{"symbol":"600000.SH","weight":50},{"symbol":"GARBAGE"},...]}`
   —— 注意要让可解析子集归一化后与步骤 2 相同。
2. 用户 B：提交只含 `600000.SH` 的等价组合，`plan_id="my-portfolio"`。
3. B 的 `/result` 返回 `plan_id="before"`、`label="before"`，
   且 `data_quality.unresolved_symbols` 里有 A 输入的 `GARBAGE`，
   `section_a.unresolved_weight` 是 A 的数字。

后果有两层：**B 的报告是错的**（覆盖率、未解析清单都不是他的），
且 **B 看到了 A 的输入代码**。

**修法**：`diagnosis_run.payload` 只保留**纯计算结果**（`section_a` 的指标部分、
`section_b/c/d`、`blindspots`、`profile`），把下列内容改为在响应组装时按**当前请求**
注入，不从共享 run 里读：

- `plan_id` / `label` —— 从 `diag.portfolio_plan` 当前行取（那里本来就存着）
- 覆盖率字段族 —— 从当前请求的 `_normalize_plan` 结果算
- `data_quality` 的 `unresolved_symbols` / `duplicated_symbols` / `coverage_summary`

这与设计 §5.5 的原话一致：「snapshot 级字段在响应组装时拼接，不入此列」。
注意 `weight_mode` **可以**留在 payload——它参与了 `calculation_hash`，同哈希必然同值。

**连带**：DDL 的 `diagnosis_run.data_quality` 列届时可能只剩纯计算相关的部分
（如各类数据源覆盖率），请一并确认它存的东西是否也跨用户安全。

## #2 SSE 永久占用连接池连接

**位置**：`packages/gr-api/src/gr_api/routers/diagnosis.py:198-232`（`stream_snapshot`）

**机制**：`gen()` 推完全部批次后进入
`while not await request.is_disconnected(): sleep(15); yield SSE_HEARTBEAT` 的**无限循环**，
只有客户端断开才结束。而 `db: AsyncConnection = Depends(get_db)` 的连接由 FastAPI 的
dependency `AsyncExitStack` 持有，该栈包着整个 response 调用，因此**连接在整条 SSE
连接存活期间都不归还**，且处于 idle-in-transaction 状态（池子非 autocommit）。

`PG_POOL_MAX` 默认 20 → **开 20 个报告页签就能耗尽连接池**，其余所有端点全部阻塞；
idle-in-transaction 还会挡住 autovacuum。

对照：既有的 `backtest_jobs.py` SSE 不会这样，因为它到终态就结束生成器。

**修法**：两处都要改。

1. 一期计算是同步的，数据推完就该**结束流**（发完 `complete` 事件直接 return），
   不要挂着心跳。心跳的用途是「计算还没结束、防代理超时」，而这里已经没有后续数据了。
2. 保险起见，在返回 `StreamingResponse` **之前**就把连接释放掉：把
   `get_result` 的调用放在依赖作用域内取完数据，生成器内部不再需要 `db`。
   （现在 `gen()` 确实没再用 `db`，但依赖仍持有它，所以必须显式改结构。）

**验证**：改完后开若干个 `curl -N .../stream` 并发，同时查
`SELECT count(*) FROM pg_stat_activity WHERE application_name='getrich-web'`，
连接数不应随流的数量线性增长。

---

# MEDIUM

## #3 `meta.instruments.symbol` 不唯一，按它建字典会取到随机行

**位置**：`services/diagnosis.py:274`

**已复核确认**：`002_meta.sql:14` 的约束是 `UNIQUE (asset, exchange, symbol)`，
**`symbol` 单列不唯一**。同一个 `600000.SH` 可以同时以 `asset='stock'` 和
`'etf'`/`'index'` 存在。

代码 `rows = {r["symbol"]: r for r in await cur.fetchall()}` 没有 `ORDER BY`，
字典构造时后来者覆盖先前者，**保留哪一行取决于执行计划**。后果：同一请求在不同
时刻可能解析到不同 `instrument_id` → `calculation_hash` 不稳定（缓存永不命中），
且可能诊断了错误的标的。

**修法**：查询加 `asset` 过滤（一期只做股票，可限定 `asset IN ('stock','etf')`）
或加确定性 `ORDER BY`，并对重复命中显式检测——查出多行时应当报错或记 dq，
而不是静默取一行。

## #4 `run_status` 有死分支，全失败时客户端会无限轮询

**位置**：`services/diagnosis.py:1187`

**机制**：

```python
if not plans:            # plans = [r["payload"] for r in rows if r["payload"] is not None]
    run_status = "pending"
elif "failed" in statuses:
    run_status = "partially_succeeded" if len(plans) else "failed"   # len(plans) 恒 > 0
```

全部 plan 都失败时 `payload` 全为 NULL → `plans` 为空 → 走第一个分支报 `pending`
→ 路由 `diagnosis.py:76` 返回 `202 + Retry-After: 1` → **客户端对一个永久失败的
计算无限轮询**。而 `"failed"` 这个取值**永远不可能返回**。

另外：run 行的 `status='partially_succeeded'` 会被报成 `"succeeded"`，
因为判定只看 `payload IS NOT NULL`、没看 `status` 列。

DDL 的 `chk_run_status` 和 `error_reason` 列都为这两个状态预留了位置，
失败落库路径一旦接上就会踩到。

**修法**：状态判定改为读 `diag.diagnosis_run.status` 列本身，而不是推断 `payload`
是否为空。四种情况分开：全成功 / 部分成功 / 全失败 / 尚未计算。

## #5 `weight_mode="user"` 可能静默变等权且不发声明

**位置**：`services/diagnosis.py:324`

**机制**：`if weight_mode == "user" and resolved_weight > 0:` 为假时落到 `else`
的等权分支，但 `weight_mode` 变量**不变**，仍是 `"user"`。

**复现**：`holdings=[{"600000.SH", weight:0}, {"999999.SH", weight:100}]`
——模型校验器只要求总和 > 0，通过；`999999.SH` 解析不了 → `resolved_weight = 0`
→ `600000.SH` 拿到权重 `1.0`，而 `weight_mode` 还是 `"user"`
→ **第 6 项强制声明「按等权假设计算」不会发出**。

用户以为看到的是自己给的权重，实际是系统替他选的。这正是 D3「不替用户猜」
要防的事，而校验器只挡住了输入层、没挡住这条归一化路径。

**修法**：这种情况应当把 `weight_mode` 改写为 `"equal"`（从而触发声明），
或直接判定为「可解析子集权重和为 0」并返回 422。倾向后者——它和「全部无法解析
→ 422」是同一类情形。

## #6 ~15 条手写 SQL 零自动化覆盖

**位置**：`packages/gr-api/tests/test_diagnosis.py` 整体

37 条测试全部是纯函数，唯一的路由测试把 `get_db` override 成了 `None`。
**测试套件里一条 SQL 都没真正执行过。**

> **对审查原文的一处更正**：审查担心
> `ON CONFLICT (calculation_hash) WHERE status IN (...) DO NOTHING` 的 partial index
> arbiter 推断可能失败、导致「每个 POST 都 500」。**这一条不成立。** 带 `ON CONFLICT`
> 的 INSERT 在**计划阶段**就要求 arbiter 可推断，与是否真的发生冲突无关；而本分支
> 已对本地真库跑通过 `POST /v1/diagnosis/snapshots`（成功建行），因此推断是 work 的。
> 但「缺自动化覆盖」这个主张成立——上面几条正是因此没被挡住。

**修法**：照 `packages/gr-api/tests/test_pick_pg_integration.py` 的模式补一个
`GETRICH_TEST_PG=1` 门控的集成用例，覆盖：POST → result → report 全链路、
幂等命中、跨请求计算复用、`diag.` 前缀是否处处正确（`diag` **不在** search_path）、
`str`→`uuid` 的参数绑定。修完 #1 后尤其要有一条**跨用户复用不串数据**的用例。

## #7 新股窗口把交易日当日历日

**位置**：`services/diagnosis.py:1036`

`(as_of - ld) < timedelta(days=250)` 是**日历日**相减，但 250 是「约一年」的
**交易日**数，而报告里这个字段的标签是「上市不足一年」（`diagnosis.py:1387`）。
上市 300 个日历日的股票只有约 205 个交易日的历史，**不会被标记**，
短历史警告因此漏掉约 4 个月的新股。

**修法**：用 ~365 日历日，或去 `meta.trading_calendar` 数真实交易日。

## #8 `/result` 没取每个 plan 的最新 run

**位置**：`services/diagnosis.py:1175`

`diag.snapshot_run` 的主键是 `(snapshot_id, plan_index, run_id)`，DDL 注释明确写了
「一个 plan 在数据修订后可以指向新的 `run_id`，保留旧关联即为历史归档」。
但 `LEFT JOIN` 没有 `DISTINCT ON` 或取最新的过滤，**一旦重算路径落地**，
一个 plan 有两行 run 就会产生：`plans` 数组重复、SSE `meta` 帧里 `plan_id` 重复、
`len(plans) < len(rows)` 的状态比较失效。

**修法**：`DISTINCT ON (p.plan_index) ... ORDER BY p.plan_index, sr.created_at DESC`。

---

# LOW

| # | 位置 | 问题 | 修法 |
|---|---|---|---|
| 9 | `services/diagnosis.py:301` | 去重用原始 `item.symbol`，而解析走 `parse_symbol` 的 `.strip().upper()`。提交 `["600000.sh","600000.SH"]` 会当成两只：`l1_count`=2、HHI 被低估（0.5 而非 1.0，集中度盲点因此不触发）、`duplicated_symbols` 为空、覆盖率误报 50% | 按归一化后的 `symbol_full` 去重 |
| 10 | `services/diagnosis.py:222` | `date.today()` 用**进程时区**。连接池只钉了会话时区（`pool.py:52`），UTC 主机上 00:00–08:00 CST 之间的请求会解析到**前一个交易日**，整份报告算错日子。违反 AGENTS.md §3.1 | `datetime.now(ZoneInfo("Asia/Shanghai")).date()`，或直接用库里的 `CURRENT_DATE` |
| 11 | `services/diagnosis.py:750`→`802` | check-then-insert 之间没有唯一键冲突处理。同一登录用户并发提交两次相同请求，两边都miss 掉 `SELECT`，其中一个 INSERT 撞 `uq_snapshot_request_hash` → **500 而不是幂等的 200** | 捕获 `UniqueViolation` 后改读，或 `ON CONFLICT ... DO NOTHING RETURNING` |
| 12 | `services/diagnosis.py:951` | 冲突回退路径里 `row["run_id"]` 没防 `None`。若导致 `DO NOTHING` 的那个并发写入方在此处重新 SELECT 前回滚，`row` 为 `None` → `TypeError` → 500。窗口很窄，但**这个分支本来就是为并发写的**，自己不该再有竞态 | 判空后重试或抛明确错误 |
| 13 | `routers/diagnosis.py` 全部端点 | `DiagnosisResult` / `SnapshotAccepted` / `SpecVersionInfo` / `ShareTokenCreated` 都定义了却**没有任何路由挂 `response_model`**，服务层也不按它们校验。`/spec-versions` 直接返 `SELECT *`，`created_at`（不在 `SpecVersionInfo` 里）会漏给前端，将来加列自动泄漏 | 挂 `response_model`；这也是 `NOTES.md`「前后端契约错位」D 节方案 1 的前置条件 |

---

# 验证

修复后验证结果：

```bash
# 从 worktree 根目录跑
uv run pytest packages/gr-api/tests/test_diagnosis.py -v
uv run pytest -v                                    # 实测：2435 passed / 38 skipped
uv run ruff check packages/ scripts/
uv run ruff format --check packages/ scripts/
uv run python scripts/lint_migrations.py
```

真库端到端（worktree 里没有 `.env`，需从 `/home/neo/project/getrich/.env` 复制，
**用完删掉，且绝不要把里面的真实值输出到终端或提交**）：

```bash
uv run uvicorn gr_api.main:app --host 127.0.0.1 --port 8021 --log-level warning &

# 基线断言：等权两只股票 → L1=2, HHI=0.5, L2=2.0, TopN=1.0
curl -s -XPOST localhost:8021/v1/diagnosis/snapshots -H 'Content-Type: application/json' \
  -d '{"plans":[{"plan_id":"p1","holdings":[{"symbol":"600000.SH"},{"symbol":"000001.SZ"}]}]}'

# #1 的回归验证：两个请求持仓等价但 plan_id / 未解析代码不同，
# 各自的 /result 必须各报各的 plan_id 与 unresolved_symbols
# #2 的回归验证：并发开多个 stream，pg_stat_activity 连接数不随之线性增长
```

`diag` schema 已实际迁移到本地 `getrich` 库；若改了 `040_diag.sql`，注意迁移记账按
`file_name + checksum`，**改动会导致整个文件重新应用**，所以 DDL 必须保持幂等
（bootstrap 的两条 INSERT 已经是 `ON CONFLICT DO NOTHING`，别改成裸 INSERT）。

# 收尾（已完成）

已按 `AGENTS.md` §7 更新 `.agent/brain/NOTES.md`，并在 `.agent/brain/DECISIONS.md`
追加 D-050（门控 PG 集成测试连接失败时的凭证泄漏防护）。
