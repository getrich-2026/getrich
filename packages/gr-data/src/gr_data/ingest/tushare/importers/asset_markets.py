"""ETF / 三类期权的显式入库；期权参数仅允许隔离验证，不发布历史定价能力。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import cast

import pandas as pd
import psycopg

from gr_data.common import contracts
from gr_data.common.paths import RawPaths
from gr_data.common.retry import int_to_date, today_int
from gr_data.ingest.base import BaseImporter, IngestContext, IngestGateError, IngestResult
from gr_data.ingest.tushare.adapter import TushareAdapter
from gr_data.ingest.tushare.importers.profile import _number, _text
from gr_data.ingest.tushare.importers.reference import parse_date
from gr_data.ingest.tushare.symbols import split_ts_code
from gr_data.raw.tushare.asset_rules import (
    OPTION_SUFFIXES,
    conflicting_etf_code_mask,
    czce_settlement_only_counts,
    czce_settlement_only_mask,
    missing_etf_listing_mask,
    numeric_values,
    ohl_zero_placeholder_counts,
    ohl_zero_placeholder_mask,
    option_underlying,
    quarantined_etf_mask,
    read_asset_observation,
    require_columns,
    source_codes,
    source_dates,
    standard_fund_codes,
    unique_rows,
    validate_bars,
    zero_settlement_candidate_counts,
    zero_settlement_candidate_mask,
)


def asset_metadata(
    paths: RawPaths, asset: str, *, notice: Callable[[str], None] | None = None
) -> pd.DataFrame:
    """读取独立参考清单，待上市 ETF 留在 raw，交易身份仍严格校验。

    Args:
        paths: 仓库外的原始数据路径。
        asset: etf 或 option。
        notice: 接收被跳过的待上市 ETF 条数及样本的软告警。
    """
    frame, _ = read_asset_observation(paths.dataset_file("tushare", "instruments", asset))
    if frame is None or frame.empty:
        raise IngestGateError(f"Missing {asset} instruments raw")
    required = ("ts_code", "exchange", "list_date")
    require_columns(frame, required, asset)
    source_codes(frame)
    frame = unique_rows(frame, ("ts_code",))
    if asset == "etf":
        require_columns(frame, ("list_status", "extname"), asset)
        if not frame["list_status"].isin(["L", "D", "P"]).all():
            raise IngestGateError("Unknown ETF list_status")
        pending = frame.loc[frame["list_status"].eq("P")]
        if not pending.empty and notice is not None:
            notice(
                f"Skipped pending ETF rows={len(pending)} "
                f"samples={pending['ts_code'].head(5).tolist()}"
            )
        # 所有 P 记录保留在 raw，上市后由后续 L 快照正式登记身份。
        frame = frame.loc[~frame["list_status"].eq("P")].copy()
        valid_code = (
            standard_fund_codes(frame["ts_code"]) & frame["ts_code"].str[-2:].eq(frame["exchange"])
        ) | conflicting_etf_code_mask(frame)
        if not valid_code.all():
            raise IngestGateError("ETF exchange and suffix mismatch")
        source_dates(frame.loc[~missing_etf_listing_mask(frame), "list_date"])
        quarantined = quarantined_etf_mask(frame)
        if quarantined.any() and notice is not None:
            notice(
                f"Quarantined unverified ETF identity rows={int(quarantined.sum())} "
                f"samples={frame.loc[quarantined, 'ts_code'].head(5).tolist()}"
            )
        frame = frame.loc[~quarantined].copy()
    else:
        require_columns(
            frame,
            (
                "name",
                "opt_code",
                "call_put",
                "exercise_type",
                "exercise_price",
                "opt_multiplier",
                "delist_date",
                "last_edate",
            ),
            asset,
        )
        if not frame["call_put"].isin(["C", "P"]).all():
            raise IngestGateError("Unknown option call_put")
        expected = frame["exchange"].map(OPTION_SUFFIXES)
        if (
            expected.isna().any()
            or not frame["ts_code"].str.rsplit(".", n=1).str[-1].eq(expected).all()
        ):
            raise IngestGateError("Option exchange and suffix mismatch")
        for value in frame["opt_code"]:
            option_underlying(value)
    listed = frame["list_date"].map(parse_date)
    if listed.isna().any():
        raise IngestGateError(f"Missing {asset} list_date")
    if asset == "option":
        expired = frame["delist_date"].map(parse_date)
        known = expired.notna()
        if expired.loc[known].lt(listed.loc[known]).any():
            raise IngestGateError("Option lifecycle reversed")
    return frame.reset_index(drop=True)


class _AssetImporter(BaseImporter):
    PROVIDER = "tushare"
    STRICT_QUALITY = True
    ASSET = ""

    def _metadata(self) -> pd.DataFrame:
        return asset_metadata(self.paths, self.ASSET, notice=self._soft)

    def _ids(self, codes: list[str], asset: str) -> dict[str, int]:
        codes = list(dict.fromkeys(codes))
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT m.source_symbol, i.instrument_id, i.exchange FROM meta.symbol_map m "
                "JOIN meta.instruments i USING (instrument_id) "
                "WHERE m.source=%s AND i.asset=%s AND m.source_symbol=ANY(%s)",
                (self.PROVIDER, asset, codes),
            )
            rows = cur.fetchall()
            if any(exchange != split_ts_code(code)[1] for code, _, exchange in rows):
                raise IngestGateError("Source mapping resolves to wrong asset exchange")
            result = {code: int(iid) for code, iid, _ in rows}
        missing = set(codes) - set(result)
        if missing:
            raise IngestGateError(
                f"Unresolved {asset} symbols count={len(missing)} samples={sorted(missing)[:5]}"
            )
        return result


class _AssetInstrumentsImporter(_AssetImporter):
    CONTRACT = contracts.INSTRUMENTS
    NOT_NULL_COLUMNS = ("symbol", "asset", "exchange", "list_date")

    def build(self) -> pd.DataFrame:
        raw = self._metadata()
        today = int_to_date(today_int())
        listed = raw["list_date"].map(parse_date)
        if self.ASSET == "etf":
            # P 在 etf_basic 中是待上市；源没有退市日，不从最后行情推测。
            status = raw["list_status"].map({"L": "active", "D": "delisted", "P": "pending"})
            expired = pd.Series(None, index=raw.index, dtype=object)
            name = raw["extname"]
        else:
            expired = raw["delist_date"].map(parse_date)
            status = pd.Series(
                [
                    "pending"
                    if first > today
                    else "delisted"
                    if last is not None and last < today
                    else "active"
                    for first, last in zip(listed, expired, strict=True)
                ],
                index=raw.index,
            )
            name = raw["name"]
        return pd.DataFrame(
            {
                "symbol": raw["ts_code"],
                "asset": self.ASSET,
                "exchange": raw["ts_code"].map(lambda c: split_ts_code(str(c))[1]),
                "name": name,
                "list_date": listed,
                "delist_date": expired,
                "status": status,
            }
        )[list(self.contract.columns)]


#: etf_profile 目标列 → (源表, 源字段)。与 meta.instruments 同义的字段（简称、上市日、
#: 状态）以及 fund_basic 中与 etf_basic 重复的名称、托管人、管理费不再重复存。
_ETF_PROFILE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("fullname", "etf", "cname"),
    ("short_name", "etf", "csname"),
    ("channel", "etf", "etf_type"),
    ("index_code", "etf", "index_code"),
    ("index_name", "etf", "index_name"),
    ("setup_date", "etf", "setup_date"),
    ("manager", "etf", "mgr_name"),
    ("manager_fullname", "fund", "management"),
    ("custodian", "etf", "custod_name"),
    ("mgt_fee", "etf", "mgt_fee"),
    ("c_fee", "fund", "c_fee"),
    ("fund_type", "fund", "fund_type"),
    ("fund_class", "fund", "type"),
    ("invest_type", "fund", "invest_type"),
    ("benchmark", "fund", "benchmark"),
    ("found_date", "fund", "found_date"),
    ("issue_date", "fund", "issue_date"),
    ("due_date", "fund", "due_date"),
    ("delist_date", "fund", "delist_date"),
    ("issue_amount", "fund", "issue_amount"),
    ("duration_year", "fund", "duration_year"),
    ("p_value", "fund", "p_value"),
    ("min_amount", "fund", "min_amount"),
    ("exp_return", "fund", "exp_return"),
    ("trustee", "fund", "trustee"),
    ("purc_startdate", "fund", "purc_startdate"),
    ("redm_startdate", "fund", "redm_startdate"),
)
_ETF_PROFILE_DATES = frozenset(
    {"setup_date", "found_date", "issue_date", "due_date", "delist_date"}
    | {"purc_startdate", "redm_startdate"}
)
#: 源单位 → 库内单位的倍率：发行份额 亿份 → 份，起点金额 万元 → 元。
_ETF_PROFILE_SCALE = {"issue_amount": 1e8, "min_amount": 1e4}
_ETF_PROFILE_NUMBERS = frozenset(
    {"mgt_fee", "c_fee", "duration_year", "p_value", "exp_return", *_ETF_PROFILE_SCALE}
)


class EtfProfileImporter(_AssetImporter):
    """etf_basic + 场内 fund_basic → meta.etf_profile，按 ts_code 精确连接。

    只覆盖已登记身份的 ETF（待上市、身份隔离的不写）。fund_basic 未匹配的 ETF 照常
    写 etf_basic 字段，fund_* 列为 NULL 并记软告警；不按名称或基准猜类型。
    """

    DATASET = "etf_profile"
    ASSET = "etf"
    CONTRACT = contracts.ETF_PROFILE
    NOT_NULL_COLUMNS = ("instrument_id", "source")

    def build(self) -> pd.DataFrame:
        etf = self._metadata()
        fund, _ = read_asset_observation(
            self.paths.dataset_file(self.PROVIDER, "instruments", "fund_basic")
        )
        if fund is None or fund.empty:
            raise IngestGateError("Missing fund_basic raw; fetch tushare fund_basic first")
        sources = {"etf": etf, "fund": fund}
        for name, frame in sources.items():
            columns = tuple(field for _, src, field in _ETF_PROFILE_FIELDS if src == name)
            require_columns(frame, columns, "etf_basic" if name == "etf" else "fund_basic")
        fund = fund.assign(ts_code=source_codes(fund))
        if fund["ts_code"].duplicated().any():
            raise IngestGateError("Duplicate fund_basic ts_code")
        fund_columns = [field for _, src, field in _ETF_PROFILE_FIELDS if src == "fund"]
        merged = etf.merge(
            fund[["ts_code", *fund_columns]].rename(columns=lambda c: f"fund.{c}"),
            left_on="ts_code",
            right_on="fund.ts_code",
            how="left",
            validate="one_to_one",
        )
        unmatched = merged["fund.ts_code"].isna()
        if unmatched.any():
            self._soft(
                f"ETF without exact fund_basic match rows={int(unmatched.sum())} "
                f"samples={merged.loc[unmatched, 'ts_code'].head(5).tolist()}"
            )
        ids = self._ids(merged["ts_code"].tolist(), self.ASSET)
        out = pd.DataFrame({"instrument_id": merged["ts_code"].map(ids)})
        for column, src, field in _ETF_PROFILE_FIELDS:
            values = merged[field if src == "etf" else f"fund.{field}"]
            if column in _ETF_PROFILE_DATES:
                out[column] = values.map(parse_date)
            elif column in _ETF_PROFILE_NUMBERS:
                number = _number(values, f"{src}.{field}")
                scale = _ETF_PROFILE_SCALE.get(column)
                out[column] = (
                    number
                    if scale is None
                    else number.map(lambda v, k=scale: None if v is None else v * k)
                )
            else:
                out[column] = _text(values)
        out["source"] = self.PROVIDER
        return out[list(self.contract.columns)].reset_index(drop=True)


class _OptionValidation:
    """四个期权 writer 共用的库调用门禁，必须在 claim / 写入之前检查。"""

    validation_only: bool

    def _require_validation(self) -> None:
        if self.validation_only is not True:
            raise IngestGateError(
                "Option writes are validation-only: historical contract parameters "
                "and publication contract are not verified"
            )


class EtfInstrumentsImporter(_AssetInstrumentsImporter):
    DATASET = "etf_instruments"
    ASSET = "etf"


class OptionInstrumentsImporter(_OptionValidation, _AssetInstrumentsImporter):
    DATASET = "option_instruments"
    ASSET = "option"

    def __init__(
        self,
        conn: psycopg.Connection,
        ctx: IngestContext,
        client: object = None,
        *,
        validation_only: bool = False,
    ) -> None:
        super().__init__(conn, ctx, client)
        self.validation_only = validation_only

    def run(self) -> IngestResult:
        self._require_validation()
        return super().run()


class _AssetSymbolMapImporter(_AssetImporter):
    CONTRACT = contracts.SYMBOL_MAP
    NOT_NULL_COLUMNS = ("instrument_id", "source", "source_symbol")

    def build(self) -> pd.DataFrame:
        codes = self._metadata()["ts_code"].tolist()
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, instrument_id, exchange FROM meta.instruments "
                "WHERE asset=%s AND symbol=ANY(%s)",
                (self.ASSET, codes),
            )
            rows = cur.fetchall()
            if len(rows) != len(codes) or any(
                exchange != split_ts_code(code)[1] for code, _, exchange in rows
            ):
                raise IngestGateError("Missing or ambiguous asset instruments")
            ids = {code: iid for code, iid, _ in rows}
            cur.execute(
                "SELECT source_symbol, instrument_id FROM meta.symbol_map "
                "WHERE source=%s AND source_symbol=ANY(%s)",
                (self.PROVIDER, codes),
            )
            existing = dict(cur.fetchall())
        if set(ids) != set(codes):
            raise IngestGateError(f"Missing registered {self.ASSET} instruments")
        if any(code in existing and existing[code] != iid for code, iid in ids.items()):
            raise IngestGateError("Conflicting existing source symbol mapping")
        return pd.DataFrame(
            [
                {"instrument_id": int(ids[code]), "source": self.PROVIDER, "source_symbol": code}
                for code in codes
            ],
            columns=list(self.contract.columns),
        )


class EtfSymbolMapImporter(_AssetSymbolMapImporter):
    DATASET = "etf_symbol_map"
    ASSET = "etf"


class OptionSymbolMapImporter(_OptionValidation, _AssetSymbolMapImporter):
    DATASET = "option_symbol_map"
    ASSET = "option"

    def __init__(
        self,
        conn: psycopg.Connection,
        ctx: IngestContext,
        client: object = None,
        *,
        validation_only: bool = False,
    ) -> None:
        super().__init__(conn, ctx, client)
        self.validation_only = validation_only

    def run(self) -> IngestResult:
        self._require_validation()
        return super().run()


class OptionContractsImporter(_OptionValidation, _AssetImporter):
    """opt_basic 当前观察 → 合约静态表，仅隔离验证，不作历史时点参数。"""

    DATASET = "option_contracts"
    ASSET = "option"
    CONTRACT = contracts.OPTION_CONTRACTS
    NOT_NULL_COLUMNS = ("instrument_id", "underlying_id", "option_type", "strike", "multiplier")

    def __init__(
        self,
        conn: psycopg.Connection,
        ctx: IngestContext,
        client: object = None,
        *,
        validation_only: bool = False,
    ) -> None:
        super().__init__(conn, ctx, client)
        self.validation_only = validation_only

    def run(self) -> IngestResult:
        self._require_validation()
        self._soft(
            "Current option parameter snapshot; historical parameters "
            "and publication are not verified"
        )
        return super().run()

    def build(self) -> pd.DataFrame:
        raw = self._metadata()
        ids = self._ids(raw["ts_code"].tolist(), "option")
        underlying = raw["opt_code"].map(option_underlying)
        underlying_ids: dict[str, int] = {}
        for exchanges, asset in (
            (("SSE", "SZSE"), "etf"),
            (("CFFEX",), "index"),
            (("DCE", "CZCE", "SHFE", "INE", "GFEX"), "future"),
        ):
            codes = underlying.loc[raw["exchange"].isin(exchanges)].tolist()
            if codes:
                underlying_ids.update(self._ids(codes, asset))
        styles = raw["exercise_type"].map({"欧式": "european", "美式": "american"})
        if styles.isna().any():
            raise IngestGateError("Unknown option exercise_type")
        strike = numeric_values(
            raw["exercise_price"], "exercise_price", precision=18, scale=4, positive=True
        )
        multiplier = numeric_values(
            raw["opt_multiplier"], "opt_multiplier", precision=18, scale=4, positive=True
        )
        if strike.isna().any() or multiplier.isna().any():
            raise IngestGateError("Missing option strike or multiplier")
        return pd.DataFrame(
            {
                "instrument_id": raw["ts_code"].map(ids),
                "underlying_id": underlying.map(underlying_ids),
                "option_type": raw["call_put"],
                "exercise_style": styles,
                "strike": strike,
                "multiplier": multiplier,
                "list_date": raw["list_date"].map(parse_date),
                "last_trade_date": raw["delist_date"].map(parse_date),
                "exercise_date": raw["last_edate"].map(parse_date),
            }
        )[list(self.contract.columns)]


class _AssetBarsImporter(_AssetImporter):
    RAW_DATASET = ""
    NOT_NULL_COLUMNS = ("instrument_id", "dt", "trading_day", "source")

    def _read(self, dataset: str) -> pd.DataFrame:
        adapter = TushareAdapter(self.paths, self.ctx.months)
        months = adapter.selected_months(dataset)
        if len(months) != 1:
            raise IngestGateError("ETF/options ingest requires exactly one month per invocation")
        raw, _ = read_asset_observation(self.paths.dataset_file(self.PROVIDER, dataset, months[0]))
        if raw is None or raw.empty:
            raise IngestGateError(f"Missing or empty {dataset} month={months[0]}")
        dates = source_dates(raw["trade_date"])
        if not pd.to_datetime(dates).dt.strftime("%Y-%m").eq(months[0]).all():
            raise IngestGateError(f"Out-of-partition dates dataset={dataset}")
        for notice in adapter.notices:
            self._soft(notice)
        return raw

    def build(self) -> pd.DataFrame:
        metadata = self._metadata().set_index("ts_code")
        raw = validate_bars(
            self._read(self.RAW_DATASET),
            option=self.ASSET == "option",
            expiry_dates=(
                # 源代码已校验为 str，parse_date 只产出 date／None；收窄 pandas 泛型。
                cast(dict[str, date | None], metadata["delist_date"].map(parse_date).to_dict())
                if self.ASSET == "option"
                else None
            ),
        )
        if self.ASSET == "etf":
            selected = raw["ts_code"].isin(metadata.index)
            excluded = int((~selected).sum())
            if excluded:
                self.log.info(
                    "Excluded non-ETF fund rows dataset=%s rows=%d nonstandard_code_rows=%d",
                    self.RAW_DATASET,
                    excluded,
                    int((~standard_fund_codes(raw.loc[~selected, "ts_code"])).sum()),
                )
            raw = raw.loc[selected].reset_index(drop=True)
            if raw.empty:
                raise IngestGateError("No ETF rows identified by authoritative metadata")
        elif not raw["ts_code"].isin(metadata.index).all():
            raise IngestGateError("Missing option metadata for daily codes")
        days = source_dates(raw["trade_date"])
        listed = raw["ts_code"].map(metadata["list_date"]).map(parse_date)
        if days.lt(listed).any():
            raise IngestGateError("Bar precedes instrument listing")
        if self.ASSET == "option":
            expired = raw["ts_code"].map(metadata["delist_date"]).map(parse_date)
            known = expired.notna()
            if days.loc[known].gt(expired.loc[known]).any():
                raise IngestGateError("Option bar follows last trade date")
        ids = self._ids(raw["ts_code"].tolist(), self.ASSET)
        out = pd.DataFrame(
            {
                "instrument_id": raw["ts_code"].map(ids),
                "dt": days,
                "trading_day": days,
                "source": self.PROVIDER,
            }
        )
        for column in (
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            *(("settle", "pre_settle") if self.ASSET == "option" else ()),
        ):
            out[column] = numeric_values(raw[column], column)
        if self.ASSET == "option":
            placeholders = ohl_zero_placeholder_mask(raw)
            out.loc[placeholders, ["open", "high", "low"]] = None
            settlement_only = czce_settlement_only_mask(raw)
            out.loc[settlement_only, ["open", "high", "low", "close"]] = None
            for exchange, counts in czce_settlement_only_counts(raw).items():
                self._soft(
                    f"Mapped settlement-only OHLC to NULL exchange={exchange} "
                    f"rows={counts['rows']} "
                    f"nonzero_activity_rows={counts['nonzero_activity_rows']} "
                    f"samples={counts['samples']}"
                )
            expiry_zero = zero_settlement_candidate_mask(raw)
            out.loc[expiry_zero, ["open", "high", "low", "close"]] = None
            for exchange, counts in zero_settlement_candidate_counts(raw).items():
                self._soft(
                    f"Mapped verified expiry-day zero settlement OHLC to NULL exchange={exchange} "
                    f"rows={counts['rows']} nonzero_volume_rows={counts['nonzero_volume_rows']} "
                    f"samples={counts['samples']}"
                )
            for exchange, counts in ohl_zero_placeholder_counts(raw).items():
                self._soft(
                    f"Mapped OHL zero placeholders exchange={exchange} rows={counts['rows']} "
                    f"nonzero_volume_rows={counts['nonzero_volume_rows']} "
                    f"samples={counts['samples']} "
                    f"nonzero_volume_samples={counts['nonzero_volume_samples']}"
                )
        out["volume"] = numeric_values(
            raw["vol"], "vol", multiplier=100 if self.ASSET == "etf" else 1, integer=True
        )
        out["amount"] = numeric_values(
            raw["amount"],
            "amount",
            multiplier=1000 if self.ASSET == "etf" else 10000,
            precision=24,
            scale=4,
        )
        out["limit_up"] = out["limit_down"] = out["trading_status"] = None
        if self.ASSET == "etf":
            factors = self._read("fund_adj")
            require_columns(factors, ("ts_code", "trade_date", "adj_factor"), "fund_adj")
            source_codes(factors)
            factors = factors.copy()
            factors["trade_date"] = source_dates(factors["trade_date"])
            factors = unique_rows(factors, ("ts_code", "trade_date"))
            keys = pd.DataFrame({"ts_code": raw["ts_code"], "trade_date": days})
            aligned = keys.merge(
                factors, on=["ts_code", "trade_date"], how="left", validate="one_to_one"
            )
            out["adj_factor"] = numeric_values(
                aligned["adj_factor"], "adj_factor", precision=18, scale=8, positive=True
            )
            if out["adj_factor"].isna().any():
                raise IngestGateError("Missing ETF adjustment factor")
        else:
            out["open_interest"] = numeric_values(raw["oi"], "oi", integer=True)
        if out.duplicated(["instrument_id", "dt"]).any():
            raise IngestGateError("Multiple source codes resolve to same asset bar key")
        return out[list(self.contract.columns)].reset_index(drop=True)


class EtfBars1dImporter(_AssetBarsImporter):
    """未复权 ETF 日线及基金因子；份额 ×100、金额 ×1000。"""

    DATASET = "etf_bar_1d"
    ASSET = "etf"
    RAW_DATASET = "fund_daily"
    CONTRACT = contracts.bar_1d("etf")


class OptionBars1dImporter(_OptionValidation, _AssetBarsImporter):
    """期权报价保持源尺度，手数不换算，金额 ×10000；仅隔离验证。"""

    DATASET = "option_bar_1d"
    ASSET = "option"
    RAW_DATASET = "opt_daily"
    CONTRACT = contracts.bar_1d("option")

    def __init__(
        self,
        conn: psycopg.Connection,
        ctx: IngestContext,
        client: object = None,
        *,
        validation_only: bool = False,
    ) -> None:
        super().__init__(conn, ctx, client)
        self.validation_only = validation_only

    def run(self) -> IngestResult:
        self._require_validation()
        self._soft(
            "Option prices validated without historical contract parameter eligibility; "
            "not published"
        )
        return super().run()
