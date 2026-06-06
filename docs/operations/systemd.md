# systemd 部署

本节介绍在生产环境用 **systemd** 部署 GetRich 平台。4 个 unit + 1 target 协同工作。

> 部署文件位于仓库根目录的 `getrich-*.service` 和 `getrich-worker.target`。

---

## 1. 服务清单

| Unit | 类型 | 启动顺序 | 作用 |
|---|---|---|---|
| `getrich-broker.service` | simple | 1（最先） | Redis 服务（Celery broker） |
| `getrich-api.service` | simple | 2 | FastAPI + uvicorn |
| `getrich-worker@{1..4}.service` | simple（template） | 3 | Celery worker 池（4 个并发） |
| `getrich-worker.target` | target | 3 | 聚合 4 个 worker |
| `getrich-signals.service` | oneshot | 4 | 实盘信号生成（被 timer 触发） |
| `getrich-signals.timer` | timer | 4 | 每 5 分钟触发 signals.service |

---

## 2. 服务依赖图

```mermaid
graph LR
    Broker[getrich-broker.service<br/>Redis]
    API[getrich-api.service<br/>FastAPI :8000]
    Worker1[getrich-worker@1.service]
    Worker2[getrich-worker@2.service]
    Worker3[getrich-worker@3.service]
    Worker4[getrich-worker@4.service]
    Target[getrich-worker.target]
    Signals[getrich-signals.service<br/>oneshot]
    Timer[getrich-signals.timer<br/>OnCalendar=*:0/5]

    Broker --> API
    Broker -.Wants.-> Target
    API --> Worker1
    API --> Worker2
    API --> Worker3
    API --> Worker4
    Target --> Worker1
    Target --> Worker2
    Target --> Worker3
    Target --> Worker4
    Timer --> Signals
```

关键点：

- `getrich-worker.target` 用 `Wants=`（**不是** `Requires=`）—— 单个 worker 死了不会拖垮整个 target
- `getrich-api.service` 与 `getrich-worker.target` 互相独立启动（不互相 wait）

---

## 3. 各 Unit 详解

### 3.1 `getrich-broker.service`（Redis）

```ini
[Unit]
Description=GetRich Redis broker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=neo
ExecStart=/usr/bin/redis-server /etc/redis/getrich.conf
Restart=on-failure
RestartSec=5s
LimitNOFILE=65536
Before=getrich-worker.target

[Install]
WantedBy=multi-user.target
```

**配置**：

- `LimitNOFILE=65536` —— Redis 需要高 fd 限制
- `Before=getrich-worker.target` —— 在 worker 之前启动

### 3.2 `getrich-api.service`（FastAPI）

```ini
[Unit]
Description=GetRich FastAPI
After=network-online.target getrich-broker.service
Wants=network-online.target

[Service]
Type=simple
User=neo
WorkingDirectory=/opt/getrich
EnvironmentFile=/opt/getrich/.env
ExecStart=/opt/getrich/.venv/bin/uv run uvicorn getrich.apps.web.main:app \
    --host 0.0.0.0 --port 8000 --workers 1
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

**关键约束**：

- **`--workers 1`**（强制）：inproc backend 绑定单进程；多 worker 会导致 inproc 状态分裂
- `EnvironmentFile`：所有 env 变量统一管理
- `WorkingDirectory=/opt/getrich`：项目根

### 3.3 `getrich-worker@.service`（Celery worker 模板）

```ini
[Unit]
Description=GetRich Celery worker %i
After=network-online.target getrich-broker.service
Wants=network-online.target

[Service]
Type=simple
User=neo
WorkingDirectory=/opt/getrich
EnvironmentFile=/opt/getrich/.env
ExecStart=/opt/getrich/.venv/bin/uv run python -m getrich.apps.worker.cli worker --concurrency=1
Restart=on-failure
RestartSec=5s
TimeoutStopSec=300

[Install]
WantedBy=getrich-worker.target
```

**实例化**：

```bash
# 启动 4 个 worker
systemctl enable --now getrich-worker@{1..4}.service
```

**关键约束**：

- `concurrency=1`：每个 worker 进程 1 个并发任务（与 `--workers 1` API 配合：4 worker × 1 = 4 个并行 backtest）
- `TimeoutStopSec=300`：给长 backtest 5 分钟优雅停止
- `WantedBy=getrich-worker.target`（不是 `multi-user.target`）：通过 target 间接拉起

### 3.4 `getrich-worker.target`（聚合）

```ini
[Unit]
Description=GetRich worker pool
After=getrich-broker.service
Wants=getrich-broker.service

[Install]
WantedBy=multi-user.target
```

**关键约束**：

- 用 `Wants=`（**不是** `Requires=`）：单个 worker 死了不影响 target 整体健康
- `systemctl status getrich-worker.target` 列出所有 worker 的聚合状态

### 3.5 `getrich-signals.service`（oneshot）

```ini
[Unit]
Description=GetRich live signal generator
After=network-online.target getrich-broker.service

