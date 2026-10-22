"""Tushare raw fetchers：日线及其配套的逐日数据集。

## 为什么按「交易日」调用而不是「日期区间」

Tushare 对一次查询的 ``offset`` 有 **100000 的硬上限**（实测：offset=100000 可用，
100001 报「查询数据失败，请确认参数」）。全市场股票约 5300 只，一个自然月约 22 个
交易日 ≈ 11.7 万行，**超过上限就取不全**。

所以这些接口一律按**单个交易日**调用（``trade_date=YYYYMMDD``），每天约 5300 行、
一页取完，永远碰不到 offset 上限。另有一个接口硬性要求如此：``index_daily``
不带 ``ts_code`` 时不接受日期区间，只接受 ``trade_date``。

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
from datetime import date

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists, write_parquet
from gr_data.common.retry import int_to_date, retry_call, sleep_s, today_int
from gr_data.raw.base import BaseFetcher, month_range
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
        open_days = cal[pd.to_numeric(cal["is_open"], errors="coerce") == 1]
        days = pd.to_datetime(open_days["cal_date"], format="%Y%m%d", errors="coerce")
        return sorted({d.date() for d in days if pd.notna(d)})

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
        months = month_range(start, int_to_date(today_int()))
        if mode == "init":
            return months

        # update：补齐缺失月份，并**重抓最新的已有月份**——当月还在长新数据，
        # 已落盘的文件必然是不完整的。
        existing = self._existing_months()
        newest = max(existing) if existing else None
        return [m for m in months if m[0] not in existing or m[0] == newest]

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

    def fetch(self, mode: str = "update") -> int:
        trading_days = self._trading_days()
        # 同一次运行只取一次「今天」，跨过午夜也不会让各月的判定口径不同。
        today = int_to_date(today_int())
        n = 0
        for ym, first, last in self._months_to_fetch(mode):
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

            frames: list[pd.DataFrame] = []
            empty_days: set[date] = set()
            for day in days:
                df = self._fetch_day(day)
                sleep_s(self.ctx.sleep_between_requests)
                if df is not None and not df.empty:
                    frames.append(df)
                else:
                    empty_days.add(day)

            if full_rebuild and empty_days and self.DATASET != "suspend_d" and out.exists():
                # 非稀疏数据返回空响应时，仍需旧数据证明不会擦掉已有日期。
                # 旧文件不可读则拒绝重建；完整的新响应不依赖旧文件能否读取。
                old = pd.read_parquet(out)
            # start_date 可能落在月中；只替换已请求的交易日，保留月内其余日期。
            # 空响应同样替换对应日期，避免已撤销的 suspend_d 事件一直残留。
            if old is not None and not old.empty:
                old_dates = pd.to_datetime(old["trade_date"], format="%Y%m%d", errors="raise")
                if self.DATASET != "suspend_d" and old_dates.dt.date.isin(empty_days).any():
                    raise ValueError(
                        f"{self.DATASET}[{ym}] 已有数据的交易日返回空响应，拒绝覆盖；"
                        "请核对供应商后重试"
                    )
                preserved = old.loc[~old_dates.dt.date.isin(days)]
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
    DATASET = "index_daily"
    API_NAME = "index_daily"
    FIELDS = INDEX_DAILY_FIELDS


class FutureBars1dFetcher(_DailyFetcher):
    DATASET = "fut_daily"
    API_NAME = "fut_daily"
    FIELDS = FUT_DAILY_FIELDS
