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

import numpy as np
import pandas as pd

from gr_data.common import contracts
from gr_data.ingest.base import BaseImporter
from gr_data.ingest.resolve import resolve_by_symbol_map
from gr_data.ingest.tushare.adapter import TushareAdapter
from gr_data.ingest.tushare.importers.reference import _require, parse_date


PROVIDER = "tushare"

# daily 与 stk_limit 各自返回 pre_close，四舍五入口径可能差一分钱。
# 超出该容差说明两者的价格基准不一致，此时涨跌停价不可信。
PRE_CLOSE_TOLERANCE = 0.011


def _to_numeric(df: pd.DataFrame, columns: list[str]) -> None:
    for c in columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")


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
        raise ValueError(f"{source} 含非法 trade_date")
    return parsed.dt.date


class _BaseBarsImporter(BaseImporter):
    PROVIDER = PROVIDER
    NOT_NULL_COLUMNS = ("instrument_id", "dt", "trading_day")
    PRICE_COLUMNS = ("open", "high", "low", "close", "pre_close")

    def _adapter(self) -> TushareAdapter:
        return TushareAdapter(self.paths)

    def _id_map(self) -> dict[str, int]:
        return resolve_by_symbol_map(self.conn, PROVIDER)

    def _validate_prices(self, df: pd.DataFrame, source: str) -> None:
        """严格校验：任一价格非有限或非正即抛错。

        只用于**股票**。股票只要当日有 bar，五个价格就必然齐全，缺失即数据损坏，
        应当中断而不是入库。指数与期货不同——它们的价格缺失是常态（只发布收盘
        点位的指数、无成交但有结算价的合约），那边走 ``_null_out_invalid``。
        """
        cols = list(self.PRICE_COLUMNS)
        values = df[cols].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"{source} 含非有限价格")
        if (values <= 0).any():
            raise ValueError(f"{source} 含非正价格")
        if (df["high"] < df["low"]).any():
            raise ValueError(f"{source} 含 high < low 的记录")

    def _attach_ids(self, df: pd.DataFrame, id_map: dict[str, int]) -> pd.DataFrame:
        """按 symbol_map 解析 instrument_id，未登记的标的丢弃并记警告。

        丢弃是必要的：instrument_id 是外键，未登记的标的写不进去。
        但**必须让丢弃可见**，否则会伪装成「这段时间没数据」。
        """
        df = df.copy()
        df["instrument_id"] = df["ts_code"].map(id_map)
        unknown = df["instrument_id"].isna()
        if unknown.any():
            codes = sorted(set(df.loc[unknown, "ts_code"]))
            self.log.warning(
                "%d 行（%d 个标的）在 meta.symbol_map 中无登记，已跳过；样例: %s。"
                "请先运行 instruments + symbol_map importer。",
                int(unknown.sum()),
                len(codes),
                codes[:5],
            )
            df = df[~unknown]
        return df


