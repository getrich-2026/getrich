from __future__ import annotations

import json

import pandas as pd

from getrich_data_import.transform.insight_p1 import normalize_insight_p1_dataset


def test_normalize_stock_adj_factor_maps_sparse_factor_interval() -> None:
    raw = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "name": "平安银行",
                "begin_date": pd.Timestamp("2025-10-15"),
                "end_date": pd.Timestamp("2026-06-11"),
                "xdy": 1.020822,
                "b_xdy": 1.0,
                "f_xdy": 145.924146,
            }
        ]
    )

    out = normalize_insight_p1_dataset("stock_adj_factor", raw, source="insight")

    assert out["source_symbol"].tolist() == ["000001.SZ"]
    assert out["begin_date"].tolist() == [pd.Timestamp("2025-10-15").date()]
    assert out["xdy"].tolist() == [1.020822]
    assert out["b_xdy"].tolist() == [1.0]
    assert out["f_xdy"].tolist() == [145.924146]
    assert json.loads(out["raw_payload"].iloc[0])["end_date"] == "2026-06-11 00:00:00"


def test_normalize_stock_valuation_maps_adjusted_close_and_ratios() -> None:
    raw = pd.DataFrame(
        [
            {
                "htsc_code": "000001.SZ",
                "trading_day": pd.Timestamp("2026-06-04"),
                "close": 10.82,
                "backward_adjusted_closing_price": 1578.8993,
                "forward_adjusted_closing_price": 10.82,
                "pettm": 4.8763,
                "pcttm": 1.101,
                "psttm": 1.5786,
            }
        ]
    )

    out = normalize_insight_p1_dataset("stock_valuation", raw, source="insight")

    assert out["source_symbol"].tolist() == ["000001.SZ"]
    assert out["back_adjusted_close"].tolist() == [1578.8993]
    assert out["front_adjusted_close"].tolist() == [10.82]
    assert out["pe_ttm"].tolist() == [4.8763]
    assert out["pc_ttm"].tolist() == [1.101]
    assert out["ps_ttm"].tolist() == [1.5786]
    assert json.loads(out["raw_payload"].iloc[0])["htsc_code"] == "000001.SZ"


def test_normalize_etf_basket_keeps_component_symbol_and_substitute_amounts() -> None:
    raw = pd.DataFrame(
        [
            {
                "htsc_code": "510300.SH",
                "trading_day": pd.Timestamp("2026-06-04"),
                "pub_date": pd.Timestamp("2026-06-04"),
                "stock_code": "300418.SZ",
                "sub_comp_list": "1",
                "c_type": "101",
                "component_num": 100,
                "unit": "3",
                "is_cash_substitute": "1",
                "cash_substitute_rate": 10,
                "cash_substitute": 4180,
                "sub_replace": 0,
                "red_replace": 0,
            }
        ]
    )

    out = normalize_insight_p1_dataset("etf_basket", raw, source="insight")

    assert out["etf_source_symbol"].tolist() == ["510300.SH"]
    assert out["component_symbol"].tolist() == ["300418.SZ"]
    assert out["quantity"].tolist() == [100]
    assert out["subscription_substitute_amount"].tolist() == [0]
    assert out["redemption_substitute_amount"].tolist() == [0]


def test_normalize_etf_nav_maps_fund_family_api_to_etf_columns() -> None:
    raw = pd.DataFrame(
        [
            {
                "htsc_code": "510300.SH",
                "end_date": pd.Timestamp("2026-06-04"),
                "net_unit": 4.9284,
                "total_net_unit": 2.1546,
                "post_net_unit": 2.3156,
                "w1_navg": -0.00149925,
                "w1_navgr": 11860,
                "sharper": 0.3042235198,
            }
        ]
    )

    out = normalize_insight_p1_dataset("etf_nav", raw, source="insight")

    assert out["source_symbol"].tolist() == ["510300.SH"]
    assert out["unit_nav"].tolist() == [4.9284]
    assert out["accumulated_nav"].tolist() == [2.1546]
    assert out["adjusted_nav"].tolist() == [2.3156]
    assert out["return_1w"].tolist() == [-0.00149925]
    assert out["return_1w_rank"].tolist() == [11860]
    assert out["sharpe"].tolist() == [0.3042235198]
