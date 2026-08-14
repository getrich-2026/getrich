"""Signal preprocessing pipeline: missing values → winsorize → standardize → neutralize.

Each stage is a frozen dataclass with a factory-method constructor and an
``apply(scores)`` method that returns a ``[symbol, score]`` DataFrame.
The ``SignalPreprocessor`` orchestrator chains them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from scipy.stats import rankdata

from getrich_backtest.exceptions import StrategyError


if TYPE_CHECKING:
    from getrich_backtest.strategy.context import BarContext


try:
    import statsmodels.api as sm

    _HAS_STATSMODELS = True
except ImportError:  # pragma: no cover
    _HAS_STATSMODELS = False


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PreprocessingError(StrategyError):
    """Raised when signal preprocessing fails."""


# ---------------------------------------------------------------------------
# MissingValue
# ---------------------------------------------------------------------------


class MissingValueMethod(Enum):
    DROP = auto()
    FILL_MEAN = auto()
    FILL_ZERO = auto()


@dataclass(frozen=True)
class MissingValue:
    """Strategy for handling null scores in the input."""

    method: MissingValueMethod

    @classmethod
    def drop(cls) -> MissingValue:
        """Drop rows with null scores."""
        return cls(method=MissingValueMethod.DROP)

    @classmethod
    def fill_mean(cls) -> MissingValue:
        """Replace null scores with the mean of non-null scores."""
        return cls(method=MissingValueMethod.FILL_MEAN)

    @classmethod
    def fill_zero(cls) -> MissingValue:
        """Replace null scores with 0.0."""
        return cls(method=MissingValueMethod.FILL_ZERO)

    def apply(self, scores: pl.DataFrame) -> pl.DataFrame:
        """Handle missing values in ``[symbol, score]`` data."""
        _require_score_schema(scores)
        if scores.is_empty():
            return scores

        result = scores.clone()

        if self.method is MissingValueMethod.DROP:
            result = result.drop_nulls(subset=["score"])
            if result.is_empty():
                raise PreprocessingError("missing value drop produced empty result")

        elif self.method is MissingValueMethod.FILL_MEAN:
            mean_val: float | None = result.select(pl.col("score").mean()).item()
            if mean_val is None or np.isnan(mean_val):
                raise PreprocessingError("cannot fill_mean when all scores are null")
            result = result.with_columns(pl.col("score").fill_null(mean_val).alias("score"))

        elif self.method is MissingValueMethod.FILL_ZERO:
            result = result.with_columns(pl.col("score").fill_null(0.0).alias("score"))

        return result


# ---------------------------------------------------------------------------
# Winsorize
# ---------------------------------------------------------------------------


class WinsorizeMethod(Enum):
    MAD = auto()
    QUANTILE = auto()
    NONE = auto()


@dataclass(frozen=True)
class Winsorize:
    """Extreme-value capping strategy.

    Parameters
    ----------
    method : WinsorizeMethod
    n : float
        MAD multiplier (used when method is MAD).
    lower : float
        Lower quantile threshold (used when method is QUANTILE).
    upper : float
        Upper quantile threshold (used when method is QUANTILE).
    """

    method: WinsorizeMethod
    n: float = 3.0
    lower: float = 0.01
    upper: float = 0.99

    @classmethod
    def mad(cls, n: float = 3.0) -> Winsorize:
        """Clip at median ± n * MAD."""
        if n <= 0:
            raise ValueError("MAD multiplier n must be positive")
        return cls(method=WinsorizeMethod.MAD, n=n)

    @classmethod
    def quantile(cls, lower: float = 0.01, upper: float = 0.99) -> Winsorize:
        """Clip at specified quantile thresholds."""
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError("requires 0 <= lower < upper <= 1")
        return cls(method=WinsorizeMethod.QUANTILE, lower=lower, upper=upper)

    @classmethod
    def none(cls) -> Winsorize:
        """Skip winsorization."""
        return cls(method=WinsorizeMethod.NONE)

    def apply(self, scores: pl.DataFrame) -> pl.DataFrame:
        """Winsorize the score column."""
        _require_score_schema(scores)
        if scores.is_empty():
            return scores

        if self.method is WinsorizeMethod.NONE:
            return scores

        arr: np.ndarray = scores.select(pl.col("score")).to_numpy().flatten()

        if self.method is WinsorizeMethod.MAD:
            median = np.nanmedian(arr)
            mad = np.nanmedian(np.abs(arr - median))
            if mad == 0.0:
                return scores  # all values identical, nothing to clip
            lower = median - self.n * mad
            upper = median + self.n * mad

        else:  # QUANTILE
            lower = float(np.nanquantile(arr, self.lower))
            upper = float(np.nanquantile(arr, self.upper))

        clipped = np.clip(arr, lower, upper)
        return scores.with_columns(pl.Series("score", clipped))


# ---------------------------------------------------------------------------
# Standardize
# ---------------------------------------------------------------------------


class StandardizeMethod(Enum):
    ZSCORE = auto()
    RANK = auto()
    MINMAX = auto()
    NONE = auto()


@dataclass(frozen=True)
class Standardize:
    """Score normalization strategy."""

    method: StandardizeMethod

    @classmethod
    def zscore(cls) -> Standardize:
        """(x - mean) / std — zero mean, unit variance."""
        return cls(method=StandardizeMethod.ZSCORE)

    @classmethod
    def rank(cls) -> Standardize:
        """Rank-transform to [0, 1] using average tie-breaking."""
        return cls(method=StandardizeMethod.RANK)

    @classmethod
    def minmax(cls) -> Standardize:
        """(x - min) / (max - min) — rescale to [0, 1]."""
        return cls(method=StandardizeMethod.MINMAX)

    @classmethod
    def none(cls) -> Standardize:
        """Skip standardization."""
        return cls(method=StandardizeMethod.NONE)

    def apply(self, scores: pl.DataFrame) -> pl.DataFrame:
        """Standardize the score column."""
        _require_score_schema(scores)
        if scores.is_empty():
            return scores

        if self.method is StandardizeMethod.NONE:
            return scores

        arr: np.ndarray = scores.select(pl.col("score")).to_numpy().flatten()

        if self.method is StandardizeMethod.ZSCORE:
            std = float(np.nanstd(arr, ddof=1))
            if std == 0.0 or np.isnan(std):
                result = np.zeros_like(arr)
            else:
                mean: float = float(np.nanmean(arr))
                result = (arr - mean) / std

        elif self.method is StandardizeMethod.RANK:
            n = len(arr)
            if n <= 1:
                result = np.array([0.5])
            else:
                ranks = rankdata(arr, method="average")
                result = (ranks - 1.0) / (n - 1.0)

        else:  # MINMAX
            lo, hi = float(np.nanmin(arr)), float(np.nanmax(arr))
            result = np.zeros_like(arr) if hi == lo else (arr - lo) / (hi - lo)

        return scores.with_columns(pl.Series("score", result))


# ---------------------------------------------------------------------------
# Neutralize (cross-sectional OLS residual)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Neutralize:
    """Cross-sectional factor neutralization via OLS regression.

    Neutralization data must be provided as a ``[symbol, ...]`` DataFrame
    containing columns matching the configured factor names (``"industry"``,
    ``"market_cap"``, etc.).

    When ``use_instruments=True`` and ``neutralization_data`` is not provided,
    the ``apply()`` method will attempt to build neutralization data from
    ``ctx.instruments`` (if available).

    Parameters
    ----------
    factors : tuple[str, ...]
        Factor names for neutralization. Empty tuple means no neutralization.
    use_instruments : bool
        If True, try to auto-build neutralization data from ctx.instruments
        when ``neutralization_data`` is not provided (default False).
    """

    factors: tuple[str, ...]
    use_instruments: bool = False

    @classmethod
    def industry(cls, use_instruments: bool = False) -> Neutralize:
        """Neutralize against industry dummy variables."""
        return cls(factors=("industry",), use_instruments=use_instruments)

    @classmethod
    def market_cap(cls, use_instruments: bool = False) -> Neutralize:
        """Neutralize against log(market_cap)."""
        return cls(factors=("market_cap",), use_instruments=use_instruments)

    @classmethod
    def industry_size(cls, use_instruments: bool = False) -> Neutralize:
        """Neutralize against industry dummies + log(market_cap)."""
        return cls(factors=("industry", "market_cap"), use_instruments=use_instruments)

    @classmethod
    def style(cls, factors: list[str], use_instruments: bool = False) -> Neutralize:
        """Neutralize against custom factor list."""
        return cls(factors=tuple(factors), use_instruments=use_instruments)

    @classmethod
    def none(cls) -> Neutralize:
        """Skip neutralization."""
        return cls(factors=())

    def apply(
        self,
        scores: pl.DataFrame,
        neutralization_data: pl.DataFrame | None = None,
        ctx: BarContext | None = None,
    ) -> pl.DataFrame:
        """Neutralize scores via cross-sectional OLS residual.

        Parameters
        ----------
        scores : pl.DataFrame [symbol, score]
            Scores to neutralize.
        neutralization_data : pl.DataFrame [symbol, ...] | None
            Must contain at least the columns referenced in ``self.factors``
            plus ``"symbol"``.  If None or empty, neutralization is skipped
            and scores are returned unchanged.
        ctx : BarContext | None
            Optional context; used to auto-build neutralization data from
            ``ctx.instruments`` when ``use_instruments=True``.

        Returns
        -------
        pl.DataFrame [symbol, score]
        """
        _require_score_schema(scores)
        if scores.is_empty():
            return scores

        if not self.factors:
            return scores

        # Auto-build neutralization data from ctx.instruments
        if neutralization_data is None and self.use_instruments and ctx is not None:
            neutralization_data = self._build_from_instruments(ctx)

        if neutralization_data is None or neutralization_data.is_empty():
            return scores

        if not _HAS_STATSMODELS:
            raise PreprocessingError("statsmodels is required for neutralization")

        # Merge with neutralization data
        merged = scores.join(neutralization_data, on="symbol", how="inner")
        if merged.is_empty():
            raise PreprocessingError("no symbols matched between scores and neutralization data")
        if merged.height < 2:
            raise PreprocessingError("at least 2 observations required for OLS neutralization")

        y: np.ndarray = merged.select(pl.col("score")).to_numpy().flatten()
        x_list: list[np.ndarray] = []

        # Build design matrix from neutralization factors
        for factor in self.factors:
            if factor == "industry":
                if "industry" not in merged.columns:
                    raise PreprocessingError(
                        "neutralization factor 'industry' requires an "
                        "'industry' column in neutralization_data"
                    )
                industry_series = merged.get_column("industry")
                if industry_series.n_unique() <= 1:
                    raise PreprocessingError(
                        "neutralization factor 'industry' requires at least 2 "
                        "distinct industry values"
                    )
                dummies = merged.select("industry").to_dummies("industry", drop_first=True)
                x_list.append(dummies.to_numpy())

            elif factor == "market_cap":
                if "market_cap" not in merged.columns:
                    raise PreprocessingError(
                        "neutralization factor 'market_cap' requires a "
                        "'market_cap' column in neutralization_data"
                    )
                mcap = merged.select(pl.col("market_cap")).to_numpy().flatten().astype(np.float64)
                log_mcap = np.log(np.maximum(mcap, 1e-10))
                x_list.append(log_mcap.reshape(-1, 1))

            else:
                if factor not in merged.columns:
                    raise PreprocessingError(
                        f"neutralization factor '{factor}' not found in neutralization_data"
                    )
                col_val = merged.select(pl.col(factor)).to_numpy().flatten().astype(np.float64)
                x_list.append(col_val.reshape(-1, 1))

        if not x_list:
            return scores

        x = np.column_stack(x_list)
        x = sm.add_constant(x)

        try:
            model = sm.OLS(y, x, missing="drop")
            results = model.fit()
            resid = results.resid
        except Exception as exc:
            raise PreprocessingError(f"OLS neutralization failed: {exc}") from exc

        return pl.DataFrame({"symbol": merged.select("symbol"), "score": resid})

    def _build_from_instruments(self, ctx: BarContext) -> pl.DataFrame | None:
        """Build neutralization data from ``ctx.instruments``."""
        if ctx.instruments is None or ctx.instruments.is_empty():
            return None

        data_cols: list[pl.Expr] = []
        has_market_cap = False
        for factor in self.factors:
            if factor == "industry":
                if "industry_l1" in ctx.instruments.columns:
                    data_cols.append(pl.col("industry_l1").alias("industry"))
            elif factor == "market_cap":
                has_market_cap = True
            else:
                if factor in ctx.instruments.columns:
                    data_cols.append(pl.col(factor))

        if not data_cols and not has_market_cap:
            return None

        base = ctx.instruments
        if data_cols:
            base = base.select(["symbol", *[c for c in data_cols]])

        # Market cap requires merging with bar close
        if has_market_cap:
            bar = ctx.bar
            mc_df = None
            if bar is not None and not bar.is_empty() and "close" in bar.columns:
                mc_df = self._merge_market_cap(ctx.instruments, bar.select(["symbol", "close"]))

            if mc_df is not None and not mc_df.is_empty():
                base = base.join(mc_df, on="symbol", how="left") if data_cols else mc_df

        # Drop symbols with null values
        base = base.drop_nulls()
        return base if not base.is_empty() else None

    @staticmethod
    def _merge_market_cap(
        instruments: pl.DataFrame,
        bar: pl.DataFrame,
    ) -> pl.DataFrame | None:
        """Join instruments with bar close to estimate market cap."""
        has_lot = "lot_size" in instruments.columns
        has_shares = "shares_outstanding" in instruments.columns

        if has_shares:
            mc = (
                instruments.select(["symbol", "shares_outstanding"])
                .join(bar.select(["symbol", "close"]), on="symbol", how="inner")
                .with_columns((pl.col("shares_outstanding") * pl.col("close")).alias("market_cap"))
                .select(["symbol", "market_cap"])
            )
            return mc
        elif has_lot:
            mc = (
                instruments.select(["symbol", "lot_size"])
                .join(bar.select(["symbol", "close"]), on="symbol", how="inner")
                .with_columns((pl.col("lot_size") * pl.col("close")).alias("market_cap"))
                .select(["symbol", "market_cap"])
            )
            return mc
        return None


# ---------------------------------------------------------------------------
# SignalPreprocessor — pipeline orchestrator
# ---------------------------------------------------------------------------


@dataclass
class SignalPreprocessor:
    """Full signal preprocessing pipeline.

    Stages: MissingValue → Winsorize → Standardize → Neutralize.

    Parameters
    ----------
    missing : MissingValue
    winsorize : Winsorize
    standardize : Standardize
    neutralize : Neutralize
    neutralization_data : pl.DataFrame | None
        Optional DataFrame with ``[symbol, ...]`` columns required by
        the neutralize stage.
    """

    missing: MissingValue = MissingValue.drop()
    winsorize: Winsorize = Winsorize.mad(3)
    standardize: Standardize = Standardize.rank()
    neutralize: Neutralize = Neutralize.none()
    neutralization_data: pl.DataFrame | None = None

    def transform(
        self,
        scores: pl.DataFrame,
        ctx: object | None = None,
    ) -> pl.DataFrame:
        """Run the full preprocessing pipeline.

        Parameters
        ----------
        scores : pl.DataFrame
            Must contain columns ``[symbol, score]``.
        ctx : object | None
            Reserved for future use (e.g., per-bar data from BarContext).

        Returns
        -------
        pl.DataFrame [symbol, score]
        """
        _require_score_schema(scores)
        if scores.is_empty():
            return scores

        result = self.missing.apply(scores)
        result = self.winsorize.apply(result)
        result = self.standardize.apply(result)
        result = self.neutralize.apply(result, self.neutralization_data, ctx)
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_score_schema(df: pl.DataFrame) -> None:
    if not {"symbol", "score"}.issubset(df.columns):
        raise PreprocessingError(f"scores must have columns ['symbol', 'score'], got {df.columns}")
