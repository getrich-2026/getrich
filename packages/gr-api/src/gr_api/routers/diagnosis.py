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
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from gr_api.deps import get_current_user, get_db, request_id
from gr_api.response import success
from gr_api.schemas.diagnosis import (
    ApiResponse,
    DataQualityReport,
    DiagnosisReport,
    DiagnosisResult,
    ShareTokenCreated,
    SnapshotAccepted,
    SnapshotRequest,
    SpecVersionInfo,
    SpecVersionList,
)
from gr_api.services import diagnosis as diag_svc
from gr_api.services.sse import sse_frame
from gr_data.db import pg_pool


if TYPE_CHECKING:
    from psycopg import AsyncConnection


router = APIRouter(prefix="/diagnosis", tags=["组合诊断"])


# ---------------------------------------------------------------- 提交与读取


@router.post("/snapshots", response_model=ApiResponse[SnapshotAccepted])
async def create_snapshot(
    body: SnapshotRequest,
    response: Response,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """提交持仓 + 意图。

    * ``200`` —— ``request_hash`` 命中，返回已有 snapshot
    * ``201`` —— 新建 snapshot，计算已完成

    一期计算同步执行（架构篇 §6.1/§6.5：毫秒量级，请求路径不引入队列），
    因此不会返回 202；``202`` 的分支保留在 ``/result`` 侧，等将来计算转异步时
    前端不需要改。
    """
    data, status_code = await diag_svc.create_snapshot(db, body, user_id=user_id)
    response.status_code = status_code
    return success(data, rid)


@router.get("/snapshots/{snapshot_id}/result", response_model=ApiResponse[DiagnosisResult])
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
    if data["run_status"] in ("pending", "running"):
        response.status_code = 202
        response.headers["Retry-After"] = "1"
    return success(data, rid)


@router.get("/snapshots/{snapshot_id}/report", response_model=ApiResponse[DiagnosisReport])
async def get_report(
    snapshot_id: UUID,
    user_level: str | None = Query(default=None, pattern=r"^(retail|pro)$"),
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """取渲染后报告，按**访问时**的 ``user_level`` 裁剪。

    不做渲染结果的持久化缓存 —— 缓存了的话用户等级变更后旧渲染内容会残留可见。
    """
    data = await diag_svc.get_report(db, snapshot_id, user_id=user_id, user_level=user_level)
    return success(data, rid)


@router.get(
    "/snapshots/{snapshot_id}/data-quality",
    response_model=ApiResponse[DataQualityReport],
)
async def get_data_quality(
    snapshot_id: UUID,
    user_id: str | None = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """单独取降级清单与强制声明。"""
    data = await diag_svc.get_data_quality(db, snapshot_id, user_id=user_id)
    return success(data, rid)


# ---------------------------------------------------------------- SSE 分批推送


async def _stream_sections(snapshot_id: UUID, result: dict, request: Request):
    """按架构篇 §6.4 的 4 个批次逐段推送。

    ``id`` 在单条连接内**全局单调递增，不按 plan 重置**：顺序是
    ``meta``(0) → 按 plan 顺序推各自的 4 个批次 → ``complete``(末)。
    ``heartbeat`` 不带 ``id:`` 行，避免干扰前端对序号连续性的判断。

    一期**不支持断线续传**（T18）：计算过程中没有批次级中间结果落盘
    （``payload`` 只在终态写入一次），``Last-Event-ID`` 无从重放。断线后
    客户端改用 ``GET /result`` 轮询取全量。
    """
    event_id = 0
    yield sse_frame(
        "meta",
        {
            "snapshot_id": str(snapshot_id),
            "plan_ids": [p["plan_id"] for p in result["plans"]],
            "cov": result["cov"],
            "weight_mode": {p["plan_id"]: p["weight_mode"] for p in result["plans"]},
            # 首帧就带口径信息：原方案把它们只放在 complete 事件里，导致前端
            # 首屏渲染 section_a 时看不到「按等权假设计算」「历史协方差降级」
            # 这些标注，违反 O6「降级可见」。
            "disclosures": result["disclosures"],
            "run_status": result["run_status"],
        },
        event_id=str(event_id),
    )

    for plan in result["plans"]:
        if await request.is_disconnected():
            return
        pid = plan["plan_id"]

        event_id += 1
        yield sse_frame(
            "section_a", {"plan_id": pid, "section_a": plan["section_a"]}, event_id=str(event_id)
        )

        event_id += 1
        yield sse_frame(
            "section_bd",
            {
                "plan_id": pid,
                "section_b": plan["section_b"],
                "section_d": plan["section_d"],
                "reason_code": None if plan["section_b"] else "factor_model_unavailable",
            },
            event_id=str(event_id),
        )

        event_id += 1
        yield sse_frame(
            "section_c",
            {
                "plan_id": pid,
                "section_c": plan["section_c"],
                "reason_code": None if plan["section_c"] else "spec_not_defined",
            },
            event_id=str(event_id),
        )

        event_id += 1
        yield sse_frame(
            "section_blindspots",
            {
                "plan_id": pid,
                "blindspots": plan["blindspots"],
                "profile": plan["profile"],
                # 压力测试在响应模型里属 RiskSection，但推送时随批次 4 走 ——
                # 它依赖批次 1/3 的中间产物。一期未启用，恒 null。
                "stress_scenarios": None,
            },
            event_id=str(event_id),
        )

    event_id += 1
    yield sse_frame(
        "complete",
        {
            "comparison": result["comparison"],
            "disclosures": result["disclosures"],
            "data_quality": result["data_quality"],
        },
        event_id=str(event_id),
    )


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
    return success({"list": rows}, rid)


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
    return success(row, rid)


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


@router.get("/share/{token}/report", response_model=ApiResponse[DiagnosisReport])
async def get_shared_report(
    token: str,
    db: AsyncConnection = Depends(get_db),
    rid: str = Depends(request_id),
):
    """分享链接专用：只暴露渲染后报告，**不暴露 /result 全量数据**。"""
    data = await diag_svc.get_shared_report(db, token)
    return success(data, rid)
