"""Tushare raw fetchers：日线及其配套的逐日数据集。

## 为什么按「交易日」调用而不是「日期区间」

Tushare 对一次查询的 ``offset`` 有 **100000 的硬上限**（实测：offset=100000 可用，
100001 报「查询数据失败，请确认参数」）。全市场股票约 5300 只，一个自然月约 22 个
交易日 ≈ 11.7 万行，**超过上限就取不全**。

股票接口按**单个交易日**调用（``trade_date=YYYYMMDD``）。指数按官方文档显式指定
``ts_code``，白名单内每个代码一次请求整段区间；期货按白名单交易所及其交易日请求，
逐页最多 2000 行。

交易日列表来自 raw 层已落盘的 calendar 数据集，因此**必须先抓 calendar**。

## 落盘

按自然月分区：``<dataset>/<YYYY-MM>.parquet``，每个文件含当月全市场记录。
调用粒度是「天」，存储粒度是「月」——两者独立。

- Bars1dFetcher       : daily       → daily/<YYYY-MM>.parquet
- AdjFactorFetcher    : adj_factor  → adj_factor/<YYYY-MM>.parquet
- StockLimitFetcher   : stk_limit   → stk_limit/<YYYY-MM>.parquet
- SuspensionFetcher   : suspend_d   → suspend_d/<YYYY-MM>.parquet
- IndexBars1dFetcher  : index_daily → index_daily/<YYYY-MM>.parquet
- FutureBars1dFetcher : fut_daily   → fut_daily/<YYYY-MM>.parquet
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists, write_parquet
from gr_data.common.retry import int_to_date, retry_call, sleep_s, today_int
from gr_data.raw.base import BaseFetcher, RawContext, month_range
from gr_data.raw.tushare.context import FUTURE_EXCHANGES, as_tushare_context
from gr_data.raw.tushare.fetchers.reference import read_open_days, require_calendar_range
from gr_data.raw.tushare.suspension_store import (
    InvalidCoverageError,
    publish_coverage,
    read_coverage,
)


_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


PROVIDER = "tushare"

INIT_START_DATE = 20130101

# 交易日列表取自哪个交易所的日历。沪深交易日相同，取其一即可。
CALENDAR_EXCHANGE = "SSE"

DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
ADJ_FACTOR_FIELDS = "ts_code,trade_date,adj_factor"
STK_LIMIT_FIELDS = "trade_date,ts_code,pre_close,up_limit,down_limit"
# 官方输出字段（doc_id=214）。suspend_timing 仅日内停牌有值，是区分日内与全天停牌的唯一依据。
SUSPEND_FIELDS = "ts_code,trade_date,suspend_timing,suspend_type"
INDEX_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"
FUT_DAILY_FIELDS = (
    "ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,vol,amount,oi"
)
# 每日指标（估值 + 股本）。字段全取 —— 目标表只有几列对得上，其余进 raw_payload，
# 少取一个字段就等于永久丢掉一段历史（这个接口不支持按字段回补）。
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
    "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
    "total_share,float_share,free_share,total_mv,circ_mv,limit_status"
)


class _DailyFetcher(BaseFetcher):
    """按交易日抓取全市场逐日数据、按自然月分区落盘的通用基类。

    子类只需声明 ``DATASET`` / ``API_NAME`` / ``FIELDS``。
    """

    PROVIDER = PROVIDER
    API_NAME: str = ""
    FIELDS: str = ""
    #: 按白名单采集的数据集；整月重建时也要保留范围外旧行。
    SCOPED: bool = False

    def __init__(self, client: object, ctx: RawContext) -> None:
        super().__init__(client, ctx)
        self.ctx = as_tushare_context(ctx)

    # ---- 交易日 ----
    def _trading_days(self) -> list[date]:
        """从 raw 层 calendar 数据集读出开市日。

        缺失时直接抛错而不是退化成「按自然日遍历」——后者会对着几百个非交易日
        空转请求，既浪费配额，也让「真的没数据」和「日历没抓」变得无法区分。
        """
        path = self.paths.dataset_file(PROVIDER, "calendar", CALENDAR_EXCHANGE)
        cal = read_parquet_if_exists(path)
        if cal is None or cal.empty:
            raise RuntimeError(
                f"缺少交易日历 {path}。请先运行 `gr-data raw tushare --only calendar`。"
            )
        return read_open_days(cal, CALENDAR_EXCHANGE)

    # ---- 月份选择 ----
    def _existing_months(self) -> set[str]:
        d = self.paths.dataset_dir(self.PROVIDER, self.DATASET)
        if not d.exists():
            return set()
        # 只认 YYYY-MM 分区：中断残留的 YYYY-MM.tmp-* 按字典序排在月份之后，
        # 会被误当成「最新月」，导致真正的最新月不再重抓。
        return {f.stem for f in d.glob("*.parquet") if _MONTH_RE.match(f.stem)}

    def _months_to_fetch(self, mode: str) -> list[tuple[str, date, date]]:
        start = int_to_date(self.ctx.start_date or INIT_START_DATE)
        end = min(int_to_date(self.ctx.end_date or today_int()), int_to_date(today_int()))
        months = month_range(start, end)
        if mode == "init":
            return months

        # update：补齐缺失月份，并**重抓最新的已有月份**——当月还在长新数据，
        # 已落盘的文件必然是不完整的。
        existing = self._existing_months()
        newest = max(existing) if existing else None
        # 扩大白名单（新增指数代码、加入 GFEX）后，旧分区缺新范围；不重抓会静默留缺口。
        stale = self._scope_gap_months([m for m in months if m[0] in existing and m[0] != newest])
        if stale:
            self.log.info(
                "Refetching partitions missing current scope dataset=%s months=%s",
                self.DATASET,
                sorted(stale),
            )
        return [m for m in months if m[0] not in existing or m[0] == newest or m[0] in stale]

    def _scope_gap_months(self, months: list[tuple[str, date, date]]) -> set[str]:
        """已有分区里缺少当前采集范围的月份。股票按日取全市场，范围固定，不检查。"""
        return set()

    # ---- 抓取 ----
    def _fetch_day(self, day: date) -> pd.DataFrame | None:
        return retry_call(
            self.client.query_all,
            self.API_NAME,
            max_retries=self.ctx.max_retries,
            backoff_base=self.ctx.backoff_base,
            logger=self.log,
            trade_date=day.strftime("%Y%m%d"),
            fields=self.FIELDS,
        )

    def _fetch_month(
        self, first: date, last: date, days: list[date]
    ) -> tuple[list[pd.DataFrame], set[date]]:
        frames: list[pd.DataFrame] = []
        empty_days: set[date] = set()
        for day in days:
            df = self._fetch_day(day)
            sleep_s(self.ctx.sleep_between_requests)
            if df is not None and not df.empty:
                frames.append(df)
            else:
                empty_days.add(day)
        return frames, empty_days

    def _replacement_days(self, first: date, last: date, days: list[date]) -> set[date]:
        return set(days)

    def _in_scope(self, frame: pd.DataFrame) -> pd.Series:
        """旧分区里属于本次采集范围的行；只有这些行会被本次请求的日期替换。

        股票按日取全市场，范围固定，全部视为范围内。白名单数据集收窄范围后，
        范围外的旧行原样保留，不能因为本次没请求就从 raw 里删掉。
        """
        return pd.Series(True, index=frame.index)

    def fetch(self, mode: str = "update") -> int:
        trading_days = self._trading_days()
        # 同一次运行只取一次「今天」，跨过午夜也不会让各月的判定口径不同。
        today = int_to_date(today_int())
        return self._publish_months(mode, self._months_to_fetch(mode), trading_days, today)

    def _publish_months(
        self,
        mode: str,
        months: list[tuple[str, date, date]],
        trading_days: list[date],
        today: date,
    ) -> int:
        """逐月调用 ``_fetch_month`` 并替换月分区；返回写出的分区数。"""
        n = 0
        for ym, first, last in months:
            days = [d for d in trading_days if first <= d <= last]
            if not days:
                continue

            out = self.paths.dataset_file(self.PROVIDER, self.DATASET, ym)
            full_rebuild = (
                mode == "init"
                and first.day == 1
                and last.day == monthrange(last.year, last.month)[1]
            )
            # 仅整月 init 可以不读取旧分区；局部更新必须保住未请求日。
            old = None
            covered_days = list(days)
            if out.exists() and not full_rebuild and self.DATASET == "suspend_d":
                try:
                    previous = read_coverage(out)
                except InvalidCoverageError:
                    # 分区已替换、凭据未写就中断：旧内容无法证明，只信本次请求的日期，
                    # 不保留旧行，凭据随新分区重新发布。
                    self.log.warning(
                        "Invalid suspension coverage, rebuilding requested days "
                        "dataset=%s month=%s days=%d",
                        self.DATASET,
                        ym,
                        len(days),
                    )
                    full_rebuild = True
                else:
                    if previous is not None:
                        covered_days = sorted(set(covered_days) | set(previous[0]))
            if out.exists() and not full_rebuild:
                old = pd.read_parquet(out)
            elif out.exists() and self.SCOPED:
                # 白名单数据集整月 init 也只重建范围内的行；范围外旧行不在本次请求内，
                # 必须保留。旧文件不可读则报错，不能借重建静默丢掉范围外数据。
                old = pd.read_parquet(out)
                old = old.loc[~self._in_scope(old)]

            frames, empty_days = self._fetch_month(first, last, days)
            replacement_days = self._replacement_days(first, last, days)

            if full_rebuild and empty_days and self.DATASET != "suspend_d" and out.exists():
                # 非稀疏数据返回空响应时，仍需旧数据证明不会擦掉已有日期。
                # 旧文件不可读则拒绝重建；完整的新响应不依赖旧文件能否读取。
                old = pd.read_parquet(out)
            # start_date 可能落在月中；只替换已请求的交易日，保留月内其余日期。
            # 空响应同样替换对应日期，避免已撤销的 suspend_d 事件一直残留。
            if old is not None and not old.empty:
                old_dates = pd.to_datetime(old["trade_date"], format="%Y%m%d", errors="raise")
                in_scope = self._in_scope(old)
                if (
                    self.DATASET != "suspend_d"
                    and (old_dates.dt.date.isin(empty_days) & in_scope).any()
                ):
                    raise ValueError(
                        f"{self.DATASET}[{ym}] 已有数据的交易日返回空响应，拒绝覆盖；"
                        "请核对供应商后重试"
                    )
                # 白名单收窄或旧版范围更宽时，范围外的旧行不在本次请求内，必须保留。
                preserved = old.loc[~(old_dates.dt.date.isin(replacement_days) & in_scope)]
                kept_out_of_scope = int((~in_scope).sum())
                if kept_out_of_scope:
                    self.log.info(
                        "Kept out-of-scope raw rows provider=%s dataset=%s month=%s rows=%d",
                        self.PROVIDER,
                        self.DATASET,
                        ym,
                        kept_out_of_scope,
                    )
                if not preserved.empty:
                    frames.insert(0, preserved)
            if self.DATASET != "suspend_d":
                self._reject_past_empty_days(ym, empty_days, today)
            if not frames and self.DATASET != "suspend_d":
                self.log.warning(
                    "Empty raw response provider=%s dataset=%s month=%s days=%d",
                    self.PROVIDER,
                    self.DATASET,
                    ym,
                    len(days),
                )
                continue
            out_df = (
                pd.concat(frames, axis=0, ignore_index=True)
                if frames
                else pd.DataFrame(columns=self.FIELDS.split(","))
            )
            if not out_df.empty:
                # 新旧 raw 可能分别使用 int8／字符串日期，Arrow 不能序列化混合列。
                # 仅统一为 YYYYMMDD 字符串，不改源日期含义、字段名或数值单位。
                dates = pd.to_datetime(out_df["trade_date"], format="%Y%m%d", errors="raise")
                if dates.isna().any():
                    raise ValueError(f"{self.DATASET}[{ym}] 含空 trade_date，拒绝覆盖")
                out_df["trade_date"] = dates.dt.strftime("%Y%m%d")
            write_parquet(out_df, out, append=False)
            if self.DATASET == "suspend_d":
                publish_coverage(out, covered_days)
            self.log.info(
                "Raw partition written provider=%s dataset=%s month=%s rows=%d days=%d",
                self.PROVIDER,
                self.DATASET,
                ym,
                len(out_df),
                len(days),
            )
            n += 1
        return n

    def _reject_past_empty_days(self, ym: str, empty_days: set[date], today: date) -> None:
        """非稀疏数据集：今天以前的交易日返回空响应即拒绝写出该月分区。

        不完整的分区一旦写出，这个月不再是最新月后 ``update`` 就不会重抓，缺口会永久
        留下。今天的空响应可能只是供应商尚未发布，留给下次 ``update`` 重抓最新月补齐。
        """
        missing = sorted(d for d in empty_days if d < today)
        if missing:
            raise ValueError(
                f"{self.DATASET}[{ym}] 有 {len(missing)} 个过去的交易日返回空响应，"
                f"样例 {[d.isoformat() for d in missing[:5]]}；"
                "拒绝写出不完整分区，请核对供应商后重试"
            )
        if empty_days:
            self.log.info(
                "Trading day not yet published provider=%s dataset=%s month=%s days=%s",
                self.PROVIDER,
                self.DATASET,
                ym,
                [d.isoformat() for d in sorted(empty_days)],
            )


class Bars1dFetcher(_DailyFetcher):
    DATASET = "daily"
    API_NAME = "daily"
    FIELDS = DAILY_FIELDS


class AdjFactorFetcher(_DailyFetcher):
    DATASET = "adj_factor"
    API_NAME = "adj_factor"
    FIELDS = ADJ_FACTOR_FIELDS


class StockLimitFetcher(_DailyFetcher):
    DATASET = "stk_limit"
    API_NAME = "stk_limit"
    FIELDS = STK_LIMIT_FIELDS


class SuspensionFetcher(_DailyFetcher):
    DATASET = "suspend_d"
    API_NAME = "suspend_d"
    FIELDS = SUSPEND_FIELDS


class DailyBasicFetcher(_DailyFetcher):
    DATASET = "daily_basic"
    API_NAME = "daily_basic"
    FIELDS = DAILY_BASIC_FIELDS


class IndexBars1dFetcher(_DailyFetcher):
    """白名单内普通指数逐代码整段采集；申万须使用独立接口，本链路明确排除。"""

    DATASET = "index_daily"
    API_NAME = "index_daily"
    FIELDS = INDEX_DAILY_FIELDS
    SCOPED = True

    def _replacement_days(self, first: date, last: date, days: list[date]) -> set[date]:
        # 月度接口可能返回非沪市开市日；按真实请求闭区间替换，避免旧、新行重复。
        return set(pd.date_range(first, last).date)

    def _in_scope(self, frame: pd.DataFrame) -> pd.Series:
        """只有本次所选代码的旧行参与替换；其余代码（旧版按日取得的全量）保留。"""
        selected = {code for code, _, _ in self._scope}
        return frame["ts_code"].astype(str).str.strip().isin(selected)

    def _trading_days(self) -> list[date]:
        days = super()._trading_days()
        frame = pd.read_parquet(self.paths.dataset_file(PROVIDER, "calendar", CALENDAR_EXCHANGE))
        require_calendar_range(
            frame,
            int_to_date(self.ctx.start_date or INIT_START_DATE),
            min(int_to_date(self.ctx.end_date or today_int()), int_to_date(today_int())),
            CALENDAR_EXCHANGE,
        )
        return days

    def fetch(self, mode: str = "update") -> int:
        """白名单内每个代码对每段连续月份只请求一次，全部校验通过后再逐月落盘。

        请求次数 = 代码数 × 连续月份段数，与月份数无关。任一代码在过去开市日缺数据即
        汇总报错，不写任何分区；今天尚未发布的数据留给下次 ``update``。
        """
        trading_days = self._trading_days()
        self._today = int_to_date(today_int())
        self._open_days = trading_days
        self._scope = self._selected_indexes()
        months = [
            m for m in self._months_to_fetch(mode) if any(m[1] <= d <= m[2] for d in trading_days)
        ]
        if not months:
            return 0
        self._prefetch(months, trading_days)
        return self._publish_months(mode, months, trading_days, self._today)

    def _scope_gap_months(self, months: list[tuple[str, date, date]]) -> set[str]:
        """已有分区缺某个所选代码（该月有其应有的过去开市日）即需重抓。"""
        stale: set[str] = set()
        for ym, first, last in months:
            path = self.paths.dataset_file(PROVIDER, self.DATASET, ym)
            present = set(
                pd.read_parquet(path, columns=["ts_code"])["ts_code"].astype(str).str.strip()
            )
            days = [d for d in self._open_days if first <= d <= last and d < self._today]
            for code, listed_day, expired_day in self._scope:
                if code not in present and any(
                    (listed_day is None or d >= listed_day)
                    and (expired_day is None or d <= expired_day)
                    for d in days
                ):
                    stale.add(ym)
                    break
        return stale

    def _selected_indexes(self) -> list[tuple[str, date | None, date | None]]:
        """按 ``index_codes`` ∪ ``index_markets`` 选代码；申万一律排除。"""
        codes, markets = set(self.ctx.index_codes), set(self.ctx.index_markets)
        if not codes and not markets:
            raise ValueError("index_daily requires providers.tushare.index_codes or index_markets")
        path = self.paths.dataset_file(PROVIDER, "instruments", "index")
        indexes = pd.read_parquet(path)
        required = {"ts_code", "list_date", "exp_date"} | ({"market"} if markets else set())
        if indexes.empty or not required <= set(indexes.columns):
            raise ValueError("Missing index instruments; run instruments first")
        if indexes["ts_code"].isna().any():
            raise ValueError("Invalid index instrument code")
        indexes = indexes.copy()
        indexes["ts_code"] = indexes["ts_code"].astype(str).str.strip()
        if indexes["ts_code"].eq("").any():
            raise ValueError("Invalid index instrument code")
        indexes = indexes.drop_duplicates("ts_code", keep="last")
        unknown = sorted(codes - set(indexes["ts_code"]))
        if unknown:
            raise ValueError(f"Unknown index codes in index_codes: {unknown[:10]}")
        sw = indexes["ts_code"].str.endswith(".SI")
        if "market" in indexes:
            sw |= indexes["market"].eq("SW")
        by_code = indexes["ts_code"].isin(codes)
        if (by_code & sw).any():
            bad = indexes.loc[by_code & sw, "ts_code"].tolist()
            raise ValueError(f"SW index codes require a separate endpoint: {bad[:10]}")
        picked = by_code
        if markets:
            picked = picked | indexes["market"].isin(markets)
        picked &= ~sw
        if not picked.any():
            raise ValueError("No index instruments selected")
        self.log.info(
            "Index scope selected codes=%d explicit=%d markets=%s",
            int(picked.sum()),
            len(codes),
            sorted(markets),
        )
        return [
            (code, _optional_date(listed), _optional_date(expired))
            for code, listed, expired in indexes.loc[
                picked, ["ts_code", "list_date", "exp_date"]
            ].itertuples(index=False)
        ]

    def _prefetch(self, months: list[tuple[str, date, date]], trading_days: list[date]) -> None:
        # update 可能选中不相邻的月份：按连续段请求，不为中间未选月份多取多年数据。
        runs: list[tuple[date, date]] = []
        for _, first, last in months:
            if runs and first == runs[-1][1] + timedelta(days=1):
                runs[-1] = (runs[-1][0], last)
            else:
                runs.append((first, last))
        wanted = [d for d in trading_days if any(f <= d <= e for f, e in runs)]
        frames: list[pd.DataFrame] = []
        expected_days: set[date] = set()
        incomplete: list[str] = []
        for code, listed_day, expired_day in self._scope:
            # list_date 是发布日期：只限定完整性检查，不截掉供应商提供的发布前回溯值。
            expected = {
                d
                for d in wanted
                if (listed_day is None or d >= listed_day)
                and (expired_day is None or d <= expired_day)
            }
            expected_days |= expected
            received: set[date] = set()
            code_frames: list[pd.DataFrame] = []
            for first, last in runs:
                df = retry_call(
                    self.client.query_all,
                    self.API_NAME,
                    ts_code=code,
                    start_date=first.strftime("%Y%m%d"),
                    end_date=last.strftime("%Y%m%d"),
                    fields=self.FIELDS,
                    max_retries=self.ctx.max_retries,
                    backoff_base=self.ctx.backoff_base,
                    logger=self.log,
                )
                sleep_s(self.ctx.sleep_between_requests)
                received |= _response_days(df, first, last, code=code)
                if df is not None and not df.empty:
                    code_frames.append(df)
            missing = sorted(d for d in expected - received if d < self._today)
            if missing:
                # 继续请求其余代码，一次报全缺口，避免逐个修配置反复消耗配额。
                incomplete.append(f"{code}:{len(missing)}:{missing[0].isoformat()}")
                continue
            frames.extend(code_frames)
        if incomplete:
            raise ValueError(
                f"index_daily incomplete codes={len(incomplete)} "
                f"samples(code:missing_days:first_missing)={incomplete[:10]}"
            )
        rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        self._rows = rows
        self._row_days = (
            pd.to_datetime(rows["trade_date"].astype(str), format="%Y%m%d").dt.date
            if not rows.empty
            else pd.Series(dtype=object)
        )
        self._expected_days = expected_days

    def _fetch_month(
        self, first: date, last: date, days: list[date]
    ) -> tuple[list[pd.DataFrame], set[date]]:
        """从整段预取结果切出本月；不再发请求。"""
        mask = (self._row_days >= first) & (self._row_days <= last)
        part = self._rows.loc[mask]
        expected = {d for d in self._expected_days if first <= d <= last}
        # 全部指数已终止／尚未发布时允许无请求期数据，不把它误报为全市场缺失。
        return ([part] if not part.empty else []), expected - set(self._row_days.loc[mask])


class FutureBars1dFetcher(_DailyFetcher):
    """期货按白名单内各交易所开市日取数；日期沿用供应商交易日，夜盘不另行改日。"""

    DATASET = "fut_daily"
    API_NAME = "fut_daily"
    FIELDS = FUT_DAILY_FIELDS
    SCOPED = True

    def _trading_days(self) -> list[date]:
        instruments = pd.read_parquet(self.paths.dataset_file(PROVIDER, "instruments", "future"))
        if instruments.empty or not {"ts_code", "exchange"} <= set(instruments.columns):
            raise ValueError("Missing future instruments; run instruments first")
        if instruments[["ts_code", "exchange"]].isna().any().any():
            raise ValueError("Invalid future instrument keys")
        exchanges = set(instruments["exchange"].astype(str).str.strip())
        if not exchanges or exchanges - set(FUTURE_EXCHANGES):
            raise ValueError("Invalid future instrument exchanges")
        selected = exchanges & set(self.ctx.future_exchanges)
        excluded = sorted(exchanges - selected)
        if excluded:
            # 白名单外的交易所整所不取，记 WARNING 让覆盖缺口可见。
            self.log.warning("Future exchanges excluded by config exchanges=%s", excluded)
        if not selected:
            raise ValueError("No future instruments in providers.tushare.future_exchanges")
        start = int_to_date(self.ctx.start_date or INIT_START_DATE)
        end = min(int_to_date(self.ctx.end_date or today_int()), int_to_date(today_int()))
        self._exchange_days: dict[str, set[date]] = {}
        self._exchange_start: dict[str, date] = {}
        for exchange in sorted(selected):
            # 交易所开业晚于 start_date（GFEX 2022-12、INE 2018-03）时，开业前不要求日历和
            # 日线；起点取源清单里该所最早上市日，避免旧配置长区间整批失败或空耗配额。
            first_listed = _first_listing(instruments, exchange)
            effective = max(start, first_listed) if first_listed is not None else start
            self._exchange_start[exchange] = effective
            if effective > start:
                self.log.info(
                    "Future exchange scope starts at first listing exchange=%s start=%s",
                    exchange,
                    effective.isoformat(),
                )
            path = self.paths.dataset_file(PROVIDER, "future_calendar", exchange)
            if not path.exists():
                raise ValueError(f"Missing future_calendar[{exchange}]; run future_calendar first")
            frame = pd.read_parquet(path)
            open_days = read_open_days(frame, exchange)
            if effective > end:
                self._exchange_days[exchange] = set()
                continue
            require_calendar_range(frame, effective, end, exchange)
            self._exchange_days[exchange] = {d for d in open_days if d >= effective}
        return sorted(set().union(*self._exchange_days.values()))

    def _in_scope(self, frame: pd.DataFrame) -> pd.Series:
        """白名单内交易所、且不早于该所有效起点的旧行才参与替换。

        收窄白名单后其余交易所的旧行保留；有效起点之前本次不请求该所，旧行也保留
        （清单缺老合约导致起点推后时，不能借同日其他所的重抓把它删掉）。
        """
        starts = {_FUTURE_SUFFIXES.get(e, e): s for e, s in self._exchange_start.items()}
        suffixes = frame["ts_code"].astype(str).str.strip().str.rsplit(".", n=1).str[-1]
        dates = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d").dt.date
        return pd.Series(
            [
                (begin := starts.get(suffix)) is not None and day >= begin
                for suffix, day in zip(suffixes, dates, strict=True)
            ],
            index=frame.index,
            dtype=bool,
        )

    def _fetch_day(self, day: date) -> pd.DataFrame | None:
        frames = []
        for exchange, days in self._exchange_days.items():
            if day not in days:
                continue
            df = retry_call(
                self.client.query_all,
                self.API_NAME,
                trade_date=day.strftime("%Y%m%d"),
                exchange=exchange,
                fields=self.FIELDS,
                max_retries=self.ctx.max_retries,
                backoff_base=self.ctx.backoff_base,
                logger=self.log,
            )
            sleep_s(self.ctx.sleep_between_requests)
            if df is None or df.empty:
                if day < int_to_date(today_int()):
                    raise ValueError(f"fut_daily incomplete exchange={exchange} day={day}")
                continue
            _response_days(df, day, day)
            # 不改 raw 后缀，仅检查响应是否属于本次请求的交易所。
            suffix = _FUTURE_SUFFIXES.get(exchange, exchange)
            if not df["ts_code"].astype(str).str.endswith(f".{suffix}").all():
                raise ValueError(f"fut_daily unexpected exchange response: {exchange}")
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _scope_gap_months(self, months: list[tuple[str, date, date]]) -> set[str]:
        """已有分区缺某个所选交易所（该月有其过去开市日）即需重抓，如新加入 GFEX。"""
        today = int_to_date(today_int())
        stale: set[str] = set()
        for ym, first, last in months:
            path = self.paths.dataset_file(PROVIDER, self.DATASET, ym)
            codes = pd.read_parquet(path, columns=["ts_code"])["ts_code"].astype(str).str.strip()
            suffixes = set(codes.str.rsplit(".", n=1).str[-1])
            for exchange, days in self._exchange_days.items():
                if _FUTURE_SUFFIXES.get(exchange, exchange) not in suffixes and any(
                    first <= d <= last and d < today for d in days
                ):
                    stale.add(ym)
                    break
        return stale


# Tushare 期货代码后缀与交易所码不同；未列出的（DCE、INE）两者相同。
_FUTURE_SUFFIXES = {"CFFEX": "CFX", "SHFE": "SHF", "CZCE": "ZCE", "GFEX": "GFE"}


def _first_listing(instruments: pd.DataFrame, exchange: str) -> date | None:
    """源期货清单中该交易所最早的上市日；缺列或全空返回 None（按 start_date 严格检查）。"""
    if "list_date" not in instruments:
        return None
    rows = instruments.loc[instruments["exchange"].astype(str).str.strip().eq(exchange)]
    listed = [d for d in (_optional_date(v) for v in rows["list_date"]) if d is not None]
    return min(listed) if listed else None


def _optional_date(value: object) -> date | None:
    if pd.isna(value) or str(value).strip() in ("", "0", "00000000"):
        return None
    # parquet 可能把 YYYYMMDD 存成浮点（如 20050104.0），先转整数再解析。
    text = str(value).strip()
    return int_to_date(int(float(text)) if "." in text else int(text))


def _response_days(
    df: pd.DataFrame | None, first: date, last: date, *, code: str | None = None
) -> set[date]:
    """拒绝越界日期、错代码和重复业务键，防止污染整月 raw。"""
    if df is None or df.empty:
        return set()
    if not {"ts_code", "trade_date"} <= set(df.columns) or df["ts_code"].isna().any():
        raise ValueError("Invalid market response keys")
    codes = df["ts_code"].astype(str).str.strip()
    dates = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="raise").dt.date
    if codes.eq("").any() or dates.isna().any() or ((dates < first) | (dates > last)).any():
        raise ValueError("Market response outside requested dates or empty keys")
    if code is not None and not codes.eq(code).all():
        raise ValueError(f"Unexpected index response code: {code}")
    if pd.DataFrame({"code": codes, "date": dates}).duplicated().any():
        raise ValueError("Duplicate market response keys")
    return set(dates)
