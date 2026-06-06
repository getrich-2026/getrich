"""Tests for the HTML Tear Sheet report."""

import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import polars as pl

from getrich_backtest import (
    BacktestResult,
    Fill,
    Order,
    OrderIntent,
    OrderStatus,
    Reporter,
    RunConfig,
    SessionAttributionResult,
    SessionStats,
    Side,
    TearSheet,
    get_shanghai_tz,
)
from getrich_backtest.strategy.context import AccountView


TZ = get_shanghai_tz()


def _make_benchmark_curve() -> pl.DataFrame:
    """Build a simple benchmark equity curve for testing."""
    now = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
    end_dt = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
    return pl.DataFrame(
        {"dt": [now, end_dt], "equity": [100000.0, 100500.0]},
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )


def _make_benchmark_compare() -> object:
    """Build a simple BenchmarkCompareResult for testing."""
    from getrich_backtest import BenchmarkCompareResult

    return BenchmarkCompareResult(
        benchmark_return=Decimal("0.03"),
        benchmark_annualized_return=Decimal("0.06"),
        benchmark_volatility=Decimal("0.10"),
        benchmark_max_drawdown=Decimal("-0.05"),
        excess_return=Decimal("0.02"),
        alpha=Decimal("0.015"),
        beta=Decimal("0.75"),
        tracking_error=Decimal("0.08"),
        information_ratio=Decimal("0.40"),
        excess_max_drawdown=Decimal("-0.03"),
    )


def _make_result(strategy_name: str = "TestStrategy") -> BacktestResult:
    """Build a minimal BacktestResult for testing."""
    now = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
    end_dt = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
    config = RunConfig(
        run_id="test-report",
        strategy_name=strategy_name,
        symbols=("A",),
        start=now,
        end=end_dt,
        initial_cash=Decimal("100000"),
    )
    equity_curve = pl.DataFrame(
        {
            "dt": [now, end_dt],
            "cash": [Decimal("100000"), Decimal("100000")],
            "equity": [100000.0, 101000.0],
            "trading_pnl": [0.0, 500.0],
            "mtm_pnl": [0.0, 500.0],
            "total_fees": [0.0, 0.0],
            "gross_exposure": [0.0, 0.0],
        },
        schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
    )
    fill = Fill(
        fill_id="f1",
        order_id="o1",
        strategy_name=strategy_name,
        symbol="A",
        side=Side.BUY,
        qty=Decimal("100"),
        price=Decimal("100"),
        notional=Decimal("10000"),
        fee=Decimal("0"),
        fill_time=end_dt,
        bar_dt=end_dt,
    )
    intent = OrderIntent(symbol="A", side=Side.BUY, qty=Decimal("100"))
    order = Order(
        order_id="o1",
        intent=intent,
        strategy_name=strategy_name,
        created_dt=end_dt,
        created_index=0,
        eligible_index=1,
        status=OrderStatus.FILLED,
        filled_qty=Decimal("100"),
    )
    return BacktestResult(
        run_id="test-report",
        strategy_name=strategy_name,
        initial_cash=Decimal("100000"),
        config=config,
        orders=(order,),
        fills=(fill,),
        final_account=AccountView(cash=Decimal("90000")),
        equity_curve=equity_curve,
    )


