"""诊断提交、输入解析、计算参数解析、A 区取数计算及固定终态存储。

网页 DTO 与报告由 diagnosis_presentation 组装；公式在 gr_api.diagnosis_calc（D-021）。
计算缓存不携带请求覆盖率、方案名称或报告画像（D-018）。B/C/D、压力测试与 E 本期
仅提供明确的不可用状态契约。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from gr_api.diagnosis_calc.exposure import (
    CalcHolding,
    IndustryAssignment,
    Valuation,
    compute_exposure,
)
from gr_api.diagnosis_calc.weights import (
    WEIGHT_UNITS,
    InputRow,
    NoCalculableHoldingsError,
    normalize_plan,
)
from gr_api.errors import BadRequest, Conflict, Forbidden, NotFound
from gr_api.schemas.diagnosis import (
    CalculationOptions,
    OptionWindow,
    PortfolioPlan,
    RecomputeRequest,
    SnapshotRequest,
)
from gr_api.schemas.diagnosis_response import CalculationPayload, ResolvedCalculationOptions
from gr_api.services import diagnosis_presentation as presentation
from gr_api.services.pick_symbols import parse_symbol


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from gr_data.db import DictConnection


logger = logging.getLogger(__name__)


#: ``diag.diagnosis_run.payload`` 的结构版本。payload 是 CalculationPayload 同形 JSON，
#: 缓存字段增删必须同步 +1；它也进入 calculation_hash，旧结构不会被新代码复用。
PAYLOAD_SCHEMA_VERSION = "4.0"

#: 进程时区不能决定业务日期；数据库连接虽钉住了会话时区，却不会改变 Python 进程时区。
PLATFORM_TZ = ZoneInfo("Asia/Shanghai")

#: 交易日历统一用上交所（一期只支持沪深，两所交易日一致）。
CALENDAR_EXCHANGE = "XSHG"

#: PA-01：一期只诊断沪深 A 股个股。
SUPPORTED_EXCHANGES = frozenset({"XSHG", "XSHE"})

SECTION_REASONS: dict[str, str] = {
    "section_b": "风险模型计算尚未开放：米筐 v2 风险数据尚未入库并按 D-022 发布，"
    "不以历史协方差替代。",
    "section_c": "组合回放与历史指标尚未开放：分红送转、退市终止价值与全收益基准数据尚未接入。",
    "section_d": "模型相关性与结构指标尚未开放：依赖尚未发布的米筐 v2 风险数据。",
    "stress_scenarios": "压力测试不在一期开放范围内。",
}


class BaseDataVersionUnavailableError(Conflict):
    """原快照的数据版本不可取得，拒绝重算（PA-14、PA-15 I7）。"""

    error_code = "BASE_DATA_VERSION_UNAVAILABLE"


def _issue_error(message: str, path: str, *, code: str = "invalid_input") -> BadRequest:
    """业务校验也携带原始输入位置，页面无需解析错误文案。"""
    error = BadRequest(message, http_status=422)
    error.issues = [{"path": path, "code": code, "message": message}]
    return error


def _feature_not_available(message: str, path: str) -> BadRequest:
    return _issue_error(message, path, code="feature_not_available")


# ===========================================================================
# canonical JSON 与计算缓存键（§7.8）
# ===========================================================================


def _canonical_json(payload: Any) -> str:
    """规范化 JSON：固定键序、无多余空白、非 ASCII 不转义。

    不要改成裸字符串拼接：拼接没有转义规则，``["a,b"]`` 与 ``["a","b"]`` 会拼出
    同一个串，两个不同的组合于是共用一份缓存。
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _calculation_hash(
    *,
    weight_mode: str,
    quantized: dict[int, int],
    resolved_as_of_date: date,
    spec_version: str,
    data_fingerprint: str,
    resolved_options: dict[str, Any],
) -> str:
    """单个 plan 的计算缓存键，跨用户共享（T17）。

    plan_id、label、plan_index、intent 与输入覆盖率都不参与；持仓按 instrument_id
    升序，权重用与计算相同的整数份额，保证输入顺序或尾数不改变命中结果。
    """
    return _sha256(
        _canonical_json(
            {
                "payload_schema_version": PAYLOAD_SCHEMA_VERSION,
                "weight_mode": weight_mode,
                "resolved_holdings": [
                    {"instrument_id": iid, "weight_units": quantized[iid]}
                    for iid in sorted(quantized)
                ],
                "resolved_as_of_date": resolved_as_of_date.isoformat(),
                "spec_version": spec_version,
                "data_fingerprint": data_fingerprint,
                "resolved_options": resolved_options,
            }
        )
    )


# ===========================================================================
# 口径版本、数据版本与诊断日期
# ===========================================================================


async def get_active_spec_version(
    db: DictConnection, spec_version: str | None = None
) -> dict[str, Any]:
    """取指定口径版本；``spec_version`` 为空时取当前生效版本。"""
    async with db.cursor() as cur:
        if spec_version:
            await cur.execute(
                "SELECT * FROM diag.spec_version WHERE spec_version = %s",
                (spec_version,),
            )
        else:
            await cur.execute("SELECT * FROM diag.spec_version WHERE is_active LIMIT 1")
        row = await cur.fetchone()
    if row is None:
        if spec_version:
            raise _issue_error("spec_version not found", "/spec_version")
        raise BadRequest("no active diagnosis spec_version", http_status=503)
    return row