[Service]
Type=oneshot
User=neo
WorkingDirectory=/opt/getrich
EnvironmentFile=/opt/getrich/.env
ExecStart=/opt/getrich/.venv/bin/uv run python -m getrich.apps.strategy.cli signals
TimeoutStartSec=600
```

**关键约束**：

- `Type=oneshot`：单次执行，不保持运行
- `TimeoutStartSec=600`：给信号生成最多 10 分钟

### 3.6 `getrich-signals.timer`（定时器）

```ini
[Unit]
Description=Trigger GetRich signal generator every 5 minutes

[Timer]
OnCalendar=*:0/5
RandomizedDelaySec=30
Persistent=true

[Install]
WantedBy=timers.target
```

**关键约束**：

- `OnCalendar=*:0/5`：每小时的 0/5/10/.../55 分
- `RandomizedDelaySec=30`：随机 0-30 秒延迟（防多个实例同时跑）
- `Persistent=true`：开机后补跑错过的触发

---

## 4. 部署流程

### 4.1 首次部署

```bash
# 1. 准备环境
sudo useradd -m -s /bin/bash neo
sudo -u neo bash -c "cd /opt && git clone <repo-url> getrich && cd getrich && uv sync --extra dev"

# 2. 配置环境
sudo -u neo cp .env.example .env
sudo -u nano nano .env  # 填入生产配置

# 3. 初始化数据库
sudo -u neo bash -c "cd /opt/getrich && uv run python -m getrich.migrations.cli all"

# 4. 复制 unit 文件
sudo cp getrich-*.service getrich-*.timer getrich-worker.target /etc/systemd/system/
sudo systemctl daemon-reload

# 5. 启用并启动
sudo systemctl enable --now getrich-broker.service
sudo systemctl enable --now getrich-api.service
sudo systemctl enable --now getrich-worker.target
sudo systemctl enable --now getrich-signals.timer
```

### 4.2 启动顺序

systemd 会按 `After=` / `Before=` 自动排序：

1. `getrich-broker.service`（Redis）
2. `getrich-api.service`（等待 broker）
3. `getrich-worker@{1..4}.service`（被 target 拉起）
4. `getrich-signals.timer` → `getrich-signals.service`（每 5 分钟）

### 4.3 验证

```bash
# 状态总览
sudo systemctl status getrich-broker getrich-api getrich-worker.target getrich-signals.timer

# 详细日志
sudo journalctl -u getrich-api -f
sudo journalctl -u getrich-worker@1 -f

# API 健康检查
curl http://localhost:8000/health
```

---

## 5. 升级流程

```bash
# 1. 拉新代码
cd /opt/getrich
sudo -u neo git pull

# 2. 更新依赖
sudo -u neo uv sync --extra dev

# 3. 应用新 migrations
sudo -u neo uv run python -m getrich.migrations.cli all

# 4. 重启服务（从依赖图尾部开始）
sudo systemctl restart getrich-api
sudo systemctl restart getrich-worker.target

# 5. 验证
sudo journalctl -u getrich-api --since "1 minute ago" | grep -i error
curl http://localhost:8000/health
```

> **零停机升级**：API 用 uvicorn `--workers 1` 不支持热重载；先启新 worker 再杀旧 worker 即可。Celery 用 `celery control cancel_consumer` 优雅替换。

---

## 6. 监控

```bash
# 进程存活
systemctl is-active getrich-api getrich-worker.target

# 资源占用
systemctl status getrich-api | grep Memory
systemctl status getrich-worker@1 | grep CPU

# 日志轮转（journalctl 默认就有）
journalctl -u getrich-api --since "1 day ago" --output json | jq

# 实时跟踪
journalctl -u getrich-api -f -n 100
```

详见 [监控](monitoring.md)（Phase 2 文档）。

---

## 7. 故障处理

| 故障 | 排查 | 修复 |
|---|---|---|
| API 502 | `journalctl -u getrich-api` | 检查 PG/CH 连接；重启 API |
| Worker 不消费 | `journalctl -u getrich-worker@1` | 检查 Redis；检查 task_routes |
| SSE 推送延迟高 | 监控 `pg_notify` 队列深度 | 检查 [BacktestJobListener](monitoring.md) |
| DB 锁等待 | `SELECT * FROM pg_locks` | 找持锁进程，kill |

详见 [Runbook](runbook.md)（Phase 2 文档）。

---

## 8. 部署检查清单

部署前对照检查：

- [ ] `JWT_SECRET` 已替换为生产强随机（≥ 32 字符）
- [ ] `CSP_POLICY` 去掉 `unsafe-inline` / `unsafe-eval`
- [ ] `BACKTEST_ARTIFACT_DIR` 设为绝对路径
- [ ] `PG_PASSWORD` / `CLICKHOUSE_PASSWORD` / `JWT_SECRET` 全部在 `/opt/getrich/.env` 中，无明文
- [ ] 防火墙：8000 (API)、6379 (Redis，仅本机)、8123 (CH，本机或内网) 端口
- [ ] Prometheus exporter 或 healthcheck endpoint 已配
- [ ] backup 任务已配（[运维 / 备份策略](index.md)）
- [ ] `.agent/brain/NOTES.md` 的踩坑记录已通读
