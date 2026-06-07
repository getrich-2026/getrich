"""后台导入模块路由。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from getrich.apps.web.deps import get_db, request_id, require_admin
from getrich.apps.web.response import success
from getrich.apps.web.schemas.admin_import import ImportPreviewIn, StrategyUpsertIn
from getrich.apps.web.services import admin_import as admin_import_svc


if TYPE_CHECKING:
    from psycopg import AsyncConnection


router = APIRouter(prefix="/admin/imports", tags=["admin-imports"])


@router.post("/strategies/upsert")
async def upsert_strategy(
    body: StrategyUpsertIn,
    admin_user_id: str = Depends(require_admin),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await admin_import_svc.upsert_strategy(db, body=body, admin_user_id=admin_user_id)
    return success(data, rid)


@router.post("/preview")
async def preview_import(
    body: ImportPreviewIn,
    admin_user_id: str = Depends(require_admin),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await admin_import_svc.preview_import(db, body=body, admin_user_id=admin_user_id)
    return success(data, rid)


@router.post("/{job_code}/commit")
async def commit_import(
    job_code: str,
    admin_user_id: str = Depends(require_admin),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    data = await admin_import_svc.commit_import(
        db, job_code=job_code, admin_user_id=admin_user_id,
    )
    return success(data, rid)


@router.get("/history")
async def list_import_history(
    admin_user_id: str = Depends(require_admin),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    _ = admin_user_id
    data = await admin_import_svc.list_import_history(db)
    return success(data, rid)


@router.get("/{job_code}")
async def get_import_job(
    job_code: str,
    admin_user_id: str = Depends(require_admin),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    _ = admin_user_id
    data = await admin_import_svc.get_import_job(db, job_code=job_code)
    return success(data, rid)


@router.get("/{job_code}/errors")
async def list_import_errors(
    job_code: str,
    admin_user_id: str = Depends(require_admin),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    _ = admin_user_id
    data = await admin_import_svc.list_import_errors(db, job_code=job_code)
    return success(data, rid)
