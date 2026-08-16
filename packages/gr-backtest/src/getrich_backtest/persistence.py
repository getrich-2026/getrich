"""PostgreSQL persistence for backtest run results."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from gr_data.db.pool import PgConnectionPool, pg_pool
from getrich_backtest.metrics import BacktestMetrics
from getrich_backtest.result import BacktestResult, CombinedResult
from getrich_backtest.runconfig import RunConfig
from getrich_backtest.time import get_shanghai_tz, require_shanghai_aware


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_STATUS_VALUES = frozenset({"running", "completed", "failed"})
_KNOWN_EQUITY_COLUMNS = frozenset(
    {
        "dt",
        "strategy_name",
        "cash",
        "equity",
        "trading_pnl",
        "mtm_pnl",
        "total_fees",
        "gross_exposure",
    }
)
_ARTIFACT_FILES = {
    "manifest.json": "manifest",
    "equity.parquet": "equity_parquet",
    "fills.parquet": "fills_parquet",
    "orders.parquet": "orders_parquet",
    "tear_sheet.html": "html",
    "report.html": "html",
}


@dataclass(frozen=True)
class BacktestArtifact:
    """External artifact generated for a backtest run."""

    artifact_type: str
    uri: str
    checksum: str | None = None
    meta: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.artifact_type.strip():
            raise ValueError("artifact_type must be non-empty")
        if not self.uri.strip():
            raise ValueError("uri must be non-empty")


class BacktestPersistenceError(Exception):
    """Raised when saving or loading backtest persistence data fails."""


class PgBacktestResultStore:
    """PostgreSQL-backed store for completed backtest results."""

    def __init__(self, pool: PgConnectionPool | None = None) -> None:
        self._pool = pool or pg_pool

    async def save_result(
        self,
        result: BacktestResult,
        *,
        metrics: BacktestMetrics | None = None,
        strategy_id: str | None = None,
        artifacts: Sequence[BacktestArtifact] = (),
        status: str = "completed",
        conn: AsyncConnection | None = None,
    ) -> None:
        """Persist a completed backtest result.

        The write is idempotent for a given ``run_id``: parent run metadata is
        upserted and dependent rows are replaced in the same transaction.
        """
        _validate_status(status)

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(_UPSERT_RUN_SQL, _run_params(result, strategy_id, status))
                await self._delete_children(cur, result.run_id)

                if metrics is not None:
                    await cur.execute(_INSERT_METRICS_SQL, _metrics_params(metrics))

                equity_rows = _equity_rows(result)
                if equity_rows:
                    await cur.executemany(_INSERT_EQUITY_SQL, equity_rows)

                position_rows = _position_rows(result)
                if position_rows:
                    await cur.executemany(_INSERT_POSITION_SQL, position_rows)

                artifact_rows = _artifact_rows(result.run_id, artifacts)
                if artifact_rows:
                    await cur.executemany(_INSERT_ARTIFACT_SQL, artifact_rows)

        try:
            await self._run(op, conn=conn)
        except Exception as exc:  # noqa: BLE001 - exercised via wrapped error tests
            if isinstance(exc, BacktestPersistenceError):
                raise
            raise BacktestPersistenceError(
                f"failed to save backtest result {result.run_id!r}"
            ) from exc

    async def mark_running(
        self,
        config: RunConfig,
        *,
        strategy_id: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Upsert a running backtest run row from a ``RunConfig``."""

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _UPSERT_RUNNING_SQL,
                    _config_run_params(config, strategy_id, "running"),
                )

        try:
            await self._run(op, conn=conn)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, BacktestPersistenceError):
                raise
            raise BacktestPersistenceError(
                f"failed to mark run {config.run_id!r} as running"
            ) from exc

    async def mark_failed(
        self,
        config: RunConfig,
        error_message: str,
        *,
        strategy_id: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Upsert a failed backtest run row from a ``RunConfig``."""

        async def op(db: AsyncConnection) -> None:
            params = _config_run_params(config, strategy_id, "failed")
            params["error_message"] = error_message
            async with db.cursor() as cur:
                await cur.execute(_UPSERT_FAILED_SQL, params)

        try:
            await self._run(op, conn=conn)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, BacktestPersistenceError):
                raise
            raise BacktestPersistenceError(
                f"failed to mark run {config.run_id!r} as failed"
            ) from exc

    async def get_run(
        self,
        run_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> dict[str, Any] | None:
        """Return one persisted backtest run row, or ``None`` if missing."""

        async def op(db: AsyncConnection) -> dict[str, Any] | None:
            async with db.cursor() as cur:
                await cur.execute(
                    """
                    SELECT *
                    FROM backtest.backtest_runs
                    WHERE run_id = %(run_id)s
                    """,
                    {"run_id": run_id},
                )
                return await cur.fetchone()

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, BacktestPersistenceError):
                raise
            raise BacktestPersistenceError(f"failed to load backtest run {run_id!r}") from exc

    async def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List persisted backtest runs with optional filters and total count."""
        if status is not None:
            _validate_status(status)
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        conds: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if strategy_id is not None:
            conds.append("strategy_id = %(strategy_id)s")
            params["strategy_id"] = strategy_id
        if status is not None:
            conds.append("status = %(status)s")
            params["status"] = status

        where = "WHERE " + " AND ".join(conds) if conds else ""
        sql = f"""
            SELECT *, COUNT(*) OVER() AS _total
            FROM backtest.backtest_runs
            {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """

        async def op(db: AsyncConnection) -> tuple[list[dict[str, Any]], int]:
            async with db.cursor() as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
            total = int(rows[0].get("_total", 0)) if rows else 0
            for row in rows:
                row.pop("_total", None)
            return rows, total

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, BacktestPersistenceError):
                raise
            raise BacktestPersistenceError("failed to list backtest runs") from exc

    async def get_equity_curve(
        self,
        run_id: str,
        *,
        strategy_name: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> list[dict[str, Any]]:
        """Return persisted equity points for a run."""
        conds = ["run_id = %(run_id)s"]
        params: dict[str, object] = {"run_id": run_id}
        if strategy_name is not None:
            conds.append("strategy_name = %(strategy_name)s")
            params["strategy_name"] = strategy_name
        where = " AND ".join(conds)

        async def op(db: AsyncConnection) -> list[dict[str, Any]]:
            async with db.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT *
                    FROM backtest.backtest_equity_points
                    WHERE {where}
                    ORDER BY dt
                    """,
                    params,
                )
                return await cur.fetchall()

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, BacktestPersistenceError):
                raise
            raise BacktestPersistenceError(
                f"failed to load equity curve for run {run_id!r}"
            ) from exc

    async def _delete_children(self, cur: Any, run_id: str) -> None:
        for table in (
            "backtest.backtest_metrics",
            "backtest.backtest_equity_points",
            "backtest.backtest_final_positions",
            "backtest.backtest_artifacts",
        ):
            await cur.execute(f"DELETE FROM {table} WHERE run_id = %(run_id)s", {"run_id": run_id})

    async def _run(
        self,
        op: Callable[[AsyncConnection], Awaitable[Any]],
        *,
        conn: AsyncConnection | None,
        commit: bool = True,
    ) -> Any:
        if conn is not None:
            return await op(conn)

        async with self._pool.connection() as owned:
            result = await op(owned)
            if commit:
                await owned.commit()
            return result


def artifacts_from_report_dir(report_dir: Path) -> list[BacktestArtifact]:
    """Build artifact references for files produced by ``Reporter.save()``."""
    artifacts: list[BacktestArtifact] = []
    for filename, artifact_type in _ARTIFACT_FILES.items():
        path = report_dir / filename
        if path.exists():
            artifacts.append(BacktestArtifact(artifact_type=artifact_type, uri=str(path)))
    return artifacts


def _validate_status(status: str) -> None:
    if status not in _STATUS_VALUES:
        valid = ", ".join(sorted(_STATUS_VALUES))
        raise ValueError(f"status must be one of: {valid}")


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(str(value))
    # Polars may expose numeric data as Python floats when test fixtures use floats.
    # Convert through str() to avoid binary-float arithmetic in persistence code.
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def _dt(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    return require_shanghai_aware(value)


def _created_at(config: RunConfig) -> datetime:
    if config.created_at is not None:
        return require_shanghai_aware(config.created_at)
    return datetime.now(get_shanghai_tz())


def _final_equity(result: BacktestResult) -> Decimal:
    if result.equity_curve.height == 0:
        return result.final_account.cash
    return _decimal_or_none(result.equity_curve["equity"][-1]) or result.final_account.cash


def _benchmark_final_equity(result: BacktestResult) -> Decimal | None:
    if result.benchmark_equity_curve is None or result.benchmark_equity_curve.height == 0:
        return None
    return _decimal_or_none(result.benchmark_equity_curve["equity"][-1])


def _strategy_names(result: BacktestResult) -> list[str]:
    if isinstance(result, CombinedResult):
        return list(result._per_strategy_results.keys())
    return list(result.config.strategy_names)


def _config_json(config: RunConfig) -> str:
    payload = config.to_dict()
    payload["run_id"] = config.run_id
    payload["strategy_name"] = config.strategy_name
    if config.created_at is not None:
        payload["created_at"] = config.created_at.isoformat()
    return _json_dumps(payload)


def _run_params(
    result: BacktestResult,
    strategy_id: str | None,
    status: str,
) -> dict[str, object]:
    config = result.config
    return {
        "run_id": result.run_id,
        "strategy_id": strategy_id,
        "strategy_name": result.strategy_name,
        "strategy_names": _json_dumps(_strategy_names(result)),
        "config_fingerprint": config.fingerprint(),
        "config": _config_json(config),
        "symbols": _json_dumps(list(config.symbols)),
        "freq": config.freq,
        "start_at": require_shanghai_aware(config.start),
        "end_at": require_shanghai_aware(config.end),
        "initial_cash": result.initial_cash,
        "final_cash": result.final_account.cash,
        "final_equity": _final_equity(result),
        "benchmark_final_equity": _benchmark_final_equity(result),
        "status": status,
        "error_message": None,
        "created_at": _created_at(config),
        "completed_at": datetime.now(get_shanghai_tz()) if status == "completed" else None,
    }


def _config_run_params(
    config: RunConfig,
    strategy_id: str | None,
    status: str,
) -> dict[str, object]:
    return {
        "run_id": config.run_id,
        "strategy_id": strategy_id,
        "strategy_name": config.strategy_name,
        "strategy_names": _json_dumps(list(config.strategy_names)),
        "config_fingerprint": config.fingerprint(),
        "config": _config_json(config),
        "symbols": _json_dumps(list(config.symbols)),
        "freq": config.freq,
        "start_at": require_shanghai_aware(config.start),
        "end_at": require_shanghai_aware(config.end),
        "initial_cash": config.initial_cash,
        "status": status,
        "error_message": None,
        "created_at": _created_at(config),
        "completed_at": datetime.now(get_shanghai_tz()) if status == "failed" else None,
    }


def _metrics_params(metrics: BacktestMetrics) -> dict[str, object]:
    return {
        "run_id": metrics.run_id,
        "total_return": metrics.total_return,
        "log_return": metrics.log_return,
        "annualized_return": metrics.annualized_return,
        "annualized_volatility": metrics.annualized_volatility,
        "sharpe_ratio": metrics.sharpe_ratio,
        "sortino_ratio": metrics.sortino_ratio,
        "calmar_ratio": metrics.calmar_ratio,
        "max_drawdown": metrics.max_drawdown,
        "max_drawdown_duration": metrics.max_drawdown_duration,
        "total_fees": metrics.total_fees,
        "total_turnover": metrics.total_turnover,
        "turnover_rate": metrics.turnover_rate,
        "total_trades": metrics.total_trades,
        "n_bars": metrics.n_bars,
        "risk_free_rate": metrics.risk_free_rate,
        "trading_days_per_year": metrics.trading_days_per_year,
        "metrics_json": _json_dumps(metrics.to_dict()),
    }


def _equity_rows(result: BacktestResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in result.equity_curve.to_dicts():
        strategy_name = row.get("strategy_name") or result.strategy_name
        extra = {k: v for k, v in row.items() if k not in _KNOWN_EQUITY_COLUMNS}
        rows.append(
            {
                "run_id": result.run_id,
                "strategy_name": str(strategy_name),
                "dt": _dt(row["dt"]),
                "cash": _decimal_or_none(row.get("cash")),
                "equity": _decimal_or_none(row.get("equity")),
                "trading_pnl": _decimal_or_none(row.get("trading_pnl")),
                "mtm_pnl": _decimal_or_none(row.get("mtm_pnl")),
                "total_fees": _decimal_or_none(row.get("total_fees")),
                "gross_exposure": _decimal_or_none(row.get("gross_exposure")),
                "row_json": _json_dumps(extra),
            }
        )
    return rows


def _position_rows(result: BacktestResult) -> list[dict[str, object]]:
    positions = result.final_account.positions or {}
    rows: list[dict[str, object]] = []
    for symbol, position in positions.items():
        rows.append(
            {
                "run_id": result.run_id,
                "symbol": symbol,
                "qty": position.qty,
                "position_json": _json_dumps({"symbol": position.symbol, "qty": position.qty}),
            }
        )
    return rows


def _artifact_rows(
    run_id: str,
    artifacts: Sequence[BacktestArtifact],
) -> list[dict[str, object]]:
    return [
        {
            "id": uuid4().hex,
            "run_id": run_id,
            "artifact_type": artifact.artifact_type,
            "uri": artifact.uri,
            "checksum": artifact.checksum,
            "meta": _json_dumps(artifact.meta or {}),
        }
        for artifact in artifacts
    ]


_UPSERT_RUN_SQL = """
INSERT INTO backtest.backtest_runs (
    run_id, strategy_id, strategy_name, strategy_names, config_fingerprint,
    config, symbols, freq, start_at, end_at, initial_cash, final_cash,
    final_equity, benchmark_final_equity, status, error_message, created_at,
    completed_at, updated_at
) VALUES (
    %(run_id)s, %(strategy_id)s, %(strategy_name)s, %(strategy_names)s::jsonb,
    %(config_fingerprint)s, %(config)s::jsonb, %(symbols)s::jsonb, %(freq)s,
    %(start_at)s, %(end_at)s, %(initial_cash)s, %(final_cash)s,
    %(final_equity)s, %(benchmark_final_equity)s, %(status)s, %(error_message)s,
    %(created_at)s, %(completed_at)s, NOW()
)
ON CONFLICT (run_id) DO UPDATE SET
    strategy_id = EXCLUDED.strategy_id,
    strategy_name = EXCLUDED.strategy_name,
    strategy_names = EXCLUDED.strategy_names,
    config_fingerprint = EXCLUDED.config_fingerprint,
    config = EXCLUDED.config,
    symbols = EXCLUDED.symbols,
    freq = EXCLUDED.freq,
    start_at = EXCLUDED.start_at,
    end_at = EXCLUDED.end_at,
    initial_cash = EXCLUDED.initial_cash,
    final_cash = EXCLUDED.final_cash,
    final_equity = EXCLUDED.final_equity,
    benchmark_final_equity = EXCLUDED.benchmark_final_equity,
    status = EXCLUDED.status,
    error_message = EXCLUDED.error_message,
    completed_at = EXCLUDED.completed_at,
    updated_at = NOW()
"""

_UPSERT_RUNNING_SQL = """
INSERT INTO backtest.backtest_runs (
    run_id, strategy_id, strategy_name, strategy_names, config_fingerprint,
    config, symbols, freq, start_at, end_at, initial_cash, status,
    error_message, created_at, completed_at, updated_at
) VALUES (
    %(run_id)s, %(strategy_id)s, %(strategy_name)s, %(strategy_names)s::jsonb,
    %(config_fingerprint)s, %(config)s::jsonb, %(symbols)s::jsonb, %(freq)s,
    %(start_at)s, %(end_at)s, %(initial_cash)s, %(status)s, %(error_message)s,
    %(created_at)s, %(completed_at)s, NOW()
)
ON CONFLICT (run_id) DO UPDATE SET
    strategy_id = EXCLUDED.strategy_id,
    strategy_name = EXCLUDED.strategy_name,
    strategy_names = EXCLUDED.strategy_names,
    config_fingerprint = EXCLUDED.config_fingerprint,
    config = EXCLUDED.config,
    symbols = EXCLUDED.symbols,
    freq = EXCLUDED.freq,
    start_at = EXCLUDED.start_at,
    end_at = EXCLUDED.end_at,
    initial_cash = EXCLUDED.initial_cash,
    status = EXCLUDED.status,
    error_message = NULL,
    completed_at = NULL,
    updated_at = NOW()
"""

_UPSERT_FAILED_SQL = """
INSERT INTO backtest.backtest_runs (
    run_id, strategy_id, strategy_name, strategy_names, config_fingerprint,
    config, symbols, freq, start_at, end_at, initial_cash, status,
    error_message, created_at, completed_at, updated_at
) VALUES (
    %(run_id)s, %(strategy_id)s, %(strategy_name)s, %(strategy_names)s::jsonb,
    %(config_fingerprint)s, %(config)s::jsonb, %(symbols)s::jsonb, %(freq)s,
    %(start_at)s, %(end_at)s, %(initial_cash)s, %(status)s, %(error_message)s,
    %(created_at)s, %(completed_at)s, NOW()
)
ON CONFLICT (run_id) DO UPDATE SET
    strategy_id = EXCLUDED.strategy_id,
    strategy_name = EXCLUDED.strategy_name,
    strategy_names = EXCLUDED.strategy_names,
    config_fingerprint = EXCLUDED.config_fingerprint,
    config = EXCLUDED.config,
    symbols = EXCLUDED.symbols,
    freq = EXCLUDED.freq,
    start_at = EXCLUDED.start_at,
    end_at = EXCLUDED.end_at,
    initial_cash = EXCLUDED.initial_cash,
    status = EXCLUDED.status,
    error_message = EXCLUDED.error_message,
    completed_at = EXCLUDED.completed_at,
    updated_at = NOW()
"""

_INSERT_METRICS_SQL = """
INSERT INTO backtest.backtest_metrics (
    run_id, total_return, log_return, annualized_return,
    annualized_volatility, sharpe_ratio, sortino_ratio, calmar_ratio,
    max_drawdown, max_drawdown_duration, total_fees, total_turnover,
    turnover_rate, total_trades, n_bars, risk_free_rate,
    trading_days_per_year, metrics_json
) VALUES (
    %(run_id)s, %(total_return)s, %(log_return)s, %(annualized_return)s,
    %(annualized_volatility)s, %(sharpe_ratio)s, %(sortino_ratio)s,
    %(calmar_ratio)s, %(max_drawdown)s, %(max_drawdown_duration)s,
    %(total_fees)s, %(total_turnover)s, %(turnover_rate)s, %(total_trades)s,
    %(n_bars)s, %(risk_free_rate)s, %(trading_days_per_year)s,
    %(metrics_json)s::jsonb
)
"""

_INSERT_EQUITY_SQL = """
INSERT INTO backtest.backtest_equity_points (
    run_id, strategy_name, dt, cash, equity, trading_pnl, mtm_pnl,
    total_fees, gross_exposure, row_json
) VALUES (
    %(run_id)s, %(strategy_name)s, %(dt)s, %(cash)s, %(equity)s,
    %(trading_pnl)s, %(mtm_pnl)s, %(total_fees)s, %(gross_exposure)s,
    %(row_json)s::jsonb
)
"""

_INSERT_POSITION_SQL = """
INSERT INTO backtest.backtest_final_positions (run_id, symbol, qty, position_json)
VALUES (%(run_id)s, %(symbol)s, %(qty)s, %(position_json)s::jsonb)
"""

_INSERT_ARTIFACT_SQL = """
INSERT INTO backtest.backtest_artifacts (id, run_id, artifact_type, uri, checksum, meta)
VALUES (%(id)s, %(run_id)s, %(artifact_type)s, %(uri)s, %(checksum)s, %(meta)s::jsonb)
"""


__all__ = [
    "BacktestArtifact",
    "BacktestPersistenceError",
    "PgBacktestResultStore",
    "artifacts_from_report_dir",
]