async def list_spec_versions(db: DictConnection) -> list[dict[str, Any]]:
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT spec_version, factor_model, factor_model_version, params,
                   effective_from, effective_to, is_active
            FROM diag.spec_version
            ORDER BY effective_from DESC, spec_version DESC
            """
        )
        return list(await cur.fetchall())


async def get_data_version(db: DictConnection) -> dict[str, Any]:
    """取最新的数据快照版本，其 id 即 ``data_fingerprint``。

    .. warning::
       版本应由 gr-data 在导入并通过质量检查后发布（D-022 2b），该流程尚未落地；
       数据重新导入后 fingerprint 不会自动推进，旧结果仍会被复用。
    """
    async with db.cursor() as cur:
        await cur.execute("SELECT * FROM diag.data_version ORDER BY snapshot_at DESC LIMIT 1")
        row = await cur.fetchone()
    if row is None:
        raise BadRequest("no diag.data_version row has been published", http_status=503)
    return row


async def _get_data_version_by_id(db: DictConnection, data_version_id: str) -> dict[str, Any]:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT * FROM diag.data_version WHERE data_version_id = %s", (data_version_id,)
        )
        row = await cur.fetchone()
    if row is None:
        raise BaseDataVersionUnavailableError("base data version is no longer available")
    return row


def _today() -> date:
    return datetime.now(PLATFORM_TZ).date()


async def _trading_day_on_or_before(db: DictConnection, day: date) -> date | None:
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT trading_day FROM meta.trading_calendar
            WHERE exchange = %s AND is_open AND trading_day <= %s
            ORDER BY trading_day DESC LIMIT 1
            """,
            (CALENDAR_EXCHANGE, day),
        )
        row = await cur.fetchone()
    return None if row is None else row["trading_day"]