class StockBars1dImporter(_BaseBarsImporter):
    """daily + adj_factor + stk_limit + suspend_d → market.stock_bar_1d。"""

    DATASET = "stock_bar_1d"
    CONTRACT = contracts.bar_1d("stock")

    def build(self) -> pd.DataFrame:
        adapter = self._adapter()
        daily = adapter.read_all_months("daily")
        if daily.empty:
            self.log.warning("daily 无 raw 数据")
            return pd.DataFrame(columns=list(self.contract.columns))

        _require(
            daily,
            {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"},
            "daily",
        )
        market = daily.drop_duplicates(subset=["ts_code", "trade_date"], keep="last").copy()
        market["ts_code"] = market["ts_code"].astype(str).str.strip()
        if market["ts_code"].eq("").any():
            raise ValueError("daily 含空 ts_code")

        market = self._merge_adj_factor(market, adapter)

        _to_numeric(market, ["open", "high", "low", "close", "pre_close", "vol", "amount"])
        self._validate_prices(market, "daily")
        if (market[["vol", "amount"]].to_numpy(dtype=float) < 0).any():
            raise ValueError("daily 含负成交量或成交额")

        market["dt"] = _parse_trade_date(market, "daily")
        market = self._merge_limits(market, adapter)
        trading_status = self._trading_status(market, adapter)
        market = self._attach_ids(market, self._id_map())
        if market.empty:
            return pd.DataFrame(columns=list(self.contract.columns))
        trading_status = trading_status.loc[market.index]

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
            }
        )
        return out[list(self.contract.columns)].reset_index(drop=True)

    def _merge_adj_factor(self, market: pd.DataFrame, adapter: TushareAdapter) -> pd.DataFrame:
        """合并复权因子。

        缺失直接抛错，不用默认值 1 兜底——``adj_factor`` 在目标表是 NOT NULL，
        用 1 冒充「未知」会让下游的前复权价格静默算错。
        """
        adj = adapter.read_all_months("adj_factor")
        if adj.empty:
            raise ValueError("缺少 adj_factor raw 数据；股票日线必须带复权因子")
        _require(adj, {"ts_code", "trade_date", "adj_factor"}, "adj_factor")
        adj = adj.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")[
            ["ts_code", "trade_date", "adj_factor"]
        ]
        merged = market.merge(adj, on=["ts_code", "trade_date"], how="left", validate="one_to_one")
        missing = int(merged["adj_factor"].isna().sum())
        if missing:
            raise ValueError(f"daily 有 {missing} 行缺少 adj_factor")
        merged["adj_factor"] = pd.to_numeric(merged["adj_factor"], errors="coerce")
        if not np.isfinite(merged["adj_factor"].to_numpy(dtype=float)).all():
            raise ValueError("adj_factor 含非有限值")
        if (merged["adj_factor"] <= 0).any():
            raise ValueError("adj_factor 含非正值")
        return merged

    def _merge_limits(self, market: pd.DataFrame, adapter: TushareAdapter) -> pd.DataFrame:
        """合并涨跌停价。

        与复权因子不同，``limit_up`` / ``limit_down`` 在目标表可为 NULL，
        因此缺失只记警告、留 NULL，不阻断整批入库。
        pre_close 对不上的记录则**丢弃其涨跌停价**——价格基准不同，涨跌停不可信。
        """
        limits = adapter.read_all_months("stk_limit")
        if limits.empty:
            self.log.warning("缺少 stk_limit raw 数据，limit_up/limit_down 将为 NULL")
            market["limit_up"] = None
            market["limit_down"] = None
            return market

        _require(limits, {"ts_code", "trade_date", "up_limit", "down_limit"}, "stk_limit")
        lim = limits.drop_duplicates(subset=["ts_code", "trade_date"], keep="last").copy()
        lim["ts_code"] = lim["ts_code"].astype(str).str.strip()
        keep = ["ts_code", "trade_date", "up_limit", "down_limit"]
        if "pre_close" in lim.columns:
            lim = lim.rename(columns={"pre_close": "limit_pre_close"})
            keep.append("limit_pre_close")
        merged = market.merge(
            lim[keep], on=["ts_code", "trade_date"], how="left", validate="one_to_one"
        )

        _to_numeric(merged, ["up_limit", "down_limit"])
        bad = (
            (merged["up_limit"] <= 0)
            | (merged["down_limit"] <= 0)
            | (merged["up_limit"] < merged["down_limit"])
        )
        if bad.any():
            self.log.warning("stk_limit 有 %d 行价格不合法，置 NULL", int(bad.sum()))
            merged.loc[bad, ["up_limit", "down_limit"]] = np.nan

        if "limit_pre_close" in merged.columns:
            lp = pd.to_numeric(merged["limit_pre_close"], errors="coerce").to_numpy(dtype=float)
            dp = merged["pre_close"].to_numpy(dtype=float)
            comparable = np.isfinite(lp)
            mismatch = comparable & ~np.isclose(dp, lp, atol=PRE_CLOSE_TOLERANCE, rtol=0)
            if mismatch.any():
                self.log.warning(
                    "daily 与 stk_limit 的 pre_close 有 %d 行不一致（容差 %.3f），"
                    "该批涨跌停价置 NULL",
                    int(mismatch.sum()),
                    PRE_CLOSE_TOLERANCE,
                )
                merged.loc[mismatch, ["up_limit", "down_limit"]] = np.nan

        missing = int(merged["up_limit"].isna().sum())
        if missing:
            self.log.warning("%d 行无可用涨跌停价，留 NULL", missing)

        merged["limit_up"] = merged["up_limit"]
        merged["limit_down"] = merged["down_limit"]
        return merged

    def _trading_status(self, market: pd.DataFrame, adapter: TushareAdapter) -> pd.Series:
        """由 suspend_d 事件推导交易状态。

        同一标的同一天可能同时有停牌(S)与复牌(R)记录，此时以 R 为准
        （盘中复牌，当日实际有成交）。无记录视为 NORMAL。
        """
        default = pd.Series("NORMAL", index=market.index, dtype=object)
        susp = adapter.read_all_months("suspend_d")
        if susp.empty:
            self.log.warning("缺少 suspend_d raw 数据，trading_status 一律记为 NORMAL")
            return default

        _require(susp, {"ts_code", "trade_date", "suspend_type"}, "suspend_d")
        s = susp.copy()
        s["ts_code"] = s["ts_code"].astype(str).str.strip()
        s["suspend_type"] = s["suspend_type"].astype(str).str.strip()
        invalid = ~s["suspend_type"].isin(("S", "R"))
        if invalid.any():
            self.log.warning("suspend_d 有 %d 行 suspend_type 非法，已忽略", int(invalid.sum()))
            s = s[~invalid]
        s["dt"] = _parse_trade_date(s, "suspend_d")

        halted = set(map(tuple, s.loc[s["suspend_type"].eq("S"), ["ts_code", "dt"]].to_numpy()))
        resumed = set(map(tuple, s.loc[s["suspend_type"].eq("R"), ["ts_code", "dt"]].to_numpy()))
        keys = list(zip(market["ts_code"], market["dt"], strict=False))
        return pd.Series(
            ["HALTED" if (k in halted and k not in resumed) else "NORMAL" for k in keys],
            index=market.index,
            dtype=object,
        )


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
        adapter = self._adapter()
        raw = adapter.read_all_months("index_daily")
        if raw.empty:
            self.log.warning("index_daily 无 raw 数据")
            return pd.DataFrame(columns=list(self.contract.columns))

        _require(
            raw,
            {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"},
            "index_daily",
        )
        m = raw.drop_duplicates(subset=["ts_code", "trade_date"], keep="last").copy()
        m["ts_code"] = m["ts_code"].astype(str).str.strip()
        _to_numeric(m, ["open", "high", "low", "close", "pre_close", "vol", "amount"])
        _null_out_invalid(m, list(self.PRICE_COLUMNS))

        usable = m["close"].notna()
        dropped = int((~usable).sum())
        if dropped:
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
                "amount": m["amount"] * 1000.0,  # 千元 → 元
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
    """

    DATASET = "future_bar_1d"
    CONTRACT = contracts.bar_1d("future")

    def build(self) -> pd.DataFrame:
        adapter = self._adapter()
        raw = adapter.read_all_months("fut_daily")
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
        m = raw.drop_duplicates(subset=["ts_code", "trade_date"], keep="last").copy()
        m["ts_code"] = m["ts_code"].astype(str).str.strip()
        _to_numeric(
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
        )
        _null_out_invalid(m, [*self.PRICE_COLUMNS, "settle", "pre_settle"])

        usable = m["close"].notna() | m["settle"].notna()
        dropped = int((~usable).sum())
        if dropped:
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
                "amount": m["amount"] * 10000.0,  # 万元 → 元
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


__all__ = [
    "StockBars1dImporter",
    "IndexBars1dImporter",
    "FutureBars1dImporter",
    "parse_date",
]