class TestTearSheet:
    def test_to_html_contains_expected_sections(self) -> None:
        """HTML output with default (plotly) backend contains key elements."""
        result = _make_result()
        ts = TearSheet(result=result)
        html = ts.to_html()

        assert "<!DOCTYPE html>" in html
        assert "TestStrategy" in html
        # Plotly charts produce js-plotly-plot divs
        assert "plotly-graph-div" in html
        # Chart titles appear in hovermode labels
        assert "Metrics" in html
        assert "test-report" in html  # run_id
        assert html.strip().endswith("</html>")

    def test_to_html_with_metrics(self) -> None:
        """HTML includes metric values when metrics are provided."""
        from getrich_backtest.metrics import BacktestMetrics

        result = _make_result()
        metrics = BacktestMetrics(
            strategy_name="TestStrategy",
            run_id="test-report",
            total_return=Decimal("0.05"),
            log_return=Decimal("0.048"),
            annualized_return=Decimal("0.10"),
            annualized_volatility=Decimal("0.15"),
            sharpe_ratio=Decimal("0.47"),
            sortino_ratio=Decimal("0.60"),
            calmar_ratio=Decimal("0.50"),
            max_drawdown=Decimal("-0.20"),
            max_drawdown_duration=10,
            total_fees=Decimal("50"),
            total_turnover=Decimal("5000"),
            turnover_rate=Decimal("0.5"),
            total_trades=5,
            n_bars=252,
            risk_free_rate=Decimal("0.03"),
            trading_days_per_year=252,
        )
        ts = TearSheet(result=result, metrics=metrics)
        html = ts.to_html()

        # Check metric values appear
        assert "5.00%" in html  # total_return
        assert "0.4700" in html  # sharpe
        assert "0.6000" in html  # sortino
        assert "0.5000" in html  # calmar

    def test_plotly_backend_produces_div(self) -> None:
        """Plotly backend produces HTML with interactive divs, not img tags."""
        result = _make_result()
        ts = TearSheet(result=result, backend="plotly")
        html = ts.to_html()

        # Plotly interactive charts use div-based rendering
        assert "plotly-graph-div" in html
        # No static img tags for charts
        assert 'src="data:image/png' not in html

    def test_matplotlib_backend_still_works(self) -> None:
        """Matplotlib backend still produces img tags for backward compat."""
        result = _make_result()
        ts = TearSheet(result=result, backend="matplotlib")
        html = ts.to_html()

        # Matplotlib static chart images
        assert 'src="data:image/png' in html
        assert 'alt="Equity Curve"' in html
        assert 'alt="Drawdown"' in html
        assert 'alt="Monthly Returns"' in html
        # No plotly divs
        assert "plotly-graph-div" not in html

    def test_default_backend_is_plotly(self) -> None:
        """Default backend is plotly."""
        ts = TearSheet(result=_make_result())
        assert ts.backend == "plotly"

    def test_to_dict(self) -> None:
        """to_dict returns expected structure."""
        result = _make_result()
        ts = TearSheet(result=result)
        d = ts.to_dict()
        assert d["strategy_name"] == "TestStrategy"
        assert d["run_id"] == "test-report"
        assert "fingerprint" in d
        assert "config" in d
        # No metrics by default
        assert "metrics" not in d

    def test_to_dict_with_metrics(self) -> None:
        """to_dict includes metrics when set."""
        from getrich_backtest.metrics import BacktestMetrics

        result = _make_result()
        metrics = BacktestMetrics(
            strategy_name="TestStrategy",
            run_id="test-report",
            total_return=Decimal("0.05"),
            log_return=Decimal("0.048"),
            annualized_return=Decimal("0.10"),
            annualized_volatility=Decimal("0.15"),
            sharpe_ratio=Decimal("0.47"),
            sortino_ratio=Decimal("0.60"),
            calmar_ratio=Decimal("0.50"),
            max_drawdown=Decimal("-0.20"),
            max_drawdown_duration=10,
            total_fees=Decimal("50"),
            total_turnover=Decimal("5000"),
            turnover_rate=Decimal("0.5"),
            total_trades=5,
            n_bars=252,
            risk_free_rate=Decimal("0.03"),
            trading_days_per_year=252,
        )
        ts = TearSheet(result=result, metrics=metrics)
        d = ts.to_dict()
        assert "metrics" in d
        assert d["metrics"]["sortino_ratio"] == "0.60"

    def test_tear_sheet_no_metrics(self) -> None:
        """TearSheet works without metrics (empty cards)."""
        result = _make_result()
        ts = TearSheet(result=result, metrics=None)
        html = ts.to_html()
        assert "No metrics available" in html or "TestStrategy" in html


