"""Signal writer protocol and in-memory evaluation writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import polars as pl


@runtime_checkable
class SignalWriter(Protocol):
    """Protocol for writing signals to a backend store.

    Implementations can write to PostgreSQL, memory, files, etc.
    """

    def write(self, signals: pl.DataFrame) -> None:
        """Persist the signal DataFrame."""
        ...


@dataclass
class EvalSignalWriter:
    """Accumulates signals in memory for evaluation/testing.

    Examples
    --------
    >>> writer = EvalSignalWriter()
    >>> writer.write(signal_df)
    >>> accumulated = writer.to_dataframe()
    >>> writer.clear()
    """

    _buffer: list[pl.DataFrame] = field(default_factory=list)

    def write(self, signals: pl.DataFrame) -> None:
        """Append a signal DataFrame to the internal buffer."""
        self._buffer.append(signals)

    def to_dataframe(self) -> pl.DataFrame:
        """Return all buffered signals concatenated into a single DataFrame.

        Returns an empty DataFrame with no columns when the buffer is empty.
        """
        if not self._buffer:
            return pl.DataFrame()
        return pl.concat(self._buffer, how="vertical")

    def clear(self) -> None:
        """Empty the internal buffer."""
        self._buffer.clear()
