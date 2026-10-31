"""Tushare ingest importers：股票 / 指数 / 期货日线。

单位换算（Tushare 原始单位 → 目标表单位），**逐接口不同，不可套用**：

| 接口 | vol | amount |
|---|---|---|
| ``daily`` / ``index_daily`` | 手 → 股（×100） | 千元 → 元（×1000）|
| ``fut_daily``              | 手（保持）      | 万元 → 元（×10000）|

期货的 ``vol`` / ``oi`` 保持「手」——折算成基础单位需要合约乘数，
那属于下游的口径，接入层不做猜测。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from gr_data.common import contracts
from gr_data.common.quality import RowValidationError
from gr_data.common.trading_status import event_flags, resolve_trading_status
from gr_data.ingest import pit
from gr_data.ingest.base import BaseImporter, IngestGateError
from gr_data.ingest.resolve import resolve_by_symbol_map
from gr_data.ingest.tushare.adapter import TushareAdapter
from gr_data.ingest.tushare.bj_pending import BJPendingImporter
from gr_data.ingest.tushare.importers.reference import _require, parse_date
from gr_data.ingest.tushare.symbols import collapse_alias_rows, expand_stock_auxiliary_aliases
from gr_data.raw.tushare.quote_rules import tas_code_mask
from gr_data.raw.tushare.suspension_store import read_coverage


PROVIDER = "tushare"


class _SymbolResolutionError(IngestGateError, RowValidationError):
    """保留未知标的的既有门禁类型，同时允许识别 BJ 行级失败。"""


# daily 与 stk_limit 各自返回 pre_close，四舍五入口径可能差一分钱。
# 超出该容差说明两者的价格基准不一致，此时涨跌停价不可信。
PRE_CLOSE_TOLERANCE = 0.011

# stk_limit 用哨兵值表示「当日不设涨跌幅」（如新股上市初期），不是价格。
# 依据 2026-09 真实样本 63 行：北交所 99999.99/0.0，沪市 99999.999/0.01，深市 999999.999/0.01。
# 两侧同时满足才认定；历史回补时须复核更早年份是否使用其他取值（D-024）。
NO_LIMIT_UP_MIN = 99999.0
NO_LIMIT_DOWN_MAX = 0.01


def _to_numeric_strict(df: pd.DataFrame, columns: list[str], source: str) -> None:
    """转数值并区分两种空：源值本身缺失保留 NULL，有值但解析失败硬失败。

    ``pd.to_numeric(errors="coerce")`` 会把非法字符串变成 NaN：可选列经 UPSERT 以 NULL 覆盖
    库内已有值，指数／期货价格被当成「源未发布」，质量门禁都看不出来。``inf`` 能被解析，
    仍交给各列原有的非有限值规则处理。
    """
    for c in columns:
        present = df[c].notna() & df[c].astype(str).str.strip().ne("")
        parsed = pd.to_numeric(df[c], errors="coerce")
        bad = present & parsed.isna()
        if bad.any():
            samples = df.loc[bad, c].head(5).tolist()
            raise RowValidationError(
                f"{source}.{c} 含无法解析的数值 rows={int(bad.sum())} samples={samples}"
            )
        df[c] = parsed


def _to_bigint(series: pd.Series) -> pd.Series:
    """转成可空整数。

    目标表的 ``volume`` / ``open_interest`` 是 BIGINT，而 Tushare 返回浮点，
    直接 COPY 会因为 "100000.0" 无法转 bigint 而报错。
    这些量本身是整数语义（股数 / 手数），四舍五入是安全的。
    """
    return series.round().astype("Int64")


def _null_out_invalid(df: pd.DataFrame, columns: list[str]) -> None:
    """把**无效**价格就地置为 NaN（→ 入库为 NULL）。

    无效 = 非有限值（NaN / inf）或负数。**0 是有效取值，原样保留**——
    它表达的是「当日就是这个数」，不是「不知道」，两者不能混为一谈。

    指数与期货的目标表允许价格列为 NULL，所以缺失如实写 NULL，
    而不是把整行丢掉——那会连同该行**有效**的收盘价 / 结算价 / 持仓量一起损失。
    """
    for c in columns:
        v = pd.to_numeric(df[c], errors="coerce")
        arr = v.to_numpy(dtype=float)
        df[c] = v.where(np.isfinite(arr) & (arr >= 0), other=np.nan)


def _check_high_low(df: pd.DataFrame, source: str) -> None:
    """只在 high / low 同时存在时校验，与 DDL 的 CHECK 口径一致。"""
    both = df["high"].notna() & df["low"].notna()
    if (df.loc[both, "high"] < df.loc[both, "low"]).any():
        raise ValueError(f"{source} 含 high < low 的记录")


def _parse_trade_date(df: pd.DataFrame, source: str) -> pd.Series:
    parsed = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    if parsed.isna().any():
        raise RowValidationError(f"{source} 含非法 trade_date")
    return parsed.dt.date


def _daily_rows(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    """先归一代码与 int8／字符串日期，再按业务键保留最后一行。"""
    out = raw.copy()
    if out["ts_code"].isna().any():
        raise RowValidationError(f"{source} 含空 ts_code")
    out["ts_code"] = out["ts_code"].astype(str).str.strip()
    if out["ts_code"].eq("").any():
        raise RowValidationError(f"{source} 含空 ts_code")
    out["trade_date"] = _parse_trade_date(out, source)
    return out.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")


def _validate_activity(raw: pd.DataFrame, columns: list[str], source: str) -> None:
    """允许缺失；已有值必须是有限非负数，不能静默写成 NULL。"""
    for column in columns:
        numeric = pd.to_numeric(raw[column], errors="coerce")
        invalid = raw[column].notna() & (numeric.isna() | ~np.isfinite(numeric) | numeric.lt(0))
        if invalid.any():
            raise RowValidationError(
                f"{source} invalid activity column={column} rows={int(invalid.sum())}"
            )


def _amount_in_yuan(series: pd.Series, multiplier: int) -> pd.Series:
    """使用十进制换算源金额单位；缺失保留 NULL，不累计二进制浮点误差。"""
    return series.map(lambda v: None if pd.isna(v) else Decimal(str(v)) * multiplier)


class _SymbolResolvingImporter(BaseImporter):
    """把 ``ts_code`` 解析成 ``instrument_id`` 的公共部分。

    行情 importer 与参考 importer（valuation_1d / adj_factor_ts）都要做这件事，
    且「未登记标的必须可见地跳过」这条纪律对两者一样重要，所以提到一处。
    """

    PROVIDER = PROVIDER
    STRICT_QUALITY = True

    def _adapter(self) -> TushareAdapter:
        # 同一 importer 共用一个适配器，残留文件等软告警才能汇总到运行结果。
        if getattr(self, "_tushare_adapter", None) is None:
            self._tushare_adapter = TushareAdapter(self.paths, self.ctx.months)
        return self._tushare_adapter

    def collect_soft_warnings(self) -> list[str]:
        adapter = getattr(self, "_tushare_adapter", None)
        notices = adapter.notices if adapter is not None else []
        return [*super().collect_soft_warnings(), *notices]

    def _read_selected(self, dataset: str, required: frozenset[str] = frozenset()) -> pd.DataFrame:
        """读取本次所选月份；所选月份缺分区即硬失败。

        ``required`` 按分区逐个校验：拼接后再查会被列齐全的月份掩盖，缺列月份的行
        在 concat 后成为 NaN，经 UPSERT 覆盖库内已有值。
        """
        adapter = self._adapter()
        frames = []
        for ym in adapter.selected_months(dataset):
            df = adapter.read_month(dataset, ym)
            if df is None or df.empty:
                continue
            _require(df, set(required), f"{dataset}[{ym}]")
            frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0, ignore_index=True)

    def _id_map(self) -> dict[str, int]:
        return resolve_by_symbol_map(self.conn, PROVIDER)

    def _attach_ids(self, df: pd.DataFrame, id_map: dict[str, int]) -> pd.DataFrame:
        """按 symbol_map 解析 instrument_id；存在未登记标的即硬失败。

        instrument_id 是外键，未登记的标的写不进去；丢掉这些行又会伪装成
        「这段时间没数据」。所以整批拒绝，先补 instruments + symbol_map 再导入。
        """
        df = df.copy()
        df["instrument_id"] = df["ts_code"].map(id_map)
        unknown = df["instrument_id"].isna()
        if unknown.any():
            codes = sorted(set(df.loc[unknown, "ts_code"]))
            raise _SymbolResolutionError(
                f"{self.DATASET}: {int(unknown.sum())} rows ({len(codes)} symbols) are not in "
                f"meta.symbol_map, samples {codes[:5]}; run instruments and symbol_map first"
            )
        day = "trading_day" if "trading_day" in df else "dt"
        if day in df and df.duplicated(["instrument_id", day]).any():
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT instrument_id, symbol FROM meta.instruments WHERE asset='stock'"
                )
                canonical = dict(cur.fetchall())
            try:
                df = collapse_alias_rows(
                    df.reset_index(drop=True),
                    canonical,
                    price_evidence=self._alias_price_evidence(df, canonical),
                    audit=self._audit_alias_override,
                )
            except ValueError as exc:
                raise RowValidationError(str(exc)) from exc
        return df

    def _audit_alias_override(self, detail: Mapping[str, object]) -> None:
        """覆盖审计与本 importer 的业务 UPSERT 同事务提交或回滚。"""
        payload = {"provider": PROVIDER, "dataset": self.DATASET, **detail}
        self.conn.execute(
            "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES (%s,%s,%s)",
            (
                "tushare_stock_alias_metadata_override",
                "info",
                json.dumps(payload, ensure_ascii=False, allow_nan=False),
            ),
        )
        self.log.info(
            "Alias metadata reconciliation validated day=%s field=%s old_code=%s "
            "canonical_code=%s old_value=%s new_value=%s rule=%s",
            detail["trading_day"],
            detail["field"],
            detail["old_code"],
            detail["canonical_code"],
            detail["old_value"],
            detail["new_value"],
            detail["processing_rule"],
        )

    def _alias_price_evidence(
        self, frame: pd.DataFrame, canonical: Mapping[int, str]
    ) -> dict[tuple[int, date], Mapping[str, object]]:
        """只为新授权的涨跌状态冲突读取源 OHLC 与限价，不使用估算限价。"""
        if self.DATASET != "valuation_1d" or "limit_status" not in frame:
            return {}
        relevant = frame.loc[
            frame["ts_code"].isin(["000022.SZ", "001872.SZ", "000043.SZ", "001914.SZ"])
        ]
        groups = []
        for key, group in relevant.groupby(["instrument_id", "trading_day"], sort=False):
            if group["limit_status"].nunique(dropna=False) <= 1:
                continue
            preferred_code = canonical.get(int(str(key[0])))
            if preferred_code is None:
                continue
            current = group.loc[group["ts_code"].eq(preferred_code)]
            if len(current) != 1 or pd.isna(current.iloc[0]["limit_status"]):
                continue
            if Decimal(str(current.iloc[0]["limit_status"])).is_finite():
                groups.append((key, group))
        if not groups:
            return {}
        adapter = self._adapter()
        months = sorted({pd.Timestamp(str(key[1])).strftime("%Y-%m") for key, _ in groups})
        observations = {}
        codes = set(relevant["ts_code"])
        for dataset in ("daily", "stk_limit"):
            adapter.require_months(dataset, months)
            raw = _daily_rows(adapter.read_all_months(dataset), dataset)
            observations[dataset] = raw.loc[raw["ts_code"].isin(codes)]
        daily, limits = observations["daily"], observations["stk_limit"]

        def unique_value(series: pd.Series, field: str) -> Decimal:
            if series.empty or series.isna().any():
                raise ValueError(f"Missing alias price evidence field={field}")
            values = {Decimal(str(value)) for value in series}
            if len(values) != 1 or not all(value.is_finite() for value in values):
                raise ValueError(f"Conflicting alias price evidence field={field}")
            return next(iter(values))

        result = {}
        for key, group in groups:
            day = pd.Timestamp(str(key[1])).date()
            quotes = daily.loc[
                daily["trade_date"].eq(day) & daily["ts_code"].isin(group["ts_code"])
            ]
            bounds = limits.loc[
                limits["trade_date"].eq(day) & limits["ts_code"].isin(group["ts_code"])
            ]
            evidence = {
                name: unique_value(quotes[name], name)
                for name in ("open", "high", "low", "close", "pre_close")
            }
            evidence.update(
                limit_up=unique_value(bounds["up_limit"], "limit_up"),
                limit_down=unique_value(bounds["down_limit"], "limit_down"),
            )
            if (
                "close" not in group
                or unique_value(group["close"], "daily_basic.close") != evidence["close"]
            ):
                raise ValueError("Alias daily_basic close differs from daily price evidence")
            if "pre_close" in bounds:
                observed = bounds["pre_close"].dropna()
                if any(
                    abs(Decimal(str(value)) - evidence["pre_close"]) > Decimal("0.011")
                    for value in observed
                ):
                    raise ValueError("Alias price limits use a different pre_close")
            result[(int(str(key[0])), day)] = evidence
        return result


class _BaseBarsImporter(_SymbolResolvingImporter):
    NOT_NULL_COLUMNS = ("instrument_id", "dt", "trading_day")
    PRICE_COLUMNS = ("open", "high", "low", "close", "pre_close")

    #: 允许缺失的价格列。``pre_close`` 是唯一一个：标的**首个交易日**没有前收盘，
    #: 这是真实语义而不是数据损坏。实测全量 2013-01~2026-08 共 12,806,285 行，
    #: 236 行 pre_close 为空（0.0018%），全部是北交所标的，且**每一行都恰好落在
    #: 该标的在全量数据里的首个交易日**，一标的一行；open/high/low/close 无一为空。
    #: 其余四列缺失仍然中断 —— 当日有 bar 却没有成交价，那就是数据损坏。
    OPTIONAL_PRICE_COLUMNS = ("pre_close",)

    def _validate_prices(self, df: pd.DataFrame, source: str) -> None:
        """严格校验：价格非正即抛错；除 ``pre_close`` 外缺失也抛错。

        只用于**股票**。指数与期货不同 —— 它们的价格缺失是常态（只发布收盘点位的
        指数、无成交但有结算价的合约），那边走 ``_null_out_invalid``。

        ``pre_close`` 缺失时留 NULL 并记 `ops.data_quality_check`：它是首日上市的
        固有属性，用 ``close`` 或 0 兜底会让当日涨跌幅凭空变成 0% 或 −100%。
        注意**非正**的 pre_close 仍然是错误 —— 那不是「没有」，是「有但不可能」。
        """
        required = [c for c in self.PRICE_COLUMNS if c not in self.OPTIONAL_PRICE_COLUMNS]
        if not np.isfinite(df[required].to_numpy(dtype=float)).all():
            raise RowValidationError(f"{source} 含非有限价格（{'/'.join(required)}）")

        values = df[list(self.PRICE_COLUMNS)].to_numpy(dtype=float)
        if np.isinf(values).any():
            raise RowValidationError(f"{source} 含非有限价格")
        # nan_to_num 只是为了让缺失值不参与「非正」判定，不改动任何入库值
        if (np.nan_to_num(values, nan=1.0) <= 0).any():
            raise RowValidationError(f"{source} 含非正价格")
        if (df["high"] < df["low"]).any():
            raise RowValidationError(f"{source} 含 high < low 的记录")

        for col in self.OPTIONAL_PRICE_COLUMNS:
            missing = int((~np.isfinite(df[col].to_numpy(dtype=float))).sum())
            if missing:
                self.log.warning("%s 有 %d 行缺少 %s（首日上市），留 NULL", source, missing, col)
                self._record_missing_price(source, col, missing)

    def _record_missing_price(self, source: str, column: str, rows: int) -> None:
        """留痕：缺失是「继续跑但结果不完整」，日志一闪而过，只有落库才追得回来。"""
        if self.conn is None:  # 单测里不带连接
            return
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.data_quality_check (rule, severity, detail) VALUES (%s, %s, %s)",
                (
                    f"tushare_{source}_missing_{column}",
                    "info",
                    json.dumps(
                        {"rows": rows, "reason": "标的首个交易日无前收盘，属真实语义"},
                        ensure_ascii=False,
                    ),
                ),
            )


class StockBars1dImporter(BJPendingImporter, _BaseBarsImporter):
    """daily + adj_factor + stk_limit + suspend_d → market.stock_bar_1d。"""

    DATASET = "stock_bar_1d"
    CONTRACT = contracts.bar_1d("stock")

    BJ_SOURCE_DATASET = "daily"

    def _build_strict(self) -> pd.DataFrame:
        adapter = self._adapter()
        months = adapter.selected_months("daily")
        # 复权因子与涨跌停按月与日线配套；缺整月不能静默写 NULL 覆盖库内已有值。
        for companion in ("adj_factor", "stk_limit"):
            adapter.require_months(companion, months)
        daily = adapter.read_all_months("daily")
        if daily.empty:
            return pd.DataFrame(columns=list(self.contract.columns))

        _require(
            daily,
            {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"},
            "daily",
        )
        market = _daily_rows(daily, "daily")

        market = self._merge_adj_factor(market, adapter)
        if market.empty:
            return pd.DataFrame(columns=list(self.contract.columns))

        _to_numeric_strict(
            market, ["open", "high", "low", "close", "pre_close", "vol", "amount"], "daily"
        )
        self._validate_prices(market, "daily")
        flow = market[["vol", "amount"]].to_numpy(dtype=float)
        # 缺失或非数值（coerce 后为 NaN）不能静默写成 NULL：无成交应是 0，不是「不知道」。
        if not np.isfinite(flow).all():
            raise RowValidationError("daily 含缺失、非数值或非有限的成交量或成交额")
        if (flow < 0).any():
            raise RowValidationError("daily 含负成交量或成交额")

        market["dt"] = market["trade_date"]
        market = self._merge_limits(market, adapter)
        market = self._attach_ids(market, self._id_map())
        trading_status = self._trading_status(market, months)

        out = pd.DataFrame(
            {
                "instrument_id": market["instrument_id"].astype("int64"),
                "dt": market["dt"],
                "trading_day": market["dt"],
                "open": market["open"],
                "high": market["high"],
                "low": market["low"],
                "close": market["close"],
                "pre_close": market["pre_close"],
                "volume": _to_bigint(market["vol"] * 100.0),  # 手 → 股
                "amount": market["amount"] * 1000.0,  # 千元 → 元
                "limit_up": market["limit_up"],
                "limit_down": market["limit_down"],
                "trading_status": trading_status,
                "adj_factor": market["adj_factor"],
                "source": PROVIDER,
                "price_limit_status": market["price_limit_status"],
            }
        )
        return out[list(self.contract.columns)].reset_index(drop=True)

    def _merge_adj_factor(self, market: pd.DataFrame, adapter: TushareAdapter) -> pd.DataFrame:
        """合并复权因子。

        BJ 失败转待处理，其他缺失直接抛错；不用默认值 1 兜底——``adj_factor`` 在目标表是 NOT NULL，
        用 1 冒充「未知」会让下游的前复权价格静默算错。
        """
        adj = adapter.read_all_months("adj_factor")
        if adj.empty:
            raise ValueError("缺少 adj_factor raw 数据；股票日线必须带复权因子")
        _require(adj, {"ts_code", "trade_date", "adj_factor"}, "adj_factor")
        adj = expand_stock_auxiliary_aliases(_daily_rows(adj, "adj_factor"))[
            ["ts_code", "trade_date", "adj_factor"]
        ]
        merged = market.merge(adj, on=["ts_code", "trade_date"], how="left", validate="one_to_one")
        missing = int(merged["adj_factor"].isna().sum())
        if missing:
            raise RowValidationError(f"daily 有 {missing} 行缺少 adj_factor")
        merged["adj_factor"] = pd.to_numeric(merged["adj_factor"], errors="coerce")
        if not np.isfinite(merged["adj_factor"].to_numpy(dtype=float)).all():
            raise RowValidationError("adj_factor 含非有限值")
        if (merged["adj_factor"] <= 0).any():
            raise RowValidationError("adj_factor 含非正值")
        return merged

    def _merge_limits(self, market: pd.DataFrame, adapter: TushareAdapter) -> pd.DataFrame:
        """合并涨跌停价并标 ``price_limit_status``（045，D-024）。

        - 哨兵值（当日不设涨跌幅）：写 NULL，状态 ``NO_LIMIT``，不计软告警。
        - 有效涨跌停价：``LIMITED``。
        - 缺行、非法、pre_close 对不上（价格基准不同，涨跌停不可信）：``UNKNOWN``，记软告警；
          首日上市无前收盘且无可用涨跌停价的行例外，只记 info，不按上市规则推断为 NO_LIMIT。

        ``limit_up`` / ``limit_down`` 在目标表可为 NULL，以上情形都不阻断整批入库。
        """
        dp = market["pre_close"].to_numpy(dtype=float)
        # 首日上市无前收盘（_validate_prices 已记 info 与 data_quality_check）；
        # 不计入软告警，否则常规全量导入几乎必然退出码 3。
        first_day = ~np.isfinite(dp)
        limits = adapter.read_all_months("stk_limit")
        if limits.empty:
            # 分区存在（build 已校验）但为空：涨跌停整体缺失，留 NULL 并要求复核。
            count = len(market)
            if self._bj_scope and any(
                len(frame)
                for (dataset, _), frame in self._bj_sources.items()
                if dataset == "stk_limit"
            ):
                # BJ 子集无匹配限价不代表原分区为空；首日无前收的合法缺失仍保留。
                count = int((~first_day).sum())
            if count:
                self._soft(f"stk_limit partitions are empty; {count} rows keep NULL limits")
            market["limit_up"] = None
            market["limit_down"] = None
            market["price_limit_status"] = "UNKNOWN"
            return market

        _require(limits, {"ts_code", "trade_date", "up_limit", "down_limit"}, "stk_limit")
        lim = expand_stock_auxiliary_aliases(_daily_rows(limits, "stk_limit"))
        lim["has_limit_row"] = True
        keep = ["ts_code", "trade_date", "up_limit", "down_limit", "has_limit_row"]
        if "pre_close" in lim.columns:
            lim = lim.rename(columns={"pre_close": "limit_pre_close"})
            keep.append("limit_pre_close")
        merged = market.merge(
            lim[keep], on=["ts_code", "trade_date"], how="left", validate="one_to_one"
        )
        has_row = merged["has_limit_row"].eq(True).to_numpy()

        _to_numeric_strict(merged, ["up_limit", "down_limit"], "stk_limit")
        up = merged["up_limit"].to_numpy(dtype=float)
        down = merged["down_limit"].to_numpy(dtype=float)
        # 两侧同时满足才认定为哨兵；只有一边像哨兵时无法确认不设涨跌幅，按非法处理。
        with np.errstate(invalid="ignore"):
            no_limit = (
                has_row
                & np.isfinite(up)  # +Inf 是坏值，不是哨兵
                & (up >= NO_LIMIT_UP_MIN)
                & (down >= 0)
                & (down <= NO_LIMIT_DOWN_MAX)
            )
        merged.loc[no_limit, ["up_limit", "down_limit"]] = np.nan

        bad = ~no_limit & (
            np.isinf(merged[["up_limit", "down_limit"]].to_numpy(dtype=float)).any(axis=1)
            | (merged["up_limit"] <= 0).to_numpy()
            | (merged["down_limit"] <= 0).to_numpy()
            | (merged["up_limit"] < merged["down_limit"]).to_numpy()
            # 只有一边出现哨兵量级：既不能认定不设涨跌幅，也不是可信价格。
            | (merged["up_limit"] >= NO_LIMIT_UP_MIN).to_numpy()
            | (merged["down_limit"] <= NO_LIMIT_DOWN_MAX).to_numpy()
        )
        if bad.any():
            self._soft(f"invalid price limits set to NULL rows={int(bad.sum())}")
            merged.loc[bad, ["up_limit", "down_limit"]] = np.nan

        mismatch = np.zeros(len(merged), dtype=bool)
        if "limit_pre_close" in merged.columns:
            _to_numeric_strict(merged, ["limit_pre_close"], "stk_limit")
            lp = merged["limit_pre_close"].to_numpy(dtype=float)
            # 哨兵值不由前收盘推算，不参与比较。
            comparable = ~no_limit & np.isfinite(lp) & np.isfinite(dp)
            mismatch = comparable & ~np.isclose(dp, lp, atol=PRE_CLOSE_TOLERANCE, rtol=0)
            if mismatch.any():
                self._soft(
                    f"pre_close of daily and stk_limit differ on {int(mismatch.sum())} rows "
                    f"(tolerance {PRE_CLOSE_TOLERANCE:.3f}); their price limits set to NULL"
                )
                merged.loc[mismatch, ["up_limit", "down_limit"]] = np.nan

        both = merged["up_limit"].notna().to_numpy() & merged["down_limit"].notna().to_numpy()
        status = np.where(no_limit, "NO_LIMIT", np.where(both, "LIMITED", "UNKNOWN"))
        unknown = status == "UNKNOWN"
        missing = int((unknown & ~first_day).sum())
        if missing:
            self._soft(f"{missing} rows have no usable price limit and keep NULL")
        first_day_unknown = int((unknown & first_day).sum())
        if first_day_unknown:
            self.log.info(
                "First listing day rows keep NULL price limits rows=%d", first_day_unknown
            )
        if no_limit.any():
            self.log.info("Rows without price limit (vendor sentinel) rows=%d", int(no_limit.sum()))
            self._record_no_limit(int(no_limit.sum()))

        merged["limit_up"] = merged["up_limit"]
        merged["limit_down"] = merged["down_limit"]
        merged["price_limit_status"] = status
        # 诊断关联列已用于验证，不属于最终行情；避免缺失诊断值造成虚假的别名冲突。
        return merged.drop(columns=["has_limit_row", "limit_pre_close"], errors="ignore")

    def _record_no_limit(self, rows: int) -> None:
        """留痕：哨兵值写 NULL 属正常语义，但需要能追溯本次识别了多少行。"""
        if self.conn is None:  # 单测里不带连接
            return
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ops.data_quality_check (rule, severity, detail) VALUES (%s, %s, %s)",
                (
                    "tushare_stk_limit_no_limit_sentinel",
                    "info",
                    json.dumps(
                        {
                            "rows": rows,
                            "reason": "供应商哨兵值表示当日不设涨跌幅，"
                            "涨跌停价写 NULL，状态 NO_LIMIT",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

    def _trading_status(self, market: pd.DataFrame, months: list[str]) -> pd.Series:
        """只为实际存在的 bar 派生状态，证据只取库内事件与覆盖表；库内缺覆盖为 UNKNOWN。

        与 ``SuspensionImporter`` 刷新已有 bar、``load_stock_trading_status`` 读取
        共用同一份库内证据，避免 raw 与库各推一套状态（D-023）。
        """
        self._check_suspension_coverage(months)
        keys = ["instrument_id", "trading_day"]
        evidence = market[["instrument_id", "dt"]].rename(columns={"dt": "trading_day"})
        days = sorted(set(evidence["trading_day"]))
        events, covered = self._status_evidence(sorted(set(evidence["instrument_id"])), days)
        flags = ["full_suspend", "intraday_suspend", "resumed"]
        if events.empty:
            for col in flags:
                evidence[col] = False
        else:
            evidence = evidence.merge(event_flags(events, keys), on=keys, how="left")
        evidence["has_bar"] = True
        evidence["covered"] = evidence["trading_day"].isin(covered)
        result = resolve_trading_status(evidence.drop(columns=keys))
        return pd.Series(result.to_numpy(), index=market.index)

    def _check_suspension_coverage(self, months: list[str]) -> None:
        """raw 停复牌凭据与库内覆盖不一致时拒绝：说明 raw 已更新而库内事件未重导。

        raw 有有效凭据时，凭据内每个日期都必须在库内有相同哈希的覆盖，库内缺覆盖
        或哈希不同均硬失败。raw 缺分区或没有凭据（旧格式）时不比较，此时库内无覆盖的
        日期按 UNKNOWN 处理。
        """
        if self.conn is None:  # 离线单测不比较库内覆盖
            return
        for month in months:
            path = self.paths.dataset_file(PROVIDER, "suspend_d", month)
            if not path.exists():
                continue
            proof = read_coverage(path)
            if proof is None:
                continue
            days, _, digest = proof
            rows = self.conn.execute(
                "SELECT trading_day, raw_sha256 FROM market.stock_suspend_coverage "
                "WHERE source=%s AND trading_day=ANY(%s)",
                (PROVIDER, days),
            ).fetchall()
            stored = dict(rows)
            if any(stored.get(day) != digest for day in days):
                raise IngestGateError(
                    f"suspend_d raw coverage for {month} differs from the database; "
                    "run the suspend_d importer before stock_bar_1d"
                )

    def _status_evidence(self, instrument_ids: list[int], days: list) -> tuple[pd.DataFrame, set]:
        """读取库内停复牌事件与已覆盖交易日。"""
        if self.conn is None:  # 单测里不带连接：等同库内尚无覆盖
            return pd.DataFrame(), set()
        cur = self.conn.execute(
            "SELECT instrument_id, trading_day, suspend_type, suspend_timing "
            "FROM market.stock_suspend_event "
            "WHERE source=%s AND instrument_id=ANY(%s) AND trading_day=ANY(%s)",
            (PROVIDER, instrument_ids, days),
        )
        columns = ["instrument_id", "trading_day", "suspend_type", "suspend_timing"]
        events = pd.DataFrame(cur.fetchall(), columns=columns)
        covered = {
            row[0]
            for row in self.conn.execute(
                "SELECT trading_day FROM market.stock_suspend_coverage "
                "WHERE source=%s AND trading_day=ANY(%s)",
                (PROVIDER, days),
            ).fetchall()
        }
        return events, covered


class IndexBars1dImporter(_BaseBarsImporter):
    """index_daily → market.index_bar_1d。

    指数没有复权因子与涨跌停：``adj_factor`` 按表语义写 1（NOT NULL DEFAULT 1），
    涨跌停留 NULL。

    大量指数（中证债券指数、各类细分指数）**只发布收盘点位、不发布 OHLC**——
    实测某个交易日 10967 条里有 8859 条 open/high/low 为空，但 close 有效。
    目标表这些列均允许 NULL，因此缺失写 NULL、保留该行；只有连 close 都没有的
    记录才丢弃。
    """

    DATASET = "index_bar_1d"
    CONTRACT = contracts.bar_1d("index")

    def build(self) -> pd.DataFrame:
        required = {
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "vol",
            "amount",
        }
        raw = self._read_selected("index_daily", frozenset(required))
        if raw.empty:
            self.log.warning("index_daily 无 raw 数据")
            return pd.DataFrame(columns=list(self.contract.columns))

        _require(
            raw,
            {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"},
            "index_daily",
        )
        m = _daily_rows(raw, "index_daily")
        _validate_activity(m, ["vol", "amount"], "index_daily")
        amounts = _amount_in_yuan(m["amount"], 1000)
        _to_numeric_strict(
            m, ["open", "high", "low", "close", "pre_close", "vol", "amount"], "index_daily"
        )
        _null_out_invalid(m, list(self.PRICE_COLUMNS))

        usable = m["close"].notna()
        dropped = int((~usable).sum())
        if dropped:
            self._soft(f"index_daily skipped rows with invalid close: {dropped}")
            self.log.warning("index_daily 有 %d 行收盘价无效或缺失，已跳过", dropped)
        partial = int((usable & m["open"].isna()).sum())
        if partial:
            self.log.info("index_daily 有 %d 行只有收盘点位（无 OHLC），已按 NULL 入库", partial)
        m = m[usable]
        if m.empty:
            return pd.DataFrame(columns=list(self.contract.columns))
        _check_high_low(m, "index_daily")

        m["dt"] = _parse_trade_date(m, "index_daily")
        m = self._attach_ids(m, self._id_map())
        if m.empty:
            return pd.DataFrame(columns=list(self.contract.columns))

        out = pd.DataFrame(
            {
                "instrument_id": m["instrument_id"].astype("int64"),
                "dt": m["dt"],
                "trading_day": m["dt"],
                "open": m["open"],
                "high": m["high"],
                "low": m["low"],
                "close": m["close"],
                "pre_close": m["pre_close"],
                "volume": _to_bigint(m["vol"] * 100.0),  # 手 → 股
                "amount": amounts.loc[m.index],  # 千元 → 元
                "limit_up": None,
                "limit_down": None,
                "trading_status": "NORMAL",
                "adj_factor": 1.0,
                "source": PROVIDER,
            }
        )
        return out[list(self.contract.columns)].reset_index(drop=True)


class FutureBars1dImporter(_BaseBarsImporter):
    """fut_daily → market.future_bar_1d。

    期货表无 ``adj_factor``，改有 ``open_interest`` / ``settle`` / ``pre_settle``。

    当日无成交的合约不返回 OHLC，但**仍会发布结算价与持仓量**（实测某交易日
    940 条里 154 条如此，且全部带有效 settle）。因此价格缺失写 NULL、保留该行；
    只有 close 与 settle 都无效的记录才丢弃。成交量 / 持仓量为 0 是真实取值，原样保留。

    原油 TAS（SCTAS）的 OHLC／前收是相对结算价的价差，settle 却是绝对价（D-025）。
    目标表没有价差语义，混写会让同一行出现两种价格尺度；在单独映射定案前整行排除，
    计软告警并保留 raw，不把负价差改成 NULL、也不把正价差当绝对价入库。
    """

    DATASET = "future_bar_1d"
    CONTRACT = contracts.bar_1d("future")

    def build(self) -> pd.DataFrame:
        required = {
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "pre_settle",
            "settle",
            "vol",
            "amount",
            "oi",
        }
        raw = self._read_selected("fut_daily", frozenset(required))
        if raw.empty:
            self.log.warning("fut_daily 无 raw 数据")
            return pd.DataFrame(columns=list(self.contract.columns))

        _require(
            raw,
            {
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "pre_settle",
                "settle",
                "vol",
                "amount",
                "oi",
            },
            "fut_daily",
        )
        m = _daily_rows(raw, "fut_daily")
        tas = tas_code_mask(m["ts_code"])
        if tas.any():
            excluded = int(tas.sum())
            codes = sorted(set(m.loc[tas, "ts_code"]))
            self._soft(
                f"fut_daily excluded TAS spread rows pending separate mapping (D-025): {excluded}"
            )
            self.log.warning(
                "fut_daily excluded TAS spread rows rows=%d symbols=%d samples=%s",
                excluded,
                len(codes),
                codes[:5],
            )
            m = m.loc[~tas]
            if m.empty:
                return pd.DataFrame(columns=list(self.contract.columns))
        _validate_activity(m, ["vol", "amount", "oi"], "fut_daily")
        amounts = _amount_in_yuan(m["amount"], 10000)
        for column in ("vol", "oi"):
            values = pd.to_numeric(m[column], errors="coerce")
            if (values.dropna() % 1 != 0).any():
                raise ValueError(f"fut_daily noninteger contracts column={column}")
        _to_numeric_strict(
            m,
            [
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "pre_settle",
                "settle",
                "vol",
                "amount",
                "oi",
            ],
            "fut_daily",
        )
        _null_out_invalid(m, [*self.PRICE_COLUMNS, "settle", "pre_settle"])

        usable = m["close"].notna() | m["settle"].notna()
        dropped = int((~usable).sum())
        if dropped:
            self._soft(f"fut_daily skipped rows with invalid close and settle: {dropped}")
            self.log.warning("fut_daily 有 %d 行收盘价与结算价均无效或缺失，已跳过", dropped)
        settle_only = int((usable & m["close"].isna()).sum())
        if settle_only:
            self.log.info("fut_daily 有 %d 行当日无成交，仅结算价入库", settle_only)
        m = m[usable]
        if m.empty:
            return pd.DataFrame(columns=list(self.contract.columns))
        _check_high_low(m, "fut_daily")
        if (m[["vol", "amount", "oi"]].fillna(0).to_numpy(dtype=float) < 0).any():
            raise ValueError("fut_daily 含负成交量、成交额或持仓量")

        m["dt"] = _parse_trade_date(m, "fut_daily")
        m = self._attach_ids(m, self._id_map())
        if m.empty:
            return pd.DataFrame(columns=list(self.contract.columns))

        out = pd.DataFrame(
            {
                "instrument_id": m["instrument_id"].astype("int64"),
                "dt": m["dt"],
                "trading_day": m["dt"],
                "open": m["open"],
                "high": m["high"],
                "low": m["low"],
                "close": m["close"],
                "pre_close": m["pre_close"],
                "volume": _to_bigint(m["vol"]),  # 手（保持原单位）
                "amount": amounts.loc[m.index],  # 万元 → 元
                "open_interest": _to_bigint(m["oi"]),  # 手（保持原单位）
                "settle": m["settle"],
                "pre_settle": m["pre_settle"],
                "limit_up": None,
                "limit_down": None,
                "trading_status": "NORMAL",
                "source": PROVIDER,
            }
        )
        return out[list(self.contract.columns)].reset_index(drop=True)


#: daily_basic 源字段 → valuation_1d 列的换算倍率。未列出的字段原值入库。
_DAILY_BASIC_SCALE = {
    # 万元 → 元
    "total_mv": 10000.0,
    "circ_mv": 10000.0,
    # 万股 → 股
    "total_share": 10000.0,
    "float_share": 10000.0,
    "free_share": 10000.0,
}


class ValuationImporter(BJPendingImporter, _SymbolResolvingImporter):
    """daily_basic → fundamental.valuation_1d（每日估值、股本与换手快照，G3）。

    这是 daily_basic 在库内**唯一**的落点，源字段一个只落一处；完整源行留在 raw
    parquet，库内不再用 JSONB 复制。单位与口径在这里一次归一，下游不再临时乘除：

    | tushare | 目标列 | 换算 |
    |---|---|---|
    | ``total_mv`` / ``circ_mv`` | 同名 | 万元 → 元（×10000）|
    | ``total_share`` / ``float_share`` / ``free_share`` | 同名 | 万股 → 股（×10000）|
    | ``pe`` / ``pe_ttm`` / ``pb`` / ``ps`` / ``ps_ttm`` / ``volume_ratio`` | 同名 | 无量纲，原样 |
    | ``dv_ratio`` / ``dv_ttm`` / ``turnover_rate(_f)`` | 同名 | 百分数原值，**不除以 100** |
    | ``limit_status`` | 同名 | 0–6 枚举原值 |

    亏损股的 ``pe`` / ``pe_ttm`` 在源侧为 NULL，保持 NULL：用 0 或极大值兜底会让
    估值分档整体失真 —— 那是「不知道」不是「等于某个数」。
    """

    DATASET = "valuation_1d"
    CONTRACT = contracts.VALUATION_1D
    NOT_NULL_COLUMNS = ("instrument_id", "trading_day", "source", "available_at")

    #: daily_basic 官方 15:00–17:00 更新。**这是文档值不是实测值**，
    #: 供应商没给逐行时间戳，只能用固定小时近似（见 ingest/pit.py 的分级说明）。
    PUBLISH_HOUR = 17

    #: 原样入库的数值字段（与 _DAILY_BASIC_SCALE 一起覆盖全部数值目标列）。
    _PASSTHROUGH = (
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
    )

    def _audit_extreme_ratios(self, frame: pd.DataFrame) -> None:
        """对已严格转数值的估值逐字段留痕：绝对值超过 1e6 时原值保留，随业务提交。"""
        records = []
        for field in ("pe", "pe_ttm", "ps", "ps_ttm"):
            values = frame[field]
            selected = frame.loc[
                np.isfinite(values) & values.abs().gt(1_000_000),
                ["instrument_id", "trading_day", "ts_code", field],
            ]
            for instrument_id, day, code, value in selected.itertuples(index=False, name=None):
                payload = {
                    "provider": PROVIDER,
                    "dataset": self.DATASET,
                    "instrument_id": int(instrument_id),
                    "trading_day": day.isoformat(),
                    "source_code": str(code),
                    "field": field,
                    "source_value": str(value),
                    "retained_value": str(value),
                    "threshold": "1000000",
                    "processing_rule": "absolute_value_gt_threshold_preserve",
                    "note": "极端值保留原值、因子层处理",
                }
                records.append(
                    (
                        "tushare_valuation_extreme_ratio",
                        "info",
                        json.dumps(payload, ensure_ascii=False, allow_nan=False),
                    )
                )
        if records:
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO ops.data_quality_check(rule,severity,detail) VALUES (%s,%s,%s)",
                    records,
                )
            self.log.info(
                "Extreme valuation ratios retained provider=%s dataset=%s fields=%d "
                "threshold_abs_gt=1000000 target=%s",
                PROVIDER,
                self.DATASET,
                len(records),
                self.contract.qualified,
            )

    BJ_SOURCE_DATASET = "daily_basic"

    def _build_strict(self) -> pd.DataFrame:
        # 缺列整列写 NULL 会经 UPSERT 覆盖库内已有值，必须硬失败；NULL 只能来自源值。
        numeric = [*_DAILY_BASIC_SCALE, *self._PASSTHROUGH]
        raw = self._read_selected(
            "daily_basic",
            frozenset({"ts_code", "trade_date", *numeric, "limit_status"}),
        )
        if raw.empty:
            self.log.warning("daily_basic 无 raw 数据")
            return pd.DataFrame(columns=list(self.contract.columns))

        df = raw.copy()
        df["ts_code"] = df["ts_code"].astype(str).str.strip()
        df["trading_day"] = _parse_trade_date(df, "daily_basic")
        df = self._attach_ids(df, self._id_map())
        if df.empty:
            return pd.DataFrame(columns=list(self.contract.columns))

        _to_numeric_strict(df, [*numeric, "limit_status"], "daily_basic")
        limit_status = df["limit_status"]
        invalid = limit_status.notna() & ~limit_status.isin(range(7))
        if invalid.any():
            # 枚举外的值说明源语义变了，CHECK 会拒掉整批；先在这里给出可定位的错误。
            bad = sorted(limit_status[invalid].unique())
            raise RowValidationError(f"daily_basic.limit_status 含 0–6 以外的值: {bad}")

        self._audit_extreme_ratios(
            df.drop_duplicates(subset=["instrument_id", "trading_day"], keep="last")
        )

        out = pd.DataFrame(
            {
                "instrument_id": df["instrument_id"].astype("int64"),
                "trading_day": df["trading_day"],
                # 换算只在这里发生一次，计算层与文档都不再乘除。
                **{name: df[name] * scale for name, scale in _DAILY_BASIC_SCALE.items()},
                **{name: df[name] for name in self._PASSTHROUGH},
                "limit_status": limit_status.astype("Int64"),
                "currency": "CNY",
                "source": PROVIDER,
                "available_at": pit.from_trading_day(
                    df["trading_day"], publish_hour=self.PUBLISH_HOUR
                ),
            }
        )
        out = out.drop_duplicates(subset=["instrument_id", "trading_day"], keep="last")
        return out[list(self.contract.columns)].reset_index(drop=True)


class AdjFactorTsImporter(BJPendingImporter, _SymbolResolvingImporter):
    """adj_factor → market.adj_factor_ts（每日单值复权因子明细，D7）。

    与 `StockBars1dImporter` 回填 ``stock_bar_1d.adj_factor`` 列是两条独立的路：
    那一列随行情表走，这张表可以在没有行情的情况下独立回补与对账。
    因子必须为正（DDL 有 CHECK），非正值说明源数据损坏，**中断而不是丢行** ——
    静默丢掉几天因子会让那段区间的复权价格无声偏移。
    """

    DATASET = "adj_factor_ts"
    CONTRACT = contracts.ADJ_FACTOR_TS
    NOT_NULL_COLUMNS = ("instrument_id", "trading_day", "adj_factor", "source")

    BJ_SOURCE_DATASET = "adj_factor"

    def _build_strict(self) -> pd.DataFrame:
        raw = self._read_selected("adj_factor")
        if raw.empty:
            self.log.warning("adj_factor 无 raw 数据")
            return pd.DataFrame(columns=list(self.contract.columns))

        _require(raw, {"ts_code", "trade_date", "adj_factor"}, "adj_factor")
        df = raw.copy()
        df["ts_code"] = df["ts_code"].astype(str).str.strip()
        df["trading_day"] = _parse_trade_date(df, "adj_factor")
        df["adj_factor"] = pd.to_numeric(df["adj_factor"], errors="coerce")

        bad = ~np.isfinite(df["adj_factor"].to_numpy(dtype=float)) | (df["adj_factor"] <= 0)
        if bad.any():
            raise RowValidationError(f"adj_factor 含 {int(bad.sum())} 行非正或非有限的复权因子")

        df = self._attach_ids(df, self._id_map())
        if df.empty:
            return pd.DataFrame(columns=list(self.contract.columns))

        out = pd.DataFrame(
            {
                "instrument_id": df["instrument_id"].astype("int64"),
                "trading_day": df["trading_day"],
                "adj_factor": df["adj_factor"],
                "source": PROVIDER,
            }
        )
        out = out.drop_duplicates(subset=["instrument_id", "trading_day"], keep="last")
        return out[list(self.contract.columns)].reset_index(drop=True)


__all__ = [
    "AdjFactorTsImporter",
    "ValuationImporter",
    "StockBars1dImporter",
    "IndexBars1dImporter",
    "FutureBars1dImporter",
    "parse_date",
]
