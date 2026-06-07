# 负载测试（k6）

> **本节讲解 GetRich 平台的 k6 负载测试套件**。4 个测试脚本（`auth_smoke` / `read_traffic` / `backtest_submit` / `live_signals`）覆盖 4 类典型流量：登录鉴权、仪表盘浏览、回测提交、实盘信号消费。所有脚本自带 k6 `thresholds`，CI / SRE 拿 SLO 直配即可。
>
> 源码：`loadtest/*.js`

---

## 1. 测试套件全景

| 脚本 | 流量类别 | 是否需要 auth | VU / 时长（默认） | 主要 SLO 阈值 |
|---|---|---|---|---|
| `auth_smoke.js` | 登录 / 注册 | ❌ | 10 VU × 30s | login p95 < 500ms, refresh p95 < 300ms, errors < 1% |
| `read_traffic.js` | 仪表盘浏览 | ✅ | 50 VU × 5min（~100 RPS） | 5 个 read endpoint p95 < 300/500ms, errors < 1% |
| `backtest_submit.js` | 回测提交 + 轮询 | ✅ | 5 VU × 2min | submit p99 < 800ms, poll p99 < 200ms, errors < 5% |
| `live_signals.js` | 实盘信号 list + mark-read | ✅ | 30 VU × 3min（~10 RPS） | list p95 < 250ms, mark_read p95 < 200ms, errors < 0.5% |

> **VU 配比的理由**：
> - `auth_smoke` 单独跑，CI smoke 用，无 auth
> - `read_traffic` 模拟"50 个活跃会话"，**总 RPS ~100** = 平台设计目标
> - `backtest_submit` 故意用 5 VU（而非 50），因为重负载在 worker 池而非 API
> - `live_signals` 30 VU × 每 3s 一次 = 10 RPS，模拟实时面板

---

## 2. 安装 k6

```bash
# macOS
brew install k6

# Debian / Ubuntu
sudo apt install k6

# Windows
winget install k6
# 或 scoop 用户: scoop install k6

# 验证
k6 version
```

> k6 是单 Go 二进制，无运行时依赖。CI 镜像预装即可（Ubuntu 22.04+ apt repo 可用）。

---

## 3. 运行测试

### 3.1 本地 smoke

```bash
# 启动后端 (uvicorn)
uv run uvicorn getrich.apps.web.main:app --host 0.0.0.0 --port 8000 &

# 10 VU × 30s，CI 等价 smoke
k6 run --vus 10 --duration 30s loadtest/auth_smoke.js
```

### 3.2 跑真实部署

```bash
export BASE_URL=https://staging.getrich.example.com
export TEST_USER_EMAIL=stress@example.com
export TEST_USER_PASSWORD=stresspw123

# 仪表盘浏览（5 分钟，~100 RPS）
k6 run loadtest/read_traffic.js

# 回测提交（2 分钟）
k6 run --vus 5 --duration 2m loadtest/backtest_submit.js

# 实盘信号（3 分钟，~10 RPS）
k6 run loadtest/live_signals.js
```

### 3.3 覆盖默认 VU/时长

每个脚本支持 `K6_VUS` / `K6_DURATION` env 覆盖：

```bash
K6_VUS=20 K6_DURATION=60s k6 run loadtest/auth_smoke.js
```

> 容量规划时把 K6_VUS 拉到 200 看水平扩展上限。

---

## 4. 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | API 根 |
| `TEST_USER_EMAIL` | `loadtest@example.com` | 鉴权脚本的用户邮箱 |
| `TEST_USER_PASSWORD` | `loadtest-pw-12345` | 鉴权脚本的用户密码 |
| `K6_VUS` | 各脚本默认 | 覆盖并发用户数 |
| `K6_DURATION` | 各脚本默认 | 覆盖测试时长 |

> ⚠️ **测试账号**必须在目标环境预创建；`read_traffic` 等脚本会调真实接口（`/strategies` 等），没有数据时 200 + 空 list 是合法响应。

---

## 5. SLO 阈值（与监控一致）