async def _trading_day_on_or_after(db: DictConnection, day: date) -> date | None:
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT trading_day FROM meta.trading_calendar
            WHERE exchange = %s AND is_open AND trading_day >= %s
            ORDER BY trading_day LIMIT 1
            """,
            (CALENDAR_EXCHANGE, day),
        )
        row = await cur.fetchone()
    return None if row is None else row["trading_day"]


async def _nth_trading_day_back(db: DictConnection, end: date, n: int) -> date:
    """``end`` 起向前第 ``n`` 个交易日（含 end）；日历不足时取最早可得日。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT trading_day FROM meta.trading_calendar
            WHERE exchange = %s AND is_open AND trading_day <= %s
            ORDER BY trading_day DESC LIMIT %s
            """,
            (CALENDAR_EXCHANGE, end, n),
        )
        rows = list(await cur.fetchall())
    return rows[-1]["trading_day"] if rows else end


async def _resolve_as_of_date(
    db: DictConnection, requested: date | None, data_version: dict[str, Any]
) -> date:
    """PA-14：一期只诊断最新已发布且通过检查的数据日期。

    显式日期晚于最新发布日（如当日数据尚未发布）时向前取最新发布日并回显；
    早于最新发布日返回 422（历史诊断未开放）；未来日期返回 422。
    """
    today = _today()
    if requested is not None and requested > today:
        raise _issue_error("as_of_date must not be in the future", "/as_of_date")
    published = data_version["snapshot_at"].astimezone(PLATFORM_TZ).date()
    latest = await _trading_day_on_or_before(db, min(published, today))
    if latest is None:
        # 日历没覆盖到发布日。不静默回退到自然日，否则后续按交易日过滤的查询会查空。
        raise BadRequest("no trading day on or before the published data date", http_status=503)
    if requested is None:
        return latest
    resolved = await _trading_day_on_or_before(db, requested)
    if resolved is None:
        raise _issue_error(f"no trading day on or before {requested}", "/as_of_date")
    if resolved < latest:
        raise _feature_not_available(
            f"historical diagnosis is not available; latest diagnosable date is {latest}",
            "/as_of_date",
        )
    return latest


# ===========================================================================
# 计算参数解析（§7.2 第 8 步）
# ===========================================================================


OPTION_GROUPS: dict[str, tuple[str, ...]] = {
    "industry_scheme": ("industry_scheme", "industry_scheme_version"),
    "benchmark": ("benchmark_instrument_id", "benchmark_version"),
    "correlation_window": ("correlation_window",),
    "beta_window": ("beta_window",),
    "replay_start": ("replay_start",),
    "stats_window": ("stats_window",),
}


async def _resolve_window(
    db: DictConnection, window: OptionWindow, *, as_of: date, path: str
) -> dict[str, str]:
    """把请求区间解析到交易日；不向区间外扩展，样本不足留给指标判定不可用。"""
    if window.end > as_of:
        raise _issue_error("window end must not be after the diagnosis date", f"{path}/end")
    start = await _trading_day_on_or_after(db, window.start)
    end = await _trading_day_on_or_before(db, window.end)
    if start is None or end is None or start >= end:
        raise _issue_error("window must contain at least two trading days", path)
    return {"start": start.isoformat(), "end": end.isoformat()}


async def _default_window(db: DictConnection, *, as_of: date, days: int) -> dict[str, str]:
    """默认最近 ``days`` 个交易日收益观测；区间前一个交易日的价格计算时另取。"""
    start = await _nth_trading_day_back(db, as_of, days)
    if start >= as_of:
        raise BadRequest("trading calendar does not cover a default window", http_status=503)
    return {"start": start.isoformat(), "end": as_of.isoformat()}


async def _resolve_options(
    db: DictConnection,
    *,
    requested: CalculationOptions,
    params: dict[str, Any],
    available: dict[str, Any],
    as_of: date,
    base: dict[str, Any] | None = None,
    reset: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """返回 ResolvedCalculationOptions 同形字典。

    新提交：未给出的项取口径默认值。重算：未给出且不在 ``reset`` 中的项沿用 ``base``。
    显式选择不可用的选项返回 422；默认项不可用时写 None，相关指标不可用（PA-05、PA-11）。
    """
    resolved: dict[str, Any] = {}

    def keep(field: str) -> bool:
        return base is not None and field not in reset and getattr(requested, field) is None

    for field, keys in OPTION_GROUPS.items():
        if keep(field):
            assert base is not None
            resolved.update({k: base[k] for k in keys})

    schemes = {s["code"]: s for s in available.get("industry_schemes", [])}
    if "industry_scheme" not in resolved:
        if requested.industry_scheme is not None:
            chosen = schemes.get(requested.industry_scheme)
            if chosen is None:
                raise _issue_error(
                    "industry_scheme is not validated in the current data version",
                    "/options/industry_scheme",
                    code="option_unavailable",
                )
        else:
            chosen = schemes.get(str(params.get("industry_scheme") or ""))
        resolved["industry_scheme"] = None if chosen is None else chosen["code"]
        resolved["industry_scheme_version"] = None if chosen is None else chosen.get("version")

    benchmarks = list(available.get("benchmarks", []))
    if "benchmark_instrument_id" not in resolved:
        if requested.benchmark is not None:
            try:
                wanted = parse_symbol(requested.benchmark).symbol_full
            except ValueError:
                wanted = requested.benchmark.strip().upper()
            match = next((b for b in benchmarks if b.get("symbol") == wanted), None)
            if match is None:
                raise _issue_error(
                    "benchmark is not a validated total-return benchmark",
                    "/options/benchmark",
                    code="option_unavailable",
                )
        else:
            default_id = params.get("benchmark_instrument_id")
            match = next(
                (
                    b
                    for b in benchmarks
                    if default_id is not None and b.get("instrument_id") == default_id
                ),
                None,
            )
        resolved["benchmark_instrument_id"] = None if match is None else int(match["instrument_id"])
        resolved["benchmark_version"] = None if match is None else match.get("version")

    for field, days in (
        (
            "correlation_window",
            int(
                (params.get("cov_method_params") or {}).get("historical", {}).get("lookback_days")
                or params.get("history_lookback_days")
                or 252
            ),
        ),
        ("beta_window", int(params.get("beta_lookback_days") or 252)),
    ):
        if field in resolved:
            continue
        window = getattr(requested, field)
        resolved[field] = (
            await _resolve_window(db, window, as_of=as_of, path=f"/options/{field}")
            if window is not None
            else await _default_window(db, as_of=as_of, days=days)
        )

    # PA-12 回放所需数据（DS06～DS08）未接入：回放能力不可用，起点与统计区间写 None；
    # 显式选择视为选了不可用的选项。
    for field in ("replay_start", "stats_window"):
        if field in resolved:
            continue
        if getattr(requested, field) is not None:
            raise _feature_not_available(
                "portfolio replay is not available yet", f"/options/{field}"
            )
        resolved[field] = None

    return ResolvedCalculationOptions.model_validate(resolved).model_dump(mode="json")


# ===========================================================================
# 代码解析与输入规范化（§7.2 第 1～6 步）
# ===========================================================================


def _normalized_symbol(raw: str) -> str:
    try:
        return parse_symbol(raw).symbol_full
    except ValueError:
        return raw.strip().upper()


@dataclass(frozen=True)
class SymbolResolution:
    instrument: dict[str, Any] | None  # 一期范围内的已识别标的
    out_of_scope: str | None = None  # 已识别但不在一期范围的原因


async def _resolve_symbols(
    db: DictConnection, symbols: set[str], *, as_of: date
) -> dict[str, SymbolResolution]:
    """规范化代码 → 解析结果。先查当前代码，查不到再查历史别名 ``meta.symbol_map``。

    ``meta.instruments.symbol`` 存带后缀全码，按全码直查不需要交易所码转换；但凡改成按
    ``exchange`` 过滤，必须先经 ``pick_symbols.to_canonical_exchange``，否则整批查不到。
    """
    parsed = sorted(s for s in symbols if _parsable(s))
    candidates: dict[str, list[dict[str, Any]]] = {s: [] for s in parsed}
    if parsed:
        async with db.cursor() as cur:
            await cur.execute(
                """
                SELECT symbol AS lookup, instrument_id, symbol, asset, exchange, name,
                       list_date, delist_date, status
                FROM meta.instruments WHERE symbol = ANY(%s)
                """,
                (parsed,),
            )
            for row in await cur.fetchall():
                candidates[row["lookup"]].append(row)
            missing = [s for s in parsed if not candidates[s]]
            if missing:
                await cur.execute(
                    """
                    SELECT DISTINCT sm.source_symbol AS lookup, i.instrument_id, i.symbol, i.asset,
                           i.exchange, i.name, i.list_date, i.delist_date, i.status
                    FROM meta.symbol_map sm
                    JOIN meta.instruments i ON i.instrument_id = sm.instrument_id
                    WHERE sm.source_symbol = ANY(%s)
                    """,
                    (missing,),
                )
                for row in await cur.fetchall():
                    candidates[row["lookup"]].append(row)

    out: dict[str, SymbolResolution] = {}
    ambiguous: list[str] = []
    for symbol in symbols:
        rows = candidates.get(symbol, [])
        stocks = {r["instrument_id"]: r for r in rows if r["asset"] == "stock"}
        if len(stocks) > 1:
            ambiguous.append(symbol)
            continue
        if not rows:
            out[symbol] = SymbolResolution(instrument=None)
        elif not stocks:
            assets = "、".join(sorted({str(r["asset"]) for r in rows}))
            out[symbol] = SymbolResolution(
                instrument=None, out_of_scope=f"{assets} 不在一期诊断范围（仅支持沪深 A 股个股）"
            )
        else:
            row = next(iter(stocks.values()))
            out[symbol] = SymbolResolution(instrument=row, out_of_scope=_scope_reason(row, as_of))
    if ambiguous:
        raise BadRequest(
            f"ambiguous symbols matched multiple stock instruments: {', '.join(sorted(ambiguous))}",
            http_status=422,
        )
    return out


def _parsable(symbol: str) -> bool:
    try:
        parse_symbol(symbol)
    except ValueError:
        return False
    return True


def _scope_reason(row: dict[str, Any], as_of: date) -> str | None:
    """PA-01、PA-07：北交所、已退市（含退市日不晚于诊断日）不在一期范围。"""
    if row["exchange"] not in SUPPORTED_EXCHANGES:
        return "北交所股票不在一期诊断范围（仅支持沪深 A 股个股）"
    if row["status"] == "delisted" or (
        row["delist_date"] is not None and row["delist_date"] <= as_of
    ):
        return "已退市股票不在一期诊断范围"
    return None


@dataclass(frozen=True)
class PlanInput:
    plan_index: int
    plan_id: str
    label: str | None
    requested_holdings: list[dict[str, Any]]
    weight_mode: str
    summary: dict[str, Any]
    quantized: dict[int, int]


async def _normalize_request_plans(
    db: DictConnection, plans: list[PortfolioPlan], *, as_of: date
) -> list[PlanInput]:
    """解析全部方案；范围外资产和无可计算持仓的方案使整个请求 422（§7.2 第 2、4 步）。"""
    symbols = {_normalized_symbol(h.symbol) for p in plans for h in p.holdings}
    resolution = await _resolve_symbols(db, symbols, as_of=as_of)

    scope_issues = [
        {
            "path": f"/plans/{p_idx}/holdings/{h_idx}/symbol",
            "code": "unsupported_asset",
            "message": res.out_of_scope,
        }
        for p_idx, plan in enumerate(plans)
        for h_idx, h in enumerate(plan.holdings)
        if (res := resolution.get(_normalized_symbol(h.symbol))) and res.out_of_scope
    ]
    if scope_issues:
        error = BadRequest("unsupported assets must be removed or corrected", http_status=422)
        error.issues = scope_issues
        raise error

    out: list[PlanInput] = []
    for p_idx, plan in enumerate(plans):
        rows = [
            InputRow(
                input_index=h_idx,
                input_symbol=h.symbol,
                input_weight=h.weight,
                normalized_symbol=_normalized_symbol(h.symbol),
                instrument=resolution[_normalized_symbol(h.symbol)].instrument,
            )
            for h_idx, h in enumerate(plan.holdings)
        ]
        try:
            normalized = normalize_plan(rows)
        except NoCalculableHoldingsError:
            raise _issue_error(
                f"plan '{plan.plan_id}': no positive holdings could be resolved",
                f"/plans/{p_idx}/holdings",
            ) from None
        out.append(
            PlanInput(
                plan_index=p_idx,
                plan_id=plan.plan_id,
                label=plan.label,
                requested_holdings=[h.model_dump(mode="json") for h in plan.holdings],
                weight_mode=normalized.weight_mode,
                summary=normalized.summary,
                quantized=normalized.quantized,
            )
        )
    return out


def _resolve_intent(requested: str | None, plans: list[PlanInput]) -> str:
    """一期只做独立诊断；调仓比较第二期开放，必须显式拒绝而不是静默改为独立诊断。"""
    if requested in ("rebalance_amount", "rebalance_holding"):
        raise _feature_not_available("rebalance comparison is not available yet", "/intent")
    if len(plans) > 1:
        return "multi_portfolio"
    summary = plans[0].summary
    single = len(summary["calculation_holdings"]) == 1 and summary["unresolved_weight"] == 0
    if requested == "single_instrument" and not single:
        raise _issue_error(
            "single_instrument requires exactly one resolved positive holding", "/intent"
        )
    if requested == "single_portfolio":
        return "single_portfolio"
    return "single_instrument" if single else "single_portfolio"


def _report_mode(intent: str) -> str:
    if intent == "single_portfolio":
        return "standard"
    if intent == "single_instrument":
        return "single_instrument"
    return "compare"


# ===========================================================================
# 取数与计算
# ===========================================================================


async def _fetch_industry(
    db: DictConnection, ids: list[int], *, scheme_code: str, level: int, as_of: date
) -> dict[int, IndustryAssignment]:
    """取诊断日有效的行业归属（``in_date <= as_of < out_date``），不用当前归属回算。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT ii.instrument_id, ii.industry_code,
                   COALESCE(n.industry_name, ii.industry_code) AS industry_name
            FROM classify.instrument_industry ii
            LEFT JOIN classify.industry_node n
                   ON n.scheme_code = ii.scheme_code
                  AND n.level = ii.level
                  AND n.industry_code = ii.industry_code
            WHERE ii.instrument_id = ANY(%s)
              AND ii.scheme_code = %s
              AND ii.level = %s
              AND ii.in_date <= %s
              AND (ii.out_date IS NULL OR ii.out_date > %s)
              AND ii.available_at <= now()
            """,
            (ids, scheme_code, level, as_of, as_of),
        )
        return {
            r["instrument_id"]: IndustryAssignment(
                code=str(r["industry_code"]), name=str(r["industry_name"])
            )
            for r in await cur.fetchall()
        }


async def _fetch_category(
    db: DictConnection, ids: list[int], *, as_of: date
) -> dict[int, dict[str, str]]:
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT instrument_id, asset_category, market
            FROM classify.instrument_category
            WHERE instrument_id = ANY(%s)
              AND in_date <= %s
              AND (out_date IS NULL OR out_date > %s)
              AND available_at <= now()
            """,
            (ids, as_of, as_of),
        )
        return {
            r["instrument_id"]: {"asset_category": r["asset_category"], "market": r["market"]}
            for r in await cur.fetchall()
        }


async def _fetch_valuation(
    db: DictConnection, ids: list[int], *, as_of: date
) -> dict[int, Valuation]:
    """取不晚于诊断日、且已可获得的最近一条估值（PA-07，不设天数上限）。

    停牌、非交易日都会让当日无行，硬等于 as_of 会整批查空；滞后由日期回显并降级。
    """
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT ON (instrument_id) instrument_id, trading_day, total_mv, pb
            FROM fundamental.valuation_1d
            WHERE instrument_id = ANY(%s)
              AND trading_day <= %s
              AND available_at <= now()
            ORDER BY instrument_id, trading_day DESC
            """,
            (ids, as_of),
        )
        return {
            r["instrument_id"]: Valuation(
                trading_day=r["trading_day"], total_mv=r["total_mv"], pb=r["pb"]
            )
            for r in await cur.fetchall()
        }


def _unavailable_section(key: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason_code": "feature_not_available",
        "reason": SECTION_REASONS[key],
    }


async def _compute_plan(
    db: DictConnection,
    *,
    item: PlanInput,
    params: dict[str, Any],
    as_of: date,
    options: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """算一个 plan 的纯计算载体与跨用户安全的数据事实。"""
    holdings = [
        CalcHolding(instrument_id=iid, weight=Decimal(units) / Decimal(WEIGHT_UNITS))
        for iid, units in sorted(item.quantized.items())
    ]
    ids = [h.instrument_id for h in holdings]
    scheme = options["industry_scheme"]
    industry = (
        await _fetch_industry(
            db, ids, scheme_code=scheme, level=int(params.get("industry_level", 1)), as_of=as_of
        )
        if scheme is not None
        else {}
    )
    metrics, facts = compute_exposure(
        holdings,
        as_of=as_of,
        params=params,
        industry_scheme=scheme,
        industry=industry,
        category=await _fetch_category(db, ids, as_of=as_of),
        valuation=await _fetch_valuation(db, ids, as_of=as_of),
    )
    payload = {
        "cov": {
            "requested": list(params.get("cov_methods") or []),
            "forward_model": None,
            "primary": None,
            "computed": [],
        },
        "section_a": {"status": "ready", "value": metrics},
        **{key: _unavailable_section(key) for key in SECTION_REASONS},
    }
    # 落库前过一遍 Pydantic：手写字典的字段拼错或三态组合非法在这里就失败，
    # 而不是等前端渲染成空白；同时完成 Decimal/date 到 JSON 的规范化。
    return CalculationPayload.model_validate(payload).model_dump(mode="json"), facts


async def _ensure_run(
    db: DictConnection,
    *,
    snapshot_id: UUID,
    item: PlanInput,
    spec: dict[str, Any],
    as_of: date,
    data_fingerprint: str,
    options: dict[str, Any],
) -> UUID:
    """算一个 plan：命中成功终态就复用，否则现算并落 ``diag.diagnosis_run``。"""
    calc_hash = _calculation_hash(
        weight_mode=item.weight_mode,
        quantized=item.quantized,
        resolved_as_of_date=as_of,
        spec_version=spec["spec_version"],
        data_fingerprint=data_fingerprint,
        resolved_options=options,
    )
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT run_id FROM diag.diagnosis_run
            WHERE calculation_hash = %s AND status IN ('succeeded', 'partially_succeeded')
            LIMIT 1
            """,
            (calc_hash,),
        )
        hit = await cur.fetchone()

    if hit is not None:
        run_id = hit["run_id"]
    else:
        payload, facts = await _compute_plan(
            db, item=item, params=spec["params"], as_of=as_of, options=options
        )
        run_id = uuid4()
        # run 行状态只表示计算是否无系统错误地完成；方案级「部分成功」由展示层按
        # 区块可用性合成（§7.4），不写进共享缓存行。
        async with db.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO diag.diagnosis_run (
                    run_id, calculation_hash, spec_version, data_fingerprint,
                    status, payload, payload_schema_version, data_quality, computed_at
                ) VALUES (%s, %s, %s, %s, 'succeeded', %s, %s, %s, now())
                ON CONFLICT (calculation_hash)
                    WHERE status IN ('succeeded', 'partially_succeeded')
                DO NOTHING
                RETURNING run_id
                """,
                (
                    run_id,
                    calc_hash,
                    spec["spec_version"],
                    data_fingerprint,
                    json.dumps(payload),
                    PAYLOAD_SCHEMA_VERSION,
                    json.dumps(facts),
                ),
            )
            inserted = await cur.fetchone()
            if inserted is None:
                # 并发下另一个请求先写成功了：同 hash 即同输入同口径，改读已成功那行。
                await cur.execute(
                    """
                    SELECT run_id FROM diag.diagnosis_run
                    WHERE calculation_hash = %s
                      AND status IN ('succeeded', 'partially_succeeded')
                    LIMIT 1
                    """,
                    (calc_hash,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise RuntimeError(
                        "successful diagnosis run disappeared after calculation hash conflict"
                    )
                run_id = row["run_id"]

    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO diag.snapshot_run (snapshot_id, plan_index, run_id)
            VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (snapshot_id, item.plan_index, run_id),
        )
    return run_id


async def _record_failed_run(
    db: DictConnection,
    *,
    snapshot_id: UUID,
    item: PlanInput,
    spec: dict[str, Any],
    as_of: date,
    data_fingerprint: str,
    options: dict[str, Any],
) -> None:
    """失败终态只新开行，不进入成功缓存；对外只暴露安全错误码。"""
    run_id = uuid4()
    calc_hash = _calculation_hash(
        weight_mode=item.weight_mode,
        quantized=item.quantized,
        resolved_as_of_date=as_of,
        spec_version=spec["spec_version"],
        data_fingerprint=data_fingerprint,
        resolved_options=options,
    )
    async with db.cursor() as cur:
        await cur.execute(
            """INSERT INTO diag.diagnosis_run
               (run_id, calculation_hash, spec_version, data_fingerprint, status,
                payload_schema_version, error_reason, computed_at)
               VALUES (%s, %s, %s, %s, 'failed', %s, 'calculation_failed', now())""",
            (run_id, calc_hash, spec["spec_version"], data_fingerprint, PAYLOAD_SCHEMA_VERSION),
        )
        await cur.execute(
            "INSERT INTO diag.snapshot_run (snapshot_id, plan_index, run_id) VALUES (%s, %s, %s)",
            (snapshot_id, item.plan_index, run_id),
        )


# ===========================================================================
# 编排：幂等、提交与重算
# ===========================================================================


async def _with_idempotency(
    db: DictConnection,
    *,
    user_id: str | None,
    idempotency_key: str | None,
    requested_payload: dict[str, Any],
    create: Callable[[str], Awaitable[UUID]],
) -> tuple[dict[str, Any], int]:
    """新提交创建新资源；相同 UUIDv4 幂等键只重放原资源，同键异体 409（D-018）。

    事务锁在匿名和登录命名空间分别仲裁。快照、方案和终态同事务提交，
    不向轮询端暴露尚未固定数据版本的半成品。
    """
    scope = str(user_id) if user_id else "anonymous"
    key_hash = _sha256(f"diagnosis.v1:{scope}:{idempotency_key or uuid4()}")
    async with db.transaction():
        if idempotency_key:
            lock_key = int.from_bytes(bytes.fromhex(key_hash)[:8], "big", signed=True)
            async with db.cursor() as cur:
                await cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
                await cur.execute(
                    "SELECT snapshot_id, requested_payload FROM diag.portfolio_snapshot "
                    "WHERE request_hash = %s AND user_id IS NOT DISTINCT FROM %s",
                    (key_hash, user_id),
                )
                existing = await cur.fetchone()
            if existing:
                if existing["requested_payload"] != requested_payload:
                    raise Conflict("idempotency key was already used with a different request")
                result = await get_result(db, existing["snapshot_id"], user_id=user_id)
                return presentation.accepted(result), 200
        snapshot_id = await create(key_hash)
        result = await get_result(db, snapshot_id, user_id=user_id)
        return presentation.accepted(result), 201


async def _persist_snapshot(
    db: DictConnection,
    *,
    key_hash: str,
    user_id: str | None,
    idempotency_key: str | None,
    requested_intent: str | None,
    resolved_intent: str,
    requested_as_of: date | None,
    as_of: date,
    requested_spec_version: str | None,
    spec: dict[str, Any],
    data_version: dict[str, Any],
    options: dict[str, Any],
    requested_payload: dict[str, Any],
    base_snapshot_id: UUID | None,
    plans: list[PlanInput],
) -> UUID:
    snapshot_id = uuid4()  # 必须 v4：匿名用户之间的隔离只依赖它不可猜测
    data_fingerprint = str(data_version["data_version_id"])
    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO diag.portfolio_snapshot (
                snapshot_id, user_id, request_hash, idempotency_key,
                requested_intent, resolved_intent,
                requested_as_of_date, resolved_as_of_date,
                requested_spec_version, resolved_spec_version,
                requested_payload, user_level,
                data_fingerprint, resolved_options, base_snapshot_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'retail', %s, %s, %s)
            """,
            (
                snapshot_id,
                user_id,
                key_hash,
                idempotency_key,
                requested_intent,
                resolved_intent,
                requested_as_of,
                as_of,
                requested_spec_version,
                spec["spec_version"],
                json.dumps(requested_payload),
                data_fingerprint,
                json.dumps(options),
                base_snapshot_id,
            ),
        )
        for item in plans:
            await cur.execute(
                """
                INSERT INTO diag.portfolio_plan (
                    snapshot_id, plan_index, plan_id, label, weight_mode,
                    requested_holdings, resolved_holdings, input_context
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    snapshot_id,
                    item.plan_index,
                    item.plan_id,
                    item.label,
                    item.weight_mode,
                    json.dumps(item.requested_holdings),
                    json.dumps(
                        [
                            {"instrument_id": iid, "weight_units": units}
                            for iid, units in sorted(item.quantized.items())
                        ]
                    ),
                    json.dumps(item.summary),
                ),
            )

    # 每个方案用 savepoint 隔离计算故障，失败终态保留输入且不参与成功缓存。
    for item in plans:
        try:
            async with db.transaction():
                await _ensure_run(
                    db,
                    snapshot_id=snapshot_id,
                    item=item,
                    spec=spec,
                    as_of=as_of,
                    data_fingerprint=data_fingerprint,
                    options=options,
                )
        except Exception as exc:
            logger.error(
                "diagnosis plan failed: snapshot_id=%s plan_index=%s error_type=%s",
                snapshot_id,
                item.plan_index,
                type(exc).__name__,
            )
            await _record_failed_run(
                db,
                snapshot_id=snapshot_id,
                item=item,
                spec=spec,
                as_of=as_of,
                data_fingerprint=data_fingerprint,
                options=options,
            )

    logger.info(
        "diagnosis snapshot created: snapshot_id=%s base=%s intent=%s plans=%d as_of=%s spec=%s",
        snapshot_id,
        base_snapshot_id,
        resolved_intent,
        len(plans),
        as_of,
        spec["spec_version"],
    )
    return snapshot_id


async def create_snapshot(
    db: DictConnection,
    req: SnapshotRequest,
    *,
    user_id: str | None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], int]:
    """``POST /snapshots``：返回 ``(SnapshotAccepted, HTTP 状态码)``。

    计算同步执行：单次数值计算在毫秒量级，请求路径不引入队列（架构篇 §6.1/§6.5）。
    幂等重放先查键，不重新解析「最新交易日」等缺省值。
    """
    requested_payload = req.model_dump(mode="json")

    async def create(key_hash: str) -> UUID:
        spec = await get_active_spec_version(db, req.spec_version)
        data_version = await get_data_version(db)
        as_of = await _resolve_as_of_date(db, req.as_of_date, data_version)
        plans = await _normalize_request_plans(db, req.plans, as_of=as_of)
        intent = _resolve_intent(req.intent, plans)
        options = await _resolve_options(
            db,
            requested=req.options,
            params=spec["params"],
            available=data_version.get("available_options") or {},
            as_of=as_of,
        )
        return await _persist_snapshot(
            db,
            key_hash=key_hash,
            user_id=user_id,
            idempotency_key=idempotency_key,
            requested_intent=req.intent,
            resolved_intent=intent,
            requested_as_of=req.as_of_date,
            as_of=as_of,
            requested_spec_version=req.spec_version,
            spec=spec,
            data_version=data_version,
            options=options,
            requested_payload=requested_payload,
            base_snapshot_id=None,
            plans=plans,
        )

    return await _with_idempotency(
        db,
        user_id=user_id,
        idempotency_key=idempotency_key,
        requested_payload=requested_payload,
        create=create,
    )


async def _base_data_version_available(db: DictConnection, snapshot: dict[str, Any]) -> bool:
    """原快照的数据是否仍可原样取得（PA-14）。

    D1 下业务表不保留修订历史，判定需要 D-022 2b 的发布清单与组成收据；在其落地前
    无法证明底层数据自原版本以来未被修订，一律返回 False，由调用方返回 409。
    回放类统计区间重算可只读持久化的回放状态，但一期回放尚未开放，没有可读的状态。
    """
    del db, snapshot
    return False


async def recompute_snapshot(
    db: DictConnection,
    base_snapshot_id: UUID,
    req: RecomputeRequest,
    *,
    user_id: str | None,
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], int]:
    """``POST /snapshots/{id}/recompute``：按新 options 基于原快照创建新快照。

    复制原快照的方案、解析结果、诊断日期、口径版本与数据版本，不重新解析缺省日期或
    最新数据；原快照不变。``user_id`` 取当前请求者，访问校验同读取原快照（PA-15 I4）。
    """
    requested_payload = {
        "base_snapshot_id": str(base_snapshot_id),
        **req.model_dump(mode="json"),
    }

    async def create(key_hash: str) -> UUID:
        base = await _load_snapshot(db, base_snapshot_id, user_id=user_id)
        if not await _base_data_version_available(db, base):
            raise BaseDataVersionUnavailableError(
                "the original data version cannot be reproduced; recompute is refused"
            )
        spec = await get_active_spec_version(db, base["resolved_spec_version"])
        data_version = await _get_data_version_by_id(db, base["data_fingerprint"])
        as_of: date = base["resolved_as_of_date"]
        options = await _resolve_options(
            db,
            requested=req.options,
            params=spec["params"],
            available=data_version.get("available_options") or {},
            as_of=as_of,
            base=base["resolved_options"],
            reset=frozenset(req.reset_to_default),
        )
        async with db.cursor() as cur:
            await cur.execute(
                """
                SELECT plan_index, plan_id, label, weight_mode,
                       requested_holdings, resolved_holdings, input_context
                FROM diag.portfolio_plan WHERE snapshot_id = %s ORDER BY plan_index
                """,
                (base_snapshot_id,),
            )
            rows = list(await cur.fetchall())
        plans = [
            PlanInput(
                plan_index=r["plan_index"],
                plan_id=r["plan_id"],
                label=r["label"],
                requested_holdings=r["requested_holdings"],
                weight_mode=r["weight_mode"],
                summary=r["input_context"],
                quantized={
                    int(h["instrument_id"]): int(h["weight_units"]) for h in r["resolved_holdings"]
                },
            )
            for r in rows
        ]
        return await _persist_snapshot(
            db,
            key_hash=key_hash,
            user_id=user_id,
            idempotency_key=idempotency_key,
            requested_intent=None,
            resolved_intent=base["resolved_intent"],
            requested_as_of=None,
            as_of=as_of,
            requested_spec_version=None,
            spec=spec,
            data_version=data_version,
            options=options,
            requested_payload=requested_payload,
            base_snapshot_id=base_snapshot_id,
            plans=plans,
        )

    return await _with_idempotency(
        db,
        user_id=user_id,
        idempotency_key=idempotency_key,
        requested_payload=requested_payload,
        create=create,
    )


# ===========================================================================
# 读取：result / report / data-quality
# ===========================================================================


async def _load_snapshot(
    db: DictConnection, snapshot_id: UUID, *, user_id: str | None
) -> dict[str, Any]:
    """取 snapshot 及其固定数据版本并做归属校验（§7.7）。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT s.*, dv.snapshot_at AS data_snapshot_at
            FROM diag.portfolio_snapshot s
            JOIN diag.data_version dv ON dv.data_version_id = s.data_fingerprint
            WHERE s.snapshot_id = %s
            """,
            (snapshot_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFound(f"snapshot not found: {snapshot_id}")
    owner = row["user_id"]
    # 匿名 snapshot（owner 为 NULL）靠 snapshot_id 的不可猜测性保护，不校验用户维度。
    if owner is not None and str(owner) != str(user_id):
        raise Forbidden("no permission to access this snapshot")
    return row


def _aggregate_run_status(rows: list[dict[str, Any]]) -> str:
    """按每个 plan 最新 run 的显式状态聚合 snapshot 状态。"""
    statuses = [row["status"] for row in rows]
    if any(status == "running" for status in statuses):
        return "running"
    if not statuses or any(status is None or status == "pending" for status in statuses):
        return "pending"
    terminal = set(statuses)
    if terminal == {"succeeded"}:
        return "succeeded"
    if terminal == {"failed"}:
        return "failed"
    return "partially_succeeded"


async def _load_result(
    db: DictConnection, snapshot_id: UUID, *, user_id: str | None
) -> tuple[dict[str, Any], dict[str, str]]:
    """组装 ``DiagnosisResult`` 并返回报告所需的行业名称标签。"""
    snapshot = await _load_snapshot(db, snapshot_id, user_id=user_id)
    spec = await get_active_spec_version(db, snapshot["resolved_spec_version"])
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT ON (p.plan_index)
                   p.plan_index, p.plan_id, p.label, p.weight_mode, p.input_context,
                   r.status, r.payload, r.data_quality
            FROM diag.portfolio_plan p
            LEFT JOIN diag.snapshot_run sr
                   ON sr.snapshot_id = p.snapshot_id AND sr.plan_index = p.plan_index
            LEFT JOIN diag.diagnosis_run r ON r.run_id = sr.run_id
            WHERE p.snapshot_id = %s
            ORDER BY p.plan_index, sr.created_at DESC NULLS LAST, sr.run_id DESC NULLS LAST
            """,
            (snapshot_id,),
        )
        rows = list(await cur.fetchall())
    result = presentation.assemble(
        snapshot, spec, rows, _aggregate_run_status(rows), report_mode=_report_mode
    )
    labels: dict[str, str] = {}
    for row in rows:
        labels.update((row["data_quality"] or {}).get("industry_names") or {})
    return result, labels


