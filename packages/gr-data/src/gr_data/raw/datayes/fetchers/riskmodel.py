"""DataYes CNE6-SW21 风险模型五表的 raw fetcher。

文件名用 `riskmodel` 而不是 `market`：这批数据不是行情，是模型估计的输出。

## 落盘与切分

统一落 ``datayes/<dataset>/<YYYY-MM>.parquet``，**原样保留供应商列名与数值**
（raw 层不归一化，见 README 的分层铁律）。

调用粒度与存储粒度分开：三张个股表按**旬**（10 天）请求，因为按月约 10.5 万行
会撞上单次 10 万条的上限；协方差按月、因子收益一次一年，它们每天只有几十到
一千多行。切分参数是类属性，改的时候连同这段理由一起看。

## `update` 为什么重抓最近两个月

通联会重述历史（回算、修正），不是只追加。只重抓「最新的一个月」会漏掉上个月
被改过的行，而这种漏是静默的 —— 库里留着旧值，看起来一切正常。
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from gr_data.common.parquet import read_parquet_if_exists, write_parquet
from gr_data.common.retry import int_to_date, retry_call, today_int
from gr_data.raw.base import BaseFetcher, month_range
from gr_data.raw.datayes.client import NotAuthorizedError, QuotaExhaustedError


PROVIDER = "datayes"

#: 本轮导入区间的默认起点（D10）。可被 providers.datayes.start_date 覆盖。
INIT_START_DATE = 20250101


class _DatayesMonthlyFetcher(BaseFetcher):
    """按自然月落盘、按 `CHUNK_DAYS` 请求的通用 fetcher。"""

    PROVIDER = PROVIDER
    API_PATH: str = ""
    CHUNK_DAYS: int = 10
    #: update 模式重抓最近 N 个月，覆盖「当月未完结」与「近期被重述」两种情况
    UPDATE_RECENT_MONTHS: int = 2

    def _months(self, mode: str) -> list[tuple[str, date, date]]:
        start = int_to_date(self.ctx.start_date or INIT_START_DATE)
        months = month_range(start, int_to_date(today_int()))
        if mode == "init":
            return months

        existing = {
            p.stem for p in self.paths.dataset_dir(PROVIDER, self.DATASET).glob("*.parquet")
        }
        missing = [m for m in months if m[0] not in existing]
        recent = months[-self.UPDATE_RECENT_MONTHS :] if months else []
        # 保序去重
        wanted = {m[0] for m in missing} | {m[0] for m in recent}
        return [m for m in months if m[0] in wanted]

    def fetch(self, mode: str = "update") -> int:
        written = 0
        for ym, begin, end in self._months(mode):
            try:
                df = retry_call(
                    self.client.query_range,
                    self.API_PATH,
                    begin,
                    end,
                    chunk_days=self.CHUNK_DAYS,
                    max_retries=self.ctx.max_retries,
                    backoff_base=self.ctx.backoff_base,
                    logger=self.log,
                )
            except QuotaExhaustedError:
                # 配额耗尽：记下断点后停整批。继续调用只是白烧剩余配额，
                # 而且会让真正的原因淹没在一串失败日志里。
                self._write_checkpoint(ym, "quota")
                self.log.error("配额耗尽，已在 %s 处停止；下次 --mode update 从此处续抓", ym)
                return written
            except NotAuthorizedError:
                # 未购买该表：只中断这一个 dataset，让 runner 继续下一个
                self.log.error("%s 未授权，跳过该表", self.DATASET)
                raise

            if df.empty:
                self.log.debug("%s %s 无数据", self.DATASET, ym)
                continue
            write_parquet(df, self.paths.dataset_file(PROVIDER, self.DATASET, ym), append=False)
            written += 1
            self.log.info("%s %s 落盘 %d 行", self.DATASET, ym, len(df))
        return written

    def _write_checkpoint(self, ym: str, reason: str) -> None:
        import json

        path = self.paths.sync_status_file(PROVIDER, self.DATASET)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"stopped_at_month": ym, "reason": reason}, ensure_ascii=False),
            encoding="utf-8",
        )

    def read_month(self, ym: str) -> pd.DataFrame | None:
        return read_parquet_if_exists(self.paths.dataset_file(PROVIDER, self.DATASET, ym))


class ExposureFetcher(_DatayesMonthlyFetcher):
    """因子暴露 X（标的 × 日 × 58 因子）。全量里最大的一张。

    `CHUNK_DAYS` 取 4 而不是 10，是**实测逼出来的**，不是按行数上限算的：
    按 10 天切时每次响应约 4 MB（约 7 个交易日 × 5500 只 × 58 列），
    供应商在这个量级上会中途断连（``peer closed connection without sending
    complete message body``），随后转成持续的读超时。

    更麻烦的是这类超时**拖不死也退不出**：httpx 的 `timeout` 是「两次收到字节之间
    的最长间隔」，服务端慢速涓流时会被不断重置，没有整体超时兜底 —— 实测单个
    chunk 卡了 33 分钟仍未超时，而 `retry_call` 重试 5 次耗尽后会让整批抓取中断。
    把响应压到约 1.5 MB 之后就不再触发。代价是请求数从约 180 涨到约 490。
    """

    DATASET = "exposure_cne6_sw21"
    API_PATH = "/api/equity/getDy1dExposureCNE6SW21.json"
    CHUNK_DAYS = 4


class SpecificReturnFetcher(_DatayesMonthlyFetcher):
    """特质收益 u（标的 × 日，单列 SPRET）。"""

    DATASET = "specific_ret_cne6_sw21"
    API_PATH = "/api/equity/getDy1dSpecificRetCNE6SW21.json"
    CHUNK_DAYS = 10


class SpecificRiskFetcher(_DatayesMonthlyFetcher):
    """特质风险 σ_u（标的 × 日，单列 SRISK，年化百分比波动率）。"""

    DATASET = "srisk_cne6_sw21"
    API_PATH = "/api/equity/getDy1dSriskCNE6SW21.json"
    CHUNK_DAYS = 10


class FactorCovarianceFetcher(_DatayesMonthlyFetcher):
    """因子协方差 F（因子 × 日 × 58 因子），每天约 50 行。"""

    DATASET = "factor_cov_cne6_sw21"
    API_PATH = "/api/equity/getDy1dCovarianceCNE6SW21.json"
    CHUNK_DAYS = 31


class FactorReturnFetcher(_DatayesMonthlyFetcher):
    """因子收益 f（日 × 58 因子），每天 1 行，可以一次取很长的区间。"""

    DATASET = "factor_ret_cne6_sw21"
    API_PATH = "/api/equity/getDy1dFactorRetCNE6SW21.json"
    CHUNK_DAYS = 366
