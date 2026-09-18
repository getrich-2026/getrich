"""raw parquet 路径约定。

所有 raw 层落地路径集中在此定义，杜绝散落硬编码（见 docs/conventions/parquet-layout.md）。

布局::

    <raw_root>/<provider>/<dataset>/...

  yinhe/calendar/calendar_<market>.parquet
  yinhe/hist_code_list/hist_code_list_<security_type>.parquet
  yinhe/backward_factor/backward_factor_<security_type>_chunk<NNNN>.parquet
  yinhe/kline_day/<code>/<YYYY-MM>.parquet
  yinhe/kline_min1/<code>/<YYYY-MM>.parquet
  ricequant/instruments/<asset>.parquet
  ricequant/calendar/<exchange>.parquet
  ricequant/bars_1d/<asset>/<code>.parquet
  insight/basic_info/<security_type>.parquet
  insight/trading_days/<exchange>.parquet
  insight/kline_day/<code>/<YYYY-MM>.parquet
  tushare/instruments/<asset>.parquet
  tushare/calendar/<exchange>.parquet
  tushare/<daily|adj_factor|stk_limit|suspend_d|index_daily|fut_daily>/<YYYY-MM>.parquet
"""

from __future__ import annotations

from pathlib import Path


DEFAULT_RAW_ROOT = Path("/opt/raw_parquet")


class RawPaths:
    """以 raw_root 为基准解析各 provider/dataset 的落地路径。"""

    def __init__(self, raw_root: str | Path = DEFAULT_RAW_ROOT):
        self.root = Path(raw_root)

    # ---- 通用 ----
    def provider_dir(self, provider: str) -> Path:
        return self.root / provider

    def dataset_dir(self, provider: str, dataset: str) -> Path:
        return self.root / provider / dataset

    def dataset_file(self, provider: str, dataset: str, name: str) -> Path:
        """单文件数据集（如 calendar/instruments）。name 不含扩展名。"""
        return self.dataset_dir(provider, dataset) / f"{name}.parquet"

    def ricequant_variant(self, dataset: str, version: str, variant: str) -> Path:
        """补充观察的隔离目录；拒绝路径片段越界和目录符号链接逃逸。"""
        import re

        from gr_data.common.ricequant_specs import INDEX_SPECS, RawIntegrityError

        if dataset not in {*INDEX_SPECS, "rq_risk_model"} or not re.fullmatch(r"v[0-9]+", version):
            raise RawIntegrityError("未知米筐数据集或契约目录")
        if not re.fullmatch(r"[0-9a-f]{64}", variant):
            raise RawIntegrityError("非法米筐 variant")
        root = self.root.resolve()
        path = self.dataset_dir("ricequant", dataset) / version / variant
        if not path.resolve().is_relative_to(root):
            raise RawIntegrityError("米筐观察目录逃出 raw_root")
        return path

    def code_month_file(self, provider: str, dataset: str, code: str, ym: str) -> Path:
        """按 code + 月分区的数据集（K 线）。ym 形如 '2024-01'。"""
        return self.dataset_dir(provider, dataset) / code / f"{ym}.parquet"

    def code_dir(self, provider: str, dataset: str, code: str) -> Path:
        return self.dataset_dir(provider, dataset) / code

    # ---- 同步水位文件（增量 fetcher 用）----
    def sync_status_file(self, provider: str, dataset: str) -> Path:
        return self.dataset_dir(provider, dataset) / "_sync_status.json"

    def ensure(self, *parts: str) -> Path:
        """创建并返回 root 下的子目录。"""
        p = self.root.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p
