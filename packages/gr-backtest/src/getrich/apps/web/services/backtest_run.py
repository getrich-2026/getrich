"""Backtest run read service.

The persisted backtest run history is business data, so all reads come from
PostgreSQL. ClickHouse/DuckDB are intentionally not involved here.

All read endpoints are owner-scoped: callers must pass the authenticated
``user_id``. Cross-user access raises ``NotFound`` to avoid leaking
existence of resources the caller does not own.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from getrich.apps.web.errors import BadRequest, NotFound


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams
    from gr_data.config.settings import BacktestStorageConfig


async def _assert_run_owner(db: AsyncConnection, run_id: str, user_id: str) -> None:
    """Raise ``NotFound`` if ``run_id`` is missing or not owned by ``user_id``."""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT user_id FROM backtest_runs WHERE run_id = %(run_id)s",
            {"run_id": run_id},
        )
        row = await cur.fetchone()
    if row is None or row["user_id"] != user_id:
        raise NotFound(f"backtest run not found: {run_id}")


async def list_runs(
    db: AsyncConnection,
    *,
    strategy_id: str | None,
    status: str | None,
    page: PageParams,
    user_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """List persisted backtest runs owned by ``user_id`` with optional filters."""
    conds: list[str] = ["user_id = %(user_id)s"]
    params: dict[str, object] = {
        "user_id": user_id,
        "limit": page.limit,
        "offset": page.offset,
    }

    if strategy_id:
        conds.append("strategy_id = %(strategy_id)s")
        params["strategy_id"] = strategy_id
    if status:
        conds.append("status = %(status)s")
        params["status"] = status

    where_sql = " AND ".join(conds)
    sql = f"""
        SELECT
            run_id,
            strategy_id,
            strategy_name,
            strategy_names,
            user_id,
            symbols,
            freq,
            status,
            initial_cash,
            final_cash,
            final_equity,
            benchmark_final_equity,
            created_at,
            completed_at,
            updated_at,
            COUNT(*) OVER() AS _total
        FROM backtest_runs
        WHERE {where_sql}
        ORDER BY created_at DESC, run_id DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """

    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    total = int(rows[0]["_total"]) if rows else 0
    return [_run_summary(r) for r in rows], total


async def get_run(
    db: AsyncConnection,
    run_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Return one persisted backtest run detail owned by ``user_id``."""
    sql = """
        SELECT
            run_id,
            strategy_id,
            strategy_name,
            strategy_names,
            user_id,
            config_fingerprint,
            config,
            symbols,
            freq,
            start_at,
            end_at,
            initial_cash,
            final_cash,
            final_equity,
            benchmark_final_equity,
            status,
            error_message,
            created_at,
            completed_at,
            updated_at
        FROM backtest_runs
        WHERE run_id = %(run_id)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"run_id": run_id})
        row = await cur.fetchone()

    if row is None or row["user_id"] != user_id:
        raise NotFound(f"backtest run not found: {run_id}")
    return _run_detail(row)


async def get_equity_curve(
    db: AsyncConnection,
    run_id: str,
    *,
    user_id: str,
    strategy_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return persisted equity points for a run owned by ``user_id``."""
    await _assert_run_owner(db, run_id, user_id)
    conds: list[str] = ["run_id = %(run_id)s"]
    params: dict[str, object] = {"run_id": run_id}
    if strategy_name:
        conds.append("strategy_name = %(strategy_name)s")
        params["strategy_name"] = strategy_name

    where_sql = " AND ".join(conds)
    sql = f"""
        SELECT
            run_id,
            strategy_name,
            dt,
            cash,
            equity,
            trading_pnl,
            mtm_pnl,
            total_fees,
            gross_exposure,
            row_json,
            created_at
        FROM backtest_equity_points
        WHERE {where_sql}
        ORDER BY dt ASC, strategy_name ASC
    """
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return [_equity_point(r) for r in rows]


