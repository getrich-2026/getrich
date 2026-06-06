# 错误码

本节列出 GetRich 引擎 + 平台层抛出的所有异常类、触发场景与处理建议。

---

## 1. 异常类层级

```text
Exception
└── BacktestError                          # 根异常（不要直接 catch 此异常）
    ├── DataLoadError
    │   ├── BarSchemaError                  # 列名缺失/类型错
    │   ├── TimezoneError                   # naive datetime
    │   └── MissingDataError                # 时间窗口内无数据
    ├── StrategyError
    │   ├── OnBarSignatureError             # on_bar 签名错
    │   ├── SignalError                     # 信号计算错
    │   └── OrderIntentError                # OrderIntent 字段非法
    ├── ExecutionError
    │   ├── InsufficientCashError           # 现金不足
    │   └── LimitHitError                   # 触及涨跌停
    ├── AccountError
    ├── MarginError                         # 保证金不足
    ├── RiskError                           # 触发风控规则
    ├── LiveDataError
    ├── SignalProductionError
    └── PersistenceError

# 平台层
ApiError
├── AuthenticationError    # 401
├── AuthorizationError     # 403
├── NotFoundError          # 404
├── ValidationError        # 422
├── IdempotencyError       # 409
└── ServerError            # 500
```

---

## 2. 引擎异常详解

### 2.1 `BarSchemaError`

**触发条件**：

- K 线 DataFrame 缺少必需列（`dt, symbol, OHLCV`）
- 列 dtype 不匹配（如 `open` 是 `Int32` 而非 `Float64`）
- 包含不允许的列名变体（如 `vol` 而非 `volume`）

**修复**：

```python
from getrich_backtest import validate_bar_schema

validate_bar_schema(bars)  # 提前验证
```

### 2.2 `TimezoneError`

**触发条件**：任何 `datetime` 字段是 naive（无 tzinfo）

**修复**：

```python
from getrich_backtest import get_shanghai_tz
dt = datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
```

> **CLAUDE.md §3.1 铁律**：所有 `dt` 必须 `Asia/Shanghai (UTC+8)` 感知。

### 2.3 `MissingDataError`

**触发条件**：bar loader 在指定 `[start, end]` 窗口内没有数据

**修复**：

1. 检查数据库中是否有该时间窗口的数据
2. 检查 `symbols` 是否正确（拼写错误、大小写）
3. 检查 `freq` 是否匹配数据频率

### 2.4 `OrderIntentError`

**触发条件**：

- `qty` 和 `weight` 同时给（必须二选一）
- `qty` 是负数
- 必填字段缺失（`symbol`、`side`）

**修复**：检查 `OrderIntent` 构造；详见 [核心概念](../engine/concepts.md#3-orderintent)。

### 2.5 `InsufficientCashError`

**触发条件**：账户现金不足以下单（仅 BUY/SELL 平仓且无足够 cash）

**修复**：

1. 检查账户 `initial_cash` 是否够
2. 检查策略 `OrderIntent.qty` 是否过大
3. 启用杠杆交易：传 `margin` 相关参数（仅期货）

### 2.6 `MarginError`

**触发条件**：

- 期货开仓时初始保证金不足
- 维持保证金不足（接近强平线）
- 已被强平

**修复**：

1. 降低杠杆 / 单笔仓位
2. 增加 `initial_cash`
3. 检查 `MarginCalculator.update_instruments()` 是否调用

### 2.7 `RiskError`

**触发条件**：

- 触发 `RiskConfig.margin_call_threshold`
- 触发 `liquidation_threshold`
- 触发 `max_leverage`
- 触发 `max_position_concentration`

**修复**：调整 `RiskConfig` 参数；详见 [执行与账户](../engine/execution-accounting.md)（Phase 2 文档）。

---

## 3. 平台层异常详解

### 3.1 401 Unauthorized（`AuthenticationError`）

**触发条件**：

- Access Token 缺失
- Access Token 过期或无效
- Refresh Token 也过期

**客户端处理**：

1. 静默调用 `/auth/refresh` 获取新 Access Token
2. 用新 Token 重试原请求
3. 仍失败 → 跳转到登录页

### 3.2 403 Forbidden（`AuthorizationError`）

**触发条件**：

- 用户尝试访问不属于自己的资源（IDOR 防护）
- 角色权限不足

**客户端处理**：显示 "无权访问" 提示，跳转到 dashboard。

### 3.3 404 Not Found（`NotFoundError`）

**触发条件**：资源 ID 不存在

**客户端处理**：显示 "资源不存在"，跳转到列表页。

### 3.4 422 Validation Error（`ValidationError`）

**触发条件**：请求体字段缺失或格式错

**响应体**：

```json
{
  "detail": [
    {"loc": ["body", "start"], "msg": "must be datetime", "type": "value_error"}
  ]
}
```

**客户端处理**：在表单上显示具体字段错误。

### 3.5 409 Conflict（`IdempotencyError`）

**触发条件**：同一 `request_hash` 重复提交（幂等防护）

**客户端处理**：查询原 job 状态，跳转到对应详情页。

### 3.6 500 Server Error（`ServerError`）

**触发条件**：未预期的内部错误

**客户端处理**：显示 "服务器开小差了"，重试按钮 + 错误上报。

---

## 4. HTTP 状态码速查

| 状态码 | 含义 | 典型场景 |
|---|---|---|
| 200 OK | 成功 | 查询、创建 |
| 201 Created | 创建成功 | POST /backtests |
| 202 Accepted | 已接受（异步） | POST /backtests（job 排队） |
| 204 No Content | 成功无 body | DELETE |
| 400 Bad Request | 请求体格式错 | JSON 解析失败 |
| 401 Unauthorized | 未鉴权 / Token 过期 | 缺失 Authorization 头 |
| 403 Forbidden | 无权访问 | IDOR 防护 |
| 404 Not Found | 资源不存在 | GET /strategies/<不存在的 code> |
| 409 Conflict | 幂等冲突 | 重复提交 |
| 422 Validation Error | 字段验证失败 | 缺字段、格式错 |
| 429 Too Many Requests | 限流 | 短时间内过多请求 |
| 500 Server Error | 内部错误 | 未捕获的异常 |
| 503 Service Unavailable | 服务暂不可用 | 数据库连接失败 |

---

## 5. 调试技巧

### 5.1 完整 stack trace

```python
import traceback
try:
    bt.run()
except BacktestError as e:
    traceback.print_exc()
    # 日志也会自动包含 stack trace
```

### 5.2 引擎 dry-run

```python
from getrich_backtest import Backtest
from getrich_backtest.exceptions import BacktestError

# 捕获所有引擎错误
try:
    result = bt.run()
except BacktestError as e:
    if isinstance(e, BarSchemaError):
        print(f"Schema error: missing column {e.missing_column}")
    elif isinstance(e, TimezoneError):
        print(f"Timezone error: {e.dt}")
    else:
        raise
```

### 5.3 平台层响应

平台层响应统一是 `ApiResponse<T>` 信封：

```json
{
  "code": 0,
  "message": "ok",
  "data": {...},
  "timestamp": 1717670000,
  "request_id": "req-abc-123"
}
```

错误时 `code != 0`，`data` 包含错误细节。

---

## 6. 源码

- 引擎异常：[`src/getrich_backtest/exceptions.py`](https://github.com/getrich/getrich/blob/main/src/getrich_backtest/exceptions.py)
- 平台异常：[`src/getrich/apps/web/errors.py`](https://github.com/getrich/getrich/blob/main/src/getrich/apps/web/errors.py)
