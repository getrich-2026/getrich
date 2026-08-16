"""Weight allocation strategies: score-to-weight mapping for portfolio construction.

Provides ``ScoreWeight`` (linear score weighting), ``InverseVol`` (volatility-based),
and ``RiskParity`` (equal risk contribution via scipy.optimize).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from scipy.optimize import minimize

from gr_backtest.exceptions import StrategyError


if TYPE_CHECKING:
    from gr_backtest.strategy.context import BarContext


_EMPTY_WEIGHTS = pl.DataFrame(
    {"symbol": [], "weight": []},
    schema={"symbol": pl.Utf8, "weight": pl.Float64},
)


def _require_columns(df: pl.DataFrame, expected: list[str]) -> None:
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise StrategyError(f"DataFrame missing required columns: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# ScoreWeight — linear score mapping
# ---------------------------------------------------------------------------


@dataclass
class ScoreWeight:
    """Linearly map signal scores to portfolio weights.

    Each symbol's weight is proportional to its score magnitude::

        weight_i = score_i / sum(|score_j|) * gross_exposure

    When ``long_only=True``, negative scores are treated as zero before
    normalization.

    Parameters
    ----------
    gross_exposure : float
        Target sum of absolute weights (default 1.0).
    long_only : bool
        If True, negative scores are truncated to zero (default True).
    """

    gross_exposure: float = 1.0
    long_only: bool = True

    def allocate(self, scores: pl.DataFrame, ctx: BarContext) -> pl.DataFrame:
        """Convert ``[symbol, score]`` to ``[symbol, weight]``."""
        _require_columns(scores, ["symbol", "score"])
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        # Drop null scores
        scores = scores.filter(pl.col("score").is_not_null())
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        # Truncate negative scores when long-only
        if self.long_only:
            scores = scores.with_columns(
                pl.when(pl.col("score") > 0.0).then(pl.col("score")).otherwise(0.0).alias("score")
            )

        # Sum of absolute scores
        sum_abs = scores.select(pl.col("score").abs().sum()).item()
        if sum_abs <= 0.0:
            return _EMPTY_WEIGHTS

        # Linear mapping
        scale = self.gross_exposure / sum_abs
        return scores.with_columns((pl.col("score") * scale).alias("weight")).select(
            ["symbol", "weight"]
        )


# ---------------------------------------------------------------------------
# InverseVol — volatility-based weighting
# ---------------------------------------------------------------------------


@dataclass
class InverseVol:
    """Weight inversely proportional to historical return volatility.

    For each symbol, weight is proportional to 1 / std(daily_returns).
    The direction (long/short) is taken from the score sign.

    Parameters
    ----------
    lookback : int
        Number of historical bars used to compute volatility (default 60).
    gross_exposure : float
        Target sum of absolute weights (default 1.0).
    """

    lookback: int = 60
    gross_exposure: float = 1.0

    def allocate(self, scores: pl.DataFrame, ctx: BarContext) -> pl.DataFrame:
        """Convert ``[symbol, score]`` to ``[symbol, weight]``."""
        _require_columns(scores, ["symbol", "score"])
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        # Drop null scores
        scores = scores.filter(pl.col("score").is_not_null())
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        # Symbols present in scores
        score_symbols = set(scores["symbol"].to_list())
        if not score_symbols:
            return _EMPTY_WEIGHTS

        # Get historical bars
        hist = ctx.history.lookback(
            symbols=list(score_symbols),
            columns=["symbol", "close", "dt"],
            n=self.lookback,
        )

        hist_symbols = set(hist["symbol"].to_list())
        valid_symbols = score_symbols & hist_symbols
        if not valid_symbols:
            return _EMPTY_WEIGHTS

        # Filter both DataFrames to valid symbols
        valid_list = list(valid_symbols)
        scores = scores.filter(pl.col("symbol").is_in(valid_list))
        hist = hist.filter(pl.col("symbol").is_in(valid_list))

        # Compute per-symbol return standard deviation
        vol_df = (
            hist.sort(["symbol", "dt"])
            .with_columns(pl.col("close").pct_change().over("symbol").alias("ret"))
            .filter(pl.col("ret").is_not_null())
            .group_by("symbol")
            .agg(pl.col("ret").drop_nulls().std(ddof=1).alias("vol"))
        )

        # Merge volatility back
        result = scores.join(vol_df, on="symbol", how="left")

        # Remove symbols with invalid volatility data
        result = result.filter(
            pl.col("vol").is_not_nan() & pl.col("vol").is_not_null() & (pl.col("vol") > 0.0)
        )

        if result.is_empty():
            return _EMPTY_WEIGHTS

        # Inverse vol -> normalize -> apply score direction
        result = result.with_columns((1.0 / pl.col("vol")).alias("inv_vol"))
        inv_sum: float = result.select(pl.col("inv_vol").sum()).item()

        if inv_sum <= 0.0:
            return _EMPTY_WEIGHTS

        return result.with_columns(
            (pl.col("inv_vol") / inv_sum * self.gross_exposure * pl.col("score").sign()).alias(
                "weight"
            )
        ).select(["symbol", "weight"])


# ---------------------------------------------------------------------------
# RiskParity — equal risk contribution
# ---------------------------------------------------------------------------


@dataclass
class RiskParity:
    """Allocate so each symbol contributes equal portfolio risk.

    Uses ``scipy.optimize.minimize`` (SLSQP) to find weights that equalize
    each asset's marginal risk contribution::

        min  sum((RC_i - RC_avg)^2)
        s.t. sum(w_i) = 1.0,  w_i >= 0

    where RC_i = w_i * (Cov * w)_i / sqrt(w' Cov w).

    Falls back to equal weight when covariance estimation or optimization
    fails.

    Parameters
    ----------
    lookback : int
        Number of historical bars for covariance estimation (default 252).
    gross_exposure : float
        Target sum of absolute weights (default 1.0).
    """

    lookback: int = 252
    gross_exposure: float = 1.0

    def allocate(self, scores: pl.DataFrame, ctx: BarContext) -> pl.DataFrame:
        """Convert ``[symbol, score]`` to ``[symbol, weight]``."""
        _require_columns(scores, ["symbol", "score"])
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        # Drop null scores
        scores = scores.filter(pl.col("score").is_not_null())
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        # Determine score direction per symbol
        dir_map: dict[str, float] = dict(
            scores.select(["symbol", pl.col("score").sign().alias("dir")]).iter_rows()
        )

        # Get historical bars for valid symbols
        score_symbols = set(scores["symbol"].to_list())
        hist = ctx.history.lookback(
            symbols=list(score_symbols),
            columns=["symbol", "close", "dt"],
            n=self.lookback,
        )

        hist_symbols = set(hist["symbol"].to_list())
        valid_symbols = score_symbols & hist_symbols
        if not valid_symbols:
            return _EMPTY_WEIGHTS

        valid_list = list(valid_symbols)
        hist = hist.filter(pl.col("symbol").is_in(valid_list))

        # Compute daily returns -> pivot to matrix
        returns = (
            hist.sort(["symbol", "dt"])
            .with_columns(pl.col("close").pct_change().over("symbol").alias("ret"))
            .filter(pl.col("ret").is_not_null())
            .select(["dt", "symbol", "ret"])
        )

        if returns.is_empty():
            return _EMPTY_WEIGHTS

        n_symbols = len(valid_list)
        if n_symbols < 1:
            return _EMPTY_WEIGHTS

        # Single symbol: no optimization needed
        if n_symbols == 1:
            sym = valid_list[0]
            direction = dir_map.get(sym, 1.0)
            return pl.DataFrame(
                {"symbol": [sym], "weight": [direction * self.gross_exposure]},
                schema={"symbol": pl.Utf8, "weight": pl.Float64},
            )

        # Pivot: rows = time, columns = symbols, values = returns
        try:
            return_matrix = returns.pivot(
                index="dt",
                columns="symbol",
                values="ret",
            ).drop("dt")
        except Exception:
            return self._fallback(valid_list)

        # Drop any fully-null columns and rows with NaN
        return_matrix = return_matrix.drop_nulls()
        if return_matrix.width < 2:
            return self._fallback(valid_list)

        # Need at least as many observations as variables for cov estimation
        if return_matrix.height <= return_matrix.width:
            return self._fallback(valid_list)

        # Remaining symbols after drop
        remaining_symbols = return_matrix.columns

        try:
            cov = np.cov(return_matrix.to_numpy().T, ddof=1)
            n = cov.shape[0]
        except np.linalg.LinAlgError:
            return self._fallback(remaining_symbols)

        # Risk parity objective
        def _objective(w: np.ndarray) -> float:
            port_var = float(w @ cov @ w)
            if port_var <= 1e-16:
                return 0.0
            port_vol = np.sqrt(port_var)
            rc = w * (cov @ w) / port_vol
            rc_target = port_vol / n
            return float(np.sum((rc - rc_target) ** 2))

        constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
        bounds = [(0.0, 1.0)] * n
        initial = np.ones(n) / n

        try:
            opt = minimize(
                _objective,
                initial,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-9, "maxiter": 1000},
            )
        except Exception:
            return self._fallback(remaining_symbols)

        if not opt.success:
            return self._fallback(remaining_symbols)

        # Apply directions from score signs
        weight_rows: list[dict[str, object]] = []
        for i, sym in enumerate(remaining_symbols):
            direction = dir_map.get(sym, 1.0)
            w = float(opt.x[i]) * direction * self.gross_exposure
            weight_rows.append({"symbol": sym, "weight": w})

        return pl.DataFrame(
            weight_rows,
            schema={"symbol": pl.Utf8, "weight": pl.Float64},
        )

    # ------------------------------------------------------------------
    # Fallback: equal weight
    # ------------------------------------------------------------------

    def _fallback(self, symbols: list[str]) -> pl.DataFrame:
        """Return equal weight allocation when optimization fails."""
        if not symbols:
            return _EMPTY_WEIGHTS
        n = len(symbols)
        w = self.gross_exposure / n
        return pl.DataFrame(
            {"symbol": symbols, "weight": [w] * n},
            schema={"symbol": pl.Utf8, "weight": pl.Float64},
        )


__all__ = [
    "BlackLitterman",
    "InverseVol",
    "MeanVariance",
    "RiskParity",
    "ScoreWeight",
]


# ---------------------------------------------------------------------------
# MeanVariance — Markowitz mean-variance optimization
# ---------------------------------------------------------------------------


@dataclass
class MeanVariance:
    """Allocate using Markowitz mean-variance optimization.

    Uses score signals as expected returns and historical returns for
    covariance estimation.  Solves::

        max  w'μ - 0.5 * λ * w'Σw

    where μ = normalized scores, Σ = historical covariance, λ = risk aversion.

    Parameters
    ----------
    lookback : int
        Number of historical bars for covariance estimation (default 252).
    gross_exposure : float
        Target sum of absolute weights (default 1.0).
    risk_aversion : float
        Risk aversion coefficient λ (default 1.0).  Higher = more conservative.
    allow_short : bool
        If True, negative weights are permitted (default False).
    """

    lookback: int = 252
    gross_exposure: float = 1.0
    risk_aversion: float = 1.0
    allow_short: bool = False

    def allocate(self, scores: pl.DataFrame, ctx: BarContext) -> pl.DataFrame:
        """Convert ``[symbol, score]`` to ``[symbol, weight]``."""
        _require_columns(scores, ["symbol", "score"])
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        scores = scores.filter(pl.col("score").is_not_null())
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        dir_map: dict[str, float] = dict(
            scores.select(["symbol", pl.col("score").sign().alias("dir")]).iter_rows()
        )
        score_symbols = set(scores["symbol"].to_list())

        hist = ctx.history.lookback(
            symbols=list(score_symbols),
            columns=["symbol", "close", "dt"],
            n=self.lookback,
        )

        hist_symbols = set(hist["symbol"].to_list())
        valid_symbols = score_symbols & hist_symbols
        if not valid_symbols:
            return _EMPTY_WEIGHTS

        valid_list = list(valid_symbols)
        scores = scores.filter(pl.col("symbol").is_in(valid_list))
        hist = hist.filter(pl.col("symbol").is_in(valid_list))

        # Compute daily returns -> pivot to matrix
        returns = (
            hist.sort(["symbol", "dt"])
            .with_columns(pl.col("close").pct_change().over("symbol").alias("ret"))
            .filter(pl.col("ret").is_not_null())
            .select(["dt", "symbol", "ret"])
        )

        if returns.is_empty():
            return _EMPTY_WEIGHTS

        n_symbols = len(valid_list)
        if n_symbols < 1:
            return _EMPTY_WEIGHTS

        if n_symbols == 1:
            sym = valid_list[0]
            direction = dir_map.get(sym, 1.0)
            if direction == 0.0:
                return _EMPTY_WEIGHTS
            return pl.DataFrame(
                {"symbol": [sym], "weight": [direction * self.gross_exposure]},
                schema={"symbol": pl.Utf8, "weight": pl.Float64},
            )

        # Pivot: rows = time, columns = symbols, values = returns
        try:
            return_matrix = returns.pivot(
                index="dt",
                columns="symbol",
                values="ret",
            ).drop("dt")
        except Exception:
            return self._fallback(valid_list, dir_map)

        return_matrix = return_matrix.drop_nulls()
        if return_matrix.width < 2:
            return self._fallback(valid_list, dir_map)

        # Need at least as many observations as variables for cov estimation
        if return_matrix.height <= return_matrix.width:
            return self._fallback(valid_list, dir_map)

        remaining_symbols = return_matrix.columns

        try:
            cov = np.cov(return_matrix.to_numpy().T, ddof=1)
        except np.linalg.LinAlgError:
            return self._fallback(remaining_symbols, dir_map)

        # Build expected return vector μ from scores, normalized to L1=1
        score_map: dict[str, float] = dict(scores.select(["symbol", "score"]).iter_rows())
        μ = np.array([float(score_map.get(sym, 0.0)) for sym in remaining_symbols], dtype=float)

        # For long-only: zero out negative scores before L1 normalization
        if not self.allow_short:
            μ = np.maximum(μ, 0.0)

        μ_norm = float(np.sum(np.abs(μ)))
        if μ_norm <= 1e-16:
            return self._fallback(remaining_symbols, dir_map)

        μ = μ / μ_norm

        # Filter zero-weight symbols for long-only
        if not self.allow_short:
            pos_mask = μ > 0.0
            n_pos = int(np.sum(pos_mask))
            if n_pos == 0:
                return _EMPTY_WEIGHTS
            if n_pos == 1:
                idx = int(np.argmax(pos_mask))
                sym = remaining_symbols[idx]
                return pl.DataFrame(
                    {"symbol": [sym], "weight": [self.gross_exposure]},
                    schema={"symbol": pl.Utf8, "weight": pl.Float64},
                )
            # Subset to positive-μ symbols
            remaining_symbols = [s for i, s in enumerate(remaining_symbols) if pos_mask[i]]
            μ = μ[pos_mask]
            cov = cov[np.ix_(pos_mask, pos_mask)]
        if self.allow_short:
            # Analytical unconstrained solution
            try:
                cov_inv = np.linalg.inv(cov)
            except np.linalg.LinAlgError:
                return self._fallback(remaining_symbols, dir_map)
            w_raw = (1.0 / self.risk_aversion) * cov_inv @ μ
            abs_sum = float(np.sum(np.abs(w_raw)))
            if abs_sum <= 1e-16:
                return self._fallback(remaining_symbols, dir_map)
            w = w_raw / abs_sum
        else:
            # Long-only SLSQP optimization
            def _mv_objective(w: np.ndarray) -> float:
                return -float(w @ μ) + 0.5 * self.risk_aversion * float(w @ cov @ w)

            constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
            bounds = [(0.0, 1.0)] * len(remaining_symbols)
            initial = np.ones(len(remaining_symbols)) / len(remaining_symbols)

            try:
                opt = minimize(
                    _mv_objective,
                    initial,
                    method="SLSQP",
                    bounds=bounds,
                    constraints=constraints,
                    options={"ftol": 1e-9, "maxiter": 1000},
                )
            except Exception:
                return self._fallback(remaining_symbols, dir_map)

            if not opt.success:
                return self._fallback(remaining_symbols, dir_map)

            w = opt.x

        # Build result
        weight_rows: list[dict[str, object]] = []
        for i, sym in enumerate(remaining_symbols):
            weight_rows.append({"symbol": sym, "weight": float(w[i]) * self.gross_exposure})

        return pl.DataFrame(
            weight_rows,
            schema={"symbol": pl.Utf8, "weight": pl.Float64},
        )

    def _fallback(self, symbols: list[str], dir_map: dict[str, float]) -> pl.DataFrame:
        """Return equal weight allocation when optimization fails."""
        if not symbols:
            return _EMPTY_WEIGHTS

        if not self.allow_short:
            pos_symbols = [s for s in symbols if dir_map.get(s, 1.0) > 0.0]
            if not pos_symbols:
                return _EMPTY_WEIGHTS
            n = len(pos_symbols)
            w = self.gross_exposure / n
            return pl.DataFrame(
                {"symbol": pos_symbols, "weight": [float(w)] * n},
                schema={"symbol": pl.Utf8, "weight": pl.Float64},
            )

        n = len(symbols)
        w = self.gross_exposure / n
        rows = [{"symbol": sym, "weight": w * dir_map.get(sym, 1.0)} for sym in symbols]
        return pl.DataFrame(
            rows,
            schema={"symbol": pl.Utf8, "weight": pl.Float64},
        )


# ---------------------------------------------------------------------------
# BlackLitterman — Black-Litterman model
# ---------------------------------------------------------------------------


@dataclass
class BlackLitterman:
    """Allocate using the Black-Litterman model.

    Combines a prior (equal-weight implied equilibrium returns) with investor
    views (score signals) to produce posterior expected returns, then runs
    mean-variance optimization on the posterior.

    The BL posterior expected returns are::

        E(R) = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹  ×  [(τΣ)⁻¹Π + P'Ω⁻¹Q]

    where Π = equilibrium returns, Q = views, Ω = view uncertainty.

    Parameters
    ----------
    lookback : int
        Number of historical bars for covariance estimation (default 252).
    gross_exposure : float
        Target sum of absolute weights (default 1.0).
    delta : float
        Risk aversion coefficient for implied equilibrium returns (default 2.5).
    tau : float
        Prior uncertainty scalar (default 0.05).  Lower = stronger prior.
    allow_short : bool
        If True, negative weights are permitted (default False).
    """

    lookback: int = 252
    gross_exposure: float = 1.0
    delta: float = 2.5
    tau: float = 0.05
    allow_short: bool = False

    def allocate(self, scores: pl.DataFrame, ctx: BarContext) -> pl.DataFrame:
        """Convert ``[symbol, score]`` to ``[symbol, weight]``."""
        _require_columns(scores, ["symbol", "score"])
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        scores = scores.filter(pl.col("score").is_not_null())
        if scores.is_empty():
            return _EMPTY_WEIGHTS

        dir_map: dict[str, float] = dict(
            scores.select(["symbol", pl.col("score").sign().alias("dir")]).iter_rows()
        )
        score_symbols = set(scores["symbol"].to_list())

        hist = ctx.history.lookback(
            symbols=list(score_symbols),
            columns=["symbol", "close", "dt"],
            n=self.lookback,
        )

        hist_symbols = set(hist["symbol"].to_list())
        valid_symbols = score_symbols & hist_symbols
        if not valid_symbols:
            return _EMPTY_WEIGHTS

        valid_list = list(valid_symbols)
        scores = scores.filter(pl.col("symbol").is_in(valid_list))
        hist = hist.filter(pl.col("symbol").is_in(valid_list))

        # Compute daily returns -> pivot to matrix
        returns = (
            hist.sort(["symbol", "dt"])
            .with_columns(pl.col("close").pct_change().over("symbol").alias("ret"))
            .filter(pl.col("ret").is_not_null())
            .select(["dt", "symbol", "ret"])
        )

        if returns.is_empty():
            return _EMPTY_WEIGHTS

        n_symbols = len(valid_list)
        if n_symbols < 1:
            return _EMPTY_WEIGHTS

        if n_symbols == 1:
            sym = valid_list[0]
            direction = dir_map.get(sym, 1.0)
            if direction == 0.0:
                return _EMPTY_WEIGHTS
            return pl.DataFrame(
                {"symbol": [sym], "weight": [direction * self.gross_exposure]},
                schema={"symbol": pl.Utf8, "weight": pl.Float64},
            )

        # Pivot: rows = time, columns = symbols, values = returns
        try:
            return_matrix = returns.pivot(
                index="dt",
                columns="symbol",
                values="ret",
            ).drop("dt")
        except Exception:
            return self._fallback(valid_list, dir_map)

        return_matrix = return_matrix.drop_nulls()
        if return_matrix.width < 2:
            return self._fallback(valid_list, dir_map)

        if return_matrix.height <= return_matrix.width:
            return self._fallback(valid_list, dir_map)

        remaining_symbols = return_matrix.columns

        # Σ — covariance matrix
        try:
            cov = np.cov(return_matrix.to_numpy().T, ddof=1)
        except np.linalg.LinAlgError:
            return self._fallback(remaining_symbols, dir_map)

        # Score vector
        score_map: dict[str, float] = dict(scores.select(["symbol", "score"]).iter_rows())
        mu_scores = np.array(
            [float(score_map.get(sym, 0.0)) for sym in remaining_symbols],
            dtype=float,
        )

        # ---- Black-Litterman posterior ----
        try:
            posterior_μ = self._compute_posterior(cov, mu_scores)
        except np.linalg.LinAlgError:
            return self._fallback(remaining_symbols, dir_map)

        if posterior_μ is None:
            return self._fallback(remaining_symbols, dir_map)

        # ---- Mean-variance optimization on posterior ----

        # For long-only: zero out negative posteriors
        if not self.allow_short:
            pos_mask = posterior_μ > 0.0
            n_pos = int(np.sum(pos_mask))
            if n_pos == 0:
                return _EMPTY_WEIGHTS
            if n_pos == 1:
                idx = int(np.argmax(pos_mask))
                sym = remaining_symbols[idx]
                return pl.DataFrame(
                    {"symbol": [sym], "weight": [self.gross_exposure]},
                    schema={"symbol": pl.Utf8, "weight": pl.Float64},
                )
            remaining_symbols = [s for i, s in enumerate(remaining_symbols) if pos_mask[i]]
            posterior_μ = posterior_μ[pos_mask]
            cov = cov[np.ix_(pos_mask, pos_mask)]

        # Normalize μ to L1=1
        μ_norm = float(np.sum(np.abs(posterior_μ)))
        if μ_norm <= 1e-16:
            return self._fallback(remaining_symbols, dir_map)
        posterior_μ = posterior_μ / μ_norm

        if self.allow_short:
            try:
                cov_inv = np.linalg.inv(cov)
            except np.linalg.LinAlgError:
                return self._fallback(remaining_symbols, dir_map)
            w_raw = cov_inv @ posterior_μ  # δ=1 since already scaled
            abs_sum = float(np.sum(np.abs(w_raw)))
            if abs_sum <= 1e-16:
                return self._fallback(remaining_symbols, dir_map)
            w = w_raw / abs_sum
        else:

            def _bl_objective(w: np.ndarray) -> float:
                return -float(w @ posterior_μ) + 0.5 * float(w @ cov @ w)

            constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
            bounds = [(0.0, 1.0)] * len(remaining_symbols)
            initial = np.ones(len(remaining_symbols)) / len(remaining_symbols)

            try:
                opt = minimize(
                    _bl_objective,
                    initial,
                    method="SLSQP",
                    bounds=bounds,
                    constraints=constraints,
                    options={"ftol": 1e-9, "maxiter": 1000},
                )
            except Exception:
                return self._fallback(remaining_symbols, dir_map)

            if not opt.success:
                return self._fallback(remaining_symbols, dir_map)

            w = opt.x

        weight_rows: list[dict[str, object]] = []
        for i, sym in enumerate(remaining_symbols):
            weight_rows.append({"symbol": sym, "weight": float(w[i]) * self.gross_exposure})

        return pl.DataFrame(
            weight_rows,
            schema={"symbol": pl.Utf8, "weight": pl.Float64},
        )

    def _compute_posterior(
        self,
        cov: np.ndarray,
        mu_scores: np.ndarray,
    ) -> np.ndarray | None:
        """Compute Black-Litterman posterior expected returns."""
        n = len(mu_scores)

        # Prior: equal-weight implied equilibrium returns pi = delta * sigma * w_eq
        w_eq = np.ones(n) / n
        pi_prior = self.delta * cov @ w_eq

        # Normalize prior to L1=1 so scores can be scaled compatibly
        pi_norm = float(np.sum(np.abs(pi_prior)))
        if pi_norm > 1e-16:
            pi_prior = pi_prior / pi_norm

        # Views: P = I, Q = mu_scores
        # Normalize views to same L1 as prior
        q_norm = float(np.sum(np.abs(mu_scores)))
        q_vec = mu_scores / q_norm * pi_norm if q_norm > 1e-16 else mu_scores

        # omega = diag(P @ Sigma @ P' * tau) — view uncertainty
        omega_diag = np.abs(np.diag(cov)) * self.tau
        omega_diag = np.maximum(omega_diag, 1e-12)  # avoid division by zero
        omega_inv = np.diag(1.0 / omega_diag)

        # Posterior: E(R) = inv(inv(tau * Sigma) + W_inv) @ (inv(tau*Sigma) @ pi + W_inv @ q)
        try:
            ts_inv = (1.0 / max(self.tau, 1e-12)) * np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            return None

        m_mat = ts_inv + omega_inv
        rhs_vec = ts_inv @ pi_prior + omega_inv @ q_vec

        try:
            posterior_μ = np.linalg.solve(m_mat, rhs_vec)
        except np.linalg.LinAlgError:
            try:
                posterior_μ = np.linalg.pinv(m_mat) @ rhs_vec
            except Exception:
                return None

        return posterior_μ

    def _fallback(self, symbols: list[str], dir_map: dict[str, float]) -> pl.DataFrame:
        """Return equal weight allocation when optimization fails."""
        if not symbols:
            return _EMPTY_WEIGHTS

        if not self.allow_short:
            pos_symbols = [s for s in symbols if dir_map.get(s, 1.0) > 0.0]
            if not pos_symbols:
                return _EMPTY_WEIGHTS
            n = len(pos_symbols)
            w = self.gross_exposure / n
            return pl.DataFrame(
                {"symbol": pos_symbols, "weight": [float(w)] * n},
                schema={"symbol": pl.Utf8, "weight": pl.Float64},
            )

        n = len(symbols)
        w = self.gross_exposure / n
        rows = [{"symbol": sym, "weight": w * dir_map.get(sym, 1.0)} for sym in symbols]
        return pl.DataFrame(
            rows,
            schema={"symbol": pl.Utf8, "weight": pl.Float64},
        )
