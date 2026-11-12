"""完整年度财务指标原件；VIP按年度分页，避免逐股全历史回补。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from gr_data.common.parquet import write_parquet
from gr_data.common.paths import RawPaths
from gr_data.common.retry import PermanentError
from gr_data.raw.tushare.client import TushareClient


@dataclass(frozen=True)
class AnnualRoeRaw:
    """完整财务观察的原件路径与采集完成时间。"""

    files: tuple[Path, ...]
    observed_at: datetime


def fetch_annual_roe(
    client: TushareClient, paths: RawPaths, *, years: tuple[int, ...]
) -> AnnualRoeRaw:
    """请求指定年度的全部公告修订；任一请求失败不返回完整观察。"""
    if not years or len(set(years)) != len(years) or any(y < 1990 or y > 9998 for y in years):
        raise ValueError("Annual financial years must be nonempty and unique")
    observation = uuid4().hex
    files = []
    for year in sorted(years):
        try:
            frame = client.query_all(
                "fina_indicator_vip",
                period=f"{year}1231",
                fields="ts_code,end_date,ann_date,roe_waa,update_flag",
            )
        except PermanentError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Annual financial request failed year={year}") from exc
        if frame.empty or not {"ts_code", "end_date", "ann_date", "roe_waa"} <= set(frame):
            raise ValueError("Annual financial response is incomplete")
        path = paths.dataset_file("tushare", "fina_indicator", f"{observation}/{year}")
        write_parquet(frame, path)
        files.append(path)
    return AnnualRoeRaw(tuple(files), datetime.now(timezone.utc))