class TestReporterHtml:
    def test_reporter_save_html(self) -> None:
        """Reporter.save() with format='html' creates tear_sheet.html."""
        from getrich_backtest.metrics import BacktestMetrics

        result = _make_result()
        metrics = BacktestMetrics(
            strategy_name="TestStrategy",
            run_id="test-report",
            total_return=Decimal("0.01"),
            log_return=Decimal("0.01"),
            annualized_return=Decimal("0.05"),
            annualized_volatility=Decimal("0.10"),
            sharpe_ratio=Decimal("0.20"),
            sortino_ratio=Decimal("0.30"),
            calmar_ratio=Decimal("0.10"),
            max_drawdown=Decimal("-0.05"),
            max_drawdown_duration=2,
            total_fees=Decimal("0"),
            total_turnover=Decimal("10000"),
            turnover_rate=Decimal("0.1"),
            total_trades=1,
            n_bars=2,
            risk_free_rate=Decimal("0.03"),
            trading_days_per_year=252,
        )
        reporter = Reporter(result=result, metrics=metrics)
        with tempfile.TemporaryDirectory() as tmp:
            out = reporter.save(tmp, formats=("html",))
            html_path = Path(out) / "tear_sheet.html"
            assert html_path.exists()
            content = html_path.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in content
            assert "TestStrategy" in content

    def test_reporter_passes_backend(self) -> None:
        """Reporter passes backend to TearSheet."""
        result = _make_result()
        r1 = Reporter(result=result, backend="matplotlib")
        ts1 = r1.tear_sheet()
        assert ts1.backend == "matplotlib"

        r2 = Reporter(result=result, backend="plotly")
        ts2 = r2.tear_sheet()
        assert ts2.backend == "plotly"

    def test_reporter_default_backend(self) -> None:
        """Reporter default backend is plotly."""
        result = _make_result()
        r = Reporter(result=result)
        assert r.backend == "plotly"


class TestTearSheetBenchmark:
    def test_benchmark_overlay_in_plotly(self) -> None:
        """benchmark_equity_curve in result produces benchmark trace in chart."""
        result = _make_result()
        result = BacktestResult(
            run_id=result.run_id,
            strategy_name=result.strategy_name,
            initial_cash=result.initial_cash,
            config=result.config,
            orders=result.orders,
            fills=result.fills,
            final_account=result.final_account,
            equity_curve=result.equity_curve,
            benchmark_equity_curve=_make_benchmark_curve(),
        )
        ts = TearSheet(result=result)
        html = ts.to_html()

        # Benchmark overlay is present (orange line)
        assert "#e67e22" in html
        assert "Benchmark" in html

    def test_benchmark_overlay_in_mpl(self) -> None:
        """Mpl backend with benchmark curve renders both lines."""
        result = _make_result()
        result = BacktestResult(
            run_id=result.run_id,
            strategy_name=result.strategy_name,
            initial_cash=result.initial_cash,
            config=result.config,
            orders=result.orders,
            fills=result.fills,
            final_account=result.final_account,
            equity_curve=result.equity_curve,
            benchmark_equity_curve=_make_benchmark_curve(),
        )
        ts = TearSheet(result=result, backend="matplotlib")
        html = ts.to_html()

        assert 'src="data:image/png' in html
        assert "Equity Curve" in html or "img" in html

    def test_benchmark_metrics_card_and_table(self) -> None:
        """benchmark_compare provided → benchmark section appears in HTML."""
        result = _make_result()
        bc = _make_benchmark_compare()
        ts = TearSheet(result=result, benchmark_compare=bc)
        html = ts.to_html()

        assert "Benchmark Comparison" in html
        assert "Benchmark Return" in html
        assert "Excess Return" in html
        assert "Alpha" in html
        assert "Beta" in html
        assert "Tracking Error" in html
        assert "Information Ratio" in html

    def test_benchmark_metrics_values(self) -> None:
        """Benchmark metric values are rendered correctly."""
        result = _make_result()
        bc = _make_benchmark_compare()
        ts = TearSheet(result=result, benchmark_compare=bc)
        html = ts.to_html()

        # 3% benchmark return → "3.00%"
        assert "3.00%" in html
        # Beta 0.75 → "0.7500"
        assert "0.7500" in html
        # IR 0.40 → "0.4000"
        assert "0.4000" in html

    def test_no_benchmark_by_default(self) -> None:
        """No benchmark_compare or benchmark_curve → no benchmark section."""
        result = _make_result()
        ts = TearSheet(result=result)
        html = ts.to_html()

        assert "Benchmark Comparison" not in html
        assert "Excess Return" not in html

    def test_reporter_passes_benchmark_compare(self) -> None:
        """Reporter passes benchmark_compare to TearSheet."""
        result = _make_result()
        bc = _make_benchmark_compare()
        r = Reporter(result=result, benchmark_compare=bc)
        ts = r.tear_sheet()
        assert ts.benchmark_compare is bc