> 详见 [监控 - SLO 指标](monitoring.md#6-关键-slo--指标)

| 流量类别 | p50 | p95 | p99 | 错误率 |
|---|---|---|---|---|
| 登录（bcrypt bound） | < 100ms | < 500ms | < 800ms | < 1% |
| 仪表盘 read | < 50ms | < 300ms | < 500ms | < 1% |
| Equity / monthly（聚合） | < 100ms | < 500ms | < 1s | < 1% |
| 回测 submit（INSERT） | < 100ms | < 300ms | < 800ms | < 0.1% |
| 回测 poll（SSE-backed GET） | < 50ms | < 150ms | < 200ms | < 0.1% |
| 信号 list | < 50ms | < 250ms | < 400ms | < 0.5% |
| 信号 mark-read（UPDATE） | < 30ms | < 200ms | < 300ms | < 0.1% |

**阈值演进原则**（记录在 `loadtest/README.md` 头部）：
1. 新接口先以 5x 当前观测值定阈值，**留安全余量**
2. 季度 review，按 P95/P99 分布调整（**不向 P99 看齐**，向 P95 看齐）
3. 错误率阈值永不 > 1%（除 `backtest_submit` 因业务有合法 fail）

---

## 6. 测试输出解读

### 6.1 终端摘要

```
     ✓ login status 200
     ✓ login returns access_token
     ✓ refresh status 200
     ✓ refresh returns access_token

     checks.........................: 100.00% ✓ 1234  ✗ 0
     http_req_duration..............: avg=247ms  p(95)=412ms  p(99)=598ms
     http_reqs......................: 1234   41.13/s
     errors.........................: 0.00%  ✓ 0     ✗ 0
```

| 指标 | 看什么 | 行动 |
|---|---|---|
| `checks` 通过率 | 应 = 100% | < 100% → 看哪个 check 失败 |
| `http_req_duration{p(95)}` | 与阈值对比 | 超阈值 → k6 exit 1 |
| `errors` rate | < 阈值 | 超阈值 → DB / 5xx 排查 |
| `http_reqs/s` | 实际 RPS | 远低于目标 → VU 不够 |

### 6.2 JSON 报告（推荐 CI 收）

```bash
k6 run --out json=results.json loadtest/read_traffic.js
# 然后用 k6-reporter / jmeter-to-csv 等工具转 HTML
```

> 推荐工具链：`k6-reporter` (HTML 报告) / `xk6` (扩展) / `k6 Cloud` (SaaS 商业版)。

---

## 7. CI 集成

### 7.1 自动跑（Round #1162 + Round #1173 follow-up）

`.github/workflows/loadtest.yml`：

```yaml
name: Load test (staging smoke)
on:
  push:
    branches: [dev, main]
  schedule:
    # 每周一 06:00 UTC 跑（亚洲工作时间窗）
    - cron: '0 6 * * 1'
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: grafana/k6-action@v0.3.0
        with:
          filename: loadtest/auth_smoke.js
          flags: --vus 10 --duration 30s
        env:
          BASE_URL: ${{ secrets.STAGING_BASE_URL }}
          TEST_USER_EMAIL: ${{ secrets.LOADTEST_USER_EMAIL }}
          TEST_USER_PASSWORD: ${{ secrets.LOADTEST_USER_PASSWORD }}
```

> **不在 main PR 上跑重型脚本**（`read_traffic` / `backtest_submit`）—— 防止 staging 被打爆。SRE 在 capacity-planning 时手动触发。

### 7.2 手动触发（重型）

```bash
# 容量规划：在 staging 跑 read_traffic 拉 200 VU
K6_VUS=200 K6_DURATION=10m k6 run loadtest/read_traffic.js

# 性能回归：单次回测提交压测
K6_VUS=20 K6_DURATION=5m k6 run loadtest/backtest_submit.js
```

---

## 8. 故障排查

### 8.1 5xx 风暴

**症状**：`errors` 率 > 5%，全是 500/502/503。

**排查**：

1. 看后端日志：`journalctl -u getrich-api --since "5 min ago" | grep -E " 5[0-9]{2} "`
2. 看 DB 连接池：`SELECT count(*) FROM pg_stat_activity;`（> 50 即瓶颈）
3. 看 worker 队列：`redis-cli LLEN celery`（> 100 即背压）
4. 看 CH 慢查询：`system.query_log` 最近 5min

**修复**：

- DB 池满：加 `pool_size` 或扩 `getrich-api` 进程
- Worker 队列深：扩 `getrich-worker@.service` 数量（4 → 8）
- CH 慢：检查 `live_optimizer` 是否在跑

### 8.2 p95 超阈值但无 5xx

**症状**：所有请求 200，但 p95 超阈值。

**排查**：

1. `histogram_quantile(0.95, ...)` 看是哪个 endpoint 慢
2. 检查慢 endpoint 的 DB query plan（`EXPLAIN ANALYZE`）
3. 检查是否在跑 nightly batch（如 `live_optimize` cron）

**修复**：

- 加 index
- 加 cache（Redis）
- 错峰调度（heavy job 移凌晨）

### 8.3 login 慢（> 500ms p95）

**症状**：`auth_smoke` 报 login p95 超阈值。

**原因**：bcrypt 算力 + DB 查询。bcrypt cost 改大后 p95 会跳。

**修复**：

- 验证 bcrypt cost（默认 12，期望 ~250ms 单次）
- 确认 `users.password_hash` 字段是 bcrypt（不是 SHA256）

### 8.4 SSE 长连接 k6 兼容性

k6 不支持长连接 SSE 模拟（HTTP/1.1 + EventStream）。如需测 SSE 路径，写 Python `httpx` 脚本或 `wrk` + Lua 脚本。

> 当前 `backtest_submit.js` 走 **短轮询**（`poll` 路径）模拟 SSE 消费者 —— 准确性 90%，完全够用。

---

## 9. 容量规划清单

| 阶段 | 测试 | 目标 | 行动 |
|---|---|---|---|
| **新版本上线** | `auth_smoke` (10 VU) | 100% pass | 必须过 |
| **新功能上线** | 对应类别的 30s 烟囱 | 不引入回归 | 推荐 |
| **月度容量 review** | `read_traffic` 100 VU / 10min | p95 < 500ms | 必跑 |
| **架构变更后** | `backtest_submit` 20 VU / 5min | 错误率 < 1% | 必跑 |
| **大促 / 行情高峰前** | `live_signals` 100 VU / 30min | 错误率 < 0.5% | 必跑 |

---

## 10. 进一步阅读

- 监控：[监控与告警](monitoring.md)（SLO 来源）
- 故障处理：[Runbook](runbook.md)
- 源码：[`loadtest/*.js`](https://github.com/getrich/getrich/blob/main/loadtest/)
- 工具：
    - [k6 官方文档](https://k6.io/docs/)
    - [k6 thresholds 指南](https://k6.io/docs/using-k6/thresholds/)
    - [k6-reporter (HTML 报告)](https://github.com/benc-uk/k6-reporter)
