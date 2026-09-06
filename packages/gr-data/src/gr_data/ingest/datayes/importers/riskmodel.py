"""DataYes CNE6-SW21 五表 → `factor` schema。

## 三条必须一起看的纪律

1. **取因子值只能经 `factors.reindex_wide`**。三张宽表的列顺序互不相同，
   按源列序展平会让每个因子都对应错，而结果依然是合法的 52 维向量 /
   对称正定矩阵，没有任何报错。
2. **量纲按配置显式换算，配置缺键就拒绝启动**（`scaling.py`）。
   SRISK 是年化百分比**波动率 σ**，入库要平方成方差。
3. **`available_at` 取供应商的 `updateTime`**，逐行精确、天然覆盖回算与重述；
   缺失才退回文档声明的发布时点。

## 符号解析

datayes 的 `secID`（``000002.XSHE``）与 `meta.instruments.symbol`
（``000002.SZ``）不是同一串。`DatayesSymbolMapImporter` 先建立
`meta.symbol_map` 的 `(datayes, secID) → instrument_id` 映射，
其余 importer 统一走 `resolve_by_symbol_map(conn, "datayes")`。
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from gr_data.common import contracts
from gr_data.ingest import pit
from gr_data.ingest.base import BaseImporter
from gr_data.ingest.datayes import factors as fx, model_run as mr
from gr_data.ingest.datayes.adapter import DatayesAdapter
from gr_data.ingest.datayes.scaling import Scaling
from gr_data.ingest.datayes.symbols import to_tushare_symbol
from gr_data.ingest.resolve import resolve_by_instrument, resolve_by_symbol_map


PROVIDER = "datayes"

#: 未解析标的的容忍上限。超过说明 symbol_map 没建好或供应商换了编码，
#: 此时继续入库会让一大批标的静默缺行 —— 中断比「少了一半数据但没报错」好。
UNRESOLVED_TOLERANCE = 0.005

#: `updateTime` 缺失时的退路：官方声明的发布时点（实测常为 T 日 17:00，
#: 但实测值不写进默认值，见 pit.from_vendor_timestamp 的 docstring）。
VENDOR_PUBLISH_HOUR = 19

_META_COLUMNS = ("secID", "ticker", "secShortName", "exchangeCD", "tradeDate", "updateTime")


def _pick(df: pd.DataFrame, *names: str) -> pd.Series | None:
    """大小写不敏感地取一列。

    JSON 接口是 camelCase（`tradeDate`/`updateTime`），CSV 导出是
    UPPER_SNAKE（`TRADE_DATE`/`UPDATE_TIME`）—— 两条通道都要能读。
    """
    lookup = {str(c).replace("_", "").upper(): c for c in df.columns}
    for n in names:
        col = lookup.get(n.replace("_", "").upper())
        if col is not None:
            return df[col]
    return None


def _require_column(df: pd.DataFrame, *names: str) -> pd.Series:
    s = _pick(df, *names)
    if s is None:
        raise ValueError(f"缺少必需列 {names[0]}（现有列：{list(df.columns)[:10]}…）")
    return s


def _trading_day(df: pd.DataFrame) -> pd.Series:
    raw = _require_column(df, "tradeDate", "TRADE_DATE")
    parsed = pd.to_datetime(raw.astype(str).str.strip(), format="mixed", errors="coerce")
    if parsed.isna().any():
        raise ValueError(f"含 {int(parsed.isna().sum())} 行无法解析的 tradeDate")
    return parsed.dt.date


def _available_at(df: pd.DataFrame) -> pd.Series:
    ts = _pick(df, "updateTime", "UPDATE_TIME")
    if ts is None:
        # 供应商这批数据没带时间戳：退回文档声明的发布时点（弱，但可解释）
        return pit.from_trading_day(pd.Series(_trading_day(df)), publish_hour=VENDOR_PUBLISH_HOUR)
    parsed = pd.to_datetime(ts, errors="coerce")
    if parsed.isna().any():
        fallback = pit.from_trading_day(
            pd.Series(_trading_day(df)), publish_hour=VENDOR_PUBLISH_HOUR
        )
        localized = pit.from_vendor_timestamp(
            parsed.fillna(pd.Timestamp("2000-01-01")), default_hour=VENDOR_PUBLISH_HOUR
        )
        return localized.where(parsed.notna(), fallback)
    return pit.from_vendor_timestamp(parsed, default_hour=VENDOR_PUBLISH_HOUR)


class _DatayesImporter(BaseImporter):
    """datayes importer 的公共部分：配置、raw 读取、model_run、数据质量记账。"""

    PROVIDER = PROVIDER
    DATASET_RAW: str = ""  # 对应的 raw dataset 名

    def __init__(self, conn, ctx, client: Any | None = None, scaling: Scaling | None = None):
        super().__init__(conn, ctx, client)
        self._scaling = scaling

    @property
    def scaling(self) -> Scaling:
        if self._scaling is None:
            raise RuntimeError(
                f"{type(self).__name__} 未注入 scaling。datayes 的量纲系数没有默认值，"
                "必须由 run_provider 从 providers.datayes.scaling 读入。"
            )
        return self._scaling

    def _adapter(self) -> DatayesAdapter:
        return DatayesAdapter(self.paths, self.ctx.months)

    def _raw(self) -> pd.DataFrame:
        return self._adapter().read_all_months(self.DATASET_RAW)

    def _empty(self) -> pd.DataFrame:
        return pd.DataFrame(columns=list(self.contract.columns))

    def _record_dq(self, rule: str, severity: str, detail: dict) -> None:
        """写一条 ops.data_quality_check。

        跳过、降级、回退这类「继续跑但结果不完整」的事必须留痕：
        它们在日志里一闪而过，只有落库才追得回来。
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.data_quality_check (rule, severity, detail) VALUES (%s, %s, %s)",
                (rule, severity, json.dumps(detail, ensure_ascii=False)),
            )

    # -- 因子集合复核 -------------------------------------------------------
    def _run_and_order(self, df: pd.DataFrame) -> tuple[Any, list[str]]:
        """取回 model_run，并复核当日活跃因子集与它一致。"""
        run_id, factor_order, set_hash = mr.load_run(self.conn)
        today = fx.active_factors(df)
        if set_hash and fx.factor_set_hash(today) != set_hash:
            raise fx.FactorSetChangedError(
                f"当日活跃因子集合与 model_run 不一致："
                f"库内 {len(factor_order)} 个，本批 {len(today)} 个"
                f"（多出 {sorted(set(today) - set(factor_order))}，"
                f"缺少 {sorted(set(factor_order) - set(today))}）。"
                "这通常意味着供应商换了行业体系，必须人工确认后开新 model_version。"
            )
        return run_id, list(factor_order)

    # -- 符号解析 -----------------------------------------------------------
    def _attach_instrument_ids(self, df: pd.DataFrame) -> pd.DataFrame:
        sec_id = _require_column(df, "secID", "SEC_ID")
        df = df.copy()
        df["sec_id"] = sec_id.astype(str).str.strip()
        id_map = resolve_by_symbol_map(self.conn, PROVIDER)
        df["instrument_id"] = df["sec_id"].map(id_map)

        unresolved = df["instrument_id"].isna()
        if unresolved.any():
            ratio = float(unresolved.mean())
            codes = sorted(set(df.loc[unresolved, "sec_id"]))
            detail = {"rows": int(unresolved.sum()), "ratio": ratio, "sample": codes[:20]}
            if ratio > UNRESOLVED_TOLERANCE:
                raise ValueError(
                    f"{ratio:.2%} 的标的在 meta.symbol_map(datayes) 中无登记，"
                    f"超过 {UNRESOLVED_TOLERANCE:.2%} 的容忍上限；样例 {codes[:5]}。"
                    "请先运行 `gr-data ingest datayes --only symbol_map`。"
                )
            self.log.warning("%d 行标的未解析（%.3f%%），已跳过", detail["rows"], ratio * 100)
            self._record_dq("datayes_unresolved_secid", "warn", detail)
            df = df[~unresolved]
        return df


