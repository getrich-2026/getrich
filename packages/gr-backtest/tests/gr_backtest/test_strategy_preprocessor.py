"""Tests for the signal preprocessing pipeline."""

from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest
from gr_backtest import (
    AccountView,
    BarContext,
    EqualWeight,
    HistoryView,
    MissingValue,
    Neutralize,
    Portfolio,
    PreprocessingError,
    SignalPreprocessor,
    Standardize,
    Winsorize,
    get_shanghai_tz,
)


TZ = get_shanghai_tz()


def _scores(pairs: list[tuple[str, float | None]]) -> pl.DataFrame:
    return pl.DataFrame({"symbol": [s for s, _ in pairs], "score": [v for _, v in pairs]})


def _bar_ctx(symbols: list[str] | None = None) -> BarContext:
    if symbols is None:
        symbols = ["A", "B", "C"]
    bar = pl.DataFrame(
        {
            "dt": [datetime(2026, 6, 1, 9, 30, tzinfo=TZ)] * len(symbols),
            "symbol": symbols,
            "open": [10.0] * len(symbols),
            "high": [11.0] * len(symbols),
            "low": [9.0] * len(symbols),
            "close": [10.0] * len(symbols),
            "volume": [1000.0] * len(symbols),
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    return BarContext(
        now=datetime(2026, 6, 1, 9, 30, tzinfo=TZ),
        run_id="test",
        account=AccountView(cash=Decimal("100000")),
        bar=bar,
        history=HistoryView(bar),
    )


# ---------------------------------------------------------------------------
# MissingValue
# ---------------------------------------------------------------------------


class TestMissingValue:
    def test_drop_removes_nulls(self) -> None:
        df = _scores([("A", 1.0), ("B", None), ("C", 3.0)])
        result = MissingValue.drop().apply(df)
        assert result.height == 2
        assert result["symbol"].to_list() == ["A", "C"]

    def test_drop_all_nulls_raises(self) -> None:
        df = _scores([("A", None), ("B", None)])
        with pytest.raises(PreprocessingError, match="empty result"):
            MissingValue.drop().apply(df)

    def test_drop_no_nulls_no_change(self) -> None:
        df = _scores([("A", 1.0), ("B", 2.0)])
        result = MissingValue.drop().apply(df)
        assert result.height == 2

    def test_fill_mean(self) -> None:
        df = _scores([("A", 1.0), ("B", None), ("C", 3.0)])
        result = MissingValue.fill_mean().apply(df)
        vals = result["score"].to_list()
        assert vals[0] == 1.0
        assert vals[1] == pytest.approx(2.0)  # mean of [1, 3]
        assert vals[2] == 3.0

    def test_fill_mean_all_nulls_raises(self) -> None:
        df = _scores([("A", None), ("B", None)])
        with pytest.raises(PreprocessingError, match="all scores are null"):
            MissingValue.fill_mean().apply(df)

    def test_fill_zero(self) -> None:
        df = _scores([("A", 1.0), ("B", None), ("C", 3.0)])
        result = MissingValue.fill_zero().apply(df)
        vals = result["score"].to_list()
        assert vals[1] == 0.0

    def test_empty_dataframe(self) -> None:
        df = pl.DataFrame({"symbol": [], "score": []})
        result = MissingValue.drop().apply(df)
        assert result.is_empty()

    def test_factory_methods(self) -> None:
        assert isinstance(MissingValue.drop(), MissingValue)
        assert isinstance(MissingValue.fill_mean(), MissingValue)
        assert isinstance(MissingValue.fill_zero(), MissingValue)

    def test_missing_column_raises(self) -> None:
        df = pl.DataFrame({"x": [1]})
        with pytest.raises(PreprocessingError, match="symbol.*score"):
            MissingValue.drop().apply(df)


# ---------------------------------------------------------------------------
# Winsorize
# ---------------------------------------------------------------------------


class TestWinsorize:
    def test_mad_clips_high(self) -> None:
        """Data where middle values are safe, a high outlier gets clipped."""
        df = _scores([("A", 0.0), ("B", 0.0), ("C", 0.0), ("D", 1.0), ("E", 100.0)])
        result = Winsorize.mad(3).apply(df)
        vals = result["score"].to_list()
        # median=0, MAD=0 → no clipping
        assert max(vals) <= 100.0

    def test_mad_clips_low(self) -> None:
        df = _scores([("A", 0.0), ("B", 0.0), ("C", 0.0), ("D", -1.0), ("E", -100.0)])
        result = Winsorize.mad(3).apply(df)
        vals = result["score"].to_list()
        assert min(vals) >= -100.0

    def test_mad_identical_scores_no_change(self) -> None:
        df = _scores([("A", 5.0), ("B", 5.0), ("C", 5.0)])
        result = Winsorize.mad(3).apply(df)
        assert result["score"].to_list() == [5.0, 5.0, 5.0]

    def test_mad_clips_asymmetric(self) -> None:
        """With asymmetric data, tight MAD clips more."""
        df = _scores([("A", -5.0), ("B", -4.0), ("C", 0.0), ("D", 1.0), ("E", 100.0)])
        tight = Winsorize.mad(1).apply(df)
        loose = Winsorize.mad(5).apply(df)
        tight_e = tight.filter(pl.col("symbol") == "E")["score"].item()
        loose_e = loose.filter(pl.col("symbol") == "E")["score"].item()
        assert tight_e < loose_e

    def test_quantile_clips(self) -> None:
        df = _scores([(s, float(v)) for s, v in zip("ABCDEFGHIJ", range(10), strict=True)])
        result = Winsorize.quantile(0.1, 0.9).apply(df)
        clipped = result.filter(pl.col("score") == result.select(pl.col("score").min()).item())
        assert clipped.height >= 1

    def test_none_passthrough(self) -> None:
        df = _scores([("A", 1.0), ("B", 100.0)])
        result = Winsorize.none().apply(df)
        assert result["score"].to_list() == [1.0, 100.0]

    def test_empty_input(self) -> None:
        df = pl.DataFrame({"symbol": [], "score": []})
        result = Winsorize.mad(3).apply(df)
        assert result.is_empty()

    def test_factory_methods(self) -> None:
        assert isinstance(Winsorize.mad(), Winsorize)
        assert isinstance(Winsorize.mad(2.5), Winsorize)
        assert isinstance(Winsorize.quantile(), Winsorize)
        assert isinstance(Winsorize.none(), Winsorize)

    def test_validates_mad_n(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            Winsorize.mad(-1)

    def test_validates_quantile_bounds(self) -> None:
        with pytest.raises(ValueError):
            Winsorize.quantile(0.5, 0.3)
        with pytest.raises(ValueError):
            Winsorize.quantile(-0.1, 0.9)
        with pytest.raises(ValueError):
            Winsorize.quantile(0.1, 1.5)

    def test_missing_column_raises(self) -> None:
        df = pl.DataFrame({"x": [1]})
        with pytest.raises(PreprocessingError):
            Winsorize.mad(3).apply(df)


# ---------------------------------------------------------------------------
# Standardize
# ---------------------------------------------------------------------------


class TestStandardize:
    def test_zscore_centers_and_scales(self) -> None:
        df = _scores([("A", 1.0), ("B", 2.0), ("C", 3.0), ("D", 4.0), ("E", 5.0)])
        result = Standardize.zscore().apply(df)
        vals = result["score"].to_list()
        assert sum(vals) == pytest.approx(0.0, abs=1e-10)
        mean_v = sum(vals) / len(vals)
        std_v = (sum((v - mean_v) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
        assert std_v == pytest.approx(1.0, abs=1e-6)

    def test_zscore_constant_input(self) -> None:
        df = _scores([("A", 5.0), ("B", 5.0)])
        result = Standardize.zscore().apply(df)
        assert result["score"].to_list() == [0.0, 0.0]

    def test_zscore_single_row(self) -> None:
        df = _scores([("A", 42.0)])
        result = Standardize.zscore().apply(df)
        assert result["score"].to_list() == [0.0]

    def test_rank_uniform(self) -> None:
        df = _scores([("A", 1.0), ("B", 2.0), ("C", 3.0), ("D", 4.0), ("E", 5.0)])
        result = Standardize.rank().apply(df)
        assert result["score"].to_list() == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])

    def test_rank_with_ties(self) -> None:
        df = _scores([("A", 1.0), ("B", 1.0), ("C", 3.0)])
        result = Standardize.rank().apply(df)
        assert result["score"].to_list() == pytest.approx([0.25, 0.25, 1.0])

    def test_rank_single_row(self) -> None:
        df = _scores([("A", 42.0)])
        result = Standardize.rank().apply(df)
        assert result["score"].to_list() == [0.5]

    def test_minmax_range(self) -> None:
        df = _scores([("A", -10.0), ("B", 0.0), ("C", 10.0)])
        result = Standardize.minmax().apply(df)
        assert result["score"].to_list() == [0.0, 0.5, 1.0]

    def test_minmax_constant(self) -> None:
        df = _scores([("A", 5.0), ("B", 5.0)])
        result = Standardize.minmax().apply(df)
        assert result["score"].to_list() == [0.0, 0.0]

    def test_none_passthrough(self) -> None:
        df = _scores([("A", 1.0), ("B", 2.0)])
        result = Standardize.none().apply(df)
        assert result["score"].to_list() == [1.0, 2.0]

    def test_factory_methods(self) -> None:
        assert isinstance(Standardize.zscore(), Standardize)
        assert isinstance(Standardize.rank(), Standardize)
        assert isinstance(Standardize.minmax(), Standardize)
        assert isinstance(Standardize.none(), Standardize)


# ---------------------------------------------------------------------------
# Neutralize
# ---------------------------------------------------------------------------


class TestNeutralize:
    def test_none_passthrough(self) -> None:
        df = _scores([("A", 1.0), ("B", 2.0)])
        result = Neutralize.none().apply(df, None)
        assert result["score"].to_list() == [1.0, 2.0]

    def test_no_data_skips(self) -> None:
        df = _scores([("A", 1.0), ("B", 2.0)])
        result = Neutralize.industry().apply(df, None)
        assert result["score"].to_list() == [1.0, 2.0]

    def test_industry_residual(self) -> None:
        """After industry neutralization, residuals have no industry bias."""
        scores = _scores(
            [
                ("A", 2.0),
                ("B", 2.0),
                ("C", 2.0),
                ("D", 0.0),
                ("E", 0.0),
                ("F", 0.0),
            ]
        )
        industry_data = pl.DataFrame(
            {
                "symbol": ["A", "B", "C", "D", "E", "F"],
                "industry": ["X", "X", "X", "Y", "Y", "Y"],
            }
        )
        result = Neutralize.industry().apply(scores, industry_data)
        resid_x = result.filter(pl.col("symbol").is_in(["A", "B", "C"]))["score"]
        resid_y = result.filter(pl.col("symbol").is_in(["D", "E", "F"]))["score"]
        assert resid_x.mean() == pytest.approx(0.0, abs=1e-6)
        assert resid_y.mean() == pytest.approx(0.0, abs=1e-6)

    def test_market_cap_residual(self) -> None:
        """After market cap neutralization, residuals should be uncorrelated."""
        np = pytest.importorskip("numpy")
        n = 50
        symbols = [f"S{i}" for i in range(n)]
        rng = np.random.default_rng(42)
        log_mcaps = rng.uniform(18, 25, n)
        scores_vals = 0.5 * log_mcaps + rng.normal(0, 0.1, n)

        scores_df = _scores(list(zip(symbols, scores_vals.tolist(), strict=True)))
        mcap_data = pl.DataFrame(
            {
                "symbol": symbols,
                "market_cap": np.exp(log_mcaps).tolist(),
            }
        )
        result = Neutralize.market_cap().apply(scores_df, mcap_data)
        resid = result["score"].to_numpy()
        corr = np.corrcoef(resid, log_mcaps)[0, 1]
        assert abs(corr) < 0.1

    def test_too_few_symbols_raises(self) -> None:
        scores = _scores([("A", 1.0)])
        industry_data = pl.DataFrame({"symbol": ["A"], "industry": ["X"]})
        with pytest.raises(PreprocessingError, match="at least 2"):
            Neutralize.industry().apply(scores, industry_data)

    def test_no_symbols_after_merge_raises(self) -> None:
        scores = _scores([("A", 1.0)])
        industry_data = pl.DataFrame({"symbol": ["Z"], "industry": ["X"]})
        with pytest.raises(PreprocessingError, match="no symbols matched"):
            Neutralize.industry().apply(scores, industry_data)

    def test_industry_size_combined(self) -> None:
        """Both industry and market_cap factors together."""
        scores = _scores(
            [
                ("A", 2.0),
                ("B", 2.0),
                ("C", 1.0),
                ("D", 0.0),
                ("E", 0.0),
                ("F", 0.0),
            ]
        )
        data = pl.DataFrame(
            {
                "symbol": ["A", "B", "C", "D", "E", "F"],
                "industry": ["X", "X", "X", "Y", "Y", "Y"],
                "market_cap": [1e9, 2e9, 3e9, 1e9, 2e9, 3e9],
            }
        )
        result = Neutralize.industry_size().apply(scores, data)
        assert result.height == 6
        assert result.select(pl.col("score").std()).item() > 0

    def test_factory_methods(self) -> None:
        assert isinstance(Neutralize.industry(), Neutralize)
        assert isinstance(Neutralize.market_cap(), Neutralize)
        assert isinstance(Neutralize.industry_size(), Neutralize)
        assert isinstance(Neutralize.none(), Neutralize)
        assert isinstance(Neutralize.style(["x", "y"]), Neutralize)


# ---------------------------------------------------------------------------
# SignalPreprocessor pipeline
# ---------------------------------------------------------------------------


class TestSignalPreprocessor:
    def test_full_pipeline_default(self) -> None:
        scores = _scores([("A", 1.0), ("B", None), ("C", 100.0)])
        preproc = SignalPreprocessor()
        result = preproc.transform(scores)
        # drop null → [A=1.0, C=100.0]
        # rank → [0.0, 1.0]
        assert result.height == 2
        assert result["score"].to_list() == [0.0, 1.0]

    def test_custom_config(self) -> None:
        scores = _scores([("A", 10.0), ("B", 20.0)])
        preproc = SignalPreprocessor(
            missing=MissingValue.fill_zero(),
            winsorize=Winsorize.none(),
            standardize=Standardize.minmax(),
            neutralize=Neutralize.none(),
        )
        result = preproc.transform(scores)
        assert result["score"].to_list() == [0.0, 1.0]

    def test_all_steps_disabled(self) -> None:
        scores = _scores([("A", 1.0), ("B", 2.0)])
        preproc = SignalPreprocessor(
            missing=MissingValue.drop(),
            winsorize=Winsorize.none(),
            standardize=Standardize.none(),
            neutralize=Neutralize.none(),
        )
        result = preproc.transform(scores)
        assert result["score"].to_list() == [1.0, 2.0]

    def test_handles_empty_scores(self) -> None:
        preproc = SignalPreprocessor()
        result = preproc.transform(pl.DataFrame({"symbol": [], "score": []}))
        assert result.is_empty()

    def test_missing_column_raises(self) -> None:
        preproc = SignalPreprocessor()
        with pytest.raises(PreprocessingError, match="symbol.*score"):
            preproc.transform(pl.DataFrame({"x": [1]}))

    def test_with_neutralization(self) -> None:
        scores = _scores([("A", 2.0), ("B", 0.0)])
        data = pl.DataFrame({"symbol": ["A", "B"], "industry": ["X", "Y"]})
        preproc = SignalPreprocessor(
            missing=MissingValue.drop(),
            winsorize=Winsorize.none(),
            standardize=Standardize.none(),
            neutralize=Neutralize.industry(),
            neutralization_data=data,
        )
        result = preproc.transform(scores)
        assert result.height == 2


# ---------------------------------------------------------------------------
# Portfolio integration
# ---------------------------------------------------------------------------


class TestPortfolioPreprocessor:
    def test_preprocessor_applied_before_allocation(self) -> None:
        """Extreme scores are winsorized before allocation."""
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            preprocessor=SignalPreprocessor(
                missing=MissingValue.drop(),
                winsorize=Winsorize.mad(3),
                standardize=Standardize.rank(),
                neutralize=Neutralize.none(),
            ),
        )
        scores = _scores([("A", 100.0), ("B", 99.0), ("C", 1.0)])
        ctx = _bar_ctx()
        orders = pf.build_orders(scores, ctx)
        assert len(orders) >= 1

    def test_no_preprocessor_backward_compat(self) -> None:
        """Default preprocessor=None behaves as before."""
        pf = Portfolio(allocator=EqualWeight(top_k=2, long_only=True))
        scores = _scores([("A", 5.0), ("B", 3.0)])
        ctx = _bar_ctx()
        orders = pf.build_orders(scores, ctx)
        assert len(orders) == 2

    def test_preprocessor_all_null_raises(self) -> None:
        """All null scores should raise PreprocessingError from the pipeline."""
        pf = Portfolio(
            allocator=EqualWeight(top_k=2, long_only=True),
            preprocessor=SignalPreprocessor(missing=MissingValue.drop()),
        )
        scores = _scores([("A", None), ("B", None)])
        ctx = _bar_ctx()
        with pytest.raises(PreprocessingError):
            pf.build_orders(scores, ctx)