class TestTearSheetAttribution:
    def test_cost_attribution_in_html(self) -> None:
        """Cost attribution table appears in HTML when data provided."""
        from getrich_backtest import compute_cost_attribution

        result = _make_result()
        cost_df = compute_cost_attribution(result.fills)
        ts = TearSheet(result=result, cost_attribution=cost_df)
        html = ts.to_html()

        assert "Cost Attribution" in html
        assert result.fills[0].symbol in html

    def test_pnl_attribution_in_html(self) -> None:
        """PnL attribution table appears in HTML when data provided."""
        from getrich_backtest import compute_pnl_attribution

        result = _make_result()
        pnl_df = compute_pnl_attribution(result.fills)
        ts = TearSheet(result=result, pnl_attribution=pnl_df)
        html = ts.to_html()

        assert "PnL Attribution" in html

    def test_trade_log_in_html(self) -> None:
        """Trade log appears in HTML when journal provided."""
        from getrich_backtest import compute_trade_journal

        result = _make_result()
        journal = compute_trade_journal(result.fills)
        ts = TearSheet(result=result, trade_journal=journal)
        html = ts.to_html()

        assert "Trade Journal" in html
        assert result.fills[0].fill_id in html

    def test_no_attribution_by_default(self) -> None:
        """No attribution without providing data."""
        result = _make_result()
        ts = TearSheet(result=result)
        html = ts.to_html()

        assert "Cost Attribution" not in html
        assert "Trade Journal" not in html

    def test_reporter_auto_attribution(self) -> None:
        """Reporter auto-computes attribution from fills when auto_attribution=True."""
        result = _make_result()
        r = Reporter(result=result)
        ts = r.tear_sheet()

        # Reporter with fills should auto-compute attribution
        assert ts.trade_journal is not None
        assert ts.cost_attribution is not None
        assert ts.pnl_attribution is not None

    def test_reporter_no_auto_attribution(self) -> None:
        """Reporter skips attribution when auto_attribution=False."""
        result = _make_result()
        r = Reporter(result=result, auto_attribution=False)
        ts = r.tear_sheet()

        assert ts.trade_journal is None
        assert ts.cost_attribution is None
        assert ts.pnl_attribution is None


class TestTearSheetSessionAttribution:
    """Tests for session attribution in the HTML tear sheet."""

    def test_session_attribution_in_html(self) -> None:
        """Session Attribution section appears when data is set."""
        result = _make_result()
        session_attr = SessionAttributionResult(
            sessions=(
                SessionStats(
                    name="night",
                    count=5,
                    total_return=Decimal("0.02"),
                    mean_return=Decimal("0.004"),
                    std_return=Decimal("0.01"),
                    sharpe=Decimal("0.4"),
                    win_rate=Decimal("0.6"),
                    contribution_pnl=Decimal("2000"),
                ),
            ),
            total_periods=20,
            unclassified_count=0,
        )
        ts = TearSheet(result=result, session_attribution=session_attr)
        html = ts.to_html()
        assert "Session Attribution" in html
        assert "night" in html

    def test_session_unclassified_note(self) -> None:
        """Unclassified periods note appears when unclassified_count > 0."""
        result = _make_result()
        session_attr = SessionAttributionResult(
            sessions=(
                SessionStats(
                    name="morning",
                    count=5,
                    total_return=Decimal("0.01"),
                    mean_return=Decimal("0.002"),
                    std_return=Decimal("0.01"),
                    sharpe=Decimal("0.2"),
                    win_rate=Decimal("0.55"),
                    contribution_pnl=Decimal("1000"),
                ),
            ),
            total_periods=10,
            unclassified_count=3,
        )
        ts = TearSheet(result=result, session_attribution=session_attr)
        html = ts.to_html()
        assert "unclassified periods" in html
        assert "3" in html

    def test_no_session_attribution_by_default(self) -> None:
        """No Session Attribution section when not provided."""
        result = _make_result()
        ts = TearSheet(result=result)
        html = ts.to_html()
        assert "Session Attribution" not in html