class DatayesSymbolMapImporter(_DatayesImporter):
    """把 datayes 的 secID 登记进 meta.symbol_map。

    `secID` 是 ``000002.XSHE``，而 `meta.instruments.symbol` 是 tushare 形态的
    ``000002.SZ``。这里做一次性折算并落进映射表，之后所有 datayes importer 都走
    `resolve_by_symbol_map`，不再在各处做后缀互转 —— 跨源对齐经 symbol_map
    是 AGENTS.md §3.4 的约定，也让「哪个 secID 对应哪个标的」可审计。
    """

    DATASET = "symbol_map"
    DATASET_RAW = "exposure_cne6_sw21"
    CONTRACT = contracts.SYMBOL_MAP
    NOT_NULL_COLUMNS = ("instrument_id", "source", "source_symbol")

    def build(self) -> pd.DataFrame:
        # 逐月累积 secID 集合，不 concat 全历史：这里只要「有哪些代码」，
        # 而全量 exposure 在 pandas 里约 3.5 GB。**必须覆盖全部月份**，
        # 只读最近一个月会漏掉期间退市的标的，那些标的的历史因子数据就永远
        # 解析不出 instrument_id、整批入不了库。
        adapter = self._adapter()
        sec_id_set: set[str] = set()
        for ym in adapter.list_months(self.DATASET_RAW):
            raw = adapter.read_month(self.DATASET_RAW, ym)
            if raw is None or raw.empty:
                continue
            sec_id_set.update(
                s.strip() for s in _require_column(raw, "secID", "SEC_ID").astype(str)
            )
            del raw

        if not sec_id_set:
            self.log.warning("%s 无 raw 数据，无法建立 symbol_map", self.DATASET_RAW)
            return self._empty()

        sec_ids = sorted(sec_id_set)
        stock_ids = resolve_by_instrument(self.conn, "stock")

        rows, unmapped = [], []
        for sec_id in sec_ids:
            symbol = to_tushare_symbol(sec_id)
            iid = stock_ids.get(symbol) if symbol else None
            if iid is None:
                unmapped.append(sec_id)
                continue
            rows.append({"instrument_id": iid, "source": PROVIDER, "source_symbol": sec_id})

        if unmapped:
            # 不抛错：meta.instruments 由 tushare 建，退市股、次新股都可能暂时缺行。
            # 但必须留痕 —— 缺映射会让这些标的的因子数据整体入不了库。
            self.log.warning(
                "%d/%d 个 secID 在 meta.instruments 中找不到对应标的；样例 %s",
                len(unmapped),
                len(sec_ids),
                unmapped[:5],
            )
            self._record_dq(
                "datayes_secid_without_instrument",
                "warn",
                {"count": len(unmapped), "total": len(sec_ids), "sample": unmapped[:20]},
            )
        return pd.DataFrame(rows, columns=list(self.contract.columns))


