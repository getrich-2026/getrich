"""显式展开 R1–R3 的源形态；缺字段、未知空响应及范围不完整均阻塞。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gr_data.common.ricequant_specs import INDEX_SPECS, ContractViolationError
from gr_data.raw.ricequant.planner import RequestSlice


def _expand(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.columns.duplicated().any():
        raise ContractViolationError("米筐响应列名重复")
    out = frame.copy()
    if not isinstance(out.index, pd.RangeIndex):
        names = out.index.names
        if any(name not in {"order_book_id", "date"} for name in names) or len(set(names)) != len(
            names
        ):
            raise ContractViolationError("米筐响应索引名称不符合契约")
        for name in names:
            values = out.index.get_level_values(name)
            if name in out.columns:
                if not np.array_equal(out[name].to_numpy(), values.to_numpy()):
                    raise ContractViolationError("米筐响应索引与列冲突")
            else:
                out[name] = values
        out = out.reset_index(drop=True)
    return out


def decode_response(request: RequestSlice, response: object) -> tuple[pd.DataFrame, str]:
    """无损展开源字段；仅可信空成分 tuple 可标 valid_empty。"""
    try:
        return _decode_response(request, response)
    except (ValueError, TypeError, OverflowError, AttributeError):
        raise ContractViolationError("米筐返回字段类型或时间格式不符合契约") from None


def _decode_response(request: RequestSlice, response: object) -> tuple[pd.DataFrame, str]:
    if request.dataset == "rq_index_daily":
        if not isinstance(response, pd.DataFrame) or response.empty:
            raise ContractViolationError("指数日值为空或返回类型不符，不能标记覆盖")
        out = _expand(response)
        if "order_book_id" not in out and len(request.codes) == 1:
            out["order_book_id"] = request.codes[0]
        required = {"order_book_id", "date", *request.fields}
        if not required <= set(out.columns):
            raise ContractViolationError("指数日值缺少所选字段或明确日期索引")
        dates = pd.to_datetime(out["date"].astype(str), format="mixed", errors="raise")
        if dates.isna().any() or dates.dt.tz is not None:
            raise ContractViolationError("指数日值须为明确的本地业务日期")
        actual = set(zip(out["order_book_id"], dates.dt.strftime("%Y-%m-%d"), strict=True))
        expected = {(code, day) for code in request.codes for day in request.trading_days}
        if actual != expected:
            raise ContractViolationError("指数日值代码／交易日覆盖不完整或返回了未请求行")
        if pd.DataFrame({"code": out["order_book_id"], "day": dates.dt.date}).duplicated().any():
            raise ContractViolationError("指数日值同一业务日重复")
        close = pd.to_numeric(out["close"], errors="coerce")
        if close.isna().any() or not np.isfinite(close).fillna(False).all() or (close < 0).any():
            raise ContractViolationError("指数 close 无效")
        numeric = {}
        for field in request.fields:
            values = pd.to_numeric(out[field], errors="coerce")
            if (out[field].notna() & (~np.isfinite(values) | values.lt(0))).any():
                raise ContractViolationError("指数日值含非法价格、数量或成交额")
            numeric[field] = values
        if "high" in numeric and "low" in numeric:
            if numeric["high"].lt(numeric["low"]).any():
                raise ContractViolationError("指数最高价低于最低价")
            for field in ("open", "close"):
                if (
                    field in numeric
                    and (
                        numeric[field].gt(numeric["high"]) | numeric[field].lt(numeric["low"])
                    ).any()
                ):
                    raise ContractViolationError("指数开收盘价格超出高低价区间")
    elif request.dataset == "rq_index_components":
        if not isinstance(response, tuple) or len(response) != 2:
            raise ContractViolationError("指数成分须返回 (members, create_tm)，禁止降级")
        members, created = response
        if not isinstance(members, list) or created is None or pd.isna(created):
            raise ContractViolationError("指数成分缺成员列表或源入库时间")
        out = pd.DataFrame({"member_source_symbol": members})
        out["create_tm"] = pd.Timestamp(created)
        if pd.isna(pd.Timestamp(created)):
            raise ContractViolationError("指数成分源入库时间无效")
        # create_tm 仅保留为供应商原始时间；未证明市场可用时点，不赋 PIT 语义。
        out.attrs["source_metadata"] = {
            "create_tm": pd.Timestamp(created).isoformat(),
            "pit_status": "unverified",
        }
        out["index_code"] = request.codes[0]
        out["query_date"] = request.start_date
        if not members:
            return out, "valid_empty"
    elif request.dataset == "rq_index_weights":
        if (
            not isinstance(response, pd.Series)
            or response.empty
            or isinstance(response.index, pd.MultiIndex)
        ):
            raise ContractViolationError("指数权重须为非空成员 Series")
        out = pd.DataFrame({"member_source_symbol": response.index, "weight": response.to_numpy()})
        out["index_code"] = request.codes[0]
        out["query_date"] = request.start_date
        values = pd.to_numeric(out["weight"], errors="coerce")
        if not np.isfinite(values).all() or (values < 0).any():
            raise ContractViolationError("指数权重含负值或非有限数")
    else:
        raise ContractViolationError("未实现的米筐 decoder")
    keys = list(INDEX_SPECS[request.dataset].raw_keys)
    if out[keys].isna().any().any() or out.duplicated(keys).any():
        raise ContractViolationError("米筐响应键为空或重复")
    code_key = "order_book_id" if request.dataset == "rq_index_daily" else "member_source_symbol"
    if not out[code_key].map(lambda v: isinstance(v, str) and bool(v.strip())).all():
        raise ContractViolationError("米筐证券代码必须是非空字符串")
    return out, "complete"
