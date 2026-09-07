"""持仓诊断路由：9 个端点（``main.py`` 里统一加 ``/v1`` 前缀）。

契约见 ``getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md`` §7.1。
**实际路径是 ``/v1/diagnosis/...``**，不是设计文档写的 ``/api/v1/...`` ——
本仓所有路由都挂在 ``/v1`` 下，没有 ``/api`` 段。

路由层只做参数校验、鉴权与响应包壳，计算与 SQL 全在 ``services/diagnosis.py``。

**计算结果与渲染报告分成两个端点**是架构篇 §3.2「表现层无领域逻辑」的接口体现：
``/result`` 是全量指标（pro 用），``/report`` 是裁剪后的 Section 数组（前端直接渲染）。
同一份 ``diagnosis_run.payload`` 服务两者，``user_level`` 不参与计算缓存键。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from gr_api.deps import get_current_user, get_db, request_id
from gr_api.errors import ApiError
from gr_api.response import success
from gr_api.schemas.diagnosis import ApiResponse, ShareTokenCreated, SnapshotRequest
from gr_api.schemas.diagnosis_response import (
    DataQualityResponse,
    DiagnosisResult,
    ErrorResponse,
    ReportResponse,
    SharedReportResponse,
    SnapshotAccepted,
    SnapshotMeta,
    SnapshotProgress,
    SpecVersionInfo,
    SpecVersionList,
)
from gr_api.services import diagnosis as diag_svc
from gr_api.services.sse import sse_frame
from gr_data.db import pg_pool


if TYPE_CHECKING:
    from psycopg import AsyncConnection


class DiagnosisRoute(APIRoute):
    """诊断专属错误契约，不改变其他业务路由的信封。"""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request: Request):
            try:
                return await handler(request)
            except (RequestValidationError, ApiError) as exc:
                if isinstance(exc, RequestValidationError):
                    status_code, code, message = (
                        422,
                        "validation_error",
                        "请求参数不符合诊断接口约束。",
                    )
                    issues = [
                        {
                            "path": "/"
                            + "/".join(
                                str(v).replace("~", "~0").replace("/", "~1")
                                for v in error["loc"]
                                if v != "body"
                            ),
                            "code": error["type"],
                            "message": error["msg"],
                        }
                        for error in exc.errors()
                    ]
                else:
                    status_code, message, issues = (
                        exc.http_status,
                        exc.message,
                        getattr(exc, "issues", []),
                    )
                    code = {
                        403: "forbidden",
                        404: "not_found",
                        409: "idempotency_conflict",
                        422: "validation_error",
                        503: "data_unavailable",
                    }.get(status_code, "request_failed")
                payload = ErrorResponse(
                    request_id=request.headers.get("X-Request-Id") or uuid4().hex,
                    error={
                        "code": code,
                        "message": message,
                        "retryable": status_code >= 500,
                        "issues": issues,
                    },
                )
                return JSONResponse(payload.model_dump(mode="json"), status_code=status_code)

        return wrapped


router = APIRouter(
    prefix="/diagnosis",
    tags=["组合诊断"],
    route_class=DiagnosisRoute,
    responses={code: {"model": ErrorResponse} for code in (403, 404, 409, 422, 503)},
)


def _response_headers(response: Response, data: dict) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    if data["run_status"] in ("pending", "running"):
        response.status_code = 202
        response.headers["Retry-After"] = "1"


# ---------------------------------------------------------------- 提交与读取


@router.post(
    "/snapshots",
    response_model=ApiResponse[SnapshotAccepted],
    responses={
        201: {"model": ApiResponse[SnapshotAccepted]},
        202: {"model": ApiResponse[SnapshotAccepted]},
    },
)
async def create_snapshot(
    body: SnapshotRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """提交持仓 + 意图。

    * ``200`` —— ``Idempotency-Key`` 重放，返回原 snapshot
    * ``201`` —— 新建 snapshot，计算已完成

    一期计算同步执行（架构篇 §6.1/§6.5：毫秒量级，请求路径不引入队列），
    因此不会返回 202；``202`` 的分支保留在 ``/result`` 侧，等将来计算转异步时
    前端不需要改。
    """
    if idempotency_key is not None:
        try:
            parsed = UUID(idempotency_key)
            if parsed.version != 4:
                raise ValueError("not UUIDv4")
            idempotency_key = str(parsed)
        except ValueError:
            raise RequestValidationError(
                [
                    {
                        "loc": ("headers", "Idempotency-Key"),
                        "type": "uuid4",
                        "msg": "Idempotency-Key must be a UUIDv4",
                    }
                ]
            ) from None
    data, status_code = await diag_svc.create_snapshot(
        db, body, user_id=user_id, idempotency_key=idempotency_key
    )
    response.status_code = status_code
    response.headers["Location"] = data["links"]["result"]
    _response_headers(response, data)
    return success(data, rid)


@router.get(
    "/snapshots/{snapshot_id}/result",
    response_model=ApiResponse[DiagnosisResult | SnapshotProgress],
    responses={202: {"model": ApiResponse[SnapshotProgress]}},
)
async def get_result(
    snapshot_id: UUID,
    response: Response,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """一次性取全量结果。

    计算未完成时返回 ``202 + Retry-After``（§7.4）。注意 ``run_status=failed``
    走的是 **200**：那是「计算失败」这一业务事实，与 5xx 的「系统故障」严格
    分离，否则运维无法用状态码区分「要排查系统」还是「这是正常的数据缺口」。
    """
    data = await diag_svc.get_result(db, snapshot_id, user_id=user_id)
    _response_headers(response, data)
    return success(data, rid)


@router.get(
    "/snapshots/{snapshot_id}/report",
    response_model=ApiResponse[ReportResponse | SnapshotProgress],
    responses={202: {"model": ApiResponse[SnapshotProgress]}},
)
async def get_report(
    snapshot_id: UUID,
    response: Response,
    user_level: str | None = Query(default=None, pattern=r"^(retail|pro)$"),
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """取渲染后报告，按**访问时**的 ``user_level`` 裁剪。

    缺省为 retail；浏览器不缓存私有报告，切换偏好不触发计算。
    """
    data = await diag_svc.get_report(db, snapshot_id, user_id=user_id, user_level=user_level)
    _response_headers(response, data)
    return success(data, rid)


@router.get(
    "/snapshots/{snapshot_id}/data-quality",
    response_model=ApiResponse[DataQualityResponse | SnapshotProgress],
    responses={202: {"model": ApiResponse[SnapshotProgress]}},
)
async def get_data_quality(
    snapshot_id: UUID,
    response: Response,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """单独取降级清单与强制声明。"""
    data = await diag_svc.get_data_quality(db, snapshot_id, user_id=user_id)
    _response_headers(response, data)
    return success(data, rid)


# ---------------------------------------------------------------- SSE 分批推送


async def _stream_sections(snapshot_id: UUID, result: dict, request: Request):
    """当前同步实现只存在晚订阅：发送 meta 和完整终态，不补造批次。"""
    meta = {k: result[k] for k in SnapshotMeta.model_fields}
    meta.update(
        run_status=result["run_status"],
        disclosures=result.get("disclosures", []),
        plans=[
            {
                "plan_id": p["plan_id"],
                "label": p["label"],
                "input": p["input"],
                "disclosures": next(
                    (
                        q["forced_disclosures"]
                        for q in result["data_quality"]["plans"]
                        if q["plan_id"] == p["plan_id"]
                    ),
                    [],
                ),
            }
            for p in result["plans"]
        ],
    )
    yield sse_frame("meta", meta, event_id="0")
    if not await request.is_disconnected():
        yield sse_frame("complete", result, event_id="1")


@router.get("/snapshots/{snapshot_id}/stream")
async def stream_snapshot(
    snapshot_id: UUID,
    request: Request,
    user_id: str | None = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 分批推送。

    归属校验在这里**先行**做完（``get_result`` 内部会校验）：StreamingResponse
    一旦开始就已经把 200 和响应头刷出去了，那之后再抛异常无法转成干净的 403/404。
    """
    # yield 型 FastAPI 依赖会等流结束才清理，不能把 get_db 挂在 SSE 路由上；
    # 在返回 StreamingResponse 前显式退出连接上下文，流只消费内存中的 result。
    async with pg_pool.connection() as db:
        result = await diag_svc.get_result(db, snapshot_id, user_id=user_id)

    if result["run_status"] in ("pending", "running"):
        return JSONResponse(
            success(result, request.headers.get("X-Request-Id") or uuid4().hex),
            status_code=202,
            headers={"Retry-After": "1", "Cache-Control": "private, no-store"},
        )

    return StreamingResponse(
        _stream_sections(snapshot_id, result, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # 关掉 nginx 缓冲，否则分批推送会被攒成一坨
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------- 口径版本


@router.get("/spec-versions", response_model=ApiResponse[SpecVersionList])
async def list_spec_versions(
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """口径版本列表。"""
    rows = await diag_svc.list_spec_versions(db)
    return success(
        {"items": [{k: row[k] for k in SpecVersionInfo.model_fields} for row in rows]}, rid
    )


@router.get("/spec-versions/current", response_model=ApiResponse[SpecVersionInfo])
async def get_current_spec_version(
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """当前生效口径、阈值与协方差方法配置。

    前端不该把阈值抄成自己的常量：阈值是 ``spec_version.params`` 的内容，
    版本化后调整不需要改代码，抄一份就会在下次调参时静默失配。
    """
    row = await diag_svc.get_active_spec_version(db)
    return success({k: row[k] for k in SpecVersionInfo.model_fields}, rid)


# ---------------------------------------------------------------- 分享


@router.post(
    "/snapshots/{snapshot_id}/share",
    status_code=201,
    response_model=ApiResponse[ShareTokenCreated],
)
async def create_share(
    snapshot_id: UUID,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """创建分享 token。"""
    data = await diag_svc.create_share_token(db, snapshot_id, user_id=user_id)
    return success(data, rid)


@router.get("/share/{token}/report", response_model=ApiResponse[SharedReportResponse])
async def get_shared_report(
    token: str,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """分享链接专用：只暴露渲染后报告，**不暴露 /result 全量数据**。"""
    data = await diag_svc.get_shared_report(db, token)
    if data["run_status"] in ("pending", "running"):
        from gr_api.errors import BadRequest

        raise BadRequest("shared report is not ready", http_status=503)
    # 分享 DTO 白名单：不带 snapshot、plan、输入持仓或私有数据质量路径。
    return success(
        {
            "report_mode": data["report_mode"],
            "disclosures": data["disclosures"],
            "sections": [
                {"title": section["title"], "content": section["content"]}
                for section in data["sections"]
                if section["kind"] != "instrument"
            ],
        },
        rid,
    )