class ModelRunImporter(_DatayesImporter):
    """建立 factor.model / definition / model_run。

    与其它 importer 不同，这三张表的写入不走 `upsert_rows` —— 它们是元数据，
    行数固定（1 / K / 1），且 `model_run` 有「不可 UPDATE」的语义，
    套用「按 contract 批量 upsert」反而会把那条语义弄丢。
    因此 `build()` 直接在同一事务里写完，返回空表让基类跳过 upsert。
    """

    DATASET = "model_run"
    DATASET_RAW = "exposure_cne6_sw21"
    CONTRACT = contracts.MODEL_RUN

    def build(self) -> pd.DataFrame:
        # 逐月读、逐月比，而不是先 concat 全历史：全量 exposure 在 pandas 里约
        # 3.5 GB，而这里只需要「列集合」这一件事。顺带得到一个更强的保证 ——
        # **要求每个月的活跃因子集合都相同**，中途换体系会当场报出是哪个月变的，
        # 而不是被 concat 成一个并集后无声地混用两套顺序。
        adapter = self._adapter()
        months = adapter.list_months(self.DATASET_RAW)
        factor_order: list[str] | None = None
        first_ym = ""
        estimated_at = None
        for ym in months:
            raw = adapter.read_month(self.DATASET_RAW, ym)
            if raw is None or raw.empty:
                continue
            # 活跃因子集合**从数据派生**，不写死：sw14 期是 49 个、sw21 期是 52 个，
            # 写死一个数字就等于在体系切换时静默算错。写死的只有超集与它的顺序。
            active = list(fx.active_factors(raw))
            if factor_order is None:
                factor_order, first_ym = active, ym
            elif set(active) != set(factor_order):
                raise fx.FactorSetChangedError(
                    f"{ym} 的活跃因子集合与 {first_ym} 不一致："
                    f"多出 {sorted(set(active) - set(factor_order))}，"
                    f"缺少 {sorted(set(factor_order) - set(active))}。"
                    "同一个 model_run 内因子集合必须恒定，请人工确认后按体系分段建 run。"
                )
            month_max = _available_at(raw).max()
            estimated_at = month_max if estimated_at is None else max(estimated_at, month_max)
            del raw

        if factor_order is None:
            raise RuntimeError(
                f"{self.DATASET_RAW} 无 raw 数据，无法确定活跃因子集合。"
                "请先运行 `gr-data raw datayes`。"
            )
        if not factor_order:
            raise ValueError("未能从 raw 数据识别出任何已知因子列")

        expected = set(fx.SW21_FACTORS)
        if set(factor_order) != expected:
            self.log.warning(
                "活跃因子集合（%d 个）与申万 2021 体系的预期（%d 个）不同：多 %s，少 %s",
                len(factor_order),
                len(expected),
                sorted(set(factor_order) - expected),
                sorted(expected - set(factor_order)),
            )

        estimated_at = estimated_at.to_pydatetime()
        mr.upsert_model_and_definitions(self.conn, factor_order)
        run_id = mr.get_or_create_run(
            self.conn, factor_order, self.scaling, estimated_at=estimated_at
        )
        self.log.info(
            "model_run 就绪 run_id=%s factors=%d calibrated=%s",
            run_id,
            len(factor_order),
            self.scaling.calibrated,
        )
        return self._empty()


