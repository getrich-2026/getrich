# Codex CLI Local Instructions — GetRich

Project-level constraints for the GetRich platform. Universal behaviors, agent routing, and coding baselines are defined in `~/.codex/AGENTS.md`. Primary project spec: `CLAUDE.md`.

---

## 1. Backend (Python 3.10+)

- **No Heavy ORM**: Hand-write native SQL with `psycopg3`'s `AsyncConnectionPool`. Use COPY protocol or multi-values UPSERT (`ON CONFLICT DO UPDATE`) for bulk writes.
- **Financial Precision**: Use `decimal.Decimal` for all monetary calculations (balances, PnL, fees). Never `float`.
- **Return Types**: Explicitly distinguish `simple_return` vs `log_return` in function signatures and docstrings.

## 2. Frontend (React 19 + TypeScript 5.9 + Vite 7)

- **Strict TypeScript**: No `any`. API types in `src/types/`, matching backend Pydantic schemas.
- **API Clients**: All network requests exported from `src/api/` (using `src/api/client.ts`). Never inline `fetch`/`axios` in components.
- **Async State**: `@tanstack/react-query` (`useQuery`/`useMutation`) for all data fetching. No `useEffect` + `useState` polling.
- **Forms**: `react-hook-form` + `zod` validation.
- **UI**: `src/components/ui/` (shadcn/ui) + Tailwind CSS 3. Charts: `echarts` for time-series/equity curves, `recharts` for statistical plots.

## 3. Database Boundaries

- **PostgreSQL (`getrich`)**: Single source of truth for business/transactional data (strategies, signals, subscriptions, billing, trades). Supports transactions and `ON CONFLICT DO UPDATE`.
- **ClickHouse**: Immutable time-series only (OHLCV bars, ticks, factors). Use `MergeTree` with `PARTITION BY`, `ORDER BY`, `TTL`. **Never** run transactional queries or row-level updates/deletes.
- **DuckDB**: In-memory ad-hoc analytics. No persistent state.

## 4. Timezone & Night Sessions

- **Timezone**: `Asia/Shanghai (UTC+8)` platform-wide.
- **ClickHouse**: `DateTime64(3, 'Asia/Shanghai')` for all time fields. Convert naive datetimes via `.astimezone(tz).date()` before writing `Date`/`Date32` columns.
- **Night Sessions**: Futures night sessions (21:00–02:30) must use `DateTime64`. Never use `Date` for night session indexing.

## 5. Look-Ahead Bias Prevention

- Backtest signals must use `shift`/`lag` to ensure decisions at time $T$ only use data available at $\le T-1$.
- Always deduct slippage and commission in backtests.
- Enforce position limits and capital constraints. No zero-cost or infinite-capital assumptions.

## 6. Column Standards

- OHLCV columns exactly: `open, high, low, close, volume, vwap, oi, symbol, dt`. No abbreviations or variants.

## 7. Verification

```bash
# Backend
uv run ruff format src/getrich/
uv run ruff check src/getrich/ --fix
uv run pytest tests/ -v --durations=10

# Frontend
npm run lint
npm run build
```

## 8. 开发进度文档 (.agent/brain/)

- **Session start**: Read `.agent/brain/NOTES.md` to restore state and TODO items. Then check `.agent/brain/TODO.md` for Web API reference.
- **Session end**: Update `.agent/brain/NOTES.md` with progress, changes, P0/P1 TODOs, and known tech debt if substantive code changes, schema changes, or technical decisions were made.
- **Self-improvement**: Record error patterns and prevention strategies in `.agent/brain/NOTES.md` when AI errors cause user corrections or test failures.

## 9. Don'ts

- Never call external APIs or make network requests on the main thread without `try-except` isolation.