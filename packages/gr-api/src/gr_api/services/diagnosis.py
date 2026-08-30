"""持仓诊断服务层：代码解析、权重归一化、缓存键、模块 A 计算、编排与持久化。

契约见 ``getrich-design/portfolio-analysis/持仓诊断_表与接口设计.md``（v0.2.2）
与 ``持仓诊断_架构设计.md``（v0.1.3）。路由层只做参数校验与响应包壳，SQL 全在这里。

本轮范围（架构篇 §10 的 P0-a + P0-c 的模块 A 部分）
--------------------------------------------------
* 模块 A 完整出数：TopN / HHI / L1 / L2 + 行业、资产类别、市场、风格分布。
* 模块 B / C / D 按契约返回 ``None``：
  - B、D 需要协方差，依赖 §6.3 的 L1 全市场日收益矩阵常驻缓存（架构篇 P0-b）；
  - C 的组合历史序列口径本身未定（缺口 G6，产品决策）。
  前端不需要为此改代码 —— 这三个字段在类型上本来就可空。

三处「算错但不报错」的高危点，改动前务必先读对应注释
----------------------------------------------------
1. :func:`_calculation_hash` 与 :func:`_request_hash` 的 canonical 定义不可混用（§7.8）。
2. 行业归属必须按 ``as_of_date`` 取**当时**的归属，不能用最新归属回算历史（前视偏差）。
3. 查 ``meta.*`` 前交易所码必须转成 canonical 码，写错不报错、只会整批查不到。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from gr_api.errors import BadRequest, Forbidden, NotFound
from gr_api.schemas.diagnosis import (
    DataQualityReport,
    DiagnosisReport,
    PlanResult,
    PortfolioPlan,
    ReportBlock,
    ReportSection,
    SnapshotRequest,
)
from gr_api.services.pick_symbols import parse_symbol


if TYPE_CHECKING:
    from psycopg import AsyncConnection


logger = logging.getLogger(__name__)


#: ``diag.diagnosis_run.payload`` 的结构版本。PlanResult 的字段增删必须同步 +1，
#: 否则新代码会去解析旧结构的 payload 而不自知。
PAYLOAD_SCHEMA_VERSION = "1.0"

#: 权重的存储精度，对齐 DDL 的 ``NUMERIC(12,8)``。
#: 哈希前必须按这个精度舍入 —— 不舍入的话 1/3 这种除不尽的权重，
#: 每次算出的尾数都可能不同，同一组合永远命中不了缓存。
WEIGHT_QUANT = Decimal("0.00000001")

#: 交易日历统一用上交所（沪深北三所交易日一致）。
CALENDAR_EXCHANGE = "XSHG"

#: §7.6 的固定披露项 1~5、7。第 6 项按 weight_mode 动态追加。
FIXED_DISCLOSURES: tuple[str, ...] = (
    "本报告使用当前成分和当前权重回放，不代表历史上任一时点的真实持仓。",
    "再平衡频率：{rebalance}。",
    "分红：{dividend}；交易成本：{cost}；汇率折算：{fx}。",
    "实际可回溯区间：{window}。",
    "本报告不代表用户的真实收益。",
)

EQUAL_WEIGHT_DISCLOSURE = "未提供权重，本报告按等权假设计算。"

SNAPSHOT_DISCLOSURE_TPL = (
    "本报告基于 {fingerprint_time} 的数据快照计算，数据供应商的后续修订不会反映在本报告中。"
)


# ===========================================================================
# canonical JSON 与两套哈希（§7.8）
# ===========================================================================


def _canonical_json(payload: Any) -> str:
    """规范化 JSON：固定键序、无多余空白、非 ASCII 不转义。

    **不要**改成裸字符串拼接 —— 拼接没有转义规则，``["a,b"]`` 与 ``["a","b"]``
    会拼出同一个串，两个不同的组合于是共用一份缓存。
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _request_hash(req: SnapshotRequest) -> str:
    """整个 snapshot 的幂等键，在**解析前**用用户原始 symbol 计算。

    ``label`` 与 ``plan_index`` 必须参与：before/after 互换后是两个不同的请求，
    漏掉它们会让两者命中同一个 snapshot，调仓结论直接反向。
    """
    return _sha256(
        _canonical_json(
            {
                "plans": [
                    {
                        "plan_index": idx,
                        "plan_id": plan.plan_id,
                        "label": plan.label,
                        # 保留用户原始顺序与原始权重值，不做归一化、不做舍入
                        "holdings": [
                            {
                                "symbol": h.symbol,
                                "weight": None if h.weight is None else str(h.weight),
                            }
                            for h in plan.holdings
                        ],
                    }
                    for idx, plan in enumerate(req.plans)
                ],
                "intent": req.intent,
                "as_of_date": req.as_of_date.isoformat() if req.as_of_date else None,
                "spec_version": req.spec_version,
            }
        )
    )


def _calculation_hash(
    *,
    weight_mode: str,
    resolved_holdings: list[dict[str, Any]],
    resolved_as_of_date: date,
    spec_version: str,
    data_fingerprint: str,
) -> str:
    """单个 plan 的计算缓存键，在**解析后**用 instrument_id 计算（T17）。

    与 :func:`_request_hash` 的关键差异（改错会静默降低或错误提升缓存命中率）：

    * 粒度是**一个 plan**，不是整个 snapshot；
    * ``plan_id`` / ``label`` / ``plan_index`` / ``intent`` **都不参与** ——
      用户给方案起什么名字不影响数值，入哈希只会白白打散跨用户复用；
    * 持仓按 ``instrument_id`` **升序**重排，否则同一组合换个输入顺序就命中不到；
    * ``data_fingerprint`` 参与，数据快照变了必须重算。
    """
    ordered = sorted(resolved_holdings, key=lambda h: h["instrument_id"])
    return _sha256(
        _canonical_json(
            {
                "weight_mode": weight_mode,
                "resolved_holdings": [
                    {
                        "instrument_id": h["instrument_id"],
                        "weight": str(
                            Decimal(str(h["weight"])).quantize(
                                WEIGHT_QUANT, rounding=ROUND_HALF_EVEN
                            )
                        ),
                    }
                    for h in ordered
                ],
                "resolved_as_of_date": resolved_as_of_date.isoformat(),
                "spec_version": spec_version,
                "data_fingerprint": data_fingerprint,
            }
        )
    )


# ===========================================================================
# 口径版本与数据快照版本
# ===========================================================================


async def get_active_spec_version(db: AsyncConnection, spec_version: str | None = None) -> dict:
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
        raise NotFound(f"spec_version not found: {spec_version or '<active>'}")
    return row


async def list_spec_versions(db: AsyncConnection) -> list[dict]:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT * FROM diag.spec_version ORDER BY effective_from DESC, spec_version DESC"
        )
        return list(await cur.fetchall())


async def get_data_version(db: AsyncConnection) -> dict:
    """取最新的数据快照版本，其 id 即 ``data_fingerprint``。

    .. warning::
       文档要求这张表由每日盘后批任务维护，**该批任务目前不存在**（见
       ``040_diag.sql`` 的同名注释）。后果：数据重新导入后 fingerprint 不变，
       已成功的计算不会失效，接口会返回按旧数据算出的结果。缓解办法是每次
       数据导入后手工插一行新的 ``diag.data_version``。
    """
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT * FROM diag.data_version ORDER BY snapshot_at DESC LIMIT 1",
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFound("no diag.data_version row: run the 040_diag.sql bootstrap first")
    return row


async def _resolve_as_of_date(db: AsyncConnection, requested: date | None) -> date:
    """把请求的日期解析成具体交易日；缺省取最近一个已开市的交易日。"""
    target = requested or date.today()
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT trading_day FROM meta.trading_calendar
            WHERE exchange = %s AND is_open AND trading_day <= %s
            ORDER BY trading_day DESC LIMIT 1
            """,
            (CALENDAR_EXCHANGE, target),
        )
        row = await cur.fetchone()
    if row is None:
        # 日历没覆盖到（未 ingest 或日期过早）。不静默回退到 target ——
        # 那会让后续所有按交易日过滤的查询悄悄查空。
        raise BadRequest(f"no trading day on or before {target} in meta.trading_calendar")
    return row["trading_day"]


# ===========================================================================
# 代码解析与权重归一化
# ===========================================================================


async def _resolve_symbols(db: AsyncConnection, symbols: list[str]) -> dict[str, dict]:
    """``600000.SH`` → ``meta.instruments`` 行。解析不出来的不进返回值。

    交易所码两套的坑：``meta.*`` 用 canonical 码（``XSHG``/``XSHE``/``XBSE``），
    而 ``parse_symbol`` 返回的是前端契约码（``SSE``/``SZSE``/``BSE``）。这里按
    ``symbol`` 全码直查 ``meta.instruments``（该列存的就是带后缀全码 ``600000.SH``），
    因此不需要转换；但凡改成按 ``exchange`` 过滤，就必须先经
    ``pick_symbols.to_canonical_exchange``，否则整批查不到且不报错。
    """
    normalized: dict[str, str] = {}
    for raw in symbols:
        try:
            normalized[raw] = parse_symbol(raw).symbol_full
        except ValueError:
            # 格式就不对（不是 6 位数字 + .SH/.SZ/.BJ），归入未解析，不抛异常 ——
            # 部分代码解析不了应当降级出数，不是整个请求失败（§7.6）。
            continue
    if not normalized:
        return {}

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT instrument_id, symbol, asset, exchange, name, list_date, delist_date, status
            FROM meta.instruments
            WHERE symbol = ANY(%s)
            """,
            (list(set(normalized.values())),),
        )
        rows = {r["symbol"]: r for r in await cur.fetchall()}

    return {raw: rows[full] for raw, full in normalized.items() if full in rows}


def _normalize_plan(
    plan: PortfolioPlan,
    resolved: dict[str, dict],
) -> tuple[str, list[dict], list[str], list[str], Decimal, Decimal]:
    """合并重复代码 → 判定 weight_mode → 归一化到和为 1。

    Returns:
        ``(weight_mode, resolved_holdings, unresolved, duplicated,
        input_weight, resolved_weight)``。
    """
    # 1) 同一 plan 内重复代码：合并权重（加总），记名后继续，不报错（§7.6）
    merged: dict[str, Decimal | None] = {}
    duplicated: list[str] = []
    for item in plan.holdings:
        if item.symbol in merged:
            duplicated.append(item.symbol)
            prev = merged[item.symbol]
            if prev is None or item.weight is None:
                merged[item.symbol] = None
            else:
                merged[item.symbol] = prev + item.weight
        else:
            merged[item.symbol] = item.weight

    # 2) weight_mode：模型校验器已保证「要么全给、要么全不给」
    weight_mode = "user" if any(w is not None for w in merged.values()) else "equal"

    unresolved = [s for s in merged if s not in resolved]
    resolvable = [s for s in merged if s in resolved]

    # 3) 覆盖率口径：分子分母都用**用户原始权重**，不能用归一化后的
    #    （归一化后分母恒为 1，覆盖率永远是 100%，等于没算）
    if weight_mode == "user":
        input_weight = sum((merged[s] or Decimal(0) for s in merged), Decimal(0))
        resolved_weight = sum((merged[s] or Decimal(0) for s in resolvable), Decimal(0))
    else:
        # 等权模式下没有用户权重，用「条目数占比」表达覆盖率
        input_weight = Decimal(len(merged))
        resolved_weight = Decimal(len(resolvable))

    # 4) 归一化。注意分母是**可解析子集**的权重和，即
    #    normalized_within_resolved_subset=True —— 解析不出来的那部分权重
    #    被排除在计算之外，这个事实必须靠覆盖率字段族显式告诉前端。
    holdings: list[dict] = []
    if resolvable:
        if weight_mode == "user" and resolved_weight > 0:
            for sym in resolvable:
                w = (merged[sym] or Decimal(0)) / resolved_weight
                holdings.append(
                    {
                        "instrument_id": resolved[sym]["instrument_id"],
                        "symbol": resolved[sym]["symbol"],
                        "weight": float(w.quantize(WEIGHT_QUANT, rounding=ROUND_HALF_EVEN)),
                    }
                )
        else:
            each = (Decimal(1) / Decimal(len(resolvable))).quantize(
                WEIGHT_QUANT, rounding=ROUND_HALF_EVEN
            )
            for sym in resolvable:
                holdings.append(
                    {
                        "instrument_id": resolved[sym]["instrument_id"],
                        "symbol": resolved[sym]["symbol"],
                        "weight": float(each),
                    }
                )

    return weight_mode, holdings, unresolved, duplicated, input_weight, resolved_weight


# ===========================================================================
# 分类与估值取数（模块 A 的分布类指标）
# ===========================================================================


async def _fetch_industry(
    db: AsyncConnection,
    instrument_ids: list[int],
    *,
    scheme_code: str,
    level: int,
    as_of: date,
) -> dict[int, str]:
    """取 ``as_of`` 当日有效的行业归属。

    **必须按 as_of 卡有效期**（``in_date <= as_of < out_date``），不能图省事取
    ``out_date IS NULL`` 的当前归属 —— 行业分类会调整，用今天的归属回算历史
    就是前视偏差。``available_at <= now()`` 同理，防的是「数据晚于报告时点才入库」。
    """
    if not instrument_ids:
        return {}
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT ii.instrument_id, COALESCE(n.industry_name, ii.industry_code) AS industry
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
            (instrument_ids, scheme_code, level, as_of, as_of),
        )
        return {r["instrument_id"]: r["industry"] for r in await cur.fetchall()}


async def _fetch_category(
    db: AsyncConnection,
    instrument_ids: list[int],
    *,
    as_of: date,
) -> dict[int, dict]:
    """取 ``as_of`` 当日有效的资产类别与市场。"""
    if not instrument_ids:
        return {}
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
            (instrument_ids, as_of, as_of),
        )
        return {r["instrument_id"]: r for r in await cur.fetchall()}


async def _fetch_valuation(
    db: AsyncConnection,
    instrument_ids: list[int],
    *,
    as_of: date,
) -> dict[int, dict]:
    """取每个标的在 ``as_of`` 当日或之前最近一个交易日的估值快照。

    用 ``DISTINCT ON`` 取「不晚于 as_of 的最近一条」而不是「等于 as_of 的那条」：
    停牌、非交易日、数据尚未导入都会让当日无行，硬等于会整批查空。
    """
    if not instrument_ids:
        return {}
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT DISTINCT ON (instrument_id)
                   instrument_id, trading_day, total_mv, pb
            FROM fundamental.valuation_1d
            WHERE instrument_id = ANY(%s)
              AND trading_day <= %s
              AND available_at <= now()
            ORDER BY instrument_id, trading_day DESC
            """,
            (instrument_ids, as_of),
        )
        return {r["instrument_id"]: r for r in await cur.fetchall()}


# ===========================================================================
# 模块 A 计算
# ===========================================================================


def _ok(value: Any, *, method: str = "exact", confidence: str = "high") -> dict:
    return {"status": "ok", "value": value, "method": method, "confidence": confidence}


def _degraded(value: Any, *, reason_code: str, reason: str, method: str = "exact") -> dict:
    return {
        "status": "degraded",
        "value": value,
        "method": method,
        "reason_code": reason_code,
        "reason": reason,
        "confidence": "medium",
    }


def _unavailable(*, reason_code: str, reason: str) -> dict:
    return {"status": "unavailable", "reason_code": reason_code, "reason": reason}


def _distribution(
    holdings: list[dict],
    mapping: dict[int, Any],
    *,
    label: str,
) -> dict:
    """把「标的 → 类别」映射汇总成「类别 → 权重」分布，并按覆盖率定状态。

    覆盖不全时在**有数据的子集内归一化**并标 degraded，且在 reason 里写明
    覆盖率 —— 直接拿缺失的权重当 0 会让分布看起来是完整的 100%。
    """
    if not holdings:
        return _unavailable(
            reason_code="coverage_below_threshold", reason=f"无可解析持仓，{label}不可用"
        )

    covered = [h for h in holdings if mapping.get(h["instrument_id"]) is not None]
    covered_weight = sum(h["weight"] for h in covered)
    if not covered or covered_weight <= 0:
        return _unavailable(
            reason_code="coverage_below_threshold",
            reason=f"组合内没有任何标的具备{label}数据",
        )

    dist: dict[str, float] = {}
    for h in covered:
        key = str(mapping[h["instrument_id"]])
        dist[key] = dist.get(key, 0.0) + h["weight"] / covered_weight

    if len(covered) == len(holdings):
        return _ok(dist)
    return _degraded(
        dist,
        reason_code="coverage_below_threshold",
        reason=(
            f"{len(holdings) - len(covered)}/{len(holdings)} 个标的缺少{label}数据，"
            f"分布在覆盖到的 {covered_weight:.1%} 权重内归一化"
        ),
    )


def _mktcap_band(total_mv_yuan: Decimal | None, bands_yi: list[float]) -> str | None:
    """总市值（元）→ 大/中/小盘分档。``bands_yi`` 的单位是**亿元**。

    单位换算只在这一处做：``total_mv`` 入库统一为元（文档 T1 已决），
    而指标文档的阈值用亿元表述。两处各乘一次就会差 1e8 且不报错。
    """
    if total_mv_yuan is None or total_mv_yuan <= 0:
        return None
    yi = float(total_mv_yuan) / 1e8
    lo, hi = (bands_yi + [1000.0, 3000.0])[:2]
    if yi >= hi:
        return "large_cap"
    if yi >= lo:
        return "mid_cap"
    return "small_cap"


def _pb_band(pb: Decimal | None, bands: list[float]) -> str | None:
    """PB → 价值/均衡/成长分档。

    ``PB <= 0``（净资产为负）返回 None 而不是塞进「价值」档：负净资产的公司
    不是「便宜」，把它算成价值股是实打实的错误分类（文档 §5.5 明确要求不分档）。
    """
    if pb is None or pb <= 0:
        return None
    lo, hi = (bands + [2.0, 4.0])[:2]
    v = float(pb)
    if v >= hi:
        return "growth"
    if v >= lo:
        return "balanced"
    return "value"


def _build_exposure_section(
    holdings: list[dict],
    *,
    params: dict,
    industry: dict[int, str],
    category: dict[int, dict],
    valuation: dict[int, dict],
    has_fund: bool,
    input_weight: Decimal,
    resolved_weight: Decimal,
) -> dict:
    """模块 A。

    这几个标量是纯权重函数，不读行情也不读因子，因此是全部 54 项指标里唯一
    **无降级**可算的部分（架构篇 §2.2）。用纯 Python 而不是 numpy：n <= 100
    时两者都在微秒级（架构篇 §6.1），少一层依赖更划算。
    """
    weights = sorted((h["weight"] for h in holdings), reverse=True)
    n = len(weights)
    hhi = sum(w * w for w in weights)
    topn_k = int(params.get("topn", 5))
    empty = _unavailable(reason_code="coverage_below_threshold", reason="无可解析持仓")

    if n == 0:
        topn_m = hhi_m = l1_m = l2_m = empty
    else:
        topn_m = _ok(sum(weights[:topn_k]))
        hhi_m = _ok(hhi)
        l1_m = _ok(n)
        # L2 权重有效持仓数 = 1/Σw²。归一化后 hhi>0 恒成立，兜底分支只是防御。
        l2_m = _ok(1.0 / hhi) if hhi > 0 else empty

    cov_ratio = float(resolved_weight / input_weight) if input_weight > 0 else 0.0

    return {
        "topn": topn_m,
        "hhi": hhi_m,
        "l1_count": l1_m,
        "l2_effective_count": l2_m,
        "industry_distribution": _distribution(holdings, industry, label="行业分类"),
        "market_distribution": _distribution(
            holdings,
            {k: v["market"] for k, v in category.items()},
            label="市场归属",
        ),
        "asset_category_distribution": _distribution(
            holdings,
            {k: v["asset_category"] for k, v in category.items()},
            label="资产类别",
        ),
        "style_distribution": _style_distribution(holdings, valuation, params),
        "lookthrough_coverage": (
            _degraded(
                0.0,
                reason_code="lookthrough_incomplete",
                reason="组合内含基金/ETF，但基金持仓明细尚无数据源（缺口 G4），按名义敞口计算",
            )
            if has_fund
            else _ok(1.0)
        ),
        "input_weight": float(input_weight),
        "resolved_weight": float(resolved_weight),
        "unresolved_weight": float(input_weight - resolved_weight),
        "calculation_coverage_ratio": cov_ratio,
        # 恒为 True：归一化的分母是可解析子集的权重和（见 _normalize_plan）
        "normalized_within_resolved_subset": True,
    }


def _style_distribution(holdings: list[dict], valuation: dict[int, dict], params: dict) -> dict:
    """市值分档 × 估值分档的联合分布。"""
    bands_yi = list(params.get("mktcap_bands_yi") or [1000, 3000])
    pb_bands = list(params.get("pb_bands") or [2, 4])

    style: dict[int, str] = {}
    for h in holdings:
        row = valuation.get(h["instrument_id"])
        if row is None:
            continue
        cap = _mktcap_band(row.get("total_mv"), bands_yi)
        pb = _pb_band(row.get("pb"), pb_bands)
        if cap and pb:
            style[h["instrument_id"]] = f"{cap}/{pb}"

    return _distribution(holdings, style, label="市值与估值风格")


def _build_profile(section_a: dict, holdings: list[dict]) -> dict:
    """整体画像（Section 0）。

    一期只用得到模块 A 的数字，因此 ``data_status`` 恒为 ``partial`` ——
    风险、归因、结构三节都还没出数，声称 ``complete`` 是不诚实的。
    """
    findings: list[str] = []
    l2 = section_a["l2_effective_count"]
    n = len(holdings)

    label = "数据不足"
    if l2.get("status") in ("ok", "degraded"):
        eff = l2["value"]
        if n and eff < max(2.0, n * 0.4):
            label = "过度集中型"
            findings.append(f"名义持有 {n} 只，但权重有效持仓数仅 {eff:.1f}，集中度偏高")
        else:
            label = "均衡型"
            findings.append(f"名义持有 {n} 只，权重有效持仓数 {eff:.1f}")

    ind = section_a["industry_distribution"]
    if ind.get("status") in ("ok", "degraded") and ind.get("value"):
        top_ind, top_w = max(ind["value"].items(), key=lambda kv: kv[1])
        findings.append(f"行业集中于「{top_ind}」，占比 {top_w:.1%}")

    findings.append("本期风险、归因、结构三节尚未出数，判断仅基于持仓构成")

    return {
        "label": label,
        "top_findings": findings[:3],
        "confidence": "low",
        "data_status": "partial",
    }


def _build_disclosures(params: dict, *, weight_mode: str, fingerprint_time: str) -> list[str]:
    """§7.6 的强制声明。渲染器不得省略其中任何一条。"""
    rebalance = str(params.get("rebalance", "daily"))
    out = [
        FIXED_DISCLOSURES[0],
        FIXED_DISCLOSURES[1].format(rebalance=rebalance),
        FIXED_DISCLOSURES[2].format(
            dividend="包含" if params.get("include_dividend") else "不包含",
            cost="包含" if params.get("include_cost") else "不包含",
            fx="包含" if params.get("include_fx") else "不包含",
        ),
        FIXED_DISCLOSURES[3].format(window="本期不涉及历史序列，无回溯区间"),
        FIXED_DISCLOSURES[4],
        SNAPSHOT_DISCLOSURE_TPL.format(fingerprint_time=fingerprint_time),
    ]
    if weight_mode == "equal":
        out.append(EQUAL_WEIGHT_DISCLOSURE)
    # 本期唯一的口径妥协，必须显式披露（架构篇 §2.1）
    out.append(
        "本期风险、归因、结构类指标尚未启用：因子模型数据缺口（G2）与组合历史序列口径"
        "（G6）未决，相关章节整体不出数，而非以估算值填充。"
    )
    return out


# ===========================================================================
# 意图路由（架构篇 §4.2）
# ===========================================================================


def _resolve_intent(req: SnapshotRequest) -> str:
    """把请求翻译成意图。这是编排层唯一的决策内容。"""
    if req.intent:
        return req.intent
    if len(req.plans) == 1:
        return "single_instrument" if len(req.plans[0].holdings) == 1 else "single_portfolio"
    if len(req.plans) == 2:
        left = {h.symbol for h in req.plans[0].holdings}
        right = {h.symbol for h in req.plans[1].holdings}
        # 标的集合相同 → 只调金额；不同 → 有标的增减
        return "rebalance_amount" if left == right else "rebalance_holding"
    return "multi_portfolio"


def _report_mode(intent: str) -> str:
    if intent == "single_portfolio":
        return "standard"
    if intent == "single_instrument":
        # 独立 report_mode 而不是在 Section 里打补丁：Section 1–2 的「退化」
        # 是一份独立的 section 序列配置，不是渲染层的 if-else
        return "single_instrument"
    return "compare"


# ===========================================================================
# 编排：创建 snapshot 并计算
# ===========================================================================


async def create_snapshot(
    db: AsyncConnection,
    req: SnapshotRequest,
    *,
    user_id: str | None,
) -> tuple[dict, int]:
    """``POST /snapshots`` 的主流程。

    Returns:
        ``(响应体, HTTP 状态码)``。200=命中已有 snapshot，201=新建。

    计算**同步执行**：架构篇 §6.1 论证过单次数值计算在毫秒量级，§6.5 明确
    请求路径不引入 Celery —— 队列的轮询与状态管理成本高于收益。
    """
    spec = await get_active_spec_version(db, req.spec_version)
    params: dict = spec["params"]
    data_version = await get_data_version(db)
    as_of = await _resolve_as_of_date(db, req.as_of_date)
    intent = _resolve_intent(req)
    req_hash = _request_hash(req)

    # 1) 同一用户的相同请求直接复用（匿名时 user_id 为 NULL，不参与唯一性比较）
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT snapshot_id FROM diag.portfolio_snapshot
            WHERE request_hash = %s AND user_id IS NOT DISTINCT FROM %s
            """,
            (req_hash, user_id),
        )
        existing = await cur.fetchone()
    if existing is not None:
        snapshot_id = existing["snapshot_id"]
        result = await get_result(db, snapshot_id, user_id=user_id)
        return (
            {
                "snapshot_id": str(snapshot_id),
                "run_status": result["run_status"],
                "report_mode": result["report_mode"],
                "retry_after": None,
            },
            200,
        )

    # 2) 解析全部 plan 的代码（一次查完，避免逐 plan 回源）
    all_symbols = {h.symbol for plan in req.plans for h in plan.holdings}
    resolved = await _resolve_symbols(db, sorted(all_symbols))

    normalized: list[dict] = []
    for idx, plan in enumerate(req.plans):
        mode, holdings, unresolved, duplicated, in_w, res_w = _normalize_plan(plan, resolved)
        if not holdings:
            # 全部标的都解析不出来 → 无法构成组合。§7.6 规定这里是 **422**
            # 而不是 400：语义上同「请求校验失败」一类（plans 超限、混合权重），
            # 前端按同一个分支提示用户改输入即可。
            raise BadRequest(
                f"plan '{plan.plan_id}': none of the symbols could be resolved: {unresolved}",
                http_status=422,
            )
        normalized.append(
            {
                "plan_index": idx,
                "plan": plan,
                "weight_mode": mode,
                "holdings": holdings,
                "unresolved": unresolved,
                "duplicated": duplicated,
                "input_weight": in_w,
                "resolved_weight": res_w,
            }
        )

    # 3) 落 snapshot + plan
    snapshot_id = uuid4()  # 必须 v4：匿名用户之间的隔离只依赖它不可猜测
    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO diag.portfolio_snapshot (
                snapshot_id, user_id, request_hash, idempotency_key,
                requested_intent, resolved_intent,
                requested_as_of_date, resolved_as_of_date,
                requested_spec_version, resolved_spec_version,
                requested_payload, user_level
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                snapshot_id,
                user_id,
                req_hash,
                req.idempotency_key,
                req.intent,
                intent,
                req.as_of_date,
                as_of,
                req.spec_version,
                spec["spec_version"],
                json.dumps(req.model_dump(mode="json")),
                req.user_level,
            ),
        )
        for item in normalized:
            await cur.execute(
                """
                INSERT INTO diag.portfolio_plan (
                    snapshot_id, plan_index, plan_id, label,
                    weight_mode, requested_holdings, resolved_holdings
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    snapshot_id,
                    item["plan_index"],
                    item["plan"].plan_id,
                    item["plan"].label,
                    item["weight_mode"],
                    json.dumps(
                        [h.model_dump(mode="json") for h in item["plan"].holdings],
                    ),
                    json.dumps(item["holdings"]),
                ),
            )

    # 4) 逐 plan 计算（或命中已有计算）
    for item in normalized:
        await _ensure_run(
            db,
            snapshot_id=snapshot_id,
            item=item,
            spec=spec,
            params=params,
            as_of=as_of,
            data_fingerprint=data_version["data_version_id"],
            fingerprint_time=data_version["snapshot_at"],
        )

    logger.info(
        "diagnosis snapshot created: snapshot_id=%s intent=%s plans=%d as_of=%s spec=%s",
        snapshot_id,
        intent,
        len(normalized),
        as_of,
        spec["spec_version"],
    )
    return (
        {
            "snapshot_id": str(snapshot_id),
            "run_status": "succeeded",
            "report_mode": _report_mode(intent),
            "retry_after": None,
        },
        201,
    )


async def _ensure_run(
    db: AsyncConnection,
    *,
    snapshot_id: UUID,
    item: dict,
    spec: dict,
    params: dict,
    as_of: date,
    data_fingerprint: str,
    fingerprint_time: datetime,
) -> UUID:
    """算一个 plan：命中成功终态就复用，否则现算并落 ``diag.diagnosis_run``。"""
    calc_hash = _calculation_hash(
        weight_mode=item["weight_mode"],
        resolved_holdings=item["holdings"],
        resolved_as_of_date=as_of,
        spec_version=spec["spec_version"],
        data_fingerprint=data_fingerprint,
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
        plan_result, dq = await _compute_plan(
            db, item=item, params=params, as_of=as_of, fingerprint_time=fingerprint_time
        )
        run_id = uuid4()
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
                    json.dumps(plan_result),
                    PAYLOAD_SCHEMA_VERSION,
                    json.dumps(dq),
                ),
            )
            inserted = await cur.fetchone()
            if inserted is None:
                # 并发下另一个请求先写成功了：放弃自己的结果，改读已成功那行（§7.6）。
                # 两份结果本就应当逐位一致（同 hash = 同输入同口径），谁赢都一样。
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
                run_id = row["run_id"]

    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO diag.snapshot_run (snapshot_id, plan_index, run_id)
            VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (snapshot_id, item["plan_index"], run_id),
        )
    return run_id


async def _compute_plan(
    db: AsyncConnection,
    *,
    item: dict,
    params: dict,
    as_of: date,
    fingerprint_time: datetime,
) -> tuple[dict, dict]:
    """算一个 plan 的 ``PlanResult`` 与它的数据质量清单。"""
    holdings: list[dict] = item["holdings"]
    ids = [h["instrument_id"] for h in holdings]

    industry = await _fetch_industry(
        db,
        ids,
        scheme_code=str(params.get("industry_scheme", "sw2021")),
        level=int(params.get("industry_level", 1)),
        as_of=as_of,
    )
    category = await _fetch_category(db, ids, as_of=as_of)
    valuation = await _fetch_valuation(db, ids, as_of=as_of)

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT instrument_id, asset, status, list_date, delist_date
            FROM meta.instruments WHERE instrument_id = ANY(%s)
            """,
            (ids,),
        )
        instruments = {r["instrument_id"]: r for r in await cur.fetchall()}

    has_fund = any(instruments.get(i, {}).get("asset") in ("etf", "fund") for i in ids)

    section_a = _build_exposure_section(
        holdings,
        params=params,
        industry=industry,
        category=category,
        valuation=valuation,
        has_fund=has_fund,
        input_weight=item["input_weight"],
        resolved_weight=item["resolved_weight"],
    )

    plan_result = {
        "plan_id": item["plan"].plan_id,
        "label": item["plan"].label,
        "weight_mode": item["weight_mode"],
        "section_a": section_a,
        # B / D 依赖协方差，需要 L1 全市场日收益矩阵（架构篇 P0-b）；
        # C 的历史序列口径未定（缺口 G6）。三节整体不出数，不以估算值填充。
        "section_b": None,
        "section_c": None,
        "section_d": None,
        "blindspots": _build_blindspots(section_a, params),
        "profile": _build_profile(section_a, holdings),
    }
    # 过一遍 Pydantic 再落库：payload 是手写 dict，字段拼错或 MetricValue 三态的
    # 字段组合非法（如 status=ok 却没有 value）在这里就会炸，而不是等到前端
    # 渲染成空白才发现。校验后的结果也顺便完成了 Decimal/date → JSON 的规范化。
    plan_result = PlanResult.model_validate(plan_result).model_dump(mode="json")

    suspended = [
        instruments[i]["instrument_id"]
        for i in ids
        if instruments.get(i, {}).get("status") not in (None, "active")
    ]
    new_listings = [
        i
        for i in ids
        if (ld := instruments.get(i, {}).get("list_date")) and (as_of - ld) < timedelta(days=250)
    ]

    symbol_of = {h["instrument_id"]: h["symbol"] for h in holdings}
    dq = {
        "unresolved_symbols": item["unresolved"],
        "duplicated_symbols": item["duplicated"],
        "suspended_or_delisted": [symbol_of.get(i, str(i)) for i in suspended],
        "new_listings_short_window": [symbol_of.get(i, str(i)) for i in new_listings],
        "lookthrough_gaps": [
            symbol_of[i] for i in ids if instruments.get(i, {}).get("asset") in ("etf", "fund")
        ],
        "coverage_summary": {
            "symbol_resolution": section_a["calculation_coverage_ratio"],
            "industry": len(industry) / len(ids) if ids else 0.0,
            "category": len(category) / len(ids) if ids else 0.0,
            "valuation": len(valuation) / len(ids) if ids else 0.0,
        },
        "forced_disclosures": _build_disclosures(
            params,
            weight_mode=item["weight_mode"],
            fingerprint_time=fingerprint_time.strftime("%Y-%m-%d %H:%M"),
        ),
    }
    return plan_result, dq


def _build_blindspots(section_a: dict, params: dict) -> list[dict]:
    """盲点检测。一期只有依赖模块 A 的检测器可跑。

    依赖 B/D 的检测器（伪分散、单因子依赖）**必须显式返回 triggered=False +
    reason_code**，而不是干脆不返回 —— 「查了没触发」和「压根没法查」在报告里
    是两回事，省略会让用户以为已经检查过了。
    """
    hits: list[dict] = []

    hhi = section_a["hhi"]
    if hhi.get("status") in ("ok", "degraded"):
        v = hhi["value"]
        triggered = v > 0.25  # 等价于有效持仓数 < 4
        hits.append(
            {
                "detector": "concentration",
                "triggered": triggered,
                "severity": "high" if v > 0.5 else "medium" if triggered else None,
                "message": (
                    f"持仓高度集中（HHI={v:.3f}，权重有效持仓数 {1 / v:.1f}）"
                    if triggered
                    else f"权重分散度尚可（HHI={v:.3f}）"
                ),
                "reason_code": None,
            }
        )

    ind = section_a["industry_distribution"]
    if ind.get("status") in ("ok", "degraded") and ind.get("value"):
        top_ind, top_w = max(ind["value"].items(), key=lambda kv: kv[1])
        triggered = top_w > 0.5
        hits.append(
            {
                "detector": "industry_concentration",
                "triggered": triggered,
                "severity": "high" if top_w > 0.7 else "medium" if triggered else None,
                "message": (
                    f"单一行业「{top_ind}」占比 {top_w:.1%}，行业风险集中"
                    if triggered
                    else f"行业分布最大占比 {top_w:.1%}"
                ),
                "reason_code": None,
            }
        )
    else:
        hits.append(
            {
                "detector": "industry_concentration",
                "triggered": False,
                "severity": None,
                "message": "缺少行业分类数据，无法判断行业集中度",
                "reason_code": "coverage_below_threshold",
            }
        )

    for detector, msg in (
        ("pseudo_diversification", "需要相关性矩阵，本期风险模块未启用"),
        ("style_bet", "需要因子暴露，因子模型数据缺口（G2）未关闭"),
    ):
        hits.append(
            {
                "detector": detector,
                "triggered": False,
                "severity": None,
                "message": msg,
                "reason_code": "factor_model_unavailable",
            }
        )
    return hits


