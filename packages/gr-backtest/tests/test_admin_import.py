from __future__ import annotations

import unittest

from getrich.apps.web.errors import BadRequest
from getrich.apps.web.services.admin_import import (
    _derive_daily_return_payload,
    _parse_csv_rows,
)


class AdminImportServiceTest(unittest.TestCase):
    def test_parse_csv_rows_rejects_header_only_csv(self) -> None:
        with self.assertRaises(BadRequest):
            _parse_csv_rows("strategy_code,trade_date,daily_return\n")

    def test_parse_csv_rows_strips_utf8_bom_and_cell_whitespace(self) -> None:
        rows = _parse_csv_rows(
            "\ufeffstrategy_code,trade_date,daily_return\n"
            " STR_A_TREND_001 , 2026-05-29 , 0.0041 \n"
        )

        self.assertEqual(rows[0]["strategy_code"], "STR_A_TREND_001")
        self.assertEqual(rows[0]["trade_date"], "2026-05-29")
        self.assertEqual(rows[0]["daily_return"], "0.0041")

    def test_compound_and_simple_monthly_returns_differ(self) -> None:
        rows = [
            {
                "strategy_id": "10000000-0000-4000-8000-000000000001",
                "trade_date": "2026-05-29",
                "daily_return": 0.1,
                "benchmark_daily_return": None,
                "position_ratio": 0.5,
            },
            {
                "strategy_id": "10000000-0000-4000-8000-000000000001",
                "trade_date": "2026-05-30",
                "daily_return": 0.1,
                "benchmark_daily_return": None,
                "position_ratio": 0.5,
            },
        ]

        compound = _derive_daily_return_payload(
            rows,
            method="compound",
            initial_nav=1.0,
            trading_days_per_year=252,
            risk_free_rate=0.0,
        )
        simple = _derive_daily_return_payload(
            rows,
            method="simple",
            initial_nav=1.0,
            trading_days_per_year=252,
            risk_free_rate=0.0,
        )

        self.assertAlmostEqual(compound["monthly_rows"][0]["monthly_return"], 0.21)
        self.assertAlmostEqual(simple["monthly_rows"][0]["monthly_return"], 0.2)
        self.assertAlmostEqual(compound["equity_rows"][-1]["nav"], 1.21)
        self.assertAlmostEqual(simple["equity_rows"][-1]["nav"], 1.2)


if __name__ == "__main__":
    unittest.main()
