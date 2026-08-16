"""Tests for bar resampling utility."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest
from gr_backtest import DEFAULT_ASHARE_SESSIONS, get_shanghai_tz, resample_bars
from gr_backtest.calendar import Session


TZ = get_shanghai_tz()


def _make_1m_bars(
    n_minutes: int = 10,
    symbols: tuple[str, ...] = ("A", "B"),
    *,
    start_hour: int = 9,
    start_minute: int = 30,
    with_amount: bool = False,
) -> pl.DataFrame:
    """Create 1m OHLCV bars for testing resample.

    Each minute increments open/high/low/close by 0.1 per symbol.
    Handles hour overflow for large minute counts.
    """
    rows = []
    for symbol in symbols:
        base = 10.0 if symbol == "A" else 20.0
        for m in range(n_minutes):
            total_minutes = start_hour * 60 + start_minute + m
            h = total_minutes // 60
            mi = total_minutes % 60
            dt = datetime(2026, 6, 1, h, mi, 0, tzinfo=TZ)
            row = {
                "dt": dt,
                "symbol": symbol,
                "open": base + m * 0.1,
                "high": base + m * 0.1 + 0.2,
                "low": base + m * 0.1 - 0.1,
                "close": base + m * 0.1 + 0.05,
                "volume": 1000.0 if symbol == "A" else 2000.0,
            }
            if with_amount:
                row["amount"] = row["close"] * row["volume"]
            rows.append(row)
    return pl.DataFrame(
        rows,
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


class TestResampleBars:
    # ── Basic aggregation correctness ───────────────────────────────────

    def test_1m_to_5m_basic(self) -> None:
        bars = _make_1m_bars(10)  # 10 minutes → two 5m buckets
        result = resample_bars(bars, "5m")

        assert result.height == 4  # 2 symbols × 2 buckets
        assert result.schema["dt"] == pl.Datetime("ms", "Asia/Shanghai")
        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        assert len(dts) == 2
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        assert dts[1] == datetime(2026, 6, 1, 9, 35, tzinfo=TZ)

    def test_1m_to_5m_ohlcv_values(self) -> None:
        bars = _make_1m_bars(5, symbols=("A",))
        result = resample_bars(bars, "5m")

        row = result.row(0, named=True)
        # first 5 minutes (indices 0-4): open=10.0, high=10.6, low=9.9, close=10.45,
        # volume=5000.0
        assert row["open"] == 10.0  # first open (index 0)
        assert row["high"] == 10.0 + 0.4 + 0.2  # max high (index 4)
        # low: min of lows [9.9, 10.0-0.1=9.9, 10.1-0.1=10.0, 10.2-0.1=10.1,
        # 10.3-0.1=10.2, 10.4-0.1=10.3]
        assert row["low"] == 9.9
        assert row["close"] == 10.0 + 0.4 + 0.05  # last close (index 4)
        assert row["volume"] == 5000.0  # 5 × 1000

    def test_1m_to_15m(self) -> None:
        bars = _make_1m_bars(30, symbols=("A",))
        result = resample_bars(bars, "15m")

        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        assert len(dts) == 2
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        assert dts[1] == datetime(2026, 6, 1, 9, 45, tzinfo=TZ)

    def test_1m_to_30m(self) -> None:
        bars = _make_1m_bars(60, symbols=("A",))
        result = resample_bars(bars, "30m")

        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        assert len(dts) == 2
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        assert dts[1] == datetime(2026, 6, 1, 10, 0, tzinfo=TZ)

    def test_1m_to_60m(self) -> None:
        # 120 minutes from 09:30 → 09:30..11:29 → 3 hourly buckets
        bars = _make_1m_bars(120, symbols=("A",))
        result = resample_bars(bars, "60m")

        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        assert len(dts) == 3
        assert dts[0] == datetime(2026, 6, 1, 9, 0, tzinfo=TZ)
        assert dts[1] == datetime(2026, 6, 1, 10, 0, tzinfo=TZ)
        assert dts[2] == datetime(2026, 6, 1, 11, 0, tzinfo=TZ)

    def test_1m_to_1h_same_as_60m(self) -> None:
        bars = _make_1m_bars(120, symbols=("A",))
        result_60m = resample_bars(bars, "60m")
        result_1h = resample_bars(bars, "1h")

        assert result_60m.height == result_1h.height
        assert result_60m["dt"].to_list() == result_1h["dt"].to_list()

    # ── Optional columns ────────────────────────────────────────────────

    def test_preserves_amount_and_vwap(self) -> None:
        bars = _make_1m_bars(5, symbols=("A",), with_amount=True)
        result = resample_bars(bars, "5m")

        assert "amount" in result.columns
        assert "vwap" in result.columns
        row = result.row(0, named=True)
        assert row["amount"] == pytest.approx(
            sum((10.0 + m * 0.1 + 0.05) * 1000.0 for m in range(5))
        )
        # vwap = total_amount / total_volume
        assert row["vwap"] == pytest.approx(row["amount"] / row["volume"])

    # ── Single symbol ───────────────────────────────────────────────────

    def test_single_symbol(self) -> None:
        bars = _make_1m_bars(10, symbols=("A",))
        result = resample_bars(bars, "5m")
        assert set(result["symbol"].unique().to_list()) == {"A"}

    def test_multiple_symbols_independent_buckets(self) -> None:
        bars = _make_1m_bars(10, symbols=("A", "B", "C"))
        result = resample_bars(bars, "5m")
        symbols_in_result = result["symbol"].unique().sort().to_list()
        assert symbols_in_result == ["A", "B", "C"]

    # ── Error cases ─────────────────────────────────────────────────────

    def test_same_freq_rejected(self) -> None:
        bars = _make_1m_bars(5, symbols=("A",))
        with pytest.raises(ValueError, match="must be coarser"):
            resample_bars(bars, "1m")

    def test_upsample_rejected(self) -> None:
        bars = _make_1m_bars(10, symbols=("A",))
        # First resample to 5m, then try to go back to 1m
        five_m = resample_bars(bars, "5m")
        with pytest.raises(ValueError, match="must be coarser"):
            resample_bars(five_m, "1m", source_freq="5m")

    def test_unknown_source_freq_rejected(self) -> None:
        bars = _make_1m_bars(5, symbols=("A",))
        with pytest.raises(ValueError, match="unknown source_freq"):
            resample_bars(bars, "5m", source_freq="2m")

    def test_unknown_target_freq_rejected(self) -> None:
        bars = _make_1m_bars(5, symbols=("A",))
        with pytest.raises(ValueError, match="unknown target_freq"):
            resample_bars(bars, "weekly")

    def test_single_bar_per_bucket(self) -> None:
        """When there is exactly one bar per target bucket (e.g. 5m from 5m)."""
        bars = _make_1m_bars(5, symbols=("A",))
        result = resample_bars(bars, "5m")
        # 5 minutes → 1 bucket, open=close (single row)
        row = result.row(0, named=True)
        assert row["open"] == 10.0
        assert row["close"] == 10.0 + 0.4 + 0.05  # last row's close

    # ── Edge case: partial bucket ───────────────────────────────────────

    def test_partial_bucket(self) -> None:
        """Only 3 minutes of data → partial 5m bucket still produces a bar."""
        bars = _make_1m_bars(3, symbols=("A",))
        result = resample_bars(bars, "5m")
        assert result.height == 1  # one symbol, one partial bucket
        row = result.row(0, named=True)
        # 3 minutes → volume = 3 × 1000
        assert row["volume"] == 3000.0

    # ── Source frequency parameter ──────────────────────────────────────

    def test_explicit_source_freq(self) -> None:
        bars = _make_1m_bars(10, symbols=("A",))
        result = resample_bars(bars, "5m", source_freq="1m")
        assert result.height == 2  # 2 buckets

    def test_5m_to_15m(self) -> None:
        bars = _make_1m_bars(15, symbols=("A",))
        five_m = resample_bars(bars, "5m")
        result = resample_bars(five_m, "15m", source_freq="5m")
        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        assert len(dts) == 1
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)


# ── Session-aware resampling (P10 Phase 2) ─────────────────────────────────


class TestSessionResample:
    """Session-aligned resampling tests using ASHARE session definitions."""

    ASHARE_SESSIONS = DEFAULT_ASHARE_SESSIONS  # 09:30–11:30, 13:00–15:00

    def test_session_resample_1m_to_1h_ashare(self) -> None:
        """1h buckets should align to 09:30, 10:30, … (not 09:00, 10:00)."""
        # 120 minutes from 09:30 → 2 hours: 09:30-11:29
        bars = _make_1m_bars(120, symbols=("A",))
        result = resample_bars(bars, "60m", sessions=self.ASHARE_SESSIONS)

        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        # Should be 09:30, 10:30 (NOT 09:00, 10:00, 11:00)
        assert len(dts) == 2
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        assert dts[1] == datetime(2026, 6, 1, 10, 30, tzinfo=TZ)

    def test_session_resample_1m_to_5m(self) -> None:
        """5m boundaries at 09:30, 09:35, … with session alignment."""
        bars = _make_1m_bars(10, symbols=("A",))
        result = resample_bars(bars, "5m", sessions=self.ASHARE_SESSIONS)

        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        assert len(dts) == 2
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
        assert dts[1] == datetime(2026, 6, 1, 9, 35, tzinfo=TZ)

    def test_session_resample_night_session(self) -> None:
        """Midnight-spanning 21:00→02:30 session resamples correctly."""
        night_session = (Session("night", 21, 0, 2, 30, spans_midnight=True),)

        # Build bars for 21:00–02:29 (night session)
        rows = []
        for total_min in range(21 * 60, 24 * 60):  # 21:00 to 23:59
            h = total_min // 60
            mi = total_min % 60
            dt = datetime(2026, 6, 1, h, mi, 0, tzinfo=TZ)
            bar_row = {
                "dt": dt,
                "symbol": "A",
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.2,
                "volume": 1000.0,
            }
            rows.append(bar_row)
        for total_min in range(0, 2 * 60 + 30):  # 00:00 to 02:29
            h = total_min // 60
            mi = total_min % 60
            dt = datetime(2026, 6, 2, h, mi, 0, tzinfo=TZ)
            bar_row = {
                "dt": dt,
                "symbol": "A",
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.2,
                "volume": 1000.0,
            }
            rows.append(bar_row)

        bars = pl.DataFrame(
            rows,
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )

        result = resample_bars(bars, "1h", sessions=night_session)
        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        # Buckets: 00:00, 01:00, 02:00, 21:00, 22:00, 23:00 (all on June 1)
        # After midnight, the bucket date stays on the session start date,
        # so 00:00-02:00 sort before 21:00-23:00.
        assert len(dts) == 6
        assert dts[0] == datetime(2026, 6, 1, 0, 0, tzinfo=TZ)
        assert dts[1] == datetime(2026, 6, 1, 1, 0, tzinfo=TZ)
        assert dts[2] == datetime(2026, 6, 1, 2, 0, tzinfo=TZ)
        assert dts[3] == datetime(2026, 6, 1, 21, 0, tzinfo=TZ)
        assert dts[4] == datetime(2026, 6, 1, 22, 0, tzinfo=TZ)
        assert dts[5] == datetime(2026, 6, 1, 23, 0, tzinfo=TZ)

    def test_session_resample_lunch_gap_filtered(self) -> None:
        """Bars at 12:00 (lunch gap) are filtered out with ASHARE sessions."""
        # Build bars including 12:00 data and some 11:25 data
        bars = _make_1m_bars(5, symbols=("A",))  # 09:30-09:34 within session
        # Add bars at 12:00 → filtered out
        extra = pl.DataFrame(
            {
                "dt": [datetime(2026, 6, 1, 12, 0, tzinfo=TZ)],
                "symbol": ["A"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.5],
                "close": [10.2],
                "volume": [1000.0],
            },
            schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
        )
        bars = pl.concat([bars, extra])

        result = resample_bars(bars, "5m", sessions=self.ASHARE_SESSIONS)
        # Only 09:30-09:34 bars (5) should remain, grouped into 1 bucket
        assert result.height == 1
        dts = result.select(pl.col("dt").unique()).to_series().to_list()
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)

    def test_session_resample_default_no_sessions(self) -> None:
        """sessions=None preserves dt.truncate() behavior."""
        bars = _make_1m_bars(120, symbols=("A",))
        result = resample_bars(bars, "60m")  # sessions=None by default

        dts = result.select(pl.col("dt").unique().sort()).to_series().to_list()
        # Default truncation: 09:00, 10:00, 11:00
        assert len(dts) == 3
        assert dts[0] == datetime(2026, 6, 1, 9, 0, tzinfo=TZ)

    def test_session_resample_empty_result(self) -> None:
        """All data outside sessions → empty result after filtering."""
        bars = _make_1m_bars(5, symbols=("A",), start_hour=12, start_minute=0)
        result = resample_bars(bars, "5m", sessions=self.ASHARE_SESSIONS)
        # All bars at 12:00-12:04 are outside morning (09:30-11:30) and afternoon (13:00-15:00)
        assert result.height == 0

    def test_session_resample_custom_sessions(self) -> None:
        """Custom session definitions work correctly."""
        custom_sessions = (Session("custom_morning", 9, 30, 11, 0, spans_midnight=False),)
        bars = _make_1m_bars(5, symbols=("A",))
        result = resample_bars(bars, "5m", sessions=custom_sessions)
        # 5 minutes from 09:30 → 1 bucket
        assert result.height == 1
        dts = result.select(pl.col("dt").unique()).to_series().to_list()
        assert dts[0] == datetime(2026, 6, 1, 9, 30, tzinfo=TZ)
