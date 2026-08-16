"""Storage-neutral bar loader interfaces."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import polars as pl

from gr_backtest.data.adj_schema import validate_adj_schema
from gr_backtest.data.calendar_schema import validate_calendar_schema
from gr_backtest.data.corp_actions_schema import validate_corp_actions_schema
from gr_backtest.data.factor_schema import validate_factor_schema
from gr_backtest.data.instruments_schema import validate_instruments_schema
from gr_backtest.data.schema import BAR_REQUIRED_COLUMNS, validate_bar_schema
from gr_backtest.exceptions import DataLoadError
from gr_backtest.time import normalize_datetime_range
from gr_backtest.types import AssetClass, Frequency


# ---------------------------------------------------------------------------
# Chunk boundary helpers for streaming bar loading
# ---------------------------------------------------------------------------


def _iter_date_chunks(
    start: datetime,
    end: datetime,
    chunk: str = "month",
) -> Generator[tuple[datetime, datetime], None, None]:
    """Yield ``(chunk_start, chunk_end)`` pairs partitioning ``[start, end)``.

    Parameters
    ----------
    start, end : datetime
        Timezone-aware Asia/Shanghai datetimes defining the full range.
    chunk : str
        One of ``"month"``, ``"quarter"``, ``"year"``, or ``"week"``.

    Yields
    ------
    (datetime, datetime)
        Left-closed / right-open chunk boundaries.
    """
    current = start
    tz = start.tzinfo

    while current < end:
        if chunk == "month":
            next_month = current.month + 1
            next_year = current.year
            if next_month > 12:
                next_month = 1
                next_year += 1
            boundary = datetime(next_year, next_month, 1, tzinfo=tz)
        elif chunk == "quarter":
            next_q = ((current.month - 1) // 3 + 1) * 3 + 1
            next_year = current.year
            if next_q > 12:
                next_q = 1
                next_year += 1
            boundary = datetime(next_year, next_q, 1, tzinfo=tz)
        elif chunk == "year":
            boundary = datetime(current.year + 1, 1, 1, tzinfo=tz)
        elif chunk == "week":
            from datetime import timedelta

            boundary = current + timedelta(days=7)
        else:
            raise ValueError(f"unknown chunk mode: '{chunk}'")

        if boundary >= end:
            yield current, end
            return
        yield current, boundary
        current = boundary


# ---------------------------------------------------------------------------
# Adj-factor application helper
# ---------------------------------------------------------------------------

_ADJ_PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")


def _apply_adj_factor(
    bars: pl.DataFrame,
    adj_df: pl.DataFrame,
    adj_policy: str,
) -> pl.DataFrame:
    """Multiply OHLC price columns by the cumulative adjustment factor.

    Parameters
    ----------
    bars : pl.DataFrame
        Raw bar data with ``dt`` (datetime) and OHLC columns.
    adj_df : pl.DataFrame
        Adj-factor data with ``symbol``, ``dt`` (Date), and either
        ``pre_factor`` or ``post_factor``.
    adj_policy : str
        ``"pre"`` or ``"post"`` — selects which factor column to use.
        ``"none"`` returns bars unchanged.

    Returns
    -------
    pl.DataFrame
        Bars with OHLC columns adjusted (or unchanged for ``"none"``).
    """
    if adj_policy == "none":
        return bars

    factor_col = "pre_factor" if adj_policy == "pre" else "post_factor"
    if factor_col not in adj_df.columns:
        return bars

    # For each bar, find the most recent adj factor at or before bar date
    bars_with_date = bars.with_columns(pl.col("dt").dt.date().alias("_adj_date")).sort(
        ["symbol", "_adj_date"]
    )
    adj_sel = adj_df.sort(["symbol", "dt"]).select(
        pl.col("symbol"),
        pl.col("dt").alias("_adj_date"),
        pl.col(factor_col).alias("_adj_factor"),
    )
    joined = bars_with_date.join_asof(
        adj_sel,
        on="_adj_date",
        by="symbol",
        strategy="forward",
    )

    for col in _ADJ_PRICE_COLUMNS:
        if col in joined.columns:
            joined = joined.with_columns(
                pl.when(pl.col("_adj_factor").is_not_null())
                .then(pl.col(col) * pl.col("_adj_factor"))
                .otherwise(pl.col(col))
                .alias(col)
            )

    return joined.drop(["_adj_date", "_adj_factor"])


class BarLoader(Protocol):
    """Protocol for storage-neutral bar loaders."""

    def load_calendar(
        self,
        exchange: str = "SSE",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load trading calendar for an exchange.

        Returns a Polars DataFrame with columns ``date``, ``is_trading_day``
        and optional ``session``, ``note``.
        """
        ...

    def load_instruments(
        self,
        asset_class: str | AssetClass,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Load instrument metadata for a given asset class.

        Returns a Polars DataFrame with columns from the instruments table
        (e.g., ``symbol``, ``name``, ``exchange``, ``industry_l1``, …).
        """
        ...

    def load_corp_actions(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load corporate actions.

        Returns a Polars DataFrame with columns ``symbol``, ``ex_date``,
        ``action_type`` and optional ``amount``, ``split_ratio``, etc.
        """
        ...

    def load_factors(
        self,
        factors: Sequence[str] | None = None,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load pre-computed factor values in long format.

        Returns a Polars DataFrame with columns ``dt``, ``symbol``,
        ``factor``, ``value`` and optional ``asset_class``.
        """
        ...

    def load_adj_factors(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load adjustment (复权) factor records.

        Returns a Polars DataFrame with columns ``symbol``, ``dt``,
        ``pre_factor``, ``post_factor`` and optional event info.
        """
        ...

    def load_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = Frequency.ONE_DAY.value,
        asset_class: str | AssetClass | None = None,
        columns: Sequence[str] | None = None,
        adj_policy: str = "none",
    ) -> pl.DataFrame:
        """Load bars for the requested left-closed/right-open range.

        Parameters
        ----------
        adj_policy : str
            Adjustment policy: ``"none"`` (raw), ``"pre"`` (前复权), or
            ``"post"`` (后复权).  Defaults to ``"none"``.
        """
        ...

    def iter_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = Frequency.ONE_DAY.value,
        asset_class: str | AssetClass | None = None,
        columns: Sequence[str] | None = None,
        chunk: str = "month",
    ) -> Generator[pl.DataFrame, None, None]:
        """Load bars in chunks, yielding one validated DataFrame per chunk.

        Parameters are the same as ``load_bars()``, with an additional
        ``chunk`` parameter that controls the chunk boundary granularity
        (``"month"``, ``"quarter"``, ``"year"``, or ``"week"``).
        """
        ...


