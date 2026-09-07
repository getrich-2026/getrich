"""持仓诊断的单元与路由测试。

重点覆盖表接口篇 §7.8 标注的「算错但不报错」区域 —— 两套哈希的分工。
其余覆盖降级契约（§7.6）的分支：混合权重、代码解析失败、等权回退、
MetricValue 三态序列化。

不用 httpx 打真实 HTTP（除安全头一例，那条必须走完整中间件栈）：路由函数
直接调用即可验证「路由 ↔ 服务层」的契约与信封，HTTP 管道对每个 FastAPI
路由都一样，已被既有用例覆盖。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gr_api.schemas.diagnosis import (
    HoldingItem,
    PlanResult,
    PortfolioPlan,
    SnapshotRequest,
    UnavailableMetric,
)
from gr_api.services import diagnosis as svc


# ===========================================================================
# §7.8 两套哈希的分工 —— 本模块最重要的一组断言
# ===========================================================================


def _req(plans: list[PortfolioPlan], **kw: Any) -> SnapshotRequest:
    return SnapshotRequest(plans=plans, **kw)


def _plan(plan_id: str, symbols: list[str], *, label: str | None = None) -> PortfolioPlan:
    return PortfolioPlan(
        plan_id=plan_id,
        label=label,
        holdings=[HoldingItem(symbol=s) for s in symbols],
    )


def test_request_hash_distinguishes_before_after_order() -> None:
    """before/after 互换必须得到不同的 request_hash。

    漏掉 label / plan_index 会让两者命中同一个 snapshot —— 调仓结论直接反向，
    而且不会有任何报错。这是 §7.8 共有规则第 2 条存在的全部理由。
    """
    a = _req(
        [_plan("p1", ["600000.SH"], label="before"), _plan("p2", ["000001.SZ"], label="after")]
    )
    b = _req(
        [_plan("p1", ["600000.SH"], label="after"), _plan("p2", ["000001.SZ"], label="before")]
    )

    assert svc._request_hash(a) != svc._request_hash(b)


def test_request_hash_is_stable_for_identical_requests() -> None:
    a = _req([_plan("p1", ["600000.SH", "000001.SZ"])])
    b = _req([_plan("p1", ["600000.SH", "000001.SZ"])])
    assert svc._request_hash(a) == svc._request_hash(b)


def _calc(holdings: list[dict], **kw: Any) -> str:
    defaults = {
        "weight_mode": "user",
        "resolved_as_of_date": date(2026, 8, 28),
        "spec_version": "v1-hist-20260901",
        "data_fingerprint": "20260830T0000",
    }
    defaults.update(kw)
    return svc._calculation_hash(resolved_holdings=holdings, **defaults)


def test_calculation_hash_ignores_holding_order() -> None:
    """换个输入顺序必须命中同一份计算 —— 否则跨用户复用形同虚设。"""
    forward = _calc([{"instrument_id": 1, "weight": 0.6}, {"instrument_id": 2, "weight": 0.4}])
    reverse = _calc([{"instrument_id": 2, "weight": 0.4}, {"instrument_id": 1, "weight": 0.6}])
    assert forward == reverse


def test_calculation_hash_changes_with_data_fingerprint() -> None:
    """数据快照变了必须重算，否则接口会拿旧数据的结果糊弄新请求。"""
    base = _calc([{"instrument_id": 1, "weight": 1.0}])
    moved = _calc([{"instrument_id": 1, "weight": 1.0}], data_fingerprint="20260831T0000")
    assert base != moved


def test_calculation_hash_changes_with_spec_version() -> None:
    base = _calc([{"instrument_id": 1, "weight": 1.0}])
    other = _calc([{"instrument_id": 1, "weight": 1.0}], spec_version="v2")
    assert base != other


def test_calculation_hash_rounds_weights_half_even() -> None:
    """权重按 8 位小数舍入后入哈希：第 9 位的差异不该打散缓存。"""
    a = _calc([{"instrument_id": 1, "weight": 0.333333333}])
    b = _calc([{"instrument_id": 1, "weight": 0.3333333334}])
    assert a == b


def test_canonical_json_is_key_order_independent() -> None:
    assert svc._canonical_json({"b": 1, "a": 2}) == svc._canonical_json({"a": 2, "b": 1})


# ===========================================================================
# 权重归一化与降级契约（§7.6）
# ===========================================================================


_INST = {
    "600000.SH": {"instrument_id": 1, "symbol": "600000.SH"},
    "000001.SZ": {"instrument_id": 2, "symbol": "000001.SZ"},
}


def test_equal_weight_fallback_when_no_weights_given() -> None:
    plan = _plan("p1", ["600000.SH", "000001.SZ"])
    mode, holdings, unresolved, dup, in_w, res_w = svc._normalize_plan(plan, _INST)

    assert mode == "equal"
    assert [h["weight"] for h in holdings] == [0.5, 0.5]
    assert unresolved == [] and dup == []
    # 等权模式下覆盖率用条目数表达
    assert (in_w, res_w) == (Decimal(2), Decimal(2))


def test_user_weights_are_normalised_to_one() -> None:
    plan = PortfolioPlan(
        plan_id="p1",
        holdings=[
            HoldingItem(symbol="600000.SH", weight=Decimal("30")),
            HoldingItem(symbol="000001.SZ", weight=Decimal("10")),
        ],
    )
    mode, holdings, *_ = svc._normalize_plan(plan, _INST)

    assert mode == "user"
    assert [h["weight"] for h in holdings] == [0.75, 0.25]


def test_unresolved_symbol_keeps_resolvable_subset_and_reports_coverage() -> None:
    """部分代码解析不了 → 保留可解析子集出数，覆盖率必须如实反映缺口。"""
    plan = PortfolioPlan(
        plan_id="p1",
        holdings=[
            HoldingItem(symbol="600000.SH", weight=Decimal("60")),
            HoldingItem(symbol="999999.SH", weight=Decimal("40")),  # 不在 _INST 里
        ],
    )
    mode, holdings, unresolved, _dup, in_w, res_w = svc._normalize_plan(plan, _INST)

    assert unresolved == ["999999.SH"]
    # 归一化在可解析子集内完成：唯一剩下的标的权重是 1.0
    assert [h["weight"] for h in holdings] == [1.0]
    # 而覆盖率仍按**原始**权重算，暴露出 40% 没算进来
    assert float(res_w / in_w) == pytest.approx(0.6)
    assert mode == "user"


def test_duplicate_symbols_are_merged_not_rejected() -> None:
    plan = PortfolioPlan(
        plan_id="p1",
        holdings=[
            HoldingItem(symbol="600000.SH", weight=Decimal("30")),
            HoldingItem(symbol="600000.SH", weight=Decimal("10")),
        ],
    )
    _mode, holdings, _unres, dup, _in_w, _res_w = svc._normalize_plan(plan, _INST)

    assert dup == ["600000.SH"]
    assert len(holdings) == 1
    assert holdings[0]["weight"] == 1.0


def test_duplicate_symbols_use_the_same_normalisation_as_resolution() -> None:
    """大小写与空白不同的同一代码仍然只能算一只。"""
    plan = PortfolioPlan(
        plan_id="p1",
        holdings=[
            HoldingItem(symbol=" 600000.sh ", weight=Decimal("30")),
            HoldingItem(symbol="600000.SH", weight=Decimal("10")),
        ],
    )

    _mode, holdings, unresolved, duplicated, *_ = svc._normalize_plan(plan, _INST)

    assert unresolved == []
    assert duplicated == ["600000.SH"]
    assert len(holdings) == 1
    assert holdings[0]["weight"] == 1.0


def test_zero_weight_resolvable_subset_is_rejected() -> None:
    """不能把用户权重为零的可解析子集静默改成等权。"""
    plan = PortfolioPlan(
        plan_id="p1",
        holdings=[
            HoldingItem(symbol="600000.SH", weight=Decimal(0)),
            HoldingItem(symbol="999999.SH", weight=Decimal(100)),
        ],
    )

    with pytest.raises(Exception, match="zero total user weight") as exc_info:
        svc._normalize_plan(plan, _INST)

    assert exc_info.value.http_status == 422


def test_mixed_weight_input_is_rejected_at_schema_level() -> None:
    """D3：部分填写、部分缺省 → 422，不替用户猜。"""
    with pytest.raises(ValueError, match="mixed weight input"):
        PortfolioPlan(
            plan_id="p1",
            holdings=[
                HoldingItem(symbol="600000.SH", weight=Decimal("0.5")),
                HoldingItem(symbol="000001.SZ"),
            ],
        )


def test_negative_weight_is_rejected() -> None:
    """一期不支持负权重/空头/杠杆（§8.1）。"""
    with pytest.raises(ValueError):
        HoldingItem(symbol="600000.SH", weight=Decimal("-0.1"))


# ===========================================================================
# 模块 A 计算
# ===========================================================================


def _exposure(holdings: list[dict], **kw: Any) -> dict:
    defaults: dict[str, Any] = {
        "params": {"topn": 5, "mktcap_bands_yi": [1000, 3000], "pb_bands": [2, 4]},
        "industry": {},
        "category": {},
        "valuation": {},
        "has_fund": False,
        "input_weight": Decimal(len(holdings)),
        "resolved_weight": Decimal(len(holdings)),
    }
    defaults.update(kw)
    return svc._build_exposure_section(holdings, **defaults)


def test_module_a_scalars_on_equal_weight_pair() -> None:
    """两只等权：L1=2、HHI=0.5、L2=2.0。这是端到端验收用的那组数。"""
    holdings = [
        {"instrument_id": 1, "symbol": "600000.SH", "weight": 0.5},
        {"instrument_id": 2, "symbol": "000001.SZ", "weight": 0.5},
    ]
    a = _exposure(holdings)

    assert a["l1_count"]["value"] == 2
    assert a["hhi"]["value"] == pytest.approx(0.5)
    assert a["l2_effective_count"]["value"] == pytest.approx(2.0)
    assert a["topn"]["value"] == pytest.approx(1.0)
    assert a["calculation_coverage_ratio"] == pytest.approx(1.0)
    assert a["normalized_within_resolved_subset"] is True


def test_module_a_concentrated_portfolio_has_lower_effective_count() -> None:
    holdings = [
        {"instrument_id": 1, "symbol": "a", "weight": 0.9},
        {"instrument_id": 2, "symbol": "b", "weight": 0.1},
    ]
    a = _exposure(holdings)
    # HHI = 0.81 + 0.01 = 0.82 → L2 ≈ 1.22，远低于名义的 2
    assert a["hhi"]["value"] == pytest.approx(0.82)
    assert a["l2_effective_count"]["value"] == pytest.approx(1.0 / 0.82)


def test_distribution_is_unavailable_not_empty_dict_when_no_data() -> None:
    """没有分类数据时必须是 unavailable，不能是空字典。

    空字典会被前端渲染成「一个没有任何行业的组合」，看上去像已经算过了。
    """
    a = _exposure([{"instrument_id": 1, "symbol": "a", "weight": 1.0}])
    assert a["industry_distribution"]["status"] == "unavailable"
    assert "value" not in a["industry_distribution"]


def test_partial_industry_coverage_degrades_and_renormalises() -> None:
    holdings = [
        {"instrument_id": 1, "symbol": "a", "weight": 0.5},
        {"instrument_id": 2, "symbol": "b", "weight": 0.5},
    ]
    a = _exposure(holdings, industry={1: "银行"})

    ind = a["industry_distribution"]
    assert ind["status"] == "degraded"
    # 在覆盖到的子集内归一化 → 银行 100%，而不是 50%
    assert ind["value"] == {"银行": pytest.approx(1.0)}
    assert "1/2" in ind["reason"]


def test_lookthrough_coverage_degrades_when_portfolio_holds_fund() -> None:
    a = _exposure([{"instrument_id": 1, "symbol": "510050.SH", "weight": 1.0}], has_fund=True)
    assert a["lookthrough_coverage"]["status"] == "degraded"
    assert a["lookthrough_coverage"]["reason_code"] == "lookthrough_incomplete"


def test_lookthrough_coverage_is_full_for_pure_stock_portfolio() -> None:
    a = _exposure([{"instrument_id": 1, "symbol": "600000.SH", "weight": 1.0}])
    assert a["lookthrough_coverage"] == {
        "status": "ok",
        "value": 1.0,
        "method": "exact",
        "confidence": "high",
    }


# ===========================================================================
# 分档口径
# ===========================================================================


def test_mktcap_band_converts_yuan_to_yi_once() -> None:
    """total_mv 入库单位是元，阈值单位是亿元，换算只能做一次（T1）。"""
    assert svc._mktcap_band(Decimal("500_00000000"), [1000, 3000]) == "small_cap"  # 500 亿
    assert svc._mktcap_band(Decimal("2000_00000000"), [1000, 3000]) == "mid_cap"
    assert svc._mktcap_band(Decimal("5000_00000000"), [1000, 3000]) == "large_cap"


def test_negative_book_value_is_not_classified_as_value_stock() -> None:
    """PB<=0 是负净资产，不是「便宜」，不得分进价值档。"""
    assert svc._pb_band(Decimal("-1.5"), [2, 4]) is None
    assert svc._pb_band(Decimal("0"), [2, 4]) is None
    assert svc._pb_band(Decimal("1.5"), [2, 4]) == "value"
    assert svc._pb_band(Decimal("5"), [2, 4]) == "growth"


# ===========================================================================
# 意图路由（架构篇 §4.2）
# ===========================================================================


@pytest.mark.parametrize(
    ("plans", "expected"),
    [
        ([("p1", ["600000.SH"])], "single_instrument"),
        ([("p1", ["600000.SH", "000001.SZ"])], "single_portfolio"),
        # 两个方案缺省都为多组合，不猜调仓意图
        ([("p1", ["600000.SH"]), ("p2", ["600000.SH"])], "multi_portfolio"),
        # 集合不同也不能推断调仓意图
        ([("p1", ["600000.SH"]), ("p2", ["000001.SZ"])], "multi_portfolio"),
        (
            [("p1", ["600000.SH"]), ("p2", ["000001.SZ"]), ("p3", ["600519.SH"])],
            "multi_portfolio",
        ),
    ],
)
def test_intent_routing(plans: list[tuple[str, list[str]]], expected: str) -> None:
    req = _req([_plan(pid, syms) for pid, syms in plans])
    assert svc._resolve_intent(req) == expected


def test_explicit_intent_wins_over_inference() -> None:
    req = _req([_plan("p1", ["600000.SH"])], intent="single_portfolio")
    assert svc._resolve_intent(req) == "single_portfolio"


@pytest.mark.parametrize(
    ("intent", "mode"),
    [
        ("single_portfolio", "standard"),
        ("single_instrument", "single_instrument"),
        ("rebalance_amount", "compare"),
        ("multi_portfolio", "compare"),
    ],
)
def test_report_mode_mapping(intent: str, mode: str) -> None:
    assert svc._report_mode(intent) == mode


# ===========================================================================
# MetricValue 三态与强制声明
# ===========================================================================


def test_unavailable_metric_has_no_value_field() -> None:
    """把「不得静默估算」从约定升级为类型约束的那一条。"""
    m = UnavailableMetric(reason_code="spec_not_defined", reason="口径未定")
    assert "value" not in m.model_dump()


def test_plan_result_validates_hand_written_payload() -> None:
    """服务层手写的 dict 必须能过 PlanResult 校验，否则落库的是坏数据。"""
    holdings = [{"instrument_id": 1, "symbol": "600000.SH", "weight": 1.0}]
    section_a = _exposure(holdings)
    payload = {
        "plan_id": "p1",
        "label": None,
        "weight_mode": "equal",
        "section_a": section_a,
        "section_b": None,
        "section_c": None,
        "section_d": None,
        "blindspots": svc._build_blindspots(section_a, {}),
        "profile": svc._build_profile(section_a, holdings),
    }
    parsed = PlanResult.model_validate(payload)

    assert parsed.section_b is None
    assert parsed.profile.data_status == "partial"


def test_equal_weight_triggers_sixth_disclosure() -> None:
    params = {"rebalance": "daily", "include_dividend": True}
    equal = svc._build_disclosures(params, weight_mode="equal", fingerprint_time="2026-08-30 00:00")
    user = svc._build_disclosures(params, weight_mode="user", fingerprint_time="2026-08-30 00:00")

    assert svc.EQUAL_WEIGHT_DISCLOSURE in equal
    assert svc.EQUAL_WEIGHT_DISCLOSURE not in user
    # 第 7 项（数据快照声明）固定披露，两种模式都要有
    assert any("数据快照" in d for d in user)


def test_blindspots_report_undecidable_detectors_explicitly() -> None:
    """依赖 B/D 的检测器必须显式说「没法查」，不能干脆不返回。

    省略会让用户以为已经检查过且没问题。
    """
    section_a = _exposure([{"instrument_id": 1, "symbol": "a", "weight": 1.0}])
    hits = {h["detector"]: h for h in svc._build_blindspots(section_a, {})}

    assert hits["pseudo_diversification"]["triggered"] is False
    assert hits["pseudo_diversification"]["reason_code"] == "factor_model_unavailable"
    assert hits["style_bet"]["reason_code"] == "factor_model_unavailable"


# ===========================================================================
# 数据质量合并
# ===========================================================================


def test_merge_data_quality_dedupes_and_takes_worst_coverage() -> None:
    merged = svc._merge_data_quality(
        [
            {"unresolved_symbols": ["X"], "coverage_summary": {"industry": 0.9}},
            {"unresolved_symbols": ["X", "Y"], "coverage_summary": {"industry": 0.5}},
        ]
    )
    assert merged["unresolved_symbols"] == ["X", "Y"]
    # 多 plan 时覆盖率取最差，别报喜不报忧
    assert merged["coverage_summary"]["industry"] == 0.5


def test_shared_cache_is_reassembled_with_current_request_metadata() -> None:
    """旧缓存即使含别人的请求字段，也不能把它们返回给当前 snapshot。"""
    holdings = [{"instrument_id": 1, "symbol": "600000.SH", "weight": 1.0}]
    section_a = _exposure(
        holdings,
        input_weight=Decimal(100),
        resolved_weight=Decimal(50),
    )
    old_payload = {
        "plan_id": "before",
        "label": "before",
        "weight_mode": "user",
        "section_a": section_a,
        "section_b": None,
        "section_c": None,
        "section_d": None,
        "blindspots": svc._build_blindspots(section_a, {}),
        "profile": svc._build_profile(section_a, holdings),
    }
    row = {
        "plan_index": 0,
        "plan_id": "my-portfolio",
        "label": "mine",
        "weight_mode": "user",
        "requested_holdings": [{"symbol": "600000.SH", "weight": "100"}],
        "resolved_holdings": holdings,
        "payload": old_payload,
        "data_quality": {
            "unresolved_symbols": ["GARBAGE"],
            "duplicated_symbols": ["SECRET"],
            "coverage_summary": {"symbol_resolution": 0.5, "industry": 0.8},
            "forced_disclosures": ["safe"],
        },
    }

    context = svc._request_context_from_plan_row(row)
    result = svc._assemble_plan_result(row, context)
    dq = svc._assemble_plan_data_quality(row, context)

    assert result["plan_id"] == "my-portfolio"
    assert result["label"] == "mine"
    assert result["section_a"]["calculation_coverage_ratio"] == pytest.approx(1.0)
    assert dq["unresolved_symbols"] == []
    assert dq["duplicated_symbols"] == []
    assert dq["coverage_summary"] == {
        "symbol_resolution": pytest.approx(1.0),
        "industry": 0.8,
    }


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([None], "pending"),
        (["pending", "succeeded"], "pending"),
        (["running", "succeeded"], "running"),
        (["succeeded", "succeeded"], "succeeded"),
        (["partially_succeeded"], "partially_succeeded"),
        (["failed", "succeeded"], "partially_succeeded"),
        (["failed", "failed"], "failed"),
    ],
)
def test_run_status_uses_explicit_latest_run_statuses(
    statuses: list[str | None], expected: str
) -> None:
    assert svc._aggregate_run_status([{"status": status} for status in statuses]) == expected


@pytest.mark.anyio
async def test_default_as_of_date_uses_platform_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> FakeDateTime:
            assert str(tz) == "Asia/Shanghai"
            return cls(2026, 8, 31, 0, 30, tzinfo=tz)

    class Cursor:
        async def __aenter__(self) -> Cursor:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def execute(self, _sql: str, params: tuple[Any, ...]) -> None:
            captured["target"] = params[1]

        async def fetchone(self) -> dict[str, date]:
            return {"trading_day": captured["target"]}

    class Db:
        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(svc, "datetime", FakeDateTime)

    resolved = await svc._resolve_as_of_date(Db(), None)

    assert resolved == date(2026, 8, 31)
    assert captured["target"] == date(2026, 8, 31)


@pytest.mark.anyio
async def test_symbol_resolution_rejects_ambiguous_stock_etf_match() -> None:
    class Cursor:
        async def __aenter__(self) -> Cursor:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def execute(self, sql: str, _params: tuple[Any, ...]) -> None:
            assert "asset IN ('stock', 'etf')" in sql
            assert "ORDER BY symbol" in sql

        async def fetchall(self) -> list[dict[str, Any]]:
            return [
                {"instrument_id": 1, "symbol": "600000.SH"},
                {"instrument_id": 2, "symbol": "600000.SH"},
            ]

    class Db:
        def cursor(self) -> Cursor:
            return Cursor()

    with pytest.raises(Exception, match="ambiguous symbols") as exc_info:
        await svc._resolve_symbols(Db(), ["600000.SH"])

    assert exc_info.value.http_status == 422


@pytest.mark.anyio
async def test_sse_stream_ends_immediately_after_complete() -> None:
    from gr_api.routers.diagnosis import _stream_sections

    class ConnectedRequest:
        async def is_disconnected(self) -> bool:
            return False

    result = {
        "snapshot_id": str(svc.uuid4()),
        "schema_version": "diagnosis.v1",
        "spec_version": "test",
        "as_of_date": "2026-09-01",
        "data_fingerprint": "test",
        "data_snapshot_at": "2026-09-01T18:00:00+08:00",
        "resolved_intent": "single_portfolio",
        "report_mode": "standard",
        "requested_cov_methods": ["historical"],
        "plans": [],
        "cov": {"primary": "historical", "computed": []},
        "disclosures": [],
        "run_status": "succeeded",
        "comparison": None,
        "data_quality": {},
    }
    frames = [
        frame
        async for frame in _stream_sections(
            svc.uuid4(),
            result,
            ConnectedRequest(),  # type: ignore[arg-type]
        )
    ]

    assert len(frames) == 2
    assert b"event: complete" in frames[-1]


def test_json_diagnosis_routes_declare_response_models() -> None:
    from fastapi.routing import APIRoute
    from gr_api.routers.diagnosis import router

    json_routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and not route.path.endswith("/stream")
    ]

    assert len(json_routes) == 8
    assert all(route.response_model is not None for route in json_routes)


# ===========================================================================
# 安全头（AGENTS.md §8 硬性要求：新增路由后仍须带这 4 个头）
# ===========================================================================


def test_diagnosis_routes_keep_security_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """新增 diagnosis 路由后，SecurityHeadersMiddleware 仍覆盖它。

    DB 依赖被 override 掉，走的是**正常 200 响应**这条路径。不用「让它 500」
    来测：未捕获异常由 Starlette 最外层的 ServerErrorMiddleware 处理，那一层
    在用户中间件之外，本来就拿不到这几个头，测了会得出错误结论。
    """
    from fastapi import FastAPI
    from gr_api.deps import get_db
    from gr_api.middleware import SecurityHeadersMiddleware
    from gr_api.routers.diagnosis import router

    async def _fake_list(db: Any) -> list[dict[str, Any]]:
        return [
            {
                "spec_version": "v1-hist-20260901",
                "factor_model": None,
                "factor_model_version": None,
                "params": {},
                "effective_from": date(2026, 8, 30),
                "effective_to": None,
                "is_active": True,
                # response_model 必须过滤未来新增的内部列。
                "created_at": datetime(2026, 8, 30),
            }
        ]

    monkeypatch.setattr(svc, "list_spec_versions", _fake_list)

    # main.create_app 的全量路由会冷导入回测统计栈；这里构造同一条
    # 「SecurityHeadersMiddleware → diagnosis router」链，专注验证本模块新增路由。
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, csp_policy="default-src 'none'")
    app.include_router(router, prefix="/v1")

    async def _fake_db() -> Any:
        yield None

    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/v1/diagnosis/spec-versions")

    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert "created_at" not in r.json()["data"]["items"][0]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in r.headers
