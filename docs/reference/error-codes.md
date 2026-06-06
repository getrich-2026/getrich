# 错误码

> **本节列出 GetRich 引擎 + 平台层抛出的所有异常类、HTTP 错误码、响应体形状、客户端处理建议。** 所有平台层错误统一经 [`apps/web/response.py::register_exception_handlers`](https://github.com/getrich/getrich/blob/main/src/getrich/apps/web/response.py) 包装成 `ApiResponse` 信封。

---

## 1. 错误响应体形状

**所有**平台层错误（4xx / 5xx）返回统一的 JSON：

```json
{
  "code": 4040,
  "message": "strategy 'MACross' not found",
  "data": null,
  "timestamp": 1717670000,
  "request_id": "9b1c4f2e..."
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | int | 业务错误码（**不与 HTTP status 相同**，见 §4） |
| `message` | str | 人类可读消息 |
| `data` | any / null | 附加上下文（通常是 null） |
| `timestamp` | int | Unix epoch seconds |
| `request_id` | str | trace ID（用于日志关联） |

> `x-request-id` header / `request_id` 字段都是同一个值。前端可以在用户报错弹窗里显示这个 ID 让 SRE 直接 grep 日志。

---

## 2. 异常类层级

### 2.1 引擎层（`getrich_backtest`）

> 源码：`src/getrich_backtest/exceptions.py`

```text
Exception
└── BacktestError                          # 根异常（不要直接 catch 此异常）
    ├── TimezoneError                      # naive datetime
    ├── BarSchemaError                     # K 线列名/类型错
    ├── DataLoadError                      # bar loader 失败（通用）
    ├── ExecutionError                     # 撮合失败（通用）
    ├── AccountError                       # 账户状态错（通用）
    │   ├── CorporateActionError           # 分红/送股/拆股
    │   └── MarginError                    # 保证金不足
    ├── StrategyError                      # 策略代码错（通用）
    │   └── OrderIntentError               # OrderIntent 字段非法
    ├── MetricsError                       # 指标计算失败
    ├── RetryableError                     # SweepRunner/WF 标记"可重试"
    └── TerminalError                      # SweepRunner/WF 标记"终止"
```

### 2.2 平台层（`apps/web`）

> 源码：`src/getrich/apps/web/errors.py`

```text
ApiError                                  # 基类，http_status=400, code=1000
├── NotFound          # http_status=404, code=4040
├── BadRequest        # http_status=400, code=4000
├── Forbidden         # http_status=403, code=4030
├── Unauthorized      # http_status=401, code=4010
└── Conflict          # http_status=409, code=4090

# 非 ApiError 类型（在 response.py handler 中处理）
RequestValidationError  # Pydantic 422  → 统一映射到 code=4220
Exception               # 未捕获异常   → 统一映射到 code=5000
```

---

## 3. 平台层错误详解

### 3.1 `Unauthorized`（HTTP 401, code 4010）

> `apps/web/errors.py::Unauthorized`

**触发**：

- 缺 `Authorization: Bearer <jwt>` header
- JWT 过期 / 签名错
- `get_current_user` 解析失败且 `X-User-Id` fallback 也没设

**响应示例**：

```json
{
  "code": 4010,
  "message": "auth required: please log in",
  "data": null,
  "timestamp": 1717670000,
  "request_id": "9b1c4f2e..."
}
```

**客户端处理**（`frontend/src/api/_client.ts`）：

```typescript
if (response.status === 401) {
  // 1) 静默调 /auth/refresh
  const refreshed = await tryRefresh();
  if (refreshed) return retry(response.request);
  // 2) 跳登录页
  navigate('/login');
}
```

> 详见 [Phase B 实施 Round #232-#234](https://github.com/getrich/getrich/blob/main/.agent/brain/NOTES.md)。

### 3.2 `Forbidden`（HTTP 403, code 4030）

**触发**：

- 跨用户访问（IDOR 防护）—— Round #880-#889 + #1014 + #1062
- 角色权限不足（未来 RBAC）

**响应示例**：

```json
{
  "code": 4030,
  "message": "forbidden: strategy 'strat-x' belongs to another user",
  "data": null,
  "request_id": "..."
}
```

**客户端处理**：显示 "无权访问" 提示，跳转到 dashboard。

### 3.3 `NotFound`（HTTP 404, code 4040）

**触发**：

- 资源 ID 不存在
- 用户主动删除了某资源

**响应示例**：

```json
{
  "code": 4040,
  "message": "backtest run 'run-001' not found",
  "data": null,
  "request_id": "..."
}
```

**客户端处理**：显示 "资源不存在"，跳转到列表页。

### 3.4 `BadRequest`（HTTP 400, code 4000）

**触发**：

- 业务逻辑层校验失败（如 `start > end`、`qty <= 0`）
- 状态机非法转换（如取消已完成 job）

**响应示例**：

```json
{
  "code": 4000,
  "message": "start date must be before end date",
  "data": null,
  "request_id": "..."
}
```

**客户端处理**：在表单 / 详情页上显示具体 message。

### 3.5 `Conflict`（HTTP 409, code 4090）

**触发**：

- 幂等冲突（同一 `request_hash` 已存在）—— 023 migration
- 重复用户名 / 邮箱注册
- 资源版本冲突（乐观锁）

**响应示例**：

```json
{
  "code": 4090,
  "message": "idempotency: job 'job-001' already exists for this request",
  "data": {"existing_job_id": "job-001"},
  "request_id": "..."
}
```

**客户端处理**：

- 幂等冲突 → 调 `GET /v1/backtest-jobs/{existing_job_id}` 跳详情页
- 注册冲突 → 在表单字段显示 "该邮箱已注册"

### 3.6 Pydantic 422 → `code 4220`

**触发**：FastAPI `RequestValidationError`（请求体字段缺失、类型错）

**响应示例**：

```json
{
  "code": 4220,
  "message": "body.start: must be datetime (type=value_error)",
  "data": null,
  "request_id": "..."
}
```

**实现位置**：`apps/web/response.py::_handle_validation_error` —— 取首个错误的 `loc` + `msg` 拼成可读消息。

### 3.7 未捕获 → `code 5000`

**触发**：任何未在 handler 中显式处理的 `Exception`

**响应示例**：

```json
{
  "code": 5000,
  "message": "internal error: <异常类名 + str(exc)>",
  "data": null,
  "request_id": "..."
}
```

> ⚠️ 生产环境**不应**把原始 `str(exc)` 暴露给客户端（可能泄漏内部状态、SQL、路径）。该行为是开发/测试环境用的；生产应在 `response.py` 中替换为 `"internal error, see request_id"`。

---

## 4. HTTP 状态码 ↔ 业务错误码速查

| HTTP status | ApiError 子类 | code | 触发 |
|---|---|---|---|
| 200 | — | 0 | 成功（`code=0`） |
| 201 | — | 0 | 创建成功 |
| 202 | — | 0 | 异步任务入队（job_id 已返回） |
| 204 | — | — | DELETE 成功无 body |
| 400 | `BadRequest` | 4000 | 业务校验失败 |
| 401 | `Unauthorized` | 4010 | 缺/失效 token |
| 403 | `Forbidden` | 4030 | 跨用户 / 权限不足 |
| 404 | `NotFound` | 4040 | 资源不存在 |
| 409 | `Conflict` | 4090 | 幂等冲突 / 重复 |
| 422 | `RequestValidationError` | 4220 | Pydantic 字段错 |
| 429 | — | 4290 | 限流（未来） |
| 500 | `Exception` | 5000 | 未捕获异常 |
| 503 | — | 5030 | DB 不可用（未来） |

> 业务 code（4000-4220 等）独立于 HTTP status。前端**应该优先看 `code`** —— HTTP 500 也可能是业务上预期的"软失败"。

---

## 5. 引擎层异常详解

> 引擎层异常**不经过** `ApiResponse` 包装。`Backtest.run()` / `SweepRunner.run()` 会**直接 raise**，调用方负责处理。

### 5.1 `TimezoneError`

**触发**：任何 `datetime` 字段是 naive（无 `tzinfo`）

**修复**：

```python
from getrich_backtest import get_shanghai_tz
dt = datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
```

> **CLAUDE.md §3.1 铁律**：所有 `dt` 必须 `Asia/Shanghai (UTC+8)` 感知。

### 5.2 `BarSchemaError`

**触发**：

- K 线 DataFrame 缺少必需列（`dt, symbol, open, high, low, close, volume`）
- 列 dtype 不匹配（如 `open` 是 `Int32` 而非 `Float64`）
- 包含不允许的列名变体（如 `vol` 而非 `volume`）

**修复**：

```python
from getrich_backtest import validate_bar_schema
validate_bar_schema(bars)  # 提前验证
```

### 5.3 `DataLoadError`

**触发**：`BarLoader.load_bars()` 抛底层 IO 错误

**修复**：

1. 检查数据库连接（`pg_pool` / `ch_pool`）
2. 检查 `symbols` 拼写
3. 检查日期窗口是否合理

### 5.4 `OrderIntentError`（继承自 `StrategyError`）

**触发**：

- `qty` 和 `weight` 同时给（必须二选一）
- `qty` 是负数
- 必填字段缺失（`symbol`、`side`）

**修复**：检查 `OrderIntent` 构造；详见 [OrderIntent 字段](../engine/concepts.md)。

### 5.5 `MarginError`（继承自 `AccountError`）

**触发**：

- 期货开仓时初始保证金不足
- 维持保证金不足（接近强平线）
- 已被强平

**修复**：

1. 降低杠杆 / 单笔仓位
2. 增加 `initial_cash`
3. 检查 `MarginCalculator.update_instruments()` 是否调用

### 5.6 `MetricsError`

**触发**：`compute_metrics()` / `compute_benchmark_comparison()` 内部计算失败（如 equity 全 0、std 为 0）

**修复**：检查数据完整性；通常意味着回测根本没运行成功。

### 5.7 `RetryableError` / `TerminalError`

> 引擎层标记信号；SweepRunner / WalkForwardRunner 据此决定是否重试。

| 异常 | 触发 | Runner 行为 |
|---|---|---|
| `RetryableError` | 临时故障（DB blip、network timeout） | 按 `retry` 策略重试 |
| `TerminalError` | 配置错误（bad param、schema 不匹配） | 立刻 `mark_failed`，不再重试 |

> 业务代码 raise 后 **不**需要自己 catch —— runner 已统一处理。

---

## 6. 调试技巧

### 6.1 完整 stack trace

```python
import traceback
try:
    bt.run()
except BacktestError as e:
    traceback.print_exc()
    # 日志也会自动包含 stack trace（logging.exception）
```

### 6.2 平台层 5xx 排查

1. **复制 `request_id`**（从错误弹窗 / 响应体）
2. **SRE grep 日志**：`journalctl -u getrich-api.service | grep <request_id>`
3. 日志行包含完整 stack trace + DB query + 调用链

### 6.3 平台层 422 修复

```json
{
  "code": 4220,
  "message": "body.start: must be datetime (type=value_error)"
}
```

`body.start` 表示 `request.body.start` 字段；`must be datetime` 是 Pydantic 错误消息。

### 6.4 引擎 dry-run

```python
from getrich_backtest import Backtest
from getrich_backtest.exceptions import BacktestError

try:
    result = bt.run()
except BacktestError as e:
    if isinstance(e, BarSchemaError):
        print(f"Schema error: {e.missing_column}")
    elif isinstance(e, TimezoneError):
        print(f"Timezone error: {e.dt}")
    else:
        raise
```

---

## 7. 常见错误

| 症状 | 真正原因 | 修法 |
|---|---|---|
| 4010 但带了 token | JWT 过期 | 客户端 `tryRefresh()` + 重试 |
| 4010 但没带 token | `require_user` 依赖生效 | 客户端加 token；或者用 `get_current_user`（返回 None） |
| 4030 跨用户访问 | IDOR 防护 | 检查 service 层是否漏 `user_id` 过滤 |
| 4040 但资源存在 | 软删 / race | `GET` 前先刷一次列表 |
| 4090 幂等冲突 | 同 `request_hash` 重复提交 | 客户端读 `data.existing_job_id` 跳详情 |
| 4220 Pydantic 错 | 字段类型/必填错 | 看 `message` 里的 `loc` + `type` |
| 5000 但生产显示 | 原始 `str(exc)` 漏出 | 改 `response.py` 不在生产暴露细节 |
| SweepRunner 一直 `RetryableError` | 真有 DB blip | 看 worker 日志，PG 慢查询？ |
| SweepRunner 一直 `TerminalError` | 配置错 | 检查 `RunConfig` / strategy 字段 |

---

## 8. 进一步阅读

- API：[Web API 参考 — 响应形状](../platform/api-reference.md)
- 设计契约：[60 客户端接口](../design-contracts/60-client-api.md)
- 中间件：[平台架构 — 异常处理](../platform/architecture.md#5-异常处理)
- 源码：
    - [`src/getrich/apps/web/errors.py`](https://github.com/getrich/getrich/blob/main/src/getrich/apps/web/errors.py)
    - [`src/getrich/apps/web/response.py`](https://github.com/getrich/getrich/blob/main/src/getrich/apps/web/response.py)
    - [`src/getrich_backtest/exceptions.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/exceptions.py)