class ExposureImporter(_DatayesImporter):
    """因子暴露 X → factor.exposure。"""

    DATASET = "exposure"
    DATASET_RAW = "exposure_cne6_sw21"
    CONTRACT = contracts.EXPOSURE
    NOT_NULL_COLUMNS = ("run_id", "instrument_id", "trading_day", "exposure")
    ARRAY_COLUMNS = ("exposure",)

    def build(self) -> pd.DataFrame:
        raw = self._raw()
        if raw.empty:
            self.log.warning("%s 无 raw 数据", self.DATASET_RAW)
            return self._empty()

        run_id, factor_order = self._run_and_order(raw)
        df = self._attach_instrument_ids(raw)
        if df.empty:
            return self._empty()

        values = fx.reindex_wide(df, factor_order)
        self._check_industry_dummies(df, factor_order, values)

        return pd.DataFrame(
            {
                "run_id": run_id,
                "instrument_id": df["instrument_id"].astype("int64").to_numpy(),
                "trading_day": _trading_day(df).to_numpy(),
                "exposure": [row.tolist() for row in values],
                "factor_count": len(factor_order),
                "available_at": _available_at(df).to_numpy(),
            }
        )

    def _check_industry_dummies(
        self, df: pd.DataFrame, factor_order: list[str], values: np.ndarray
    ) -> None:
        """行业哑变量每行恰有一个 1，且 COUNTRY 恒为 1。

        这是**列序是否对齐的最强证据**：一旦因子错位，行业列里会混进风格因子的
        z-score，行和立刻就不是 1 了。所以不做「取最大值」这类兜底 —— 那正好会
        把错位掩盖过去。
        """
        ind_idx = [i for i, f in enumerate(factor_order) if fx.FACTOR_TYPE[f] == "industry"]
        if ind_idx:
            row_sum = np.nan_to_num(values[:, ind_idx], nan=0.0).sum(axis=1)
            bad = ~np.isclose(row_sum, 1.0)
            if bad.any():
                raise ValueError(
                    f"{int(bad.sum())} 行的行业哑变量之和不为 1（样例和值 "
                    f"{row_sum[bad][:5].tolist()}）—— 通常意味着因子列错位或体系切换"
                )
        if fx.MARKET_FACTOR in factor_order:
            country = values[:, factor_order.index(fx.MARKET_FACTOR)]
            if not np.allclose(np.nan_to_num(country, nan=0.0), 1.0):
                raise ValueError("COUNTRY 因子并非恒为 1 —— 通常意味着因子列错位")