async def get_metrics(
    db: AsyncConnection,
    run_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Return persisted performance metrics for a run owned by ``user_id``."""
    await _assert_run_owner(db, run_id, user_id)
    sql = """
        SELECT
            run_id,
            total_return,
            log_return,
            annualized_return,
            annualized_volatility,
            sharpe_ratio,
            sortino_ratio,
            calmar_ratio,
            max_drawdown,
            max_drawdown_duration,
            total_fees,
            total_turnover,
            turnover_rate,
            total_trades,
            n_bars,
            risk_free_rate,
            trading_days_per_year,
            metrics_json,
            created_at
        FROM backtest_metrics
        WHERE run_id = %(run_id)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"run_id": run_id})
        row = await cur.fetchone()

    if row is None:
        raise NotFound(f"backtest metrics not found: {run_id}")
    return _metrics(row)


async def get_positions(
    db: AsyncConnection,
    run_id: str,
    *,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return final position rows for a run owned by ``user_id``."""
    await _assert_run_owner(db, run_id, user_id)
    sql = """
        SELECT
            run_id,
            symbol,
            qty,
            position_json,
            created_at
        FROM backtest_final_positions
        WHERE run_id = %(run_id)s
        ORDER BY symbol ASC
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"run_id": run_id})
        rows = await cur.fetchall()
    return [_position(r) for r in rows]


