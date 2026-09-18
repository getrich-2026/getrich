"""补充任务离线样本；其中准入证据仅为测试 fixture，不表示账号获准。"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.config.ricequant import parse_ricequant_options
from gr_data.raw.base import RawContext
from gr_data.raw.ricequant.planner import plan_slices
from gr_tools.config import load_environment


@pytest.fixture
def rq_config(tmp_path):
    def build(names=("rq_index_daily",), **overrides):
        entries = {}
        for name in names:
            entries[name] = dict(
                selected=True,
                contract_version="v1",
                start_date="2024-01-02",
                end_date="2024-01-03",
                index_codes=["866002.RI"],
                fields=["close"] if name == "rq_index_daily" else [],
                enable_bjse=False,
                evidence=dict(
                    tushare_overlap="distinct",
                    datayes_overlap="distinct",
                    rq_permission="confirmed",
                    contract_status="verified",
                    references=["fixture-only"],
                    checked_on="2026-09-18",
                ),
            )
            entries[name].update(overrides)
        env = load_environment(
            root=tmp_path,
            environ={
                "RICEQUANT_API_KEY": "fixture-secret",
                "RICEQUANT_ENABLED": "true",
                "RAW_PARQUET_ROOT": str(tmp_path / "raw"),
            },
        )
        return Config(
            {
                "providers": {
                    "ricequant": {
                        "license_env": "RICEQUANT_API_KEY",
                        "supplements": {"datasets": entries},
                        "rate_limit": {
                            "max_retries": 2,
                            "sleep_between_requests_sec": 0,
                            "retry_backoff_base_sec": 0,
                        },
                    }
                }
            },
            environment=env,
        )

    return build


@pytest.fixture
def rq_options(rq_config):
    def build(name="rq_index_daily", **overrides):
        return parse_ricequant_options(rq_config((name,), **overrides), phase="raw").datasets[name]

    return build


@pytest.fixture
def rq_request(rq_options):
    def build(name="rq_index_daily", **overrides):
        options = rq_options(name, **overrides)
        days = tuple(pd.bdate_range(options.start_date, options.end_date).date)
        return plan_slices(options, days, "a" * 64, mode="init", completed=set())[0]

    return build


class FakeSupplementClient:
    def __init__(self):
        self.calls = []
        self.quota_used = 0
        self.failures = []
        self.close = 10.0

    def get_quota(self):
        self.calls.append(("quota",))
        return {"bytes_limit": 1000, "bytes_used": self.quota_used}

    def get_price(self, codes, start, end, **kwargs):
        self.calls.append(("price", codes, start, end, kwargs))
        if self.failures:
            raise self.failures.pop(0)
        rows = [
            {"order_book_id": code, "date": d, "close": self.close}
            for code in codes
            for d in pd.bdate_range(start, end)
        ]
        return pd.DataFrame(rows).set_index(["order_book_id", "date"])

    def index_components(self, code, *, date):
        self.calls.append(("components", code, date))
        return ["000001.XSHE", "600000.XSHG"], pd.Timestamp(date + " 19:00:00")

    def index_weights(self, code, *, date):
        self.calls.append(("weights", code, date))
        return pd.Series([0.4, 0.6], index=["000001.XSHE", "600000.XSHG"])


@pytest.fixture
def rq_client():
    return FakeSupplementClient()


@pytest.fixture
def rq_context(tmp_path):
    paths = RawPaths(tmp_path / "raw")
    days = pd.date_range(date(2024, 1, 1), date(2024, 3, 31))
    path = paths.dataset_file("tushare", "calendar", "SSE")
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        {"cal_date": days.strftime("%Y%m%d"), "is_open": (days.weekday < 5).astype(int)}
    ).to_parquet(path)
    return RawContext(
        paths, {"max_retries": 2, "sleep_between_requests_sec": 0, "retry_backoff_base_sec": 0}
    )
