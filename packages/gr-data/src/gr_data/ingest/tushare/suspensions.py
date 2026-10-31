"""读取经过哈希和覆盖验证的停复牌观察，禁止将旧稀疏文件视作完整覆盖。"""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from gr_data.common.paths import RawPaths
from gr_data.common.quality import RowValidationError
from gr_data.ingest.tushare.adapter import TushareAdapter
from gr_data.raw.tushare.suspension_store import normalize_events, read_coverage


def read_suspensions(
    paths: RawPaths,
    months: tuple[str, ...],
    *,
    required: bool,
    adapter: TushareAdapter | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """读取指定月分区；required=False 容许缺文件／旧凭据，损坏仍报错。

    Returns:
        规范事件（trade_date 为 date）与成功请求的日期覆盖；不推断缺分区为无事件。
    """
    events, coverage = [], []
    for month in months:
        path = paths.dataset_file("tushare", "suspend_d", month)
        if not path.exists():
            if required or path.with_suffix(".coverage.json").exists():
                raise ValueError(f"Missing suspension partition: {month}")
            continue
        content = path.read_bytes()
        proof = read_coverage(path, content=content)
        if proof is None:
            if required:
                raise ValueError(f"Missing suspension coverage; recapture suspend_d: {month}")
            continue
        days, observed, digest = proof
        raw = (
            adapter.read_month("suspend_d", month) if adapter else pd.read_parquet(BytesIO(content))
        )
        if raw is None:
            raise ValueError(f"Missing suspension partition: {month}")
        frame = normalize_events(raw)
        if not frame["trade_date"].isin(days).all():
            raise RowValidationError(f"Suspension events outside proven coverage: {month}")
        frame["observed_at"] = observed
        events.append(frame)
        coverage.extend(
            {"trading_day": day, "source": "tushare", "raw_sha256": digest, "observed_at": observed}
            for day in days
        )
    event_columns = ["ts_code", "trade_date", "suspend_type", "suspend_timing", "observed_at"]
    coverage_columns = ["trading_day", "source", "raw_sha256", "observed_at"]
    return (
        pd.concat(events, ignore_index=True) if events else pd.DataFrame(columns=event_columns),
        pd.DataFrame(coverage, columns=coverage_columns),
    )