async def get_result(
    db: DictConnection, snapshot_id: UUID, *, user_id: str | None
) -> dict[str, Any]:
    """``GET /snapshots/{id}/result``：组装全量 ``DiagnosisResult`` 或进度。"""
    result, _ = await _load_result(db, snapshot_id, user_id=user_id)
    return result


async def get_data_quality(
    db: DictConnection, snapshot_id: UUID, *, user_id: str | None
) -> dict[str, Any]:
    """``GET /snapshots/{id}/data-quality``：单独取降级清单与强制声明。"""
    result = await get_result(db, snapshot_id, user_id=user_id)
    if result["run_status"] in ("pending", "running"):
        return result
    return presentation.data_quality(result)


async def get_report(
    db: DictConnection,
    snapshot_id: UUID,
    *,
    user_id: str | None,
    user_level: str | None = None,
) -> dict[str, Any]:
    """只读取已固定的终态，渲染偏好不进入计算或缓存。"""
    result, labels = await _load_result(db, snapshot_id, user_id=user_id)
    return presentation.report(result, user_level or "retail", industry_labels=labels)


# ===========================================================================
# 分享
# ===========================================================================


async def create_share_token(
    db: DictConnection,
    snapshot_id: UUID,
    *,
    user_id: str | None,
    ttl_days: int = 30,
) -> dict[str, str]:
    """``POST /snapshots/{id}/share``：建一个只能访问 /report 的分享凭证。"""
    await _load_snapshot(db, snapshot_id, user_id=user_id)
    token = uuid4().hex + uuid4().hex[:16]  # 48 hex chars
    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO diag.share_token (token, snapshot_id, created_by, expires_at)
            VALUES (%s, %s, %s, now() + make_interval(days => %s))
            RETURNING token, expires_at
            """,
            (token, snapshot_id, user_id, ttl_days),
        )
        row = await cur.fetchone()
    if row is None:
        raise RuntimeError("share token insert returned no row")
    return {"token": row["token"], "expires_at": row["expires_at"].isoformat()}


async def get_shared_report(db: DictConnection, token: str) -> dict[str, Any]:
    """``GET /share/{token}/report``：token 只换报告，不暴露 /result 全量指标。"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT snapshot_id, expires_at, revoked_at FROM diag.share_token WHERE token = %s",
            (token,),
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFound("share token not found")
    if row["revoked_at"] is not None:
        raise NotFound("share token revoked")
    if row["expires_at"] < datetime.now(row["expires_at"].tzinfo):
        raise NotFound("share token expired")

    snapshot_id = row["snapshot_id"]
    # 分享链接绕过归属校验是刻意的：token 本身就是授权凭证，因此只能换 /report。
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT user_id FROM diag.portfolio_snapshot WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        owner = await cur.fetchone()
    owner_id = owner["user_id"] if owner else None
    return await get_report(db, snapshot_id, user_id=str(owner_id) if owner_id else None)


__all__ = [
    "PAYLOAD_SCHEMA_VERSION",
    "BaseDataVersionUnavailableError",
    "create_share_token",
    "create_snapshot",
    "get_active_spec_version",
    "get_data_quality",
    "get_data_version",
    "get_report",
    "get_result",
    "get_shared_report",
    "list_spec_versions",
    "recompute_snapshot",
]
