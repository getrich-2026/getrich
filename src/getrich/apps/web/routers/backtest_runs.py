"""Backtest run history read endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from getrich.apps.web.deps import get_db, page_dep, request_id, require_user
from getrich.apps.web.pagination import make_pagination
from getrich.apps.web.response import success
from getrich.apps.web.services import backtest_run as backtest_run_svc
from getrich.config import settings
from getrich.config.settings import BacktestStorageConfig


if TYPE_CHECKING:
    from pathlib import Path

    from psycopg import AsyncConnection

    from getrich.apps.web.pagination import PageParams


router = APIRouter(prefix="/backtest-runs", tags=["backtest"])


def backtest_storage_dep() -> BacktestStorageConfig:
    """Dependency-injected artifact storage configuration.

    Exposed as a function so tests can override it via
    ``app.dependency_overrides`` without monkey-patching the global
    ``settings`` singleton.
    """
    return settings.backtest_storage


def _iter_file_chunks(path: Path, *, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """Yield ``path`` in fixed-size chunks for :class:`StreamingResponse`.

    The file handle is scoped to the generator so it is closed as soon as
    the stream is exhausted or the client disconnects.
    """
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                return
            yield chunk


@router.get("")
async def list_runs(
    strategy_id: str | None = None,
    status: str | None = Query(None, pattern=r"^(running|completed|failed)$"),
    page: PageParams = Depends(page_dep),
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    items, total = await backtest_run_svc.list_runs(
        db,
        strategy_id=strategy_id,
        status=status,
        page=page,
        user_id=user_id,
    )
    return success({"list": items, "pagination": make_pagination(page, total)}, rid)


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await backtest_run_svc.get_run(db, run_id, user_id=user_id)
    return success(data, rid)


@router.get("/{run_id}/equity-curve")
async def get_equity_curve(
    run_id: str,
    strategy_name: str | None = None,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    points = await backtest_run_svc.get_equity_curve(
        db,
        run_id,
        user_id=user_id,
        strategy_name=strategy_name,
    )
    return success({"points": points, "total_points": len(points)}, rid)


@router.get("/{run_id}/metrics")
async def get_metrics(
    run_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await backtest_run_svc.get_metrics(db, run_id, user_id=user_id)
    return success(data, rid)


@router.get("/{run_id}/positions")
async def get_positions(
    run_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    positions = await backtest_run_svc.get_positions(db, run_id, user_id=user_id)
    return success({"list": positions}, rid)


@router.get("/{run_id}/artifacts")
async def get_artifacts(
    run_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    artifacts = await backtest_run_svc.get_artifacts(db, run_id, user_id=user_id)
    return success({"list": artifacts}, rid)


@router.get("/{run_id}/artifacts/{artifact_id}/content")
async def get_artifact_content(
    run_id: str,
    artifact_id: str,
    user_id: str = Depends(require_user),
    db: AsyncConnection = Depends(get_db),
    storage: BacktestStorageConfig = Depends(backtest_storage_dep),
    rid: str = Depends(request_id),
):
    """Stream the binary content of a single artifact owned by ``user_id``.

    Authorization: the artifact row is loaded with the same owner check
    used for the metadata endpoint, so cross-user access raises
    ``NotFound``. URI scheme is restricted to local file paths in the
    service layer (``BadRequest`` otherwise). Path traversal is blocked
    via ``Path.is_relative_to`` in the service.
    """
    content = await backtest_run_svc.stream_artifact_file(
        db,
        run_id,
        artifact_id,
        user_id=user_id,
        storage=storage,
    )
    quoted = quote(content.filename, safe="")
    headers = {
        "Content-Disposition": f'attachment; filename="{quoted}"',
        "Content-Length": str(content.size),
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(
        _iter_file_chunks(content.path),
        media_type=content.content_type,
        headers=headers,
    )