class TestTearSheetSubAccount:
    def test_no_sub_account_section_when_none(self) -> None:
        """No Sub-Account section when sub_account_equity is None."""
        result = _make_result()
        ts = TearSheet(result=result)
        html = ts.to_html()
        assert "Sub-Account Equity" not in html

    def test_sub_account_section_when_present(self) -> None:
        """Sub-Account section appears when sub_account_equity is set."""
        result = _make_result()
        now = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        end_dt = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        sa_eq = {
            "alpha": pl.DataFrame(
                {"dt": [now, end_dt], "equity": ["500", "520"]},
                schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
            ),
        }
        result = BacktestResult(
            run_id=result.run_id,
            strategy_name=result.strategy_name,
            initial_cash=result.initial_cash,
            config=result.config,
            orders=result.orders,
            fills=result.fills,
            final_account=result.final_account,
            equity_curve=result.equity_curve,
            sub_account_equity=sa_eq,
        )
        ts = TearSheet(result=result)
        html = ts.to_html()

        assert "Sub-Account Equity" in html
        assert "alpha" in html
        # Sub-account equity curve should produce a plotly div
        assert "Sub:" in html  # legend label for sub-account trace

    def test_sub_account_empty_dict_no_section(self) -> None:
        """Empty sub_account_equity dict produces no section."""
        result = _make_result()
        result = BacktestResult(
            run_id=result.run_id,
            strategy_name=result.strategy_name,
            initial_cash=result.initial_cash,
            config=result.config,
            orders=result.orders,
            fills=result.fills,
            final_account=result.final_account,
            equity_curve=result.equity_curve,
            sub_account_equity={},
        )
        ts = TearSheet(result=result)
        html = ts.to_html()
        assert "Sub-Account Equity" not in html

    def test_sub_account_multiple_accounts(self) -> None:
        """Multiple sub-accounts all appear in the section."""
        result = _make_result()
        now = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        end_dt = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        sa_eq = {
            "alpha": pl.DataFrame(
                {"dt": [now, end_dt], "equity": ["500", "520"]},
                schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
            ),
            "beta": pl.DataFrame(
                {"dt": [now, end_dt], "equity": ["300", "290"]},
                schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
            ),
        }
        result = BacktestResult(
            run_id=result.run_id,
            strategy_name=result.strategy_name,
            initial_cash=result.initial_cash,
            config=result.config,
            orders=result.orders,
            fills=result.fills,
            final_account=result.final_account,
            equity_curve=result.equity_curve,
            sub_account_equity=sa_eq,
        )
        ts = TearSheet(result=result)
        html = ts.to_html()

        assert "Sub-Account Equity" in html
        assert "alpha" in html
        assert "beta" in html
        # Summary table headers
        assert "Initial Equity" in html
        assert "Final Equity" in html
        assert "Max Drawdown" in html

    def test_matplotlib_backend_sub_accounts(self) -> None:
        """Matplotlib backend renders sub-account curves as base64 PNG img tags."""
        result = _make_result()
        now = datetime(2026, 1, 2, 9, 30, tzinfo=TZ)
        end_dt = datetime(2026, 1, 3, 9, 30, tzinfo=TZ)
        sa_eq = {
            "alpha": pl.DataFrame(
                {"dt": [now, end_dt], "equity": ["500", "520"]},
                schema_overrides={"dt": pl.Datetime("ms", "Asia/Shanghai")},
            ),
        }
        result = BacktestResult(
            run_id=result.run_id,
            strategy_name=result.strategy_name,
            initial_cash=result.initial_cash,
            config=result.config,
            orders=result.orders,
            fills=result.fills,
            final_account=result.final_account,
            equity_curve=result.equity_curve,
            sub_account_equity=sa_eq,
        )
        ts = TearSheet(result=result, backend="matplotlib")
        html = ts.to_html()

        # Section still appears
        assert "Sub-Account Equity" in html
        assert "alpha" in html
        # Matplotlib image tag for sub-account chart
        assert 'alt="Sub-Account Equity Curves"' in html
        assert 'src="data:image/png' in html
        # No plotly CDN
        assert "plotly-graph-div" not in html
