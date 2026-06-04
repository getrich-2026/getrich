from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Iterable


BAR_ASSETS = ("index", "future", "option", "stock", "etf")
BAR_FREQUENCIES = ("1d", "1m")
BAR_MODES = ("auto", "full", "incremental")
BAR_TABLES = {
    ("index", "1d"): "index_bar_1d",
    ("future", "1d"): "future_bar_1d",
    ("option", "1d"): "option_bar_1d",
    ("stock", "1d"): "stock_bar_1d",
    ("etf", "1d"): "etf_bar_1d",
    ("index", "1m"): "index_bar_1m",
    ("future", "1m"): "future_bar_1m",
    ("option", "1m"): "option_bar_1m",
    ("stock", "1m"): "stock_bar_1m",
    ("etf", "1m"): "etf_bar_1m",
}


@dataclass(frozen=True)
class BarsExtractionRequest:
    """Structured request for historical bar extraction."""

    asset: str
    freq: str
    start_date: date | None = None
    end_date: date | None = None
    symbols: tuple[str, ...] = ()
    mode: str = "auto"

    def __post_init__(self) -> None:
        asset = _normalize_choice(self.asset, choices=BAR_ASSETS, field="asset")
        freq = _normalize_choice(self.freq, choices=BAR_FREQUENCIES, field="freq")
        mode = _normalize_choice(self.mode, choices=BAR_MODES, field="mode")
        start_date = _normalize_date(self.start_date, field="start_date")
        end_date = _normalize_date(self.end_date, field="end_date")
        symbols = _normalize_symbols(self.symbols)

        if (asset, freq) not in BAR_TABLES:
            raise ValueError(f"unsupported bar extraction target: asset={asset!r}, freq={freq!r}")
        if start_date and end_date and start_date > end_date:
            raise ValueError(f"start_date {start_date.isoformat()} is after end_date {end_date.isoformat()}")

        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "freq", freq)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "start_date", start_date)
        object.__setattr__(self, "end_date", end_date)
        object.__setattr__(self, "symbols", symbols)

    @classmethod
    def from_import_bars_args(
        cls,
        *,
        asset: str,
        freq: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Iterable[str] | None = None,
        mode: str = "auto",
    ) -> BarsExtractionRequest:
        """Build a request from the import-bars CLI/pipeline argument shape."""

        return cls(
            asset=asset,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            symbols=tuple(symbols or ()),
            mode=mode,
        )

    @property
    def table_name(self) -> str:
        return BAR_TABLES[(self.asset, self.freq)]

    @property
    def job_name(self) -> str:
        return f"import_{self.asset}_{self.freq}"

    @property
    def uses_watermark(self) -> bool:
        return self.mode in {"auto", "incremental"}


@dataclass(frozen=True)
class BarsExtractionPlan:
    """Resolved extraction plan for one historical bar import request."""

    request: BarsExtractionRequest
    table_name: str
    job_name: str
    uses_watermark: bool
    watermark_schema: str = "market"
    watermark_column: str = "trading_day"

    @classmethod
    def from_request(cls, request: BarsExtractionRequest) -> BarsExtractionPlan:
        return cls(
            request=request,
            table_name=request.table_name,
            job_name=request.job_name,
            uses_watermark=request.uses_watermark,
        )

    @classmethod
    def from_import_bars_args(
        cls,
        *,
        asset: str,
        freq: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        symbols: Iterable[str] | None = None,
        mode: str = "auto",
    ) -> BarsExtractionPlan:
        request = BarsExtractionRequest.from_import_bars_args(
            asset=asset,
            freq=freq,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            mode=mode,
        )
        return cls.from_request(request)

    def source_kwargs(self, *, watermark: date | str | None = None) -> dict[str, object]:
        """Return adapter-compatible keyword arguments for bar frame extraction."""

        since = _normalize_date(watermark, field="watermark") if self.uses_watermark else None
        return {
            "asset": self.request.asset,
            "freq": self.request.freq,
            "since": since,
            "start_date": self.request.start_date,
            "end_date": self.request.end_date,
            "symbols": list(self.request.symbols) if self.request.symbols else None,
        }


def _normalize_choice(value: str, *, choices: tuple[str, ...], field: str) -> str:
    text = str(value).strip()
    if text in choices:
        return text
    expected = ", ".join(choices)
    raise ValueError(f"unsupported {field}: {value!r}; expected one of: {expected}")


def _normalize_date(value: date | str | None, *, field: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        raise ValueError(f"{field} must be a date, not a datetime")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date in YYYY-MM-DD format: {value!r}") from exc


def _normalize_symbols(symbols: Iterable[str] | None) -> tuple[str, ...]:
    if not symbols:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        text = str(symbol).strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return tuple(out)
