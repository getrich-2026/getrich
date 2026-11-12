"""年度ROE：单位、公告日期和缺失边界。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import polars as pl
import pytest
from gr_data.ingest.tushare.financial import normalize_annual_roe


def row(value=36.02, end="20241231", ann: str | None = "20250403", flag="1"):
    return {
        "ts_code": "600519.SH",
        "end_date": end,
        "ann_date": ann,
        "roe_waa": value,
        "update_flag": flag,
    }


def normalize(rows):
    return normalize_annual_roe(
        pl.DataFrame(rows),
        symbol_ids={"600519.SH": 1},
        as_of=date(2026, 11, 5),
        observed_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    "value,expected",
    [(36.02, Decimal("0.360200")), (0, Decimal(0)), (-10, Decimal("-0.1")), (None, None)],
)
def test_roe_percentage_conversion_and_sign(value, expected):
    assert normalize([row(value)])["roe"][0] == expected


def test_future_announcement_and_nonannual_are_not_used():
    assert normalize(
        [row(ann="20261106"), row(end="20250930", ann="20251030"), row(ann=None)]
    ).is_empty()


def test_conflicting_revisions_rejected_unless_explicitly_updated():
    with pytest.raises(ValueError, match="Conflicting"):
        normalize([row(30), row(35)])
    assert normalize([row(30, flag="0"), row(35, flag="1")])["roe"][0] == Decimal("0.35")


def test_financial_pagination_rejects_ignored_offset():
    from unittest.mock import Mock

    import pandas as pd
    from gr_data.common.retry import PermanentError
    from gr_data.raw.tushare.client import TushareProClient

    client = TushareProClient("fixture-token", sleep_between_requests=0)
    page = pd.DataFrame({"ts_code": [str(i) for i in range(100)]})
    client.query = Mock(return_value=page)
    with pytest.raises(PermanentError, match="Repeated financial pagination"):
        client.query_all("fina_indicator_vip", period="20251231")
    assert client.query.call_count == 2


def test_annual_fetch_preserves_raw_and_permanent_errors(tmp_path):
    from unittest.mock import Mock

    import pandas as pd
    from gr_data.common.paths import RawPaths
    from gr_data.common.retry import PermanentError
    from gr_data.raw.tushare.fetchers.financial import fetch_annual_roe

    client = Mock()
    client.query_all.return_value = pd.DataFrame([row()])
    result = fetch_annual_roe(client, RawPaths(tmp_path), years=(2025, 2024))
    assert len(result.files) == 2 and all(p.exists() for p in result.files)
    assert [c.kwargs["period"] for c in client.query_all.call_args_list] == ["20241231", "20251231"]
    client.query_all.side_effect = PermanentError("credentials missing")
    with pytest.raises(PermanentError, match="credentials missing"):
        fetch_annual_roe(client, RawPaths(tmp_path), years=(2025,))