# ===========================================================================
# 读取：result / report / data-quality
# ===========================================================================


async def _load_snapshot(db: AsyncConnection, snapshot_id: UUID, *, user_id: str | None) -> dict:
    """取 snapshot 并做归属校验（§7.7）。"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT * FROM diag.portfolio_snapshot WHERE snapshot_id = %s",
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


async def get_result(
    db: AsyncConnection,
    snapshot_id: UUID,
    *,
    user_id: str | None,
) -> dict:
    """``GET /snapshots/{id}/result``：组装全量 ``DiagnosisResult``。

    snapshot 级字段（disclosures / data_quality）在这里拼接 —— 它们不在
    ``diagnosis_run.payload`` 里，因为 run 的粒度是 plan、且要跨用户复用。
    """
    snapshot = await _load_snapshot(db, snapshot_id, user_id=user_id)
    spec = await get_active_spec_version(db, snapshot["resolved_spec_version"])

    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT p.plan_index, r.status, r.payload, r.data_quality, r.error_reason
            FROM diag.portfolio_plan p
            LEFT JOIN diag.snapshot_run sr
                   ON sr.snapshot_id = p.snapshot_id AND sr.plan_index = p.plan_index
            LEFT JOIN diag.diagnosis_run r ON r.run_id = sr.run_id
            WHERE p.snapshot_id = %s
            ORDER BY p.plan_index
            """,
            (snapshot_id,),
        )
        rows = list(await cur.fetchall())

    plans = [r["payload"] for r in rows if r["payload"] is not None]
    statuses = {r["status"] for r in rows}
    if not plans:
        run_status = "pending"
    elif "failed" in statuses:
        run_status = "partially_succeeded" if len(plans) else "failed"
    elif len(plans) < len(rows):
        run_status = "partially_succeeded"
    else:
        run_status = "succeeded"

    merged_dq = _merge_data_quality([r["data_quality"] for r in rows if r["data_quality"]])
    params = spec["params"]

    return {
        "snapshot_id": str(snapshot_id),
        "spec_version": snapshot["resolved_spec_version"],
        "cov": {
            "primary": str(params.get("primary_cov_method", "historical")),
            # 一期一个都没实际算出来（B/D 未启用）。写成 [] 而不是照抄配置的
            # cov_methods —— 后者会让前端以为历史协方差已经算过了。
            "computed": [],
        },
        "as_of_date": snapshot["resolved_as_of_date"].isoformat(),
        "report_mode": _report_mode(snapshot["resolved_intent"]),
        "run_status": run_status,
        "plans": plans,
        "comparison": None,  # 模块 E 属 P2-b
        "disclosures": merged_dq.get("forced_disclosures", []),
        "data_quality": merged_dq,
        "error_reason": next((r["error_reason"] for r in rows if r["error_reason"]), None),
    }