class FactorReturnImporter(_DatayesImporter):
    """因子收益 f → factor.factor_return。"""

    DATASET = "factor_return"
    DATASET_RAW = "factor_ret_cne6_sw21"
    CONTRACT = contracts.FACTOR_RETURN
    NOT_NULL_COLUMNS = ("run_id", "trading_day", "ret_vector")
    ARRAY_COLUMNS = ("ret_vector",)

    def build(self) -> pd.DataFrame:
        raw = self._raw()
        if raw.empty:
            self.log.warning("%s 无 raw 数据", self.DATASET_RAW)
            return self._empty()

        run_id, factor_order = self._run_and_order(raw)
        values = fx.reindex_wide(raw, factor_order)
        out = pd.DataFrame(
            {
                "run_id": run_id,
                "trading_day": _trading_day(raw).to_numpy(),
                "ret_vector": [row.tolist() for row in values],
                "factor_count": len(factor_order),
                "available_at": _available_at(raw).to_numpy(),
            }
        )
        return out.drop_duplicates(subset=["trading_day"], keep="last").reset_index(drop=True)


class CovarianceImporter(_DatayesImporter):
    """因子协方差 F → factor.covariance（上三角展平）。"""

    DATASET = "covariance"
    DATASET_RAW = "factor_cov_cne6_sw21"
    CONTRACT = contracts.COVARIANCE
    NOT_NULL_COLUMNS = ("run_id", "trading_day", "cov_flat")
    ARRAY_COLUMNS = ("cov_flat",)

    #: 对称性容差：绝对 1e-9 或相对 1e-6，取大者。实测样本 max|C - Cᵀ| = 0.0，
    #: 所以设紧是安全的；放松了就等于不检查。
    SYMMETRY_ATOL = 1e-9
    SYMMETRY_RTOL = 1e-6

    def build(self) -> pd.DataFrame:
        raw = self._raw()
        if raw.empty:
            self.log.warning("%s 无 raw 数据", self.DATASET_RAW)
            return self._empty()

        run_id, factor_order = self._run_and_order(raw)
        df = raw.copy()
        df["_day"] = _trading_day(df)
        df["_avail"] = _available_at(df).to_numpy()
        # 行标签（factorName）也要经 canonical 归一：它用的是原大小写，
        # 而列名是全大写，直接比会一个都对不上。
        df["_factor"] = _require_column(df, "factorName", "FACTOR_NAME").map(fx.canonical)

        rows = []
        for day, group in df.groupby("_day", sort=True):
            matrix = self._matrix_for_day(group, factor_order, day)
            rows.append(
                {
                    "run_id": run_id,
                    "trading_day": day,
                    "cov_flat": fx.upper_triangle(matrix).tolist(),
                    "factor_count": len(factor_order),
                    "available_at": group["_avail"].max(),
                }
            )
        return pd.DataFrame(rows, columns=list(self.contract.columns))

    def _matrix_for_day(self, group: pd.DataFrame, factor_order: list[str], day) -> np.ndarray:
        labels = list(group["_factor"])
        if set(labels) != set(factor_order):
            raise ValueError(
                f"{day} 的协方差行标签集合与因子集合不一致："
                f"多 {sorted(set(labels) - set(factor_order))}，"
                f"少 {sorted(set(factor_order) - set(labels))}"
            )
        # 先按行标签排成 factor_order 的顺序，再按 factor_order 取列 ——
        # 行和列**分别**重排，因为源数据的行序与列序本来就不一样。
        ordered = group.set_index("_factor").loc[factor_order].reset_index()
        matrix = fx.reindex_wide(ordered, factor_order)

        if not np.isfinite(matrix).all():
            raise ValueError(f"{day} 的协方差含 NaN/Inf")
        tol = np.maximum(self.SYMMETRY_ATOL, self.SYMMETRY_RTOL * np.abs(matrix))
        if not (np.abs(matrix - matrix.T) <= tol).all():
            raise ValueError(
                f"{day} 的协方差矩阵不对称，最大偏差 {np.abs(matrix - matrix.T).max()}"
            )
        diag = np.diag(matrix)
        if (diag <= 0).any():
            raise ValueError(f"{day} 的协方差对角元存在非正值，最小 {diag.min()}")

        # 半正定是**软**校验：轻微负特征值可能只是估计噪声，中断整批代价过大。
        eigmin = float(np.linalg.eigvalsh(matrix).min())
        if eigmin < -1e-8 * float(np.trace(matrix)):
            self.log.warning("%s 的协方差最小特征值 %.6g < 0，非半正定", day, eigmin)
            self._record_dq(
                "datayes_covariance_not_psd",
                "warn",
                {"trading_day": str(day), "min_eigenvalue": eigmin},
            )
        return matrix


