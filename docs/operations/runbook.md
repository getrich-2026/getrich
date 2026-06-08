# 故障 Runbook

> **本节是 GetRich 平台 8 个最常见故障的处置清单**。每个故障给出：**症状 → 定位 → 缓解 → 根因 → 复盘**。SRE / 值班同学遇到告警时直接对照本文操作。

---

## 目录

1. [API 5xx / DB 连接失败](#1-api-5xx--db-连接失败)
2. [Worker 不消费 / Celery 队列堆积](#2-worker-不消费--celery-队列堆积)
3. [SSE 推送延迟 / 不推](#3-sse-推送延迟--不推)
4. [DB 锁等待 / 长事务](#4-db-锁等待--长事务)
5. [ClickHouse 磁盘满 / 写入失败](#5-clickhouse-磁盘满--写入失败)
6. [Artifact 写失败 / 报告打不开](#6-artifact-写失败--报告打不开)
7. [内存飙升 / OOM](#7-内存飙升--oom)
8. [前端 CSP 拦截 / 浏览器拒加载](#8-前端-csp-拦截--浏览器拒加载)
9. [通用应急 SOP](#9-通用应急-sop)
10. [联系 / 升级路径](#10-联系--升级路径)
11. [进一步阅读](#11-进一步阅读)
12. [文档 CI 故障（gh-pages 部署）](#12-文档-ci-故障（gh-pages-部署）)
13. [备份演练（每月一次 DR drill）](#13-备份演练（每月一次-dr-drill）)

---

## 1. API 5xx / DB 连接失败

### 症状

- 用户报"服务器开小差了"
- Grafana / 探活报 5xx 飙升
- 日志大量 `psycopg.OperationalError`

### 定位

```bash
# 1. 看 API 错误聚合
journalctl -u getrich-api.service --since "10 min ago" | grep -oE 'code=[0-9]+' | sort | uniq -c

# 2. 看 PG 连接数
psql -U quant getrich -c "SELECT count(*) FROM pg_stat_activity;"
psql -U quant getrich -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"

# 3. 看 CH 探活
curl -s http://localhost:8123/ping

# 4. 看池子状态
journalctl -u getrich-api.service | grep -i "pool exhausted"
```

### 缓解

```bash
# 1. 重启 API（最简单）
systemctl restart getrich-api.service

# 2. 如果 PG 连接数耗尽（> 90% of max_connections）
#    a) 查并 kill 长事务
psql -U quant getrich -c "
  SELECT pg_terminate_backend(pid), query, state, age(clock_timestamp(), query_start) AS age
  FROM pg_stat_activity
  WHERE state != 'idle' AND query_start < now() - interval '5 min'
  ORDER BY age DESC;
"
#    b) 临时调大 max_connections（仅紧急）
psql -U quant getrich -c "ALTER SYSTEM SET max_connections = 500; SELECT pg_reload_conf();"
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| `pg_pool` 配置太小 | `min_size=2, max_size=20` | 调大 `max_size` |
| 慢查询拖死连接 | `pg_stat_activity` 看 `query_start` | 加索引 / 改 SQL |
| `ch_pool` 卡住 | `pgrep -af clickhouse` | 重启 CH |
| 网络分区 | `pg_isready -h pg` | 检查 VPC / firewall |

### 复盘

- 监控加 `pg_stat_activity` count > 80% threshold
- `pool_size` 调到与 PG `max_connections / N_workers` 对齐
- 写"长事务检测"SQL 告警

---

## 2. Worker 不消费 / Celery 队列堆积

### 症状

- 用户报"backtest 一直 running 不结束"
- `redis-cli LLEN celery` 持续增长
- Flower 显示 `active=0` 但 `received > 0`

### 定位

```bash
# 1. 看 worker 状态
systemctl status getrich-worker.target
journalctl -u getrich-worker@1.service --since "10 min ago" | tail -50

# 2. 看队列深度
redis-cli LLEN celery

# 3. 看 task 详情
celery -A getrich.apps.worker.celery_app inspect active
celery -A getrich.apps.worker.celery_app inspect scheduled
celery -A getrich.apps.worker.celery_app inspect reserved

# 4. 看 Flower（如果有部署）
curl -s http://localhost:5555/flower/api/tasks | python -m json.tool | head -30
```

### 缓解

```bash
# 1. 重启 worker
systemctl restart getrich-worker.target

# 2. 临时加 worker
systemctl start getrich-worker@2.service

# 3. 取消堆积任务（紧急）
#    a) 找出 stuck job
psql -U quant getrich -c "SELECT id, status, started_at FROM frontend.backtest_jobs WHERE status = 'running' AND started_at < now() - interval '1 hour';"
#    b) 标记为 cancelled（让 worker 跳过）
psql -U quant getrich -c "UPDATE frontend.backtest_jobs SET status = 'cancelled' WHERE id IN (...);"
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| worker 进程崩了 | `systemctl status` | 重启 + 看 crash log |
| 单 task 死循环 | Flower 看 runtime | 加 timeout，加 watchdog |
| 内存泄漏 → OOM | `dmesg \| grep -i kill` | 限制 `--max-tasks-per-child` |
| Redis 满 | `redis-cli INFO memory` | `redis-cli FLUSHDB`（仅 dev） |
| Celery 配置错 | `celery -A ... inspect stats` | 重新读 `celery_app.py` |

### 复盘

- 加 `Celery worker_max_tasks_per_child=100` 防内存泄漏
- 加 task timeout（`task_time_limit=1800`）
- 加 worker 数量自动扩缩

---

## 3. SSE 推送延迟 / 不推

### 症状

- 前端 SSE EventSource 收不到 `event:` 消息
- 用户报"页面卡住，等几秒才有反应"
- 状态变化要 1+ 秒才反映（说明 fallback 1s 轮询在工作）

### 定位

```bash
# 1. 看 listener 是否 alive
ps aux | grep -E "uvicorn|getrich"
journalctl -u getrich-api.service | grep -i "BacktestJobListener\|pg_notify"

# 2. 看 NOTIFY 队列使用率
psql -U quant getrich -c "SELECT pg_notification_queue_usage();"
# > 0.5 表示队列快满（< 8GB 内存时）

# 3. 看 listener 收到的事件数（debug log）
journalctl -u getrich-api.service | grep -c "BacktestJobListener.*event"
```

### 缓解

```bash
# 1. 重启 API（重置 listener）
systemctl restart getrich-api.service

# 2. 临时提高 PG `max_locks_per_transaction`（如果 listener 连接数打满）
psql -U quant getrich -c "ALTER SYSTEM SET max_locks_per_transaction = 256;"

# 3. 紧急降级：前端轮询（已有 fallback）
#    当前 EventSource 实现有 1s setTimeout 兜底，无需操作
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| listener 断了未重连 | journald | Round #1077 已实现 reconnect loop，确认 5s sleep 在跑 |
| PG `LISTEN` 配额满 | `pg_notification_queue_usage` | 增加 `shared_buffers` |
| web 进程崩溃 | `systemctl status` | restart |
| browser 主动断开（用户切 tab） | 前端 console | 切回时自动 reconnect |
| 反向代理缓冲 | nginx config | `proxy_buffering off;` |

### 复盘

- 加 Prometheus `sse_push_latency_seconds` histogram
- 加 `pg_notification_queue_usage` 告警（> 0.5）

---

## 4. DB 锁等待 / 长事务

### 症状

- API P99 飙升但 5xx 不增加
- `pg_stat_activity` 大量 `state=active` + 长 `query_start`
- 用户报"操作卡住"

### 定位

```bash
# 1. 找长事务
psql -U quant getrich -c "
SELECT pid, state, query, age(clock_timestamp(), query_start) AS age, wait_event
FROM pg_stat_activity
WHERE state != 'idle' AND query_start < now() - interval '1 min'
ORDER BY age DESC LIMIT 20;
"

# 2. 找锁等待
psql -U quant getrich -c "
SELECT blocked_locks.pid AS blocked_pid,
       blocking_locks.pid AS blocking_pid,
       blocked_activity.query AS blocked_query,
       blocking_activity.query AS blocking_query
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
  AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
"

# 3. 找慢查询
psql -U quant getrich -c "
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 20;
"
```

### 缓解

```bash
# 1. 取消长事务（保留数据）
psql -U quant getrich -c "SELECT pg_cancel_backend(<pid>);"

# 2. 强制 kill（事务会回滚）
psql -U quant getrich -c "SELECT pg_terminate_backend(<pid>);"

# 3. 临时增大 lock 配额
psql -U quant getrich -c "ALTER SYSTEM SET max_locks_per_transaction = 512; SELECT pg_reload_conf();"
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| migration 跑一半卡住 | `pg_stat_activity` 查 DDL | `pg_terminate_backend` 后重跑 |
| 大 UPDATE 没索引 | `pg_stat_statements` | 加索引 / 分批 |
| 同一行多 worker 写 | `pg_locks` | 改 UPSERT / 加 advisory lock |
| sweeper worker 全表扫 | EXPLAIN ANALYZE | 加 WHERE 条件 + 索引 |
| `pg_dump` 锁库 | 看 `pg_dump` 进程 | 用 `--no-acl --no-owner` 并行 |

### 复盘

- 加 `pg_stat_activity` count > 50 active 告警
- 加 `pg_stat_statements` top-10 慢查询每日报告
- migration 加 `lock_timeout = '5s'`

---

## 5. ClickHouse 磁盘满 / 写入失败

### 症状

- live signal 跑完没落库
- API `code=5000`, 日志 `ClickHouseDiskSpaceException`
- `du -sh /var/lib/clickhouse` 显示 > 90%

### 定位

```bash
# 1. 看磁盘
df -h /var/lib/clickhouse
du -sh /var/lib/clickhouse/data/*

# 2. 看大表
clickhouse-client --query "
SELECT database, table, formatReadableSize(sum(bytes_on_disk)) AS size
FROM system.parts
WHERE active
GROUP BY database, table
ORDER BY sum(bytes_on_disk) DESC
LIMIT 20;
"

# 3. 看 TTL 情况
clickhouse-client --query "
SELECT database, table, count() AS parts
FROM system.parts
WHERE active
GROUP BY database, table
ORDER BY parts DESC
LIMIT 20;
"
```

### 缓解

```bash
# 1. 手动 DROP PARTITION（释放空间）
clickhouse-client --query "
ALTER TABLE getrich.bar_1d DROP PARTITION '202301';
"

# 2. 强制 TTL 触发
clickhouse-client --query "SYSTEM MERGES getrich.bar_1d;"

# 3. 临时扩大磁盘（紧急）
#    改挂载点 / 加盘
systemctl stop clickhouse-server
# ... 加盘 / 扩 LVM
systemctl start clickhouse-server

# 4. 紧急降级：禁用 live signal（systemd）
systemctl stop getrich-signals.timer
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| 5 年前的 bar 没清 | `system.parts` 看 `min/max(dt)` | 调 TTL（当前 5y）或加 partition drop |
| 写入峰值突发 | `system.query_log` 看 INSERT QPS | 限流 / 加 buffer |
| 备份残留 | `ls /backup/ch/` | 清旧备份 |
| ZooKeeper 满 | ZK 日志 | `DU` 配额 |

### 复盘

- 监控 `df -h /var/lib/clickhouse` 阈值 80%
- 监控 `system.parts` 数量（> 1000 = 合并积压）
- 加 `merge_tree.max_parts_in_total = 1000`

---

## 6. Artifact 写失败 / 报告打不开

### 症状

- 用户报"下载报告 404"
- TearSheet 文件不存在但 PG `backtest_artifacts` 表有记录
- MinIO 报 403/500

### 定位

```bash
# 1. 看 artifact 表
psql -U quant getrich -c "SELECT run_id, artifact_type, uri FROM frontend.backtest_artifacts WHERE run_id = '...' ORDER BY created_at DESC;"

# 2. 看文件是否存在
ls -la /var/lib/getrich/artifacts/<run_id>/

# 3. 看 BacktestStorageConfig
grep -A5 "BacktestStorage" src/getrich/config/settings.py

# 4. 看 /content endpoint 日志
journalctl -u getrich-api.service | grep "/content"
```

### 缓解

```bash
# 1. 重新生成缺失 artifact
uv run python -c "
from getrich_backtest import Backtest, PgBacktestResultStore
# ... 找到缺失的 run_id 重新跑
"

# 2. 临时：让 /content 服务从 DB 流
#    （如果 artifact 存在但 storage 挂了）
#    apps/web/services/backtest_run.py::stream_artifact_file 有 fallback
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| 磁盘满 | `df -h` | 同 §5 |
| 权限错 | `ls -la` | `chown getrich:getrich` |
| MinIO 凭证过期 | MinIO 日志 | 重生 access key |
| `BACKEND_TYPE` 错配 | settings | 检查 `BacktestStorageConfig` |
| NFS 挂载断了 | `mount` | `mount -a` |

### 复盘

- 监控 artifact 目录大小
- 加 artifact health check（每天扫一次）

---

## 7. 内存飙升 / OOM

### 症状

- `dmesg | grep -i kill` 显示 OOM Killer
- API / worker 突然重启
- Grafana 内存曲线陡升

### 定位

```bash
# 1. 看哪个进程
ps aux --sort=-%mem | head -10

# 2. 看 Python 进程
ps -o pid,rss,vsz,cmd -p <pid>

# 3. 抓 heap dump
py-spy dump --pid <pid>

# 4. 看历史 RSS 曲线（如果装了 prometheus）
#    node_memory_rss 或 process_resident_memory_bytes
```

### 缓解

```bash
# 1. 重启（最简单）
systemctl restart getrich-api.service
# 或
systemctl restart getrich-worker@1.service

# 2. 临时限制内存
systemctl edit getrich-api.service
#   [Service]
#   MemoryMax=4G
#   MemoryHigh=3G

# 3. 调小 worker concurrency
systemctl edit getrich-worker@1.service
#   [Service]
#   Environment=CELERY_CONCURRENCY=2
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| Backtest equity 50 万行 × 多个 strategy | 内存监控 | 流式写 PG（已实现） |
| CH 拉取大表 | `system.query_log` | 加 LIMIT / 用 sample |
| Matplotlib 后端 | import 占用 | 用 plotly / 减少 fig |
| DataFrame 复制 | py-spy | 删 `.copy()` 链 |
| SweepRunner 不释放 | `del result` 后 GC | 显式 `del` |

### 复盘

- 加 `worker_max_tasks_per_child=100` 防内存泄漏
- 加 Prometheus RSS 告警（> 80% MemoryMax）
- 限制单 task 内存（`--max-memory-per-child=2G`）

---

## 8. 前端 CSP 拦截 / 浏览器拒加载

### 症状

- 浏览器 console 报错 `Refused to load the script ... violates Content-Security-Policy`
- 浏览器 console 报错 `Refused to apply inline style ...`
- 某些第三方 CDN 资源加载失败
- `strategy.detail_html` 里的图片 / 链接失效

### 定位

```bash
# 1. 浏览器 F12 → Console → 看 CSP violation
# 2. 看响应头
curl -sI https://getrich.example.com/ | grep -i "content-security-policy"
# 3. 看 middleware 配置
grep -A10 "csp_policy" src/getrich/config/settings.py
```

### 缓解

```bash
# 1. 临时：开发环境用 "default-src * 'unsafe-inline' 'unsafe-eval'"
#    （生产**绝对不允许**）

# 2. 长期：在 CSP 里加白名单
#    例如允许 jsdelivr CDN：
#    csp_policy = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline';"
```

### 根因（典型）

| 根因 | 检查 | 修法 |
|---|---|---|
| inline `<script>` | console | 改 `script-src 'self'` + 外部文件 |
| inline `<style>` | console | 加 `'unsafe-inline'` 到 `style-src` |
| 第三方 CDN | network tab | 加 `https://cdn.example.com` 到对应 src |
| `data:` URI 图 | 资源加载错 | `img-src 'self' data:` |
| `strategy.detail_html` 用了 `<img>` | 浏览器 inspector | 改用 `<a href>` 外链；或 `img-src https://` 加白 |

### 复盘

- Round #1024 加了 CSP 头（4 个静态头 + 动态 CSP）
- 新增第三方域名时**必须**同步更新 CSP 白名单
- CI 跑前端 build 时带 `csp-evaluator` 检测

---

## 9. 通用应急 SOP

### 9.1 快速诊断 4 步

```bash
# 1. 进程在不在？
systemctl status getrich-api.service
systemctl status getrich-worker.target
systemctl status clickhouse-server
systemctl status postgresql

# 2. 端口在不在？
ss -tlnp | grep -E ":(8000|6379|5432|8123)"

# 3. 日志有异常吗？
journalctl -u getrich-api.service --since "5 min ago" --no-pager | tail -30

# 4. 探活通吗？
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health
```

### 9.2 紧急回滚

```bash
# 1. 切到上一个 commit
cd /opt/getrich
git log --oneline -5
git checkout <last-good-commit>

# 2. 重装依赖
uv sync --frozen

# 3. 重启所有服务
systemctl restart getrich-api.service
systemctl restart getrich-worker.target

# 4. 验证
curl -s http://localhost:8000/health
```

### 9.3 升级通知

- 内部 IM 群（飞书/Slack）发"开始回滚"
- 标注预计恢复时间
- 完成后发"已恢复，影响时间 X 分钟"

---

## 10. 联系 / 升级路径

| 严重度 | 升级到 | 通知方式 |
|---|---|---|
| P3（已知问题） | - | 异步 |
| P2（影响 1 个用户） | 团队 lead | IM |
| P1（影响 10+ 用户） | 全组 + on-call | IM + 电话 |
| P0（服务完全挂） | 创始人 / VP | 全员 |

> 联系信息见团队 Confluence "On-call 排班"。

---

## 11. 进一步阅读

- 监控：[监控与告警](monitoring.md)
- systemd：[systemd 部署](systemd.md)
- 数据库拓扑：[数据库拓扑](database-topology.md)
- 设计契约：
    - [30 执行引擎](../design-contracts/30-execution-engine.md)
    - [31 账户与保证金](../design-contracts/31-account-margin.md)
    - [32 风险控制](../design-contracts/32-risk-control.md)
- 内部 IM：<https://feishu.example.com/getrich>
- on-call 排班：<https://confluence.example.com/oncall>

---

## 12. 文档 CI 故障（gh-pages 部署）

> **本节是 `.github/workflows/docs.yml` 5 类故障的处置清单**。
> 文档 CI 跟业务 CI 一样会在 PR 上跑，区别在
> (a) 它不跑 pytest，只跑 `mkdocs build --strict`
> (b) main / dev push 触发 gh-pages 部署
> 监控入口：`.github/workflows/docs.yml` 的 run history。

### 12.1 症状：mkdocs build --strict 失败

#### 定位

```bash
# 1. 本地复现：与 CI 一致的环境
uv run --frozen mkdocs build --strict --clean

# 2. 跑验证脚本（预检）
uv run python scripts/verify_docs_ci.py
#   - 第 [3/4] 步会跑相同的 strict build
#   - 第 [4/4] 步会验证 site/index.html / size / subdir 完整性
```

#### 根因（典型）

| 根因 | 修法 |
|---|---|
| 死链：加了新页但没在 mkdocs.yml `nav:` 登记 | 加 nav 条目；或加到 omitted_files 忽略清单 |
| 死链：相对路径写错（`engine/...` 写成 `../engine/...`） | 相对路径以 docs 源文件位置为基准 |
| `pymdownx.tabbed` 嵌套超 3 层 | 拆 tab 或用 `=== "title"` 扁平化 |
| Mermaid 语法错 | 本地起 `mkdocs serve` 看浏览器 console 报错 |
| `mkdocstrings` 找不到类 | `paths: [src]` 配置 + 类是否在 `__all__` |
| git-revision-date-localized 报 WARNING | 新文件没 commit history；`fetch-depth: 0` 已配，等下次 commit |

### 12.2 症状：gh-pages deploy 失败

#### 定位

```bash
# 1. 看 deploy job 的 Actions 日志
#    重点是 "Upload to GitHub Pages" 和 "Deploy to GitHub Pages" 两步

# 2. 最常见：actions/upload-pages-artifact 报
#    "Error: Path does not exist"
#    意味着 site/ 没生成
ls -la site/index.html      # 本地跑过 verify_docs_ci.py 必存在
```

#### 根因（典型）

| 根因 | 修法 |
|---|---|
| `site/index.html` 缺失 | build job 失败；先查 §12.1 |
| `actions/upload-pages-artifact` 版本过旧 | 升级到 v5（Round #1156 已升级） |
| `permissions: pages: write` 缺失 | 已在 docs.yml 配好；新环境要确认 repo settings → Pages |
| `concurrency` 冲突 | 同 PR 多 push；`cancel-in-progress: true` 已配 |
| `environment: github-pages` 没建 | repo Settings → Environments → New → name: github-pages |

#### 手动强制重部署

```bash
# 在 GitHub UI：
# 1. Actions → Docs workflow → 失败 run
# 2. 右上角 "Re-run all jobs"
# 或：
gh workflow run docs.yml --ref dev
```

### 12.3 症状：部署后页面 404

#### 定位

```bash
# 1. 打开 https://getrich.github.io/getrich/ 测主页
# 2. 找具体死链
#    mkdocs build --strict 应该已经捕获，没有就查 build log
curl -sI https://getrich.github.io/getrich/platform/live-signal-pipeline/ | head -1
# 应为 200 OK；404 即问题
```

#### 根因（典型）

| 根因 | 修法 |
|---|---|
| `use_directory_urls: true` 但没部署 `index.html` | mkdocs 自动生成，build 失败即无；查 §12.1 |
| 子页有跨目录相对链接但没 `..` | 修链接为 `../engine/live-signals.md` |
| gh-pages 缓存 | 浏览器 hard refresh (Ctrl+Shift+R) |
| CDN 缓存 5-10 分钟 | 等；或 Cloudflare purge |

### 12.4 症状：strict-mode warning（非 ERROR）

#### 定位

`mkdocs build --strict` 把 WARNING 当 ERROR。
**所有 WARNING 必须解决**。常见：

```text
WARNING -  A relative path to 'foo.md' is included in the 'nav' configuration,
            which is not found in the documentation files
WARNING -  Documentation file 'docs/x.md' is not included in the "nav" configuration
WARNING -  An absolute path to '/x.md' is included in the 'nav', which is not found
WARNING -  A relative path to '../foo.md' is included in the 'nav'
```

#### 修法

| 根因 | 修法 |
|---|---|
| 忘了加到 nav | 加条目 |
| 路径写错 | 改成相对 docs 根的路径 |
| validation 配置太严 | mkdocs.yml 已有 `omitted_files: ignore` / `absolute_links: ignore`，需要时再调 |

### 12.5 预防：pre-push 验证（Round #1154）

```bash
# 任何 push docs 相关改动前都跑：
uv run python scripts/verify_docs_ci.py

# 4 步：workflow YAML 解析 → glob 校验 → strict build → deploy-step 输入校验
# 全绿才推，省去一次 round-trip
```

`scripts/verify_docs_ci.py` 跑的事与 CI 完全一致，
**本地绿 = CI 必绿**。

### 12.6 进一步阅读

- 文档 CI 配置：`.github/workflows/docs.yml`（含 Round #1156 升级到 v5 的注释）
- 预检脚本：`scripts/verify_docs_ci.py`（4 步本地验证）
- 验证脚本测试：`tests/scripts/test_verify_docs_ci.py`（6+ regression tests）
- Material i18n 文档：<https://squidfunk.github.io/mkdocs-material/setup/setting-up-site-search/#language>
- i18n 路线图：[../translations.md](../translations.md)

---

## 13. 备份演练（每月一次 DR drill）

> **本节是 `scripts/backup/` 6 个脚本的实战演练 SOP**。备份在没人测过的情况下约等于没有 ——
> 月度演练的目的是让 SRE 在真正出事时不用在 P0 故障中边读代码边敲命令。
> 监控入口：`/var/log/getrich/backup.log` + `journalctl -u getrich-backup.service --since='-30d'`。

### 13.1 演练节奏

| 频率 | 责任人 | 范围 | 通过标准 |
|---|---|---|---|
| 每月 1 日 | SRE on-call | 随机抽最近 7 天的 1 个 PG dump + 1 个 CH snapshot | restore 在 4h 内完成；sanity check 全过 |
| 季度 | Tech lead | **全量**：PG + CH + artifact 恢复到独立 sandbox | 业务可冷启动到「接受首单」状态 |
| 灾备演练（年度） | 全 SRE 团队 | 切流量到 standby | RPO ≤ 24h, RTO ≤ 4h |

### 13.2 演练前置

```bash
# 1. 确认最新备份存在
ls -lh /var/backups/getrich/pg/ | tail -3
ls -lh /var/backups/getrich/ch/ | tail -3
ls -lh /var/backups/getrich/artifact/ | tail -3

# 2. 准备 scratch 资源（不污染 prod）
#    - PG: 临时建一个 getrich_restore_scratch 库
#    - CH: 临时一个 data dir 挂载点
#    - artifact: 一个 /tmp/getrich-artifact-drill 目录
PG_NEW_DB="getrich_restore_scratch_$(date +%s)"
CH_DATA=/var/lib/clickhouse-drill
ARTIFACT_DIR=/tmp/getrich-artifact-drill
mkdir -p "${CH_DATA}" "${ARTIFACT_DIR}"
chown clickhouse:clickhouse "${CH_DATA}"
```

### 13.3 PG 演练

```bash
# 1. 选 dump（取最近 7 天里体积最大的，挑大概率命中写）
DUMP=$(ls -t /var/backups/getrich/pg/*.dump | head -1)
echo "Restoring: ${DUMP}"
ls -lh "${DUMP}"

# 2. 创建空库
sudo -u postgres createdb "${PG_NEW_DB}"

# 3. 恢复
sudo -u postgres /opt/getrich/scripts/backup/pg_restore.sh "${DUMP}" "${PG_NEW_DB}"

# 4. Sanity check（脚本内置的 6 项校验）
#    - 必须看到 "Restore verified" 才算过
#    - 主要关注 frontend.* 表行数与生产 diff < 5%
```

**典型耗时**：1 GB dump ≈ 2 min（`pg_restore --jobs=4`）

**常见失败 & 修法**：

| 现象 | 根因 | 修法 |
|---|---|---|
| `pg_restore: error: could not execute query: ERROR: relation "xxx" already exists` | 上次演练残留 | `sudo -u postgres dropdb "${PG_NEW_DB}"` 重做 |
| `FATAL: password authentication failed` | PGPASSWORD_FILE 路径错 | 检查 `/etc/getrich/.pgpass` 权限 0600, owner getrich |
| 恢复后 `frontend.strategies` 行数为 0 | 用了 `--section=pre-data` 之类的误参数 | 严格用 `pg_restore.sh` 包装脚本，不直跑底层命令 |

### 13.4 ClickHouse 演练

```bash
# 1. 选最近一个 freeze
SNAP=$(ls -td /var/backups/getrich/ch/freeze-* | head -1)
echo "Restoring CH from: ${SNAP}"

# 2. 停 server（演练服务器是独立的，不影响 prod）
sudo systemctl stop clickhouse-drill.service   # 假设演练用独立 unit

# 3. 恢复
sudo -u clickhouse /opt/getrich/scripts/backup/ch_restore.sh "${SNAP}"

# 4. 启 server
sudo systemctl start clickhouse-drill.service

# 5. Sanity check
clickhouse-client --query "SELECT count() FROM default.md_bars_1m" --database default
# 预期：行数与生产同窗口的 diff < 5%
clickhouse-client --query "SELECT partition, count() FROM system.parts WHERE database='default' AND table='md_bars_1m' AND active GROUP BY partition ORDER BY partition" | head -10
# 预期：每个 partition 都有 active parts
```

**典型耗时**：100 GB 行情表 ≈ 8 min（`rsync -a` + chown 是瓶颈）

**常见失败 & 修法**：

| 现象 | 根因 | 修法 |
|---|---|---|
| `ERROR: clickhouse-server is still running` | 演练 unit 名字错或没停 | 改用演练专属的 `clickhouse-drill.service`，配置独立的 `path=` |
| restore 后 `md_bars_1m` 0 rows | `rsync` 把空目录当 source | 检查 `${SNAP}/data/` 是否非空（freeze 失败时是空目录） |
| `chown: cannot access ...` | 演练机的 clickhouse user uid 不同 | 加 `useradd -u <same-uid> clickhouse` 对齐 |

### 13.5 Artifact 演练

```bash
# 1. 选最近一个 tar
TAR=$(ls -t /var/backups/getrich/artifact/*.tar.zst | head -1)
echo "Restoring artifact: ${TAR}"

# 2. 恢复（脚本会做完整性校验）
sudo /opt/getrich/scripts/backup/artifact_backup.sh --restore "${TAR}" "${ARTIFACT_DIR}"

# 3. 抽样打开一个 parquet
ls "${ARTIFACT_DIR}/runs/$(ls -t "${ARTIFACT_DIR}"/runs | head -1)/equity.parquet"
python -c "import polars as pl; print(pl.read_parquet('${ARTIFACT_DIR}/runs/$(ls -t ${ARTIFACT_DIR}/runs | head -1)/equity.parquet').shape)"
# 预期：(> 100, 5) 至少 100 个 bar、5 列 OHLCV 衍生
```

**典型耗时**：10 GB artifact ≈ 1 min

### 13.6 演练报告（必填）

演练结束后 24h 内由当班 SRE 在 `docs/operations/dr-drills/` 下写一份 markdown 报告，模板：

```markdown
# DR Drill YYYY-MM-DD

- 执行人：<姓名>
- 范围：PG | CH | Artifact | 全量
- 选择的备份文件：<dump / snapshot / tar 路径>
- 恢复耗时：<mm 分钟>
- Sanity check：通过 / 部分失败 / 失败
- 失败项：<具体哪个表/文件>
- 根因 + 修法：<填在 SRE 排障表里>
- 备份策略是否调整：是（见 commit <hash>）/ 否
- 备份脚本是否调整：是（见 commit <hash>）/ 否
```

### 13.7 升级路径

| 失败严重度 | 升级对象 | 通知方式 |
|---|---|---|
| 单次演练失败但脚本本身没问题（如磁盘满） | 当班 SRE | 飞书 SRE 群 |
| **连续 2 个月**演练失败 | Tech lead | 飞书 + 邮件 |
| 备份脚本本身有 bug（导致演练根本起不来） | Tech lead + 平台 owner | PagerDuty P3 |
| 真实灾备触发 | 平台 owner + CTO | PagerDuty P1 + 全员飞书 |

### 13.8 进一步阅读

- 备份脚本源码：`scripts/backup/`（6 个 bash 脚本 + 2 个 systemd unit）
- 备份脚本测试：`tests/scripts/test_backup_scripts.py`（14 passed, 9 skipped）
- 备份日志：`/var/log/getrich/backup.log`
- systemd timer：`scripts/backup/getrich-backup.{service,timer}`
- 历史演练报告：`docs/operations/dr-drills/`
- CH FREEZE 机制：<https://clickhouse.com/docs/en/operations/backup#backup-as-a-copy-of-remote-filesystem>
- pg_dump -Fc 格式：<https://www.postgresql.org/docs/current/app-pgdump.html>

---

## 14. Admin Import（策略导入）异常

> Admin Import 是后台批量导入/更新策略定义的通道，通过 `/v1/admin/imports/*` 暴露（仅 `admin` 角色可访问）。
> 6 个端点：`upsert` / `preview` / `{job_code}/commit` / `history` / `{job_code}` / `{job_code}/errors`。
> 详见：[`reference/database-schema.md`](../reference/database-schema.md#import_jobs) 的 `import_jobs` 表段。

### 14.1 症状

- `POST /v1/admin/imports/strategies/upsert` 返回 5xx
- `GET /v1/admin/imports/history` 一直 0 行
- `GET /v1/admin/imports/{job_code}/errors` 报 404
- 导入 preview 通过但 commit 后 strategies 表未变化

### 14.2 定位

```bash
# 1) 确认 router 已挂载（fastapi 启动日志应包含 'admin-imports' tag）
journalctl -u getrich-api -n 200 | grep -i admin-imports

# 2) 确认 admin 角色正确（无 admin 角色 → 403）
psql -d getrich -c "SELECT id, role FROM user_auth WHERE email = 'admin@…';"

# 3) 看最新 import job 的状态
psql -d getrich -c "SELECT job_code, status, summary, file_name, created_by, created_at
                    FROM import_jobs ORDER BY created_at DESC LIMIT 5;"

# 4) 失败明细
psql -d getrich -c "SELECT row_number, column_name, error_code, message
                    FROM import_job_errors
                    WHERE job_id = (SELECT id FROM import_jobs WHERE job_code = '<JOB_CODE>')
                    ORDER BY row_number LIMIT 50;"

# 5) 端到端烟囱（不需要 admin 角色也能跑 — 应直接 401/403）
curl -i http://localhost:8000/v1/admin/imports/history
```

### 14.3 缓解

| 故障 | 处置 |
|---|---|
| router 未挂载 → 404 | 确认 `apps/web/main.py` 有 `app.include_router(admin_imports_router.router, prefix="/v1")`，重启 `getrich-api` |
| 403 Forbidden | 确认调用者 role='admin'（不是 'user'） |
| 401 Unauthorized | JWT 过期或缺失，重新登录拿新 token |
| `error_message: 'CSV too many rows'` | 单批 ≤ 10,000 行；拆分文件再上传 |
| `error_message: 'schema mismatch'` | 校验 CSV 表头是否匹配 Pydantic `StrategyUpsertIn` 字段，参考 [API 参考](../platform/api-reference.md) |
| commit 成功但 strategies 未变 | 检查 `_delete_existing_records` 是否被跳过（已有专门测试覆盖） |
| preview 一直 200 但从未 commit | 手动 commit：等待操作员 review，或触发 `pg_notify` 唤醒 SSE |

### 14.4 根因（典型）

- **P1：CSV 行数 > 10,000** — 单元测试覆盖，但前端未做客户端预检
- **P2：detail_html 长度 > 64 KB** — Pydantic `max_length` + 024 migration 的 `CHECK` 约束都会拦截
- **P2：admin 角色误判** — `user_auth.role` 字段被旧 migration 漏改；运行 `scripts/sql/grant-admin.sql <email>`
- **P3：CSV 编码不是 UTF-8** — admin 上传 GBK 编码 CSV；Pydantic 报错 `UnicodeDecodeError`

### 14.5 复盘

- 是否漏写迁移？→ `python -m getrich.migrations.cli status` 应显示 `admin_imports` 已应用
- 单元测试是否覆盖到？→ `tests/getrich/apps/web/test_admin_import.py`（36 个测试）
- 是否需要 re-run preview？→ preview 不可重入（每次都是新 `job_code`），错误需手动修 CSV 后重新上传

### 14.6 进一步阅读

- Service 源码：`src/getrich/apps/web/services/admin_import.py`（约 600 行）
- Router 源码：`src/getrich/apps/web/routers/admin_imports.py`
- 迁移脚本：`migrations/025_admin_imports.sql`（如未应用则先 `python -m getrich.migrations.cli postgres`）
- Schema 定义：[`reference/database-schema.md`](../reference/database-schema.md#admin_imports)
- 单元测试：`tests/getrich/apps/web/test_admin_import.py`
- OpenAPI 标签：`admin-imports`（`/v1/admin/imports/*`）


