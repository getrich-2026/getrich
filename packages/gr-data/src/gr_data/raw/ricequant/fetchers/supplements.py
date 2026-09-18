"""米筐指数补充采集：准入后串行抓取，不写 PostgreSQL。"""

from __future__ import annotations

import logging
import math
from collections import deque
from datetime import datetime
from importlib.metadata import version
from zoneinfo import ZoneInfo

import pandas as pd

from gr_data.common.retry import PermanentError, sleep_s
from gr_data.common.ricequant_specs import (
    BudgetDeferredError,
    ContractViolationError,
    RangeTooLargeError,
    RawIntegrityError,
)
from gr_data.config.ricequant import DatasetOptions, RicequantImportOptions
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.client import RicequantClient
from gr_data.raw.ricequant.planner import RequestSlice, plan_slices, split_slice
from gr_data.raw.ricequant.shapes import decode_response
from gr_data.raw.ricequant.store import RqRawStore, file_hash


log = logging.getLogger(__name__)


def _check_quota(client: RicequantClient, reserve: float) -> None:
    try:
        quota = client.get_quota()
    except ConnectionError:
        # 账户配额查询失败无法用缩小行情日期恢复；暂停，避免误触发分片树。
        raise BudgetDeferredError("米筐配额暂不可读，保留进度等待恢复") from None
    if not isinstance(quota, dict):
        raise PermanentError("米筐配额返回类型无效，请核对账号契约")
    limit, used = quota.get("bytes_limit"), quota.get("bytes_used")
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in (limit, used)):
        raise PermanentError("米筐配额返回字段无效，请核对账号契约")
    if limit and used >= limit * (1 - reserve):
        raise BudgetDeferredError("米筐已触及配额安全余量，剩余分片等待恢复")


def fetch_slice(client: RicequantClient, request: RequestSlice) -> tuple[pd.DataFrame, str]:
    """静态派发已实现接口，SDK 日期与 fields 均来自验证过的计划。"""
    if request.dataset == "rq_index_daily":
        response = client.get_price(
            list(request.codes),
            request.start_date,
            request.end_date,
            frequency="1d",
            adjust_type="none",
            market="cn",
            fields=list(request.fields),
            expect_df=True,
        )
    elif request.dataset == "rq_index_components":
        response = client.index_components(request.codes[0], date=request.start_date)
    elif request.dataset == "rq_index_weights":
        response = client.index_weights(request.codes[0], date=request.start_date)
    else:
        raise ContractViolationError("米筐数据集没有实现 SDK 派发")
    return decode_response(request, response)


def run_supplement(
    client: RicequantClient,
    ctx: RawContext,
    options: DatasetOptions,
    shared: RicequantImportOptions,
    *,
    mode: str,
) -> int:
    """读取主源日历快照并按片发布；失败片不推进覆盖，结束返回非零错误。"""
    calendar_path = ctx.paths.dataset_file("tushare", "calendar", "SSE")
    try:
        calendar_hash = file_hash(calendar_path)
        calendar = pd.read_parquet(calendar_path)
        dates = pd.to_datetime(calendar["cal_date"], format="%Y%m%d", errors="raise")
        flags = pd.to_numeric(calendar["is_open"], errors="raise")
        expected_dates = set(pd.date_range(options.start_date, options.end_date).date)
        if dates.isna().any() or not flags.isin([0, 1]).all() or dates.duplicated().any():
            raise ValueError
        if not expected_dates <= set(dates.dt.date):
            raise ValueError
        days = tuple(dates.loc[flags.eq(1)].dt.date)
        if calendar_hash != file_hash(calendar_path):
            raise ValueError
    except (OSError, ValueError, KeyError):
        raise RawIntegrityError("补充任务缺少覆盖所选区间的完整 Tushare 日历快照") from None
    store = RqRawStore(ctx.paths, options.name, options.contract_version, options.variant_id)
    count = 0
    failed = []
    if ctx.max_retries < 1:
        raise ContractViolationError("米筐重试次数必须为正整数")
    with store.writer():
        completed, previous_splits = store.progress()
        scope = plan_slices(options, days, calendar_hash, mode="init", completed=set())
        requests = plan_slices(options, days, calendar_hash, mode=mode, completed=completed)
        tasks, minimum_seq = store.start_round(scope, requests, completed)
        round_completed, round_splits = store.progress(minimum_seq=minimum_seq)
        pending = deque(tasks)
        while pending:
            request, resume = pending.popleft()
            coverage = completed if resume else round_completed
            splits = previous_splits if resume else round_splits
            if request.request_id in coverage:
                continue
            if request.request_id in splits:
                pending.extendleft(
                    (child, resume) for child in reversed(splits[request.request_id])
                )
                continue
            plan = store.begin(
                request,
                sdk_version=version("rqdatac"),
                evidence=options.evidence,
                minimum_seq=0 if resume else minimum_seq,
            )
            if request.not_applicable:
                store.publish(
                    plan,
                    None,
                    status="not_applicable",
                    observed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
                )
                continue
            try:
                _check_quota(client, shared.quota_reserve_fraction)
                for attempt in range(ctx.max_retries):
                    try:
                        frame, status = fetch_slice(client, request)
                        observed_at = datetime.now(ZoneInfo("Asia/Shanghai"))
                        break
                    except ConnectionError:
                        if attempt + 1 >= ctx.max_retries:
                            raise
                        sleep_s(ctx.backoff_base * 2**attempt)
                    finally:
                        sleep_s(ctx.sleep_between_requests)
                if frame.memory_usage(deep=True).sum() > options.max_pending_bytes:
                    frame = None  # 在拆分请求前释放大响应，避免父片与子片同时驻留。
                    raise RangeTooLargeError("米筐响应超过分片内存预算")
                store.publish(plan, frame, status=status, observed_at=observed_at)
                count += 1
            except BudgetDeferredError:
                raise
            except (ContractViolationError, PermanentError, ConnectionError) as exc:
                children = (
                    split_slice(request)
                    if isinstance(exc, (RangeTooLargeError, ConnectionError))
                    else ()
                )
                if children:
                    store.publish(
                        plan,
                        None,
                        status="split",
                        children=children,
                        observed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
                        detail=type(exc).__name__,
                    )
                    pending.extendleft((child, resume) for child in reversed(children))
                    continue
                status = "failed" if isinstance(exc, ConnectionError) else "blocked"
                # 只持久化固定错误类别，不保存 SDK 异常全文或响应。
                store.publish(
                    plan,
                    None,
                    status=status,
                    observed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
                    detail=type(exc).__name__,
                )
                failed.append(request.request_id)
                log.error(
                    "Ricequant slice blocked dataset=%s request=%s",
                    options.name,
                    request.request_id,
                )
                if isinstance(exc, PermanentError):
                    raise
                continue
            _check_quota(client, shared.quota_reserve_fraction)
        if failed:
            raise ContractViolationError(f"米筐补充任务有 {len(failed)} 个未完成分片，成功片已保留")
        store.finish_round(scope)
    return count