class SpecificRiskImporter(_DatayesImporter):
    """特质风险 SRISK → factor.specific_risk（**平方成方差**）。"""

    DATASET = "specific_risk"
    DATASET_RAW = "srisk_cne6_sw21"
    CONTRACT = contracts.SPECIFIC_RISK
    NOT_NULL_COLUMNS = ("run_id", "instrument_id", "trading_day", "specific_var")

    def build(self) -> pd.DataFrame:
        raw = self._raw()
        if raw.empty:
            self.log.warning("%s 无 raw 数据", self.DATASET_RAW)
            return self._empty()

        run_id, _ = self._run_and_order_lenient(raw)
        df = self._attach_instrument_ids(raw)
        if df.empty:
            return self._empty()

        srisk = pd.to_numeric(_require_column(df, "SRISK"), errors="coerce")
        if srisk.isna().any():
            raise ValueError(f"SRISK 含 {int(srisk.isna().sum())} 行无法解析的值")

        # 供应商给的是年化百分比**波动率 σ**，目标列存的是**方差**。
        # 配置里 srisk_is_variance=true 时说明供应商改了口径，此时不再平方。
        var = srisk if self.scaling.srisk_is_variance else srisk**2
        if (var < 0).any():
            raise ValueError("specific_var 出现负值")

        # SRISK == 0 的语义未定（停牌股？），不静默剔除也不插值，只记录。
        zeros = int((srisk == 0).sum())
        if zeros:
            self.log.warning("%d 行 SRISK 为 0，语义待供应商确认，已原样入库", zeros)
            self._record_dq("datayes_srisk_zero", "info", {"rows": zeros})

        out = pd.DataFrame(
            {
                "run_id": run_id,
                "instrument_id": df["instrument_id"].astype("int64").to_numpy(),
                "trading_day": _trading_day(df).to_numpy(),
                "specific_var": var.astype("float64").to_numpy(),
                "source": PROVIDER,
                "available_at": _available_at(df).to_numpy(),
            }
        )
        return out.drop_duplicates(
            subset=["instrument_id", "trading_day"], keep="last"
        ).reset_index(drop=True)

    def _run_and_order_lenient(self, df: pd.DataFrame) -> tuple[Any, list[str]]:
        """窄表（只有 SRISK / SPRET 一列）没有因子列，无法复核因子集，只取 run_id。"""
        run_id, factor_order, _ = mr.load_run(self.conn)
        return run_id, list(factor_order)


class SpecificReturnImporter(SpecificRiskImporter):
    """特质收益 SPRET → factor.specific_return（百分比，原样入库）。"""

    DATASET = "specific_return"
    DATASET_RAW = "specific_ret_cne6_sw21"
    CONTRACT = contracts.SPECIFIC_RETURN
    NOT_NULL_COLUMNS = ("run_id", "instrument_id", "trading_day", "specific_ret")

    def build(self) -> pd.DataFrame:
        raw = self._raw()
        if raw.empty:
            self.log.warning("%s 无 raw 数据", self.DATASET_RAW)
            return self._empty()

        run_id, _ = self._run_and_order_lenient(raw)
        df = self._attach_instrument_ids(raw)
        if df.empty:
            return self._empty()

        spret = pd.to_numeric(_require_column(df, "SPRET"), errors="coerce")
        if spret.isna().any():
            raise ValueError(f"SPRET 含 {int(spret.isna().sum())} 行无法解析的值")

        out = pd.DataFrame(
            {
                "run_id": run_id,
                "instrument_id": df["instrument_id"].astype("int64").to_numpy(),
                "trading_day": _trading_day(df).to_numpy(),
                # 百分比日频，原样入库（与 factor_return 的小数不同量纲，
                # 联用时 r = 100 * X·f + u，换算在计算层做，不在这里）
                "specific_ret": spret.astype("float64").to_numpy(),
                "available_at": _available_at(df).to_numpy(),
            }
        )
        return out.drop_duplicates(
            subset=["instrument_id", "trading_day"], keep="last"
        ).reset_index(drop=True)


__all__ = [
    "CovarianceImporter",
    "DatayesSymbolMapImporter",
    "ExposureImporter",
    "FactorReturnImporter",
    "ModelRunImporter",
    "SpecificReturnImporter",
    "SpecificRiskImporter",
]