async def get_artifacts(
    db: AsyncConnection,
    run_id: str,
    *,
    user_id: str,
) -> list[dict[str, Any]]:
    """Return external artifact references for a run owned by ``user_id``."""
    await _assert_run_owner(db, run_id, user_id)
    sql = """
        SELECT
            id,
            run_id,
            artifact_type,
            uri,
            checksum,
            meta,
            created_at
        FROM backtest_artifacts
        WHERE run_id = %(run_id)s
        ORDER BY artifact_type ASC, id ASC
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"run_id": run_id})
        rows = await cur.fetchall()
    return [_artifact(r) for r in rows]


async def get_artifact(
    db: AsyncConnection,
    run_id: str,
    artifact_id: str,
    *,
    user_id: str,
) -> dict[str, Any]:
    """Return a single artifact row owned by ``user_id``.

    Cross-user access, missing runs, and missing artifacts all raise
    ``NotFound`` — existence of a resource the caller does not own is never
    disclosed.
    """
    await _assert_run_owner(db, run_id, user_id)
    sql = """
        SELECT
            id,
            run_id,
            artifact_type,
            uri,
            checksum,
            meta,
            created_at
        FROM backtest_artifacts
        WHERE run_id = %(run_id)s
          AND id = %(artifact_id)s
    """
    async with db.cursor() as cur:
        await cur.execute(sql, {"run_id": run_id, "artifact_id": artifact_id})
        row = await cur.fetchone()
    if row is None:
        raise NotFound(f"backtest artifact not found: {artifact_id}")
    return _artifact(row)


@dataclass(frozen=True)
class ArtifactFileContent:
    """Resolved on-disk artifact ready for streaming download."""

    path: Path
    filename: str
    content_type: str
    size: int


# Schemes that the binary download endpoint refuses to serve directly.
# HTTPS artifacts continue to flow through the front-end's external link
# helper; S3 / GCS / Azure URIs need a different (presigned) flow that is
# out of scope for this P1 task.
_REJECTED_URI_SCHEMES = frozenset({"http", "https", "s3", "gs", "azure"})

# RFC 6266: filename must be a quoted-string; restrict to printable ASCII
# without quotes / backslashes / control characters.
_FILENAME_SAFE_RE = re.compile(r"[^\x20\x21\x23-\x7e]")


def _sanitize_filename(name: str) -> str:
    cleaned = _FILENAME_SAFE_RE.sub("_", name).strip().strip('"')
    return cleaned or "artifact"


def _resolve_local_path(uri: str, *, artifact_root: Path) -> Path:
    """Resolve ``uri`` to an absolute on-disk path under ``artifact_root``.

    Accepted URI shapes:
      - bare absolute path: ``/var/lib/getrich/artifacts/run-1/manifest.json``
        or ``C:\\artifacts\\run-1\\manifest.json`` (Windows).
      - file URL:           ``file:///var/lib/getrich/artifacts/...``

    Any other scheme (``http``, ``https``, ``s3``, ...) raises
    ``BadRequest``. Resolved paths that escape ``artifact_root`` (via
    ``..`` segments, symlink hops, or absolute escapes) raise
    ``NotFound`` to avoid leaking existence of files outside the root.
    """
    if not uri:
        raise NotFound("backtest artifact not found")

    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    # On Windows, ``Path("C:\\foo").as_uri()`` produces
    # ``file:///C:/foo`` and urlparse will split that into scheme='file',
    # netloc='', path='/C:/foo'. Plain Windows paths like
    # ``C:\\foo`` get parsed with scheme='c' (the drive letter) — we
    # detect single-letter schemes and treat the input as a bare path so
    # dev environments on Windows work the same way as Linux.
    is_windows_drive = len(scheme) == 1 and scheme.isalpha()

    if scheme and not is_windows_drive and scheme not in ("file", ""):
        # Any non-local scheme is rejected so the request cannot be turned
        # into an SSRF or an unauthorized external fetch by tampering with
        # the artifact row.
        raise BadRequest(f"artifact uri is not a local file: scheme={scheme!r}")

    if scheme == "file":
        # urlparse puts the on-disk path in ``path`` for ``file://`` URLs.
        # On Windows, ``Path.as_uri()`` produces ``file:///C:/foo`` whose
        # parsed path is ``/C:/foo`` — strip the extra leading slash so
        # ``Path(...)`` resolves the drive letter correctly.
        raw = parsed.path
        if (
            os.name == "nt"
            and len(raw) >= 3
            and raw[0] == "/"
            and raw[2] == ":"
            and raw[1].isalpha()
        ):
            raw = raw[1:]
        target = Path(raw)
    else:
        # Bare absolute path (the shape produced by
        # ``artifacts_from_report_dir`` in getrich_backtest.persistence).
        target = Path(uri)

    if not target.is_absolute():
        # Relative paths would otherwise be resolved against CWD and
        # accidentally escape the artifact root.
        raise NotFound("backtest artifact not found")

    resolved_root = artifact_root.resolve()
    try:
        resolved_target = target.resolve(strict=False)
    except OSError:
        raise NotFound("backtest artifact not found") from None

    if not resolved_target.is_relative_to(resolved_root):
        # Path traversal / symlink escape — do not reveal that the file
        # exists.
        raise NotFound("backtest artifact not found")

    return resolved_target


async def stream_artifact_file(
    db: AsyncConnection,
    run_id: str,
    artifact_id: str,
    *,
    user_id: str,
    storage: BacktestStorageConfig,
) -> ArtifactFileContent:
    """Resolve an artifact row to a streamable on-disk file for download.

    - Owner scope: re-uses ``_assert_run_owner`` so cross-user access
      raises ``NotFound``.
    - URI scheme: only bare absolute paths and ``file://`` URLs are
      accepted; everything else raises ``BadRequest``.
    - Path safety: the resolved path must remain under
      ``storage.artifact_dir``; otherwise ``NotFound``.
    - File existence: the path must be a regular file; otherwise
      ``NotFound``.

    Returns an :class:`ArtifactFileContent` carrying the resolved path,
    a sanitized filename, a best-effort MIME type, and the file size.
    """
    artifact = await get_artifact(db, run_id, artifact_id, user_id=user_id)
    target = _resolve_local_path(artifact["uri"], artifact_root=storage.artifact_dir)

    if not target.is_file():
        raise NotFound("backtest artifact not found")

    guessed, _ = mimetypes.guess_type(artifact["uri"])
    content_type = guessed or "application/octet-stream"
    size = target.stat().st_size
    filename = _sanitize_filename(Path(artifact["uri"]).name)
    return ArtifactFileContent(path=target, filename=filename, content_type=content_type, size=size)


# ---------------------------------------------------------------- helpers


def _run_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "strategy_id": row["strategy_id"],
        "strategy_name": row["strategy_name"],
        "strategy_names": _json_value(row["strategy_names"], []),
        "symbols": _json_value(row["symbols"], []),
        "freq": row["freq"],
        "status": row["status"],
        "initial_cash": _f(row["initial_cash"]),
        "final_cash": _f_nullable(row["final_cash"]),
        "final_equity": _f_nullable(row["final_equity"]),
        "benchmark_final_equity": _f_nullable(row["benchmark_final_equity"]),
        "created_at": _dt(row["created_at"]),
        "completed_at": _dt_nullable(row["completed_at"]),
        "updated_at": _dt(row["updated_at"]),
    }


def _run_detail(row: dict[str, Any]) -> dict[str, Any]:
    data = _run_summary(row)
    data.update(
        {
            "config_fingerprint": row["config_fingerprint"],
            "config": _json_value(row["config"], {}),
            "start_at": _dt(row["start_at"]),
            "end_at": _dt(row["end_at"]),
            "error_message": row["error_message"],
        }
    )
    return data


def _equity_point(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "strategy_name": row["strategy_name"],
        "dt": _dt(row["dt"]),
        "cash": _f_nullable(row["cash"]),
        "equity": _f(row["equity"]),
        "trading_pnl": _f_nullable(row["trading_pnl"]),
        "mtm_pnl": _f_nullable(row["mtm_pnl"]),
        "total_fees": _f_nullable(row["total_fees"]),
        "gross_exposure": _f_nullable(row["gross_exposure"]),
        "row_json": _json_value(row["row_json"], {}),
        "created_at": _dt(row["created_at"]),
    }


def _metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "total_return": _f_nullable(row["total_return"]),
        "log_return": _f_nullable(row["log_return"]),
        "annualized_return": _f_nullable(row["annualized_return"]),
        "annualized_volatility": _f_nullable(row["annualized_volatility"]),
        "sharpe_ratio": _f_nullable(row["sharpe_ratio"]),
        "sortino_ratio": _f_nullable(row["sortino_ratio"]),
        "calmar_ratio": _f_nullable(row["calmar_ratio"]),
        "max_drawdown": _f_nullable(row["max_drawdown"]),
        "max_drawdown_duration": _int_nullable(row["max_drawdown_duration"]),
        "total_fees": _f_nullable(row["total_fees"]),
        "total_turnover": _f_nullable(row["total_turnover"]),
        "turnover_rate": _f_nullable(row["turnover_rate"]),
        "total_trades": _int_nullable(row["total_trades"]),
        "n_bars": _int_nullable(row["n_bars"]),
        "risk_free_rate": _f_nullable(row["risk_free_rate"]),
        "trading_days_per_year": _int_nullable(row["trading_days_per_year"]),
        "metrics_json": _json_value(row["metrics_json"], {}),
        "created_at": _dt(row["created_at"]),
    }


def _position(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "symbol": row["symbol"],
        "qty": _f(row["qty"]),
        "position_json": _json_value(row["position_json"], {}),
        "created_at": _dt(row["created_at"]),
    }


def _artifact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "artifact_type": row["artifact_type"],
        "uri": row["uri"],
        "checksum": row["checksum"],
        "meta": _json_value(row["meta"], {}),
        "created_at": _dt(row["created_at"]),
    }


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _f(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _f_nullable(value: Any) -> float | None:
    if value is None:
        return None
    return _f(value)


def _int_nullable(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _dt(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dt_nullable(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    return _dt(value)