def _merge_data_quality(items: list[dict]) -> dict:
    """把各 plan 的数据质量清单并成 snapshot 级的一份（去重保序）。"""
    out = DataQualityReport().model_dump()
    for item in items:
        for key, value in item.items():
            if isinstance(value, list):
                seen = out.setdefault(key, [])
                for v in value:
                    if v not in seen:
                        seen.append(v)
            elif isinstance(value, dict):
                bucket = out.setdefault(key, {})
                for k, v in value.items():
                    # 多 plan 时同名覆盖率取最差的那个，别报喜不报忧
                    bucket[k] = min(bucket[k], v) if k in bucket else v
    return out


async def get_data_quality(
    db: AsyncConnection,
    snapshot_id: UUID,
    *,
    user_id: str | None,
) -> dict:
    """``GET /snapshots/{id}/data-quality``：单独取降级清单与强制声明。"""
    result = await get_result(db, snapshot_id, user_id=user_id)
    return result["data_quality"]


def _metric_block(key: str, label: str, metric: dict, *, fmt: str = "{}") -> ReportBlock:
    """把一个 MetricValue 渲染成报告块。

    ``unavailable`` 必须渲染成「不可用 + 原因」而不是隐藏或填 0 ——
    这是架构篇 §8.2 的硬约束，也是渲染层唯一不能省的分支。
    """
    status = metric.get("status", "unavailable")
    if status == "unavailable":
        return ReportBlock(
            key=key, label=label, value=None, status="unavailable", reason=metric.get("reason")
        )
    value = metric.get("value")
    return ReportBlock(
        key=key,
        label=label,
        value=fmt.format(value) if isinstance(value, (int, float)) else value,
        status=status,
        reason=metric.get("reason"),
    )


