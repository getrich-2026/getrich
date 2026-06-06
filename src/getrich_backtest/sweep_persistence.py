"""PostgreSQL persistence for parameter sweep results."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import polars as pl

from getrich.libs.postgres.pool import PgConnectionPool, pg_pool
from getrich_backtest.persistence import PgBacktestResultStore
from getrich_backtest.sweep import SweepResult, SweepTrialResult
from getrich_backtest.time import get_shanghai_tz


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_SWEEP_STATUS_VALUES = frozenset({"running", "completed", "failed"})
_TRIAL_STATUS_VALUES = frozenset({"completed", "failed"})

# Sentinel for "do not filter by user_id" — used by internal callers
# (job runner, recovery) when they need to read any owner's row.
_SYSTEM_USER = "*"


class SweepPersistenceError(Exception):
    """Raised when saving or loading sweep persistence data fails."""


class PgSweepResultStore:
    """PostgreSQL-backed store for parameter sweep results."""

    def __init__(self, pool: PgConnectionPool | None = None) -> None:
        self._pool = pool or pg_pool
        self._result_store = PgBacktestResultStore(pool=self._pool)

    async def save_sweep_result(
        self,
        result: SweepResult,
        *,
        search_spec: Mapping[str, object] | None = None,
        search_type: str = "grid",
        strategy_id: str | None = None,
        user_id: str | None = None,
        save_backtest_results: bool = True,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Persist a completed sweep and its per-trial summaries.

        Completed trial ``BacktestResult`` objects are optionally saved through
        ``PgBacktestResultStore`` in the same transaction. Failed trials are
        persisted even when no run result exists.
        """
        if not result.sweep_id.strip():
            raise ValueError("sweep_id must be non-empty")
        if not search_type.strip():
            raise ValueError("search_type must be non-empty")

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _UPSERT_SWEEP_SQL,
                    _sweep_params(result, search_spec or {}, search_type, user_id),
                )
                await cur.execute(
                    "DELETE FROM backtest_sweep_trials WHERE sweep_id = %(sweep_id)s",
                    {"sweep_id": result.sweep_id},
                )

                rows = _trial_rows(result)
                if rows:
                    await cur.executemany(_INSERT_TRIAL_SQL, rows)

            if save_backtest_results:
                for trial_result in result.completed():
                    if trial_result.result is not None:
                        await self._result_store.save_result(
                            trial_result.result,
                            metrics=trial_result.metrics,
                            strategy_id=strategy_id,
                            conn=db,
                        )

        try:
            await self._run(op, conn=conn)
        except Exception as exc:  # noqa: BLE001 - wrap persistence boundary errors
            if isinstance(exc, SweepPersistenceError):
                raise
            raise SweepPersistenceError(f"failed to save sweep result {result.sweep_id!r}") from exc

    async def get_sweep(
        self,
        sweep_id: str,
        *,
        user_id: str | None = None,
        conn: AsyncConnection | None = None,
    ) -> dict[str, Any] | None:
        """Return one persisted sweep row, or ``None`` if missing.

        When ``user_id`` is provided, the row is only returned if its
        stored owner matches (NULL owners remain visible to the
        system caller, which passes the system sentinel ``"*"``).
        """

        async def op(db: AsyncConnection) -> dict[str, Any] | None:
            async with db.cursor() as cur:
                await cur.execute(
                    _SELECT_SWEEP_SQL,
                    {"sweep_id": sweep_id, "user_id": user_id},
                )
                return await cur.fetchone()

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, SweepPersistenceError):
                raise
            raise SweepPersistenceError(f"failed to load sweep {sweep_id!r}") from exc

    async def list_sweeps(
        self,
        *,
        status: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List persisted sweeps with optional status filtering and owner scoping."""
        if status is not None:
            _validate_sweep_status(status)
        _validate_pagination(limit, offset)

        conds: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status is not None:
            conds.append("status = %(status)s")
            params["status"] = status
        if user_id is not None and user_id != _SYSTEM_USER:
            conds.append("user_id IS NOT DISTINCT FROM %(user_id)s")
            params["user_id"] = user_id
        where = "WHERE " + " AND ".join(conds) if conds else ""
        sql = f"""
            SELECT *, COUNT(*) OVER() AS _total
            FROM backtest_sweeps
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
            if isinstance(exc, SweepPersistenceError):
                raise
            raise SweepPersistenceError("failed to list sweeps") from exc

    async def list_sweep_trials(
        self,
        sweep_id: str,
        *,
        status: str | None = None,
        user_id: str | None = None,
        limit: int = 500,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List persisted trial rows for one sweep owned by ``user_id``."""
        if not sweep_id.strip():
            raise ValueError("sweep_id must be non-empty")
        if status is not None:
            _validate_trial_status(status)
        _validate_pagination(limit, offset)
        if user_id is not None:
            await self._assert_owner(sweep_id, user_id, conn=conn)

        conds = ["sweep_id = %(sweep_id)s"]
        params: dict[str, object] = {"sweep_id": sweep_id, "limit": limit, "offset": offset}
        if status is not None:
            conds.append("status = %(status)s")
            params["status"] = status
        where = " AND ".join(conds)
        sql = f"""
            SELECT *, COUNT(*) OVER() AS _total
            FROM backtest_sweep_trials
            WHERE {where}
            ORDER BY trial_index
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
            if isinstance(exc, SweepPersistenceError):
                raise
            raise SweepPersistenceError(f"failed to list trials for sweep {sweep_id!r}") from exc

    async def _assert_owner(
        self,
        sweep_id: str,
        user_id: str,
        *,
        conn: AsyncConnection | None,
    ) -> None:
        """Raise ``SweepPersistenceError`` if the sweep is not owned by ``user_id``."""
        if user_id == _SYSTEM_USER:
            return  # system caller bypasses the filter
        sweep = await self.get_sweep(sweep_id, user_id=user_id, conn=conn)
        if sweep is None:
            raise SweepPersistenceError(f"sweep not found or not owned: {sweep_id}")

    async def get_trials_frame(
        self,
        sweep_id: str,
        *,
        status: str | None = None,
        limit: int = 10_000,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> pl.DataFrame:
        """Return persisted sweep trials as an analysis-friendly Polars frame."""
        rows, _total = await self.list_sweep_trials(
            sweep_id,
            status=status,
            limit=limit,
            offset=offset,
            conn=conn,
        )
        return trials_to_frame(rows)

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


def trials_to_frame(rows: list[Mapping[str, Any]]) -> pl.DataFrame:
    """Convert persisted sweep trial rows to a flattened Polars DataFrame."""
    frame_rows: list[dict[str, object]] = []
    for row in rows:
        params = _json_loads_if_needed(row.get("params")) or {}
        metrics = _json_loads_if_needed(row.get("metrics_json")) or {}
        frame_row: dict[str, object] = {
            "sweep_id": row.get("sweep_id"),
            "trial_id": row.get("trial_id"),
            "run_id": row.get("run_id"),
            "index": row.get("trial_index"),
            "status": row.get("status"),
            "error_message": row.get("error_message"),
            "param_fingerprint": row.get("param_fingerprint"),
            "params": params,
            "select_metric_value": row.get("select_metric_value"),
        }
        if isinstance(params, Mapping):
            for name, value in params.items():
                frame_row[f"param_{name}"] = value
        if isinstance(metrics, Mapping):
            frame_row.update(metrics)
        frame_rows.append(frame_row)
    return pl.DataFrame(frame_rows)


def _sweep_params(
    result: SweepResult,
    search_spec: Mapping[str, object],
    search_type: str,
    user_id: str | None = None,
) -> dict[str, object]:
    now = datetime.now(get_shanghai_tz())
    summary = result.summary()
    return {
        "sweep_id": result.sweep_id,
        "search_type": search_type,
        "search_spec": _json_dumps(search_spec),
        "select_metric": result.select_metric,
        "maximize": result.maximize,
        "status": "completed",
        "total_trials": summary["total_trials"],
        "completed_trials": summary["completed_trials"],
        "failed_trials": summary["failed_trials"],
        "best_trial_id": summary["best_trial_id"],
        "best_run_id": summary["best_run_id"],
        "best_metric_value": _decimal_or_none(summary["best_metric_value"]),
        "summary_json": _json_dumps(summary),
        "user_id": user_id,
        "created_at": now,
        "completed_at": now,
    }


def _trial_rows(result: SweepResult) -> list[dict[str, object]]:
    now = datetime.now(get_shanghai_tz())
    return [_trial_row(trial_result, result.select_metric, now) for trial_result in result.trials]


def _trial_row(
    trial_result: SweepTrialResult,
    select_metric: str,
    timestamp: datetime,
) -> dict[str, object]:
    _validate_trial_status(trial_result.status)
    return {
        "trial_id": trial_result.trial.trial_id,
        "sweep_id": trial_result.trial.sweep_id,
        "run_id": trial_result.trial.run_id,
        "trial_index": trial_result.trial.index,
        "params": _json_dumps(trial_result.trial.params),
        "param_fingerprint": trial_result.trial.param_fingerprint,
        "status": trial_result.status,
        "error_message": trial_result.error_message,
        "select_metric_value": _select_metric_value(trial_result, select_metric),
        "metrics_json": _metrics_json(trial_result),
        "created_at": timestamp,
        "completed_at": timestamp if trial_result.status in _TRIAL_STATUS_VALUES else None,
    }


def _select_metric_value(
    trial_result: SweepTrialResult,
    select_metric: str,
) -> Decimal | None:
    if trial_result.metrics is None or not hasattr(trial_result.metrics, select_metric):
        return None
    return _decimal_or_none(getattr(trial_result.metrics, select_metric))


def _metrics_json(trial_result: SweepTrialResult) -> str:
    if trial_result.metrics is None:
        return _json_dumps({})
    return _json_dumps(trial_result.metrics.to_dict())


def _validate_sweep_status(status: str) -> None:
    if status not in _SWEEP_STATUS_VALUES:
        valid = ", ".join(sorted(_SWEEP_STATUS_VALUES))
        raise ValueError(f"status must be one of: {valid}")


def _validate_trial_status(status: str) -> None:
    if status not in _TRIAL_STATUS_VALUES:
        valid = ", ".join(sorted(_TRIAL_STATUS_VALUES))
        raise ValueError(f"status must be one of: {valid}")


def _validate_pagination(limit: int, offset: int) -> None:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must be non-negative")


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


def _json_loads_if_needed(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


_UPSERT_SWEEP_SQL = """
INSERT INTO backtest_sweeps (
    sweep_id, search_type, search_spec, select_metric, maximize, status,
    total_trials, completed_trials, failed_trials, best_trial_id, best_run_id,
    best_metric_value, summary_json, user_id, created_at, completed_at, updated_at
) VALUES (
    %(sweep_id)s, %(search_type)s, %(search_spec)s::jsonb, %(select_metric)s,
    %(maximize)s, %(status)s, %(total_trials)s, %(completed_trials)s,
    %(failed_trials)s, %(best_trial_id)s, %(best_run_id)s,
    %(best_metric_value)s, %(summary_json)s::jsonb, %(user_id)s,
    %(created_at)s, %(completed_at)s, NOW()
)
ON CONFLICT (sweep_id) DO UPDATE SET
    search_type = EXCLUDED.search_type,
    search_spec = EXCLUDED.search_spec,
    select_metric = EXCLUDED.select_metric,
    maximize = EXCLUDED.maximize,
    status = EXCLUDED.status,
    total_trials = EXCLUDED.total_trials,
    completed_trials = EXCLUDED.completed_trials,
    failed_trials = EXCLUDED.failed_trials,
    best_trial_id = EXCLUDED.best_trial_id,
    best_run_id = EXCLUDED.best_run_id,
    best_metric_value = EXCLUDED.best_metric_value,
    summary_json = EXCLUDED.summary_json,
    user_id = EXCLUDED.user_id,
    completed_at = EXCLUDED.completed_at,
    updated_at = NOW()
"""


_SELECT_SWEEP_SQL = """
SELECT *
FROM backtest_sweeps
WHERE sweep_id = %(sweep_id)s
  AND (
      %(user_id)s::text IS NULL
      OR user_id IS NOT DISTINCT FROM %(user_id)s
  )
"""

_INSERT_TRIAL_SQL = """
INSERT INTO backtest_sweep_trials (
    trial_id, sweep_id, run_id, trial_index, params, param_fingerprint,
    status, error_message, select_metric_value, metrics_json, created_at,
    completed_at, updated_at
) VALUES (
    %(trial_id)s, %(sweep_id)s, %(run_id)s, %(trial_index)s, %(params)s::jsonb,
    %(param_fingerprint)s, %(status)s, %(error_message)s,
    %(select_metric_value)s, %(metrics_json)s::jsonb, %(created_at)s,
    %(completed_at)s, NOW()
)
"""


__all__ = [
    "PgSweepResultStore",
    "SweepPersistenceError",
    "trials_to_frame",
]
