"""PostgreSQL persistence for walk-forward results."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import polars as pl

from gr_data.db.pool import PgConnectionPool, pg_pool
from getrich_backtest.persistence import PgBacktestResultStore
from getrich_backtest.sweep_persistence import PgSweepResultStore
from getrich_backtest.time import get_shanghai_tz, require_shanghai_aware
from getrich_backtest.walk_forward import WalkForwardResult, WalkForwardWindowResult


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_WALK_FORWARD_STATUS_VALUES = frozenset({"running", "completed", "failed"})
_WINDOW_STATUS_VALUES = frozenset({"completed", "failed"})


class WalkForwardPersistenceError(Exception):
    """Raised when saving or loading walk-forward persistence data fails."""


class PgWalkForwardResultStore:
    """PostgreSQL-backed store for walk-forward study results."""

    def __init__(self, pool: PgConnectionPool | None = None) -> None:
        self._pool = pool or pg_pool
        self._sweep_store = PgSweepResultStore(pool=self._pool)
        self._result_store = PgBacktestResultStore(pool=self._pool)

    async def save_walk_forward_result(
        self,
        result: WalkForwardResult,
        *,
        search_type: str = "grid",
        search_spec: Mapping[str, object] | None = None,
        save_child_results: bool = True,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Persist a walk-forward result and its per-window summaries.

        The write is idempotent for a given ``walk_forward_id``: the parent row
        is upserted and window rows are replaced in the same transaction. Child
        train sweeps and validation backtest runs are optionally persisted in the
        same transaction using the existing sweep/run stores.
        """
        if not result.walk_forward_id.strip():
            raise ValueError("walk_forward_id must be non-empty")
        if not search_type.strip():
            raise ValueError("search_type must be non-empty")

        async def op(db: AsyncConnection) -> None:
            async with db.cursor() as cur:
                await cur.execute(
                    _UPSERT_WALK_FORWARD_SQL,
                    _walk_forward_params(result, search_type, search_spec or {}),
                )
                await cur.execute(
                    """
                    DELETE FROM backtest_walk_forward_windows
                    WHERE walk_forward_id = %(walk_forward_id)s
                    """,
                    {"walk_forward_id": result.walk_forward_id},
                )

                rows = _window_rows(result)
                if rows:
                    await cur.executemany(_INSERT_WINDOW_SQL, rows)

            if save_child_results:
                for window_result in result.completed():
                    if window_result.train_sweep is not None:
                        await self._sweep_store.save_sweep_result(
                            window_result.train_sweep,
                            search_type=search_type,
                            search_spec=search_spec,
                            conn=db,
                        )
                    if window_result.validation_result is not None:
                        await self._result_store.save_result(
                            window_result.validation_result,
                            metrics=window_result.validation_metrics,
                            conn=db,
                        )

        try:
            await self._run(op, conn=conn)
        except Exception as exc:  # noqa: BLE001 - wrap persistence boundary errors
            if isinstance(exc, WalkForwardPersistenceError):
                raise
            raise WalkForwardPersistenceError(
                f"failed to save walk-forward result {result.walk_forward_id!r}"
            ) from exc

    async def get_walk_forward(
        self,
        walk_forward_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> dict[str, Any] | None:
        """Return one persisted walk-forward parent row, or ``None`` if missing."""

        async def op(db: AsyncConnection) -> dict[str, Any] | None:
            async with db.cursor() as cur:
                await cur.execute(
                    """
                    SELECT *
                    FROM backtest_walk_forwards
                    WHERE walk_forward_id = %(walk_forward_id)s
                    """,
                    {"walk_forward_id": walk_forward_id},
                )
                return await cur.fetchone()

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, WalkForwardPersistenceError):
                raise
            raise WalkForwardPersistenceError(
                f"failed to load walk-forward {walk_forward_id!r}"
            ) from exc

    async def list_walk_forwards(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List persisted walk-forward studies with optional status filtering."""
        if status is not None:
            _validate_walk_forward_status(status)
        _validate_pagination(limit, offset)

        conds: list[str] = []
        params: dict[str, object] = {"limit": limit, "offset": offset}
        if status is not None:
            conds.append("status = %(status)s")
            params["status"] = status
        where = "WHERE " + " AND ".join(conds) if conds else ""
        sql = f"""
            SELECT *, COUNT(*) OVER() AS _total
            FROM backtest_walk_forwards
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
            if isinstance(exc, WalkForwardPersistenceError):
                raise
            raise WalkForwardPersistenceError("failed to list walk-forwards") from exc

    async def list_windows(
        self,
        walk_forward_id: str,
        *,
        status: str | None = None,
        limit: int = 500,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List persisted window rows for one walk-forward study."""
        if not walk_forward_id.strip():
            raise ValueError("walk_forward_id must be non-empty")
        if status is not None:
            _validate_window_status(status)
        _validate_pagination(limit, offset)

        conds = ["walk_forward_id = %(walk_forward_id)s"]
        params: dict[str, object] = {
            "walk_forward_id": walk_forward_id,
            "limit": limit,
            "offset": offset,
        }
        if status is not None:
            conds.append("status = %(status)s")
            params["status"] = status
        where = " AND ".join(conds)
        sql = f"""
            SELECT *, COUNT(*) OVER() AS _total
            FROM backtest_walk_forward_windows
            WHERE {where}
            ORDER BY window_index
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
            if isinstance(exc, WalkForwardPersistenceError):
                raise
            raise WalkForwardPersistenceError(
                f"failed to list windows for walk-forward {walk_forward_id!r}"
            ) from exc

    async def get_windows_frame(
        self,
        walk_forward_id: str,
        *,
        status: str | None = None,
        limit: int = 10_000,
        offset: int = 0,
        conn: AsyncConnection | None = None,
    ) -> pl.DataFrame:
        """Return persisted window rows as an analysis-friendly Polars frame."""
        rows, _total = await self.list_windows(
            walk_forward_id,
            status=status,
            limit=limit,
            offset=offset,
            conn=conn,
        )
        return walk_forward_windows_to_frame(rows)

    async def get_oos_equity_curve(
        self,
        walk_forward_id: str,
        *,
        conn: AsyncConnection | None = None,
    ) -> pl.DataFrame:
        """Return persisted OOS equity points tagged with walk-forward window metadata."""
        if not walk_forward_id.strip():
            raise ValueError("walk_forward_id must be non-empty")

        async def op(db: AsyncConnection) -> pl.DataFrame:
            async with db.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        w.walk_forward_id,
                        w.window_index,
                        e.run_id,
                        e.strategy_name,
                        e.dt,
                        e.cash,
                        e.equity,
                        e.trading_pnl,
                        e.mtm_pnl,
                        e.total_fees,
                        e.gross_exposure,
                        e.row_json,
                        e.created_at
                    FROM backtest_walk_forward_windows w
                    JOIN backtest_equity_points e
                        ON e.run_id = w.validation_run_id
                    WHERE w.walk_forward_id = %(walk_forward_id)s
                      AND w.validation_run_id IS NOT NULL
                    ORDER BY w.window_index ASC, e.dt ASC, e.strategy_name ASC
                    """,
                    {"walk_forward_id": walk_forward_id},
                )
                rows = await cur.fetchall()
            return pl.DataFrame([_equity_row(row) for row in rows])

        try:
            return await self._run(op, conn=conn, commit=False)
        except Exception as exc:  # pragma: no cover
            if isinstance(exc, WalkForwardPersistenceError):
                raise
            raise WalkForwardPersistenceError(
                f"failed to load OOS equity for walk-forward {walk_forward_id!r}"
            ) from exc

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


def walk_forward_windows_to_frame(rows: list[Mapping[str, Any]]) -> pl.DataFrame:
    """Convert persisted walk-forward window rows to a flattened Polars DataFrame."""
    frame_rows: list[dict[str, object]] = []
    for row in rows:
        params = _json_loads_if_needed(row.get("best_params")) or {}
        metrics = _json_loads_if_needed(row.get("validation_metrics_json")) or {}
        frame_row: dict[str, object] = {
            "walk_forward_id": row.get("walk_forward_id"),
            "window_index": row.get("window_index"),
            "train_start": row.get("train_start"),
            "train_end": row.get("train_end"),
            "val_start": row.get("val_start"),
            "val_end": row.get("val_end"),
            "status": row.get("status"),
            "error_message": row.get("error_message"),
            "train_sweep_id": row.get("train_sweep_id"),
            "best_trial_id": row.get("best_trial_id"),
            "best_run_id": row.get("best_run_id"),
            "validation_run_id": row.get("validation_run_id"),
            "best_params": params,
            "train_metric_value": row.get("train_metric_value"),
            "validation_metric_value": row.get("validation_metric_value"),
            "validation_metrics_json": metrics,
        }
        if isinstance(params, Mapping):
            for name, value in params.items():
                frame_row[f"param_{name}"] = value
        if isinstance(metrics, Mapping):
            for name, value in metrics.items():
                frame_row[f"validation_{name}"] = value
        frame_rows.append(frame_row)
    return pl.DataFrame(frame_rows)


def _walk_forward_params(
    result: WalkForwardResult,
    search_type: str,
    search_spec: Mapping[str, object],
) -> dict[str, object]:
    now = datetime.now(get_shanghai_tz())
    summary = result.summary()
    return {
        "walk_forward_id": result.walk_forward_id,
        "search_type": search_type,
        "search_spec": _json_dumps(search_spec),
        "select_metric": result.select_metric,
        "maximize": result.maximize,
        "refit": result.refit,
        "status": "completed",
        "total_windows": summary["total_windows"],
        "completed_windows": summary["completed_windows"],
        "failed_windows": summary["failed_windows"],
        "mean_validation_metric": _decimal_or_none(summary["mean_validation_metric"]),
        "summary_json": _json_dumps(summary),
        "created_at": now,
        "completed_at": now,
    }


def _window_rows(result: WalkForwardResult) -> list[dict[str, object]]:
    now = datetime.now(get_shanghai_tz())
    return [
        _window_row(result.walk_forward_id, window_result, result.select_metric, now)
        for window_result in result.windows
    ]


def _window_row(
    walk_forward_id: str,
    window_result: WalkForwardWindowResult,
    select_metric: str,
    timestamp: datetime,
) -> dict[str, object]:
    _validate_window_status(window_result.status)
    best_trial = window_result.best_trial
    train_sweep = window_result.train_sweep
    validation_result = window_result.validation_result
    best_params = dict(best_trial.trial.params) if best_trial is not None else {}
    return {
        "walk_forward_id": walk_forward_id,
        "window_index": window_result.window.index,
        "train_start": require_shanghai_aware(window_result.window.train_start),
        "train_end": require_shanghai_aware(window_result.window.train_end),
        "val_start": require_shanghai_aware(window_result.window.val_start),
        "val_end": require_shanghai_aware(window_result.window.val_end),
        "status": window_result.status,
        "error_message": window_result.error_message,
        "train_sweep_id": train_sweep.sweep_id if train_sweep is not None else None,
        "best_trial_id": best_trial.trial.trial_id if best_trial is not None else None,
        "best_run_id": best_trial.trial.run_id if best_trial is not None else None,
        "validation_run_id": validation_result.run_id if validation_result is not None else None,
        "best_params": _json_dumps(best_params),
        "train_metric_value": _trial_metric_value(window_result, select_metric),
        "validation_metric_value": _metrics_value(window_result.validation_metrics, select_metric),
        "validation_metrics_json": _validation_metrics_json(window_result),
        "created_at": timestamp,
        "completed_at": timestamp if window_result.status in _WINDOW_STATUS_VALUES else None,
    }


def _trial_metric_value(
    window_result: WalkForwardWindowResult,
    select_metric: str,
) -> Decimal | None:
    if window_result.best_trial is None:
        return None
    return _metrics_value(window_result.best_trial.metrics, select_metric)


def _metrics_value(metrics: object, select_metric: str) -> Decimal | None:
    if metrics is None or not hasattr(metrics, select_metric):
        return None
    return _decimal_or_none(getattr(metrics, select_metric))


def _validation_metrics_json(window_result: WalkForwardWindowResult) -> str:
    if window_result.validation_metrics is None:
        return _json_dumps({})
    return _json_dumps(window_result.validation_metrics.to_dict())


def _equity_row(row: Mapping[str, Any]) -> dict[str, object]:
    return {
        "walk_forward_id": row.get("walk_forward_id"),
        "window_index": row.get("window_index"),
        "run_id": row.get("run_id"),
        "strategy_name": row.get("strategy_name"),
        "dt": row.get("dt"),
        "cash": row.get("cash"),
        "equity": row.get("equity"),
        "trading_pnl": row.get("trading_pnl"),
        "mtm_pnl": row.get("mtm_pnl"),
        "total_fees": row.get("total_fees"),
        "gross_exposure": row.get("gross_exposure"),
        "row_json": _json_loads_if_needed(row.get("row_json")) or {},
        "created_at": row.get("created_at"),
    }


def _validate_walk_forward_status(status: str) -> None:
    if status not in _WALK_FORWARD_STATUS_VALUES:
        valid = ", ".join(sorted(_WALK_FORWARD_STATUS_VALUES))
        raise ValueError(f"status must be one of: {valid}")


def _validate_window_status(status: str) -> None:
    if status not in _WINDOW_STATUS_VALUES:
        valid = ", ".join(sorted(_WINDOW_STATUS_VALUES))
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
    if isinstance(value, bool):
        return None
    return Decimal(str(value))


_UPSERT_WALK_FORWARD_SQL = """
INSERT INTO backtest_walk_forwards (
    walk_forward_id, search_type, search_spec, select_metric, maximize, refit,
    status, total_windows, completed_windows, failed_windows,
    mean_validation_metric, summary_json, created_at, completed_at, updated_at
) VALUES (
    %(walk_forward_id)s, %(search_type)s, %(search_spec)s::jsonb,
    %(select_metric)s, %(maximize)s, %(refit)s, %(status)s, %(total_windows)s,
    %(completed_windows)s, %(failed_windows)s, %(mean_validation_metric)s,
    %(summary_json)s::jsonb, %(created_at)s, %(completed_at)s, NOW()
)
ON CONFLICT (walk_forward_id) DO UPDATE SET
    search_type = EXCLUDED.search_type,
    search_spec = EXCLUDED.search_spec,
    select_metric = EXCLUDED.select_metric,
    maximize = EXCLUDED.maximize,
    refit = EXCLUDED.refit,
    status = EXCLUDED.status,
    total_windows = EXCLUDED.total_windows,
    completed_windows = EXCLUDED.completed_windows,
    failed_windows = EXCLUDED.failed_windows,
    mean_validation_metric = EXCLUDED.mean_validation_metric,
    summary_json = EXCLUDED.summary_json,
    completed_at = EXCLUDED.completed_at,
    updated_at = NOW()
"""

_INSERT_WINDOW_SQL = """
INSERT INTO backtest_walk_forward_windows (
    walk_forward_id, window_index, train_start, train_end, val_start, val_end,
    status, error_message, train_sweep_id, best_trial_id, best_run_id,
    validation_run_id, best_params, train_metric_value, validation_metric_value,
    validation_metrics_json, created_at, completed_at, updated_at
) VALUES (
    %(walk_forward_id)s, %(window_index)s, %(train_start)s, %(train_end)s,
    %(val_start)s, %(val_end)s, %(status)s, %(error_message)s,
    %(train_sweep_id)s, %(best_trial_id)s, %(best_run_id)s,
    %(validation_run_id)s, %(best_params)s::jsonb, %(train_metric_value)s,
    %(validation_metric_value)s, %(validation_metrics_json)s::jsonb,
    %(created_at)s, %(completed_at)s, NOW()
)
"""


__all__ = [
    "PgWalkForwardResultStore",
    "WalkForwardPersistenceError",
    "walk_forward_windows_to_frame",
]