async def get_report(
    db: AsyncConnection,
    snapshot_id: UUID,
    *,
    user_id: str | None,
    user_level: str | None = None,
) -> dict:
    """``GET /snapshots/{id}/report``：按 ``user_level`` 裁剪后的报告。

    等级只影响**渲染**，不影响计算：同一份 ``diagnosis_run`` 服务两种等级，
    裁剪在访问时动态做、不做持久化缓存（避免等级变更后旧渲染残留，§7.7）。
    """
    snapshot = await _load_snapshot(db, snapshot_id, user_id=user_id)
    result = await get_result(db, snapshot_id, user_id=user_id)
    level = user_level or snapshot["user_level"]

    sections: list[ReportSection] = []
    for plan in result["plans"]:
        a = plan["section_a"]
        prefix = f"{plan['plan_id']}." if len(result["plans"]) > 1 else ""

        profile = plan["profile"]
        sections.append(
            ReportSection(
                section_id=f"{prefix}0",
                title="整体判断",
                blocks=[
                    ReportBlock(key="label", label="组合画像", value=profile["label"]),
                    ReportBlock(key="findings", label="Top 发现", value=profile["top_findings"]),
                    ReportBlock(key="confidence", label="置信度", value=profile["confidence"]),
                    ReportBlock(key="data_status", label="数据状态", value=profile["data_status"]),
                ],
            )
        )

        blocks = [
            _metric_block("l1", "名义持仓数", a["l1_count"]),
            _metric_block("industry", "行业分布", a["industry_distribution"]),
            _metric_block("category", "资产类别分布", a["asset_category_distribution"]),
            _metric_block("market", "市场分布", a["market_distribution"]),
            _metric_block("style", "风格分布", a["style_distribution"]),
        ]
        if level == "pro":
            # 散户等级给判断不给中间指标；专业等级才展开原始数字（架构篇 §4.4）
            blocks.extend(
                [
                    _metric_block("hhi", "HHI 集中度", a["hhi"], fmt="{:.4f}"),
                    _metric_block("topn", "TopN 权重", a["topn"], fmt="{:.2%}"),
                    _metric_block(
                        "coverage",
                        "解析覆盖率",
                        {"status": "ok", "value": a["calculation_coverage_ratio"]},
                        fmt="{:.2%}",
                    ),
                ]
            )
        sections.append(
            ReportSection(section_id=f"{prefix}1", title="你实际持有的是什么", blocks=blocks)
        )

        sections.append(
            ReportSection(
                section_id=f"{prefix}2",
                title="分散度真相",
                blocks=[
                    _metric_block("l2", "权重有效持仓数", a["l2_effective_count"], fmt="{:.2f}"),
                    *[
                        ReportBlock(
                            key=b["detector"],
                            label=b["detector"],
                            value=b["message"],
                            status="unavailable" if b["reason_code"] else "ok",
                            reason=b["reason_code"],
                        )
                        for b in plan["blindspots"]
                    ],
                ],
            )
        )

        for sid, title, key in (
            ("3", "风险画像", "section_b"),
            ("4", "风格与暴露", "section_d"),
            ("5", "归因与分位", "section_c"),
        ):
            if plan.get(key) is None:
                sections.append(
                    ReportSection(
                        section_id=f"{prefix}{sid}",
                        title=title,
                        blocks=[
                            ReportBlock(
                                key=key,
                                label=title,
                                value=None,
                                status="unavailable",
                                reason="本期该模块未启用：因子模型（G2）与历史序列口径（G6）未就绪",
                            )
                        ],
                    )
                )

    # Section 6 是降级信息唯一的落脚点 —— 没有它，降级说明只能散在各节角标里，
    # 用户看不到全貌（架构篇 §8.1 评审新增）。
    dq = result["data_quality"]
    sections.append(
        ReportSection(
            section_id="6",
            title="方法与数据局限",
            blocks=[
                ReportBlock(
                    key="unresolved", label="未能解析的代码", value=dq["unresolved_symbols"]
                ),
                ReportBlock(
                    key="duplicated", label="重复代码（已合并）", value=dq["duplicated_symbols"]
                ),
                ReportBlock(key="suspended", label="停牌或退市", value=dq["suspended_or_delisted"]),
                ReportBlock(
                    key="new_listing", label="上市不足一年", value=dq["new_listings_short_window"]
                ),
                ReportBlock(
                    key="lookthrough", label="未穿透的基金/ETF", value=dq["lookthrough_gaps"]
                ),
                ReportBlock(key="coverage", label="各项数据覆盖率", value=dq["coverage_summary"]),
            ],
        )
    )

    return DiagnosisReport(
        snapshot_id=snapshot_id,
        report_mode=result["report_mode"],
        user_level=level,
        sections=sections,
        disclosures=result["disclosures"],
    ).model_dump(mode="json")


# ===========================================================================
# 分享
# ===========================================================================


async def create_share_token(
    db: AsyncConnection,
    snapshot_id: UUID,
    *,
    user_id: str | None,
    ttl_days: int = 30,
) -> dict:
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
    return {"token": row["token"], "expires_at": row["expires_at"].isoformat()}


async def get_shared_report(db: AsyncConnection, token: str) -> dict:
    """``GET /share/{token}/report``：token 只换报告，不暴露 /result 全量指标。"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT snapshot_id, expires_at, revoked_at
            FROM diag.share_token WHERE token = %s
            """,
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
    # 分享链接绕过归属校验是**刻意**的：token 本身就是授权凭证。
    # 因此它只能换 /report，绝不能换 /result（§7.7）。
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT user_id FROM diag.portfolio_snapshot WHERE snapshot_id = %s",
            (snapshot_id,),
        )
        owner = await cur.fetchone()
    return await get_report(
        db, snapshot_id, user_id=str(owner["user_id"]) if owner["user_id"] else None
    )


__all__ = [
    "PAYLOAD_SCHEMA_VERSION",
    "create_share_token",
    "create_snapshot",
    "get_active_spec_version",
    "get_data_quality",
    "get_data_version",
    "get_report",
    "get_result",
    "get_shared_report",
    "list_spec_versions",
]
