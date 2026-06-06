"""Tests for the SignalWriter protocol and EvalSignalWriter."""

import polars as pl

from getrich_backtest.live import EvalSignalWriter, SignalWriter


class TestEvalSignalWriter:
    def test_write_append_to_buffer(self) -> None:
        """Writing adds a DataFrame to the internal buffer."""
        writer = EvalSignalWriter()
        assert len(writer._buffer) == 0

        df = pl.DataFrame({"symbol": ["A"], "action": ["buy"]})
        writer.write(df)
        assert len(writer._buffer) == 1

    def test_to_dataframe_concatenates(self) -> None:
        """Multiple writes produce a concatenated DataFrame."""
        writer = EvalSignalWriter()
        df1 = pl.DataFrame({"symbol": ["A"], "action": ["buy"]})
        df2 = pl.DataFrame({"symbol": ["B"], "action": ["sell"]})
        writer.write(df1)
        writer.write(df2)

        result = writer.to_dataframe()
        assert result.height == 2
        assert result["symbol"].to_list() == ["A", "B"]

    def test_to_dataframe_empty_buffer(self) -> None:
        """Empty buffer returns empty DataFrame."""
        writer = EvalSignalWriter()
        result = writer.to_dataframe()
        assert result.is_empty()
        assert result.columns == []

    def test_clear_empties_buffer(self) -> None:
        """Clear removes all buffered DataFrames."""
        writer = EvalSignalWriter()
        writer.write(pl.DataFrame({"symbol": ["A"], "action": ["buy"]}))
        assert len(writer._buffer) == 1

        writer.clear()
        assert len(writer._buffer) == 0
        assert writer.to_dataframe().is_empty()

    def test_protocol_conformance(self) -> None:
        """EvalSignalWriter satisfies the SignalWriter protocol."""
        assert isinstance(EvalSignalWriter(), SignalWriter)