@dataclass(frozen=True)
class DataFrameBarLoader:
    """In-memory Polars DataFrame implementation of ``BarLoader``.

    Parameters
    ----------
    bars : pl.DataFrame
        Bar data (required columns per ``validate_bar_schema``).
    instruments : pl.DataFrame | None
        Optional instrument metadata table.
    calendar_df : pl.DataFrame | None
        Optional exchange calendar table.
    corp_actions_df : pl.DataFrame | None
        Optional corporate actions table.
    factors_df : pl.DataFrame | None
        Optional factor data table in long format (``dt``, ``symbol``,
        ``factor``, ``value``).
    adj_factors_df : pl.DataFrame | None
        Optional adjustment factor table (``symbol``, ``dt``,
        ``pre_factor``, ``post_factor``).
    """

    bars: pl.DataFrame = field(repr=False)
    instruments: pl.DataFrame | None = field(default=None, repr=False)
    calendar_df: pl.DataFrame | None = field(default=None, repr=False)
    corp_actions_df: pl.DataFrame | None = field(default=None, repr=False)
    factors_df: pl.DataFrame | None = field(default=None, repr=False)
    adj_factors_df: pl.DataFrame | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", validate_bar_schema(self.bars))

    def load_instruments(
        self,
        asset_class: str | AssetClass,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Load instrument metadata from the in-memory table."""
        if self.instruments is None:
            return pl.DataFrame({"symbol": []}, schema={"symbol": pl.Utf8})

        result = self.instruments.clone()

        if columns is not None:
            missing = set(columns).difference(result.columns)
            if missing:
                msg = ", ".join(sorted(missing))
                raise DataLoadError(f"requested columns are not available: {msg}")
            result = result.select(list(columns))

        return validate_instruments_schema(result, asset_class_value(asset_class))

    def load_calendar(
        self,
        exchange: str = "SSE",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load trading calendar from the in-memory table."""
        if self.calendar_df is None:
            return pl.DataFrame(
                {"date": [], "is_trading_day": []},
                schema={"date": pl.Date, "is_trading_day": pl.Boolean},
            )

        result = self.calendar_df.clone()

        if "exchange" in result.columns:
            result = result.filter(pl.col("exchange") == exchange)

        if start is not None and "date" in result.columns:
            result = result.filter(pl.col("date") >= start.date())
        if end is not None and "date" in result.columns:
            result = result.filter(pl.col("date") <= end.date())

        return validate_calendar_schema(result)

    def load_corp_actions(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load corporate actions from the in-memory table."""
        if self.corp_actions_df is None:
            return pl.DataFrame(
                {col: [] for col in ("symbol", "ex_date", "action_type")},
                schema={"symbol": pl.Utf8, "ex_date": pl.Date, "action_type": pl.Utf8},
            )

        result = self.corp_actions_df.clone()

        if symbols is not None:
            result = result.filter(pl.col("symbol").is_in(list(symbols)))

        if start is not None and "ex_date" in result.columns:
            result = result.filter(pl.col("ex_date") >= start.date())
        if end is not None and "ex_date" in result.columns:
            result = result.filter(pl.col("ex_date") <= end.date())

        return validate_corp_actions_schema(result)

    def load_factors(
        self,
        factors: Sequence[str] | None = None,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load pre-computed factor values from the in-memory table."""
        if self.factors_df is None:
            return pl.DataFrame(
                {col: [] for col in ("dt", "symbol", "factor", "value")},
                schema={
                    "dt": pl.Datetime("ms", "Asia/Shanghai"),
                    "symbol": pl.Utf8,
                    "factor": pl.Utf8,
                    "value": pl.Float64,
                },
            )

        result = self.factors_df.clone()

        if factors is not None:
            result = result.filter(pl.col("factor").is_in(list(factors)))

        if symbols is not None:
            result = result.filter(pl.col("symbol").is_in(list(symbols)))

        if start is not None and "dt" in result.columns:
            result = result.filter(pl.col("dt") >= start)
        if end is not None and "dt" in result.columns:
            result = result.filter(pl.col("dt") <= end)

        return validate_factor_schema(result)

    def load_adj_factors(
        self,
        symbols: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pl.DataFrame:
        """Load adjustment factors from the in-memory table."""
        if self.adj_factors_df is None:
            return pl.DataFrame(
                {col: [] for col in ("symbol", "dt", "pre_factor", "post_factor")},
                schema={
                    "symbol": pl.Utf8,
                    "dt": pl.Date,
                    "pre_factor": pl.Float64,
                    "post_factor": pl.Float64,
                },
            )

        result = self.adj_factors_df.clone()

        if symbols is not None:
            result = result.filter(pl.col("symbol").is_in(list(symbols)))

        if start is not None and "dt" in result.columns:
            result = result.filter(pl.col("dt") >= start.date())
        if end is not None and "dt" in result.columns:
            result = result.filter(pl.col("dt") <= end.date())

        return validate_adj_schema(result)

    def load_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = Frequency.ONE_DAY.value,
        asset_class: str | AssetClass | None = None,
        columns: Sequence[str] | None = None,
        adj_policy: str = "none",
    ) -> pl.DataFrame:
        """Load bars from the in-memory table."""
        normalized_start, normalized_end = normalize_datetime_range(start, end)
        result = self.bars.filter(
            (pl.col("dt") >= normalized_start) & (pl.col("dt") < normalized_end)
        )

        if symbols is not None:
            result = result.filter(pl.col("symbol").is_in(list(symbols)))

        if "freq" in result.columns:
            result = result.filter(pl.col("freq") == freq)

        if asset_class is not None:
            if "asset_class" not in result.columns:
                raise DataLoadError(
                    "asset_class filter requested but bars have no asset_class column"
                )
            asset_class_value = (
                asset_class.value if isinstance(asset_class, AssetClass) else asset_class
            )
            result = result.filter(pl.col("asset_class") == asset_class_value)

        if columns is not None:
            requested_columns = set(columns)
            missing_required = BAR_REQUIRED_COLUMNS.difference(requested_columns)
            if missing_required:
                missing = ", ".join(sorted(missing_required))
                raise DataLoadError(f"columns must include required bar columns: {missing}")
            missing_columns = requested_columns.difference(result.columns)
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise DataLoadError(f"requested columns are not available: {missing}")
            result = result.select(list(columns))

        result = validate_bar_schema(result)

        if adj_policy != "none":
            adj_df = self.load_adj_factors(symbols=symbols, start=start, end=end)
            if not adj_df.is_empty():
                result = _apply_adj_factor(result, adj_df, adj_policy)

        return result

    def iter_bars(
        self,
        symbols: Sequence[str] | None,
        start: datetime,
        end: datetime,
        freq: str = Frequency.ONE_DAY.value,
        asset_class: str | AssetClass | None = None,
        columns: Sequence[str] | None = None,
        chunk: str = "month",
    ) -> Generator[pl.DataFrame, None, None]:
        """Load bars in monthly (or other) chunks from the in-memory table."""
        for chunk_start, chunk_end in _iter_date_chunks(start, end, chunk=chunk):
            yield self.load_bars(
                symbols=symbols,
                start=chunk_start,
                end=chunk_end,
                freq=freq,
                asset_class=asset_class,
                columns=columns,
            )


def asset_class_value(asset_class: str | AssetClass) -> str:
    """Normalise an asset class parameter to a string."""
    return asset_class.value if isinstance(asset_class, AssetClass) else asset_class
