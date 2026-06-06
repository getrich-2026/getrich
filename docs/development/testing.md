# 测试

本节介绍 GetRich 项目的测试体系、运行命令与最佳实践。

---

## 1. 测试栈

| 层级 | 工具 | 用途 |
|---|---|---|
| 后端单元/集成 | `pytest` | 引擎 + 服务层 |
| 前端单元 | `vitest` | React 组件 + 工具函数 |
| 前端组件 | `@testing-library/react` | 行为级测试 |
| 类型检查 | `basedpyright` | Python type check（CI） |
| 静默失败扫描 | `scripts/find_silent_fails.py` | CI 强制门禁 |
| Lint | `ruff check` + `ruff format` | 后端格式 |
| Lint | `eslint` | 前端格式 |
| E2E | 手动（暂无 Playwright） | 关键流程验证 |

---

## 2. 后端测试

### 2.1 运行所有测试

```bash
# 引擎（不需要 live DB）
uv run pytest tests/getrich_backtest/ -v --durations=10

# 平台
uv run pytest tests/getrich/ -v --durations=10

# 完整
uv run pytest tests/ -v --durations=10
```

### 2.2 运行单个测试文件

```bash
uv run pytest tests/getrich_backtest/test_api.py -v
```

### 2.3 运行单个测试函数

```bash
uv run pytest tests/getrich_backtest/test_api.py::TestBacktest::test_basic_run -v
```

### 2.4 按关键字过滤

```bash
uv run pytest tests/ -k "macross" -v
```

### 2.5 跳过需要 live DB 的测试

```bash
uv run pytest tests/ -v --durations=10 -m "not integration"
```

---

## 3. 覆盖率

```bash
uv run pytest tests/ --cov=src/getrich_backtest --cov=src/getrich/apps --cov-report=html
# 报告：htmlcov/index.html
```

CI 覆盖率最低门槛：**80%**。

---

## 4. 前端测试

### 4.1 运行

```bash
cd frontend

# 监听模式
npm run test

# 一次性
npm run test -- --run

# UI 模式
npm run test:ui
```

### 4.2 按文件过滤

```bash
npm run test -- --run src/pages/Dashboard.test.tsx
```

### 4.3 覆盖率

```bash
npm run test -- --run --coverage
```

CI 覆盖率最低门槛：**70%**。

---

## 5. 编写测试

### 5.1 后端：引擎测试

模板（`tests/getrich_backtest/test_my_strategy.py`）：

```python
import pytest
from decimal import Decimal
from datetime import datetime
from getrich_backtest import (
    Backtest, DataFrameBarLoader, MyStrategy, ZeroFee, ZeroSlippage,
    get_shanghai_tz,
)
import polars as pl


def test_my_strategy_generates_trades():
    """Smoke test: 策略至少产生 1 笔成交。"""
    bars = build_synthetic_bars(["A", "B"], n_days=60)
    bt = Backtest(
        strategy=MyStrategy(),
        bar_loader=DataFrameBarLoader(bars),
        symbols=["A", "B"],
        start=datetime(2024, 1, 1, tzinfo=get_shanghai_tz()),
        end=datetime(2024, 3, 1, tzinfo=get_shanghai_tz()),
        initial_cash=Decimal("100000"),
        fee_model=ZeroFee(),
        slippage_model=ZeroSlippage(),
        freq="1d",
    )
    result = bt.run()
    assert result.metrics().total_trades >= 1


def build_synthetic_bars(symbols, n_days=60):
    """构造测试数据。"""
    rows = []
    import random
    rng = random.Random(42)
    for sym in symbols:
        base = rng.uniform(50, 200)
        for i in range(n_days):
            dt = datetime(2024, 1, 1, 9, 30, tzinfo=get_shanghai_tz())
            dt = dt.replace(day=1 + i)
            close = base * (1 + rng.uniform(-0.05, 0.05))
            rows.append({
                "dt": dt, "symbol": sym,
                "open": close * 0.99, "high": close * 1.02, "low": close * 0.98,
                "close": close, "volume": rng.uniform(1e5, 1e6),
            })
    return pl.DataFrame(rows).sort(["symbol", "dt"])
```

### 5.2 前端：组件测试

模板（`src/pages/MyPage.test.tsx`）：

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import MyPage from "./MyPage";

vi.mock("../api/myapi", () => ({
  myQuery: vi.fn(),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <MyPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("MyPage", () => {
  it("renders loading state", () => {
    // ... test loading
  });
  it("renders data on success", async () => {
    // ... test success
  });
  it("renders error state on failure", async () => {
    // ... test error
  });
});
```

---

## 6. 静默失败扫描

**CLAUDE.md §7 + scripts/find_silent_fails.py**：

```bash
# 严格模式（CI 用）：任何未声明的 try/except: log 都会失败
python scripts/find_silent_fails.py --strict

# 列出已声明的 silent-fail
python scripts/find_silent_fails.py
```

任何新增的 `try/except: log` 必须配 `# silent-fail-ok: <reason>` 注释：

```python
try:
    result = await asyncio.wait_for(connect(), timeout=5)
except asyncio.TimeoutError:
    logger.warning("connect timeout")  # silent-fail-ok: dev-only fast fail
```

CI 会拦截未声明的版本（见 [CI 工作流](#ci-工作流)）。

---

## 7. 常见模式

### 7.1 测试 PG 持久化

```python
import pytest
from getrich.libs.postgres.pool import pg_pool

@pytest.fixture
async def pg_pool_init():
    await pg_pool.init()
    yield pg_pool
    await pg_pool.close()


@pytest.mark.integration
async def test_persist_backtest(pg_pool_init):
    store = PgBacktestResultStore()
    await store.save_result(...)
    loaded = await store.load_result(...)
    assert loaded.run_id == "..."
```

集成测试需要 `pytest-asyncio` + 真实 PG/CH/Redis；CI 在 job 启动 services 容器。

### 7.2 测试 CELERY 任务

```python
from apps.worker.celery_app import celery

def test_backtest_run_job():
    """直接同步执行 Celery 任务（CI 默认 GETRICH_WORKER_BACKEND=inproc）。"""
    result = celery.send_task(
        "apps.worker.tasks.backtest.run_job",
        args=["job-123"],
    )
    assert result.successful()
```

CI 环境变量 `GETRICH_WORKER_BACKEND=celery` + Redis 服务，模拟生产。

### 7.3 测试 SSE 流

```python
async def test_stream_events():
    events = []
    async for event in stream_job_events("job-1", request=mock_request):
        events.append(event)
        if len(events) >= 3:
            break
    assert events[0].startswith("event: update")
```

---

## 8. CI 工作流

```bash
# 完整 CI 一键运行
uv run ruff check src/ tests/                # Lint
uv run ruff format --check src/ tests/       # 格式检查
uv run pytest tests/ -v --durations=10       # 测试
python scripts/find_silent_fails.py --strict # 静默失败扫描

# 前端
cd frontend
npm run lint
npm run test -- --run
npm run build
```

GitHub Actions 自动跑这 6 步；详见 [CI 工作流](ci-workflow.md)（Phase 2 文档）。
