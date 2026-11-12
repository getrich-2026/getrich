"""行业采集必须包含历史成员；失败不得生成完整快照。"""

from __future__ import annotations

from unittest.mock import Mock

import pandas as pd
import pytest
from gr_data.common.paths import RawPaths
from gr_data.raw.tushare.fetchers.industry import fetch_industry


def test_fetches_both_current_and_historical_members(tmp_path):
    client = Mock()
    client.query_all.side_effect = [
        pd.DataFrame({"index_code": ["801780.SI"], "industry_name": ["银行"], "level": ["L1"]}),
        pd.DataFrame(
            {
                "ts_code": ["600000.SH"],
                "l1_code": ["801780.SI"],
                "in_date": ["20000101"],
                "out_date": [None],
            }
        ),
        pd.DataFrame(),
    ]
    result = fetch_industry(client, RawPaths(tmp_path))
    assert result.nodes.exists() and len(result.members) == 2
    assert result.observed_at.tzinfo is not None
    assert client.query_all.call_args_list[1].kwargs["is_new"] == "Y"
    assert client.query_all.call_args_list[2].kwargs["is_new"] == "N"


def test_failed_history_request_does_not_return_complete_snapshot(tmp_path):
    client = Mock()
    client.query_all.side_effect = [
        pd.DataFrame({"index_code": ["801780.SI"], "industry_name": ["银行"], "level": ["L1"]}),
        RuntimeError("supplier failure"),
    ]
    with pytest.raises(RuntimeError, match="Industry membership request failed"):
        fetch_industry(client, RawPaths(tmp_path))


def test_membership_pagination_uses_supplier_2000_row_limit():
    from gr_data.raw.tushare.client import TushareProClient

    client = TushareProClient("fixture-token", sleep_between_requests=0)
    query = Mock(
        side_effect=[
            pd.DataFrame({"ts_code": [str(i) for i in range(2000)]}),
            pd.DataFrame({"ts_code": ["last"]}),
        ]
    )
    client.query = query
    result = client.query_all("index_member_all", l1_code="801780.SI", is_new="N")
    assert len(result) == 2001
    assert query.call_args_list[1].kwargs["offset"] == 2000
