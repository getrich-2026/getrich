"""显式启用的 ETF / 三类期权采集；范围固定，源值原样留存。"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gr_data.common.parquet import read_parquet_strict, write_parquet
from gr_data.common.retry import PermanentError, int_to_date, retry_call, today_int
from gr_data.raw.base import BaseFetcher, RawContext, month_range
from gr_data.raw.tushare.asset_rules import (
    BAR_COLUMNS,
    OPTION_BAR_COLUMNS,
    OPTION_SUFFIXES,
    conflicting_etf_code_mask,
    czce_settlement_only_counts,
    missing_etf_listing_mask,
    nonstandard_code_counts,
    ohl_zero_placeholder_counts,
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
)
from gr_data.raw.tushare.context import as_tushare_context
from gr_data.raw.tushare.fetchers.reference import (
    FutureCalendarFetcher,
    read_open_days,
    require_calendar_range,
)


ETF_FIELDS = (
    "ts_code,csname,extname,cname,index_code,index_name,setup_date,list_date,list_status,"
    "exchange,mgr_name,custod_name,mgt_fee,etf_type"
)
# fund_basic 官方字段全取（tushare doc_id=19）；场内 ETF 的投资类型是资产类别映射的依据。
FUND_FIELDS = (
    "ts_code,name,management,custodian,fund_type,found_date,due_date,list_date,issue_date,"
    "delist_date,issue_amount,m_fee,c_fee,duration_year,p_value,min_amount,exp_return,"
    "benchmark,status,invest_type,type,trustee,purc_startdate,redm_startdate,market"
)
# D 摘牌／到期、I 发行、L 存续；不指定 status 时源只返回部分状态。
FUND_STATUSES = ("L", "D", "I")
OPTION_FIELDS = (
    "ts_code,symbol,exchange,name,per_unit,opt_code,opt_type,call_put,exercise_type,"
    "exercise_price,opt_multiplier,s_month,maturity_date,list_price,list_date,delist_date,"
    "last_edate,last_ddate,quote_unit,min_price_chg"
)


class _AssetFetcher(BaseFetcher):
    PROVIDER = "tushare"

    def __init__(self, client: object, ctx: RawContext) -> None:
        super().__init__(client, ctx)
        self.ctx = as_tushare_context(ctx)
        self._requests: list[dict[str, object]] = []

    def _query(self, api: str, **params: object) -> pd.DataFrame:
        result = retry_call(
            self.client.query_all,
            api,
            **params,
            max_retries=self.ctx.max_retries,
            backoff_base=self.ctx.backoff_base,
            logger=self.log,
        )
        # 只保存允许的只读参数，凭据始终留在 client 内。
        allowed = {
            "fields",
            "exchange",
            "list_status",
            "market",
            "status",
            "ts_code",
            "trade_date",
            "opt_code",
        }
        self._requests.append(
            {
                "api": api,
                "parameters": {k: v for k, v in params.items() if k in allowed},
                "rows": len(result),
            }
        )
        return result

    def _range(self) -> tuple[date, date]:
        if self.ctx.start_date is None:
            raise ValueError("ETF/options require explicit providers.tushare.start_date")
        first = int_to_date(self.ctx.start_date)
        last = min(int_to_date(self.ctx.end_date or today_int()), int_to_date(today_int()))
        if first > last:
            raise ValueError("Invalid ETF/options date range")
        return first, last

    def _recoverable_manifest(
        self,
        out: Path,
        previous_observation_id: str | None,
        *,
        require_no_successor: bool,
    ) -> dict[str, Any] | None:
        """扫描本数据集观察证据；首次缺收据恢复还须排除已被取代的观察。"""
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        observations = self.paths.dataset_dir(self.PROVIDER, "observations") / self.DATASET
        manifests: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(observations.glob("*/manifest.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(manifest, dict):
                manifests.append((path, manifest))
        successors = {
            manifest["previous_observation_id"]
            for _, manifest in manifests
            if isinstance(manifest.get("previous_observation_id"), str)
        }
        for path, manifest in manifests:
            if (
                manifest.get("sha256") != digest
                or manifest.get("dataset") != self.DATASET
                or manifest.get("observation_id") != path.parent.name
                or manifest.get("previous_observation_id") != previous_observation_id
                or (require_no_successor and path.parent.name in successors)
            ):
                continue
            try:
                if (
                    hashlib.sha256((path.parent / "data.parquet").read_bytes()).hexdigest()
                    != digest
                ):
                    continue
            except OSError:
                continue
            return manifest
        return None

    def _previous_observation(self, out: Path) -> tuple[pd.DataFrame | None, dict[str, Any]]:
        """采集侧只恢复有完整观察证据的中断发布；缺收据仅可恢复无后继首次观察。"""
        try:
            return read_asset_observation(out)
        except ValueError as exc:
            receipt_path = out.with_suffix(".json")
            previous_observation_id = None
            require_no_successor = not receipt_path.exists()
            if not require_no_successor:
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as receipt_error:
                    raise exc from receipt_error
                if (
                    not isinstance(receipt, dict)
                    or not isinstance(receipt.get("sha256"), str)
                    or not isinstance(receipt.get("observation_id"), str)
                ):
                    raise exc
                previous_observation_id = receipt["observation_id"]
            manifest = self._recoverable_manifest(
                out,
                previous_observation_id,
                require_no_successor=require_no_successor,
            )
            if manifest is None:
                raise exc
            previous = read_parquet_strict(out)
            self.log.warning(
                "Recovered interrupted asset publication dataset=%s file=%s observation=%s",
                self.DATASET,
                out.name,
                manifest["observation_id"],
            )
            self._write_receipt(out, manifest)
            return previous, manifest

    @staticmethod
    def _write_receipt(out: Path, manifest: dict[str, Any]) -> None:
        """原子替换已落地文件的收据；失败时不遗留临时收据。"""
        receipt = out.with_suffix(".json")
        temp = receipt.with_suffix(f".tmp-{uuid.uuid4().hex}")
        try:
            temp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            os.replace(temp, receipt)
        finally:
            temp.unlink(missing_ok=True)

    def _publish(
        self,
        frame: pd.DataFrame,
        out: Path,
        scope: dict[str, object],
        *,
        observed_dates: dict[str, int] | None = None,
        source_responses: list[Path] | None = None,
    ) -> None:
        """先保存不可变观察与旧文件，再发布兼容文件；不覆盖历史证据。"""
        previous, previous_receipt = self._previous_observation(out)
        observation = uuid.uuid4().hex
        root = self.paths.dataset_dir(self.PROVIDER, "observations") / self.DATASET / observation
        root.mkdir(parents=True, exist_ok=False)
        if previous is not None:
            write_parquet(previous, root / "previous.parquet")
            (root / "previous-manifest.json").write_text(
                json.dumps(previous_receipt, indent=2), encoding="utf-8"
            )
        write_parquet(frame, root / "data.parquet")
        manifest = {
            "observation_id": observation,
            "observed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "dataset": self.DATASET,
            "rows": len(frame),
            "scope": scope,
            "sha256": hashlib.sha256((root / "data.parquet").read_bytes()).hexdigest(),
            "historical_parameters_verified": False,
            "previous_observation_id": previous_receipt.get("observation_id"),
            "requests": self._requests,
        }
        if observed_dates is not None:
            dates_file = root / "observation_dates.parquet"
            write_parquet(
                pd.DataFrame(
                    {
                        "ts_code": list(observed_dates),
                        "last_observed_date": list(observed_dates.values()),
                    }
                ),
                dates_file,
            )
            manifest["observation_dates_sha256"] = hashlib.sha256(
                dates_file.read_bytes()
            ).hexdigest()
        if source_responses is not None:
            responses = []
            for index, response in enumerate(source_responses):
                path = root / "responses" / f"{index:04d}.parquet"
                source = read_parquet_strict(response)
                if source is None:
                    raise ValueError("Missing option source response")
                write_parquet(source, path)
                responses.append(
                    {
                        "file": str(path.relative_to(root)),
                        "rows": len(source),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
            manifest["source_responses"] = responses
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        write_parquet(frame, out)
        # 水位始终引用已发布文件的哈希；崩溃后哈希不匹配即拒绝把旧水位当成功。
        self._write_receipt(out, manifest)
        self._requests = []
        self.log.info(
            "Raw asset published dataset=%s file=%s rows=%d", self.DATASET, out.name, len(frame)
        )


class EtfInstrumentsFetcher(_AssetFetcher):
    """etf_basic 的 L / D / P 名单；P 是待上市，保留源状态。"""

    DATASET = "etf_instruments"

    def fetch(self, mode: str = "update") -> int:
        frames = []
        for exchange in ("SH", "SZ"):
            for status in ("L", "D", "P"):
                frame = self._query(
                    "etf_basic", exchange=exchange, list_status=status, fields=ETF_FIELDS
                )
                if frame.empty:
                    if status == "L":
                        raise ValueError(f"Missing listed ETF metadata exchange={exchange}")
                    continue
                require_columns(
                    frame,
                    ("ts_code", "exchange", "list_status")
                    if status == "P"
                    else ("ts_code", "exchange", "list_status", "list_date", "extname"),
                    "etf_basic",
                )
                codes = source_codes(frame)
                if (
                    not frame["exchange"].eq(exchange).all()
                    or not frame["list_status"].eq(status).all()
                    or (
                        status != "P"
                        and not (
                            codes.str.fullmatch(rf"\d{{6}}\.{exchange}")
                            | conflicting_etf_code_mask(frame)
                        ).all()
                    )
                ):
                    raise ValueError("Unexpected ETF metadata scope")
                if status != "P":
                    source_dates(frame.loc[~missing_etf_listing_mask(frame), "list_date"])
                frames.append(frame)
        combined = unique_rows(pd.concat(frames, ignore_index=True), ("ts_code",))
        pending = combined.loc[combined["list_status"].eq("P")]
        self._publish(
            combined,
            self.paths.dataset_file(self.PROVIDER, "instruments", "etf"),
            {
                "statuses": ["L", "D", "P"],
                "quarantined_rows": {
                    "rows": int(quarantined_etf_mask(combined).sum()),
                    "samples": combined.loc[quarantined_etf_mask(combined), "ts_code"]
                    .head(5)
                    .tolist(),
                },
                "missing_listing_date_rows": {
                    "rows": int(missing_etf_listing_mask(combined).sum()),
                    "samples": combined.loc[missing_etf_listing_mask(combined), "ts_code"]
                    .head(5)
                    .tolist(),
                },
                "pending_rows": {
                    "rows": len(pending),
                    "nonstandard_code_rows": nonstandard_code_counts(pending)["rows"],
                    "missing_list_date_rows": int(
                        (pending["list_date"].isna() | pending["list_date"].eq("")).sum()
                    ),
                    "samples": pending["ts_code"].head(5).tolist(),
                },
            },
        )
        return 1


class FundBasicFetcher(_AssetFetcher):
    """场内（market=E）fund_basic 的 L / D / I 全量；与 ETF 名单按 ts_code 精确连接。"""

    DATASET = "fund_basic"

    def fetch(self, mode: str = "update") -> int:
        frames = []
        counts: dict[str, int] = {}
        for status in FUND_STATUSES:
            frame = self._query("fund_basic", market="E", status=status, fields=FUND_FIELDS)
            counts[status] = len(frame)
            if frame.empty:
                if status == "L":
                    raise ValueError("Missing listed exchange fund metadata")
                continue
            require_columns(frame, ("ts_code", "fund_type", "status", "market"), "fund_basic")
            source_codes(frame)
            if not frame["status"].eq(status).all() or not frame["market"].eq("E").all():
                raise ValueError("Unexpected fund_basic scope")
            frames.append(frame)
        combined = pd.concat(frames, ignore_index=True)
        duplicated = combined["ts_code"].duplicated(keep=False)
        if duplicated.any():
            # 同一代码出现在两种状态里时无法判断哪条是当前事实，不替源做选择。
            samples = combined.loc[duplicated, "ts_code"].head(5).tolist()
            raise ValueError(f"Duplicate fund_basic ts_code across statuses samples={samples}")
        self._publish(
            combined,
            self.paths.dataset_file(self.PROVIDER, "instruments", "fund_basic"),
            {"market": "E", "statuses": list(FUND_STATUSES), "status_rows": counts},
        )
        return 1


class OptionCalendarFetcher(FutureCalendarFetcher):
    """仅采所选期权市场需要的期货日历；沪深仍用 calendar。"""

    def _exchanges(self) -> tuple[str, ...]:
        return tuple(e for e in self.ctx.option_exchanges if e not in ("SSE", "SZSE"))


class AssetDailyFetcher(_AssetFetcher):
    """按市场交易日请求，逐月发布；update 重核显式范围以发现缺口和范围变化。

    内存上限为一个月；不会因最新月之外的文件已经存在而跳过未核验日期。
    """

    API_NAME = ""
    FIELDS: tuple[str, ...] = ()
    OPTION = False

    def _calendars(self, first: date, last: date) -> dict[str, set[date]]:
        result = {}
        for exchange in self.ctx.option_exchanges if self.OPTION else ("SSE", "SZSE"):
            dataset = "calendar" if exchange in ("SSE", "SZSE") else "future_calendar"
            cal = read_parquet_strict(self.paths.dataset_file(self.PROVIDER, dataset, exchange))
            if cal is None:
                raise ValueError(f"Missing asset calendar exchange={exchange}")
            days = read_open_days(cal, exchange)
            require_calendar_range(cal, first, last, exchange)
            result[exchange] = set(days)
        return result

    def fetch(self, mode: str = "update") -> int:
        if mode not in ("init", "update"):
            raise ValueError("Unsupported asset fetch mode")
        first, last = self._range()
        today = int_to_date(today_int())
        calendars = self._calendars(first, last)
        written = 0
        for ym, start, end in month_range(first, last):
            frames = []
            published_days: dict[str, set[date]] = {}
            pending_days: list[dict[str, str]] = []
            days = sorted({d for values in calendars.values() for d in values if start <= d <= end})
            for day in days:
                markets = [e for e, values in calendars.items() if day in values]
                queries = [{"exchange": e} for e in markets] if self.OPTION else [{}]
                for params in queries:
                    frame = self._query(
                        self.API_NAME,
                        trade_date=day.strftime("%Y%m%d"),
                        fields=",".join(self.FIELDS),
                        **params,
                    )
                    if frame.empty:
                        market = params.get("exchange", "fund")
                        if day >= today:
                            self.log.warning(
                                "Asset day pending dataset=%s day=%s exchange=%s",
                                self.DATASET,
                                day,
                                market,
                            )
                            pending_days.append(
                                {
                                    "trade_date": day.strftime("%Y%m%d"),
                                    "exchange": market,
                                }
                            )
                            continue
                        raise ValueError(
                            f"Unexplained empty asset response dataset={self.DATASET} "
                            f"day={day} market={params.get('exchange', 'fund')}"
                        )
                    require_columns(frame, self.FIELDS, self.DATASET)
                    source_codes(frame)
                    if not source_dates(frame["trade_date"]).eq(day).all():
                        raise ValueError("Unexpected asset response date")
                    if self.OPTION and not frame["exchange"].eq(params["exchange"]).all():
                        raise ValueError("Unexpected option response exchange")
                    if self.API_NAME == "fund_adj":
                        from gr_data.raw.tushare.asset_rules import numeric_values

                        values = numeric_values(
                            frame["adj_factor"], "adj_factor", precision=18, scale=8, positive=True
                        )
                        if values.isna().any():
                            raise ValueError("Missing fund adjustment factor")
                        frame = unique_rows(frame, ("ts_code", "trade_date"))
                    else:
                        frame = validate_bars(
                            frame,
                            option=self.OPTION,
                            capture_unverified_expiry=self.OPTION,
                        )
                        if not self.OPTION:
                            expected_market = (
                                frame["ts_code"].str[-2:].map({"SH": "SSE", "SZ": "SZSE"})
                            )
                            if (
                                not expected_market.loc[standard_fund_codes(frame["ts_code"])]
                                .isin(markets)
                                .all()
                            ):
                                raise ValueError("Fund response contains closed-market rows")
                    frames.append(frame)
                    published_days.setdefault(params.get("exchange", "fund"), set()).add(day)
            if not days:
                continue
            incoming = unique_rows(
                pd.concat(frames, ignore_index=True)
                if frames
                else pd.DataFrame(columns=self.FIELDS),
                ("ts_code", "trade_date"),
            )
            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, ym)
            previous = read_parquet_strict(out)
            if previous is not None and not previous.empty:
                dates = source_dates(previous["trade_date"])
                if self.OPTION:
                    replace = pd.Series(False, index=previous.index)
                    for exchange, successful in published_days.items():
                        replace |= dates.isin(successful) & previous["exchange"].eq(exchange)
                else:
                    replace = dates.isin(published_days.get("fund", set()))
                # 当天尚未发布的日期 / 交易所不在成功替换集合内，保留已有记录。
                keep = previous.loc[~replace]
                incoming = pd.concat([keep, incoming], ignore_index=True)
            incoming["trade_date"] = pd.to_datetime(
                source_dates(incoming["trade_date"])
            ).dt.strftime("%Y%m%d")
            self._publish(
                incoming,
                out,
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "exchanges": list(calendars),
                    "pending_days": pending_days,
                    **(
                        {
                            "ohl_zero_placeholder_rows": ohl_zero_placeholder_counts(incoming),
                            "czce_settlement_only_rows": czce_settlement_only_counts(incoming),
                            "zero_settlement_pending_expiry": zero_settlement_candidate_counts(
                                incoming
                            ),
                        }
                        if self.OPTION
                        else {"nonstandard_code_rows": nonstandard_code_counts(incoming)}
                    ),
                },
            )
            written += 1
        return written


class FundDailyFetcher(AssetDailyFetcher):
    DATASET = API_NAME = "fund_daily"
    FIELDS = BAR_COLUMNS


class FundAdjFetcher(AssetDailyFetcher):
    DATASET = API_NAME = "fund_adj"
    FIELDS = ("ts_code", "trade_date", "adj_factor")


class OptionDailyFetcher(AssetDailyFetcher):
    DATASET = API_NAME = "opt_daily"
    FIELDS = OPTION_BAR_COLUMNS
    OPTION = True


class OptionInstrumentsFetcher(_AssetFetcher):
    """先覆盖目标行情实际出现的代码；不冒充完整挂牌全集。

    复用已观察 opt_code；未知标的按一个精确代码引导，再按标的分页补齐。
    update 仅重查缺观察或上次观察时尚未到期的合约；init 强制重观察。
    当前快照及观察日不证明历史调整参数的业务生效区间。
    """

    DATASET = "option_instruments"

    @staticmethod
    def _metadata_scope(
        frame: pd.DataFrame,
        exchange: str,
        *,
        code: str | None = None,
        underlying: str | None = None,
    ) -> pd.DataFrame:
        """校验精确查询或标的查询的完整响应，禁止借过滤掩盖错市场／错标的。"""
        require_columns(
            frame,
            ("ts_code", "exchange", "opt_code", "call_put", "list_date", "delist_date"),
            "opt_basic",
        )
        codes = source_codes(frame)
        if (
            not frame["exchange"].eq(exchange).all()
            or not codes.str.endswith(f".{OPTION_SUFFIXES[exchange]}").all()
            or (code is not None and not codes.eq(code).all())
            or (underlying is not None and not frame["opt_code"].eq(underlying).all())
        ):
            if code is not None:
                raise PermanentError(f"Unresolved option metadata code={code}")
            raise ValueError("Option metadata response scope mismatch")
        for value in frame["opt_code"]:
            option_underlying(value)
        return unique_rows(frame, ("ts_code",))

    def _batches(
        self, codes: list[str], existing: pd.DataFrame, folder: Path
    ) -> tuple[pd.DataFrame, dict[str, int], list[Path]]:
        """按显式标的覆盖目标代码；完整响应分批落临时文件，峰值为单标的响应加目标行。

        不解析期权字符串推测标的。未知代码先精确查询，已覆盖代码不再引导；
        标的整页响应保留至观察归档，兼容文件只更新本轮目标代码。
        """
        pending = set(codes)
        frames = []
        responses: list[Path] = []
        queried: set[tuple[str, str]] = set()
        stats = {
            "underlying_queries": 0,
            "bootstrap_queries": 0,
            "fallback_queries": 0,
            "fallback_rows": 0,
        }

        def query(exchange: str, **params: str) -> pd.DataFrame:
            frame = self._query("opt_basic", exchange=exchange, fields=OPTION_FIELDS, **params)
            path = folder / f"{len(responses):04d}.parquet"
            write_parquet(frame, path)
            responses.append(path)
            return frame

        def exact(code: str, exchange: str, underlying: str | None = None) -> pd.DataFrame:
            frame = query(exchange, ts_code=code)
            if frame.empty:
                raise PermanentError(f"Unresolved option metadata code={code}")
            return self._metadata_scope(frame, exchange, code=code, underlying=underlying)

        while pending:
            code = min(pending)
            exchange = next(
                (e for e, suffix in OPTION_SUFFIXES.items() if code.endswith(f".{suffix}")), None
            )
            if exchange is None:
                raise ValueError("Unknown option code suffix")
            seed = None
            if code in existing.index:
                raw_underlying = existing.at[code, "opt_code"]
            else:
                seed = exact(code, exchange)
                raw_underlying = seed["opt_code"].iloc[0]
                stats["bootstrap_queries"] += 1
            if not isinstance(raw_underlying, str):
                raise ValueError("Invalid option opt_code")
            option_underlying(raw_underlying)
            underlying = raw_underlying
            required = {code}
            if not existing.empty:
                required.update(
                    existing.index[
                        existing["exchange"].eq(exchange) & existing["opt_code"].eq(underlying)
                    ].intersection(list(pending))
                )
            key = (exchange, underlying)
            batch = pd.DataFrame(columns=OPTION_FIELDS.split(","))
            if key not in queried:
                batch = query(exchange, opt_code=underlying)
                queried.add(key)
                stats["underlying_queries"] += 1
                if not batch.empty:
                    batch = self._metadata_scope(batch, exchange, underlying=underlying)
                else:
                    batch = pd.DataFrame(columns=OPTION_FIELDS.split(","))
            available = set(batch["ts_code"]) & pending
            if available:
                frames.append(batch.loc[batch["ts_code"].isin(available)])
            missing = required - available
            if missing:
                stats["fallback_rows"] += len(missing)
                self.log.warning(
                    "Option metadata batch fallback exchange=%s opt_code=%s rows=%d samples=%s",
                    exchange,
                    underlying,
                    len(missing),
                    sorted(missing)[:5],
                )
            for absent in sorted(missing):
                if absent == code and seed is not None:
                    frame = seed  # 已有精确引导响应，无需重复消耗同一代码请求。
                else:
                    frame = exact(absent, exchange, underlying)
                    stats["fallback_queries"] += 1
                frames.append(frame)
            pending.difference_update(available | missing)
        return unique_rows(pd.concat(frames, ignore_index=True), ("ts_code",)), stats, responses

    def _observation_dates(self, receipt: dict[str, Any]) -> dict[str, int]:
        """读取独立、带哈希的观察日文件；缺失或损坏只意味着必须重查。"""
        observation = receipt.get("observation_id", "")
        if (
            not isinstance(observation, str)
            or len(observation) != 32
            or any(c not in "0123456789abcdef" for c in observation)
        ):
            return {}
        path = (
            self.paths.dataset_dir(self.PROVIDER, "observations")
            / self.DATASET
            / observation
            / "observation_dates.parquet"
        )
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("sha256") != receipt.get("sha256")
                or manifest.get("observation_dates_sha256") != digest
                or receipt.get("observation_dates_sha256") != digest
            ):
                raise ValueError("Observation date hash mismatch")
            dates = read_parquet_strict(path)
            if dates is None:
                return {}
            require_columns(dates, ("ts_code", "last_observed_date"), "observation_dates")
            source_codes(dates)
            source_dates(dates["last_observed_date"])
            if dates["ts_code"].duplicated().any():
                raise ValueError("Duplicate observation date keys")
            return {code: int(day) for code, day in dates.itertuples(index=False, name=None)}
        except (OSError, ValueError, TypeError):
            self.log.warning("Option observation dates unavailable; requerying requested codes")
            return {}

    @staticmethod
    def _needs_observation(code: str, existing: pd.DataFrame, dates: dict[str, int]) -> bool:
        """只有上次已在到期之后观察过的参数才允许复用；不猜观察时间。"""
        if code not in existing.index or code not in dates:
            return True
        expiry = existing.at[code, "delist_date"]
        try:
            parsed = source_dates(pd.Series([expiry])).iloc[0]
        except (ValueError, TypeError):
            return True
        return int_to_date(dates[code]) <= parsed

    def fetch(self, mode: str = "update") -> int:
        if mode not in ("init", "update"):
            raise ValueError("Unsupported option metadata fetch mode")
        first, last = self._range()
        codes: set[str] = set()
        for ym, _, _ in month_range(first, last):
            raw, _ = read_asset_observation(self.paths.dataset_file(self.PROVIDER, "opt_daily", ym))
            if raw is None:
                raise ValueError(f"Missing opt_daily partition month={ym}")
            require_columns(raw, ("ts_code", "trade_date", "exchange"), "opt_daily")
            dates = source_dates(raw["trade_date"])
            scope = dates.between(first, last) & raw["exchange"].isin(self.ctx.option_exchanges)
            codes.update(source_codes(raw.loc[scope]).tolist())
        if not codes:
            raise ValueError("No observed option codes in requested scope")
        out = self.paths.dataset_file(self.PROVIDER, "instruments", "option")
        old, receipt = self._previous_observation(out)
        observed_dates = self._observation_dates(receipt)
        existing = old.set_index("ts_code") if old is not None else pd.DataFrame()
        to_query = sorted(
            code
            for code in codes
            if mode == "init" or self._needs_observation(code, existing, observed_dates)
        )
        self.log.info(
            "Option metadata observation scope_codes=%d query_codes=%d skipped_codes=%d mode=%s",
            len(codes),
            len(to_query),
            len(codes) - len(to_query),
            mode,
        )
        if not to_query:
            self.log.info("Option metadata unchanged; no observation published")
            return 0
        today = today_int()
        staging = self.paths.dataset_dir(self.PROVIDER, "metadata_requests")
        staging.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=staging) as folder:
            combined, stats, responses = self._batches(to_query, existing, Path(folder))
            observed_dates.update({code: today for code in to_query})
            if old is not None:
                combined = pd.concat(
                    [old.loc[~old["ts_code"].isin(to_query)], combined], ignore_index=True
                )
            self._publish(
                unique_rows(combined, ("ts_code",)),
                out,
                {
                    "coverage": "observed_daily_codes",
                    "start": first.isoformat(),
                    "end": last.isoformat(),
                    **stats,
                },
                observed_dates=observed_dates,
                source_responses=responses,
            )
        self.log.info(
            "Option metadata batches underlying_queries=%d bootstrap_queries=%d "
            "fallback_queries=%d fallback_rows=%d",
            stats["underlying_queries"],
            stats["bootstrap_queries"],
            stats["fallback_queries"],
            stats["fallback_rows"],
        )
        return 1
