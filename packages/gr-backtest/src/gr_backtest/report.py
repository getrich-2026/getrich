"""Backtest report export (JSON + Parquet + HTML)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import matplotlib
import plotly.graph_objects as go
import plotly.io as pio
import polars as pl
from matplotlib import pyplot as plt, ticker as mticker


matplotlib.use("Agg")  # non-interactive backend

from gr_backtest.attribution import (
    FactorRegResult,
    SessionAttributionResult,
    compute_cost_attribution,
    compute_pnl_attribution,
    compute_trade_journal,
)
from gr_backtest.benchmark import BenchmarkCompareResult
from gr_backtest.execution import Fill, Order
from gr_backtest.metrics import BacktestMetrics
from gr_backtest.result import BacktestResult


_CHART_DPI = 100
_CHART_WIDTH = 10
_CHART_HEIGHT = 3.5

_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; padding: 20px; background: #f5f5f5; color: #333; }
.wrap { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.4em; margin: 0 0 4px; }
.subtitle { color: #666; font-size: 0.85em; margin-bottom: 16px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
.card { background: #fff; border-radius: 8px; padding: 12px 18px;
        flex: 0 0 auto; min-width: 120px;
        box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.card .val { font-size: 1.3em; font-weight: 600; }
.card .lbl { font-size: 0.75em; color: #888; margin-top: 2px; }
.chart { background: #fff; border-radius: 8px; padding: 12px; margin-bottom: 16px;
         box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.chart img { width: 100%; height: auto; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px;
        overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
th, td { padding: 6px 12px; text-align: left; border-bottom: 1px solid #eee;
         font-size: 0.85em; }
th { background: #fafafa; font-weight: 600; color: #555; }
.bm-section { margin-top: 8px; }
.bm-title { font-size: 1.1em; font-weight: 600; margin: 0 0 4px; color: #e67e22; }
.sa-section { margin-top: 8px; }
.sa-title { font-size: 1.1em; font-weight: 600; margin: 0 0 4px; color: #059669; }
.attr-section { margin-top: 8px; }
.attr-title { font-size: 1.1em; font-weight: 600; margin: 0 0 4px; color: #8b5cf6; }
.collapse { max-height: 400px; overflow-y: auto; }
.footer { margin-top: 16px; font-size: 0.75em; color: #999; }
"""


class _DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts Decimal to string."""

    def default(self, o: object) -> object:
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


def _fill_to_row(fill: Fill) -> dict[str, object]:
    return {
        "fill_id": fill.fill_id,
        "order_id": fill.order_id,
        "symbol": fill.symbol,
        "side": fill.side.value,
        "qty": str(fill.qty),
        "price": str(fill.price),
        "notional": str(fill.notional),
        "fee": str(fill.fee),
        "fill_time": fill.fill_time.isoformat(),
        "bar_dt": fill.bar_dt.isoformat(),
        "slippage": str(fill.slippage),
        "tag": fill.tag,
    }


def _order_to_row(order: Order) -> dict[str, object]:
    return {
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "qty": str(order.qty),
        "filled_qty": str(order.filled_qty),
        "status": order.status.value,
        "reject_reason": order.reject_reason,
        "created_dt": order.created_dt.isoformat(),
        "created_index": order.created_index,
        "eligible_index": order.eligible_index,
        "tag": order.intent.tag,
    }


# ---------------------------------------------------------------------------
# Chart helpers (matplotlib → base64 PNG)
# ---------------------------------------------------------------------------


def _fig_to_b64(fig: plt.Figure) -> str:
    """Convert a matplotlib figure to a base64 PNG string."""
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=_CHART_DPI, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _plot_equity_curve(
    equity_curve: pl.DataFrame,
    benchmark_curve: pl.DataFrame | None = None,
) -> str:
    """Plot the equity curve, return base64 PNG.

    When ``benchmark_curve`` is provided it is overlaid as a dashed orange
    line, normalized to the same initial equity value as the strategy curve.
    """
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT))
    dts = equity_curve["dt"].to_list()
    eq = equity_curve["equity"].to_numpy().astype("float64")

    ax.plot(dts, eq, color="#2563eb", linewidth=1.2, label="Strategy")
    ax.fill_between(dts, eq, eq[0], alpha=0.08, color="#2563eb")
    ax.axhline(y=eq[0], color="#ccc", linewidth=0.5, linestyle="--")

    if benchmark_curve is not None:
        bm_dts = benchmark_curve["dt"].to_list()
        bm_eq = benchmark_curve["equity"].to_numpy().astype("float64")
        bm_eq = bm_eq * (eq[0] / bm_eq[0])
        ax.plot(bm_dts, bm_eq, color="#e67e22", linewidth=1.0, linestyle="--", label="Benchmark")
        ax.legend(fontsize=8)

    ax.set_ylabel("Equity")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    fig.autofmt_xdate()
    _style_ax(ax)
    b64 = _fig_to_b64(fig)
    plt.close(fig)
    return b64


def _plot_drawdown_curve(equity_curve: pl.DataFrame) -> str:
    """Plot the drawdown curve, return base64 PNG."""
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT))
    dts = equity_curve["dt"].to_list()
    eq = equity_curve["equity"].to_numpy().astype("float64")
    running_max = eq[0]
    dd = [0.0]
    for v in eq[1:]:
        if v > running_max:
            running_max = v
        dd.append((v - running_max) / running_max)

    ax.fill_between(dts, dd, 0, alpha=0.4, color="#dc2626")
    ax.plot(dts, dd, color="#dc2626", linewidth=0.8)
    ax.set_ylabel("Drawdown")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1%}"))
    fig.autofmt_xdate()
    _style_ax(ax)
    b64 = _fig_to_b64(fig)
    plt.close(fig)
    return b64


def _plot_monthly_heatmap(equity_curve: pl.DataFrame) -> str:
    """Plot monthly return heatmap, return base64 PNG."""
    from gr_backtest.metrics import monthly_returns_heatmap

    monthly = monthly_returns_heatmap(equity_curve)
    if monthly.is_empty():
        # Return a blank placeholder
        fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT * 0.6))
        ax.text(0.5, 0.5, "No monthly data", ha="center", va="center", transform=ax.transAxes)
        _style_ax(ax)
        b64 = _fig_to_b64(fig)
        plt.close(fig)
        return b64

    pivot = monthly.pivot(index="year", columns="month", values="return").sort(
        by="year", descending=True
    )
    years = (
        pivot["year"].to_list() if "year" in pivot.columns else pivot.select(pl.first()).to_list()
    )
    months_labels = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    data = pivot.to_numpy()
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT * 0.8))

    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", interpolation="nearest")

    # Labels
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels([str(int(y)) for y in years], fontsize=8)
    ax.set_xticks(range(12))
    ax.set_xticklabels(months_labels, fontsize=7, rotation=45)

    # Annotate cells
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            val = data[i, j]
            if not np.isnan(val):
                ax.text(j, i, f"{val:.1%}", ha="center", va="center", fontsize=6)

    plt.colorbar(im, ax=ax, shrink=0.6)
    _style_ax(ax)
    b64 = _fig_to_b64(fig)
    plt.close(fig)
    return b64


def _style_ax(ax: plt.Axes) -> None:
    """Apply consistent styling to a matplotlib Axes."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#ddd")
    ax.spines["bottom"].set_color("#ddd")
    ax.tick_params(colors="#666", labelsize=8)


# ---------------------------------------------------------------------------
# Chart helpers (plotly → HTML div)
# ---------------------------------------------------------------------------


def _plotly_equity_curve(
    equity_curve: pl.DataFrame,
    benchmark_curve: pl.DataFrame | None = None,
) -> str:
    """Plot the equity curve as a Plotly interactive chart, return HTML div.

    When ``benchmark_curve`` is provided it is overlaid as a dashed orange
    line, normalized to the same initial equity value as the strategy curve.
    """
    dts = equity_curve["dt"].to_list()
    eq = equity_curve["equity"].to_numpy().astype("float64")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dts,
            y=eq,
            mode="lines",
            name="Strategy",
            line=dict(color="#2563eb", width=1.5),
        )
    )
    fig.add_hline(
        y=eq[0],
        line=dict(color="#ccc", width=0.8, dash="dash"),
    )

    if benchmark_curve is not None:
        bm_dts = benchmark_curve["dt"].to_list()
        bm_eq = benchmark_curve["equity"].to_numpy().astype("float64")
        # Normalize benchmark to the same initial value
        bm_eq = bm_eq * (eq[0] / bm_eq[0])
        fig.add_trace(
            go.Scatter(
                x=bm_dts,
                y=bm_eq,
                mode="lines",
                name="Benchmark",
                line=dict(color="#e67e22", width=1.2, dash="dash"),
            )
        )
        fig.update_layout(showlegend=True)

    fig.update_layout(
        template="plotly_white",
        height=380,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(rangeslider=dict(visible=True), title=None),
        yaxis=dict(title="Equity", tickformat=",.0f"),
        hovermode="x unified",
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _plotly_drawdown_curve(equity_curve: pl.DataFrame) -> str:
    """Plot the drawdown curve as a Plotly interactive chart, return HTML div."""
    dts = equity_curve["dt"].to_list()
    eq = equity_curve["equity"].to_numpy().astype("float64")

    running_max = eq[0]
    dd = [0.0]
    for v in eq[1:]:
        if v > running_max:
            running_max = v
        dd.append((v - running_max) / running_max)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dts,
            y=dd,
            mode="lines",
            name="Drawdown",
            line=dict(color="#dc2626", width=1),
            fill="tozeroy",
            fillcolor="rgba(220, 38, 38, 0.15)",
        )
    )
    fig.update_layout(
        template="plotly_white",
        height=380,
        margin=dict(l=0, r=0, t=0, b=0),
        yaxis=dict(title="Drawdown", tickformat=".1%"),
        xaxis=dict(rangeslider=dict(visible=True)),
        hovermode="x unified",
        showlegend=False,
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _plotly_monthly_heatmap(equity_curve: pl.DataFrame) -> str:
    """Plot monthly return heatmap as a Plotly interactive chart, return HTML div."""
    from gr_backtest.metrics import monthly_returns_heatmap

    monthly = monthly_returns_heatmap(equity_curve)
    if monthly.is_empty():
        fig = go.Figure()
        fig.add_annotation(
            text="No monthly data",
            showarrow=False,
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
        )
        fig.update_layout(template="plotly_white", height=300)
        return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    years = sorted(monthly["year"].unique().to_list(), reverse=True)
    month_labels = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    z_data: list[list[float | None]] = []
    texts: list[list[str]] = []
    for y in years:
        row: list[float | None] = []
        text_row: list[str] = []
        for m in range(1, 13):
            val = monthly.filter((pl.col("year") == y) & (pl.col("month") == m))
            if val.is_empty():
                row.append(None)
                text_row.append("")
            else:
                r = float(val["return"][0])
                row.append(r)
                text_row.append(f"{r:.1%}")
        z_data.append(row)
        texts.append(text_row)

    fig = go.Figure(
        data=go.Heatmap(
            z=z_data,
            x=month_labels,
            y=[str(y) for y in years],
            colorscale="RdYlGn",
            zmid=0,
            text=texts,
            texttemplate="%{text}",
            hovertemplate=("Year: %{y}<br>Month: %{x}<br>Return: %{text}<extra></extra>"),
        )
    )
    fig.update_layout(
        template="plotly_white",
        height=max(300, len(years) * 40 + 80),
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(side="bottom"),
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _plot_sub_account_curves(
    sub_account_equity: dict[str, pl.DataFrame],
    main_equity: pl.DataFrame,
) -> str:
    """Plot per-sub-account equity curves overlaid on the main curve (matplotlib).

    Returns a base64 PNG string.
    """
    fig, ax = plt.subplots(figsize=(_CHART_WIDTH, _CHART_HEIGHT))
    dts = main_equity["dt"].to_list()
    main_eq = main_equity["equity"].to_numpy().astype("float64")

    ax.plot(dts, main_eq, color="#2563eb", linewidth=1.5, label="Main Account")
    ax.fill_between(dts, main_eq, main_eq[0], alpha=0.06, color="#2563eb")

    colors = ["#059669", "#e67e22", "#8b5cf6", "#dc2626", "#0891b2", "#ca8a04"]
    for i, (name, df) in enumerate(sub_account_equity.items()):
        sa_dts = df["dt"].to_list()
        sa_eq = df["equity"].cast(pl.Float64).to_numpy().astype("float64") if df.height > 0 else []
        if len(sa_eq) == 0:
            continue
        color = colors[i % len(colors)]
        ax.plot(sa_dts, sa_eq, color=color, linewidth=1.0, linestyle="--", label=f"Sub: {name}")

    ax.legend(fontsize=7, ncol=2)
    ax.set_ylabel("Equity")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    fig.autofmt_xdate()
    _style_ax(ax)
    b64 = _fig_to_b64(fig)
    plt.close(fig)
    return b64


def _plotly_sub_account_curves(
    sub_account_equity: dict[str, pl.DataFrame],
    main_equity: pl.DataFrame,
) -> str:
    """Plot per-sub-account equity curves overlaid on the main equity curve.

    Each sub-account curve is normalized to start from its own initial value.
    Returns an HTML div string.
    """
    dts = main_equity["dt"].to_list()
    main_eq = main_equity["equity"].to_numpy().astype("float64")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dts,
            y=main_eq,
            mode="lines",
            name="Main Account",
            line=dict(color="#2563eb", width=2),
        )
    )

    colors = ["#059669", "#e67e22", "#8b5cf6", "#dc2626", "#0891b2", "#ca8a04"]
    for i, (name, df) in enumerate(sub_account_equity.items()):
        sa_dts = df["dt"].to_list()
        sa_eq = df["equity"].cast(pl.Float64).to_numpy().astype("float64") if df.height > 0 else []
        if len(sa_eq) == 0:
            continue
        color = colors[i % len(colors)]
        fig.add_trace(
            go.Scatter(
                x=sa_dts,
                y=sa_eq,
                mode="lines",
                name=f"Sub: {name}",
                line=dict(color=color, width=1.2, dash="dot"),
            )
        )

    fig.update_layout(
        template="plotly_white",
        height=400,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(rangeslider=dict(visible=True), title=None),
        yaxis=dict(title="Equity", tickformat=",.0f"),
        hovermode="x unified",
        showlegend=True,
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


# ---------------------------------------------------------------------------
# TearSheet
# ---------------------------------------------------------------------------


@dataclass
class TearSheet:
    """Single-run tear sheet report (HTML + dict export).

    Parameters
    ----------
    result : BacktestResult
        The completed backtest result.
    metrics : BacktestMetrics | None
        Pre-computed metrics (will be computed on demand if None).
    benchmark_compare : BenchmarkCompareResult | None
        Pre-computed benchmark comparison metrics.
    backend : str
        Chart rendering backend: ``"plotly"`` (default, interactive) or
        ``"matplotlib"`` (static PNG images).
    """

    result: BacktestResult
    metrics: BacktestMetrics | None = None
    benchmark_compare: BenchmarkCompareResult | None = None
    trade_journal: pl.DataFrame | None = None
    cost_attribution: pl.DataFrame | None = None
    pnl_attribution: pl.DataFrame | None = None
    brinson_attribution: pl.DataFrame | None = None
    factor_regression: FactorRegResult | None = None
    session_attribution: SessionAttributionResult | None = None
    backend: str = "plotly"

    def to_html(self) -> str:
        """Generate a standalone HTML tear sheet with inline charts."""
        eq = self.result.equity_curve
        bm_eq = self.result.benchmark_equity_curve

        cards_html = self._render_cards()
        metrics_rows = self._render_metrics_table()

        if self.backend == "plotly":
            equity_div = _plotly_equity_curve(eq, benchmark_curve=bm_eq)
            drawdown_div = _plotly_drawdown_curve(eq)
            heatmap_div = _plotly_monthly_heatmap(eq)
        else:
            equity_b64 = _plot_equity_curve(eq, benchmark_curve=bm_eq)
            drawdown_b64 = _plot_drawdown_curve(eq)
            heatmap_b64 = _plot_monthly_heatmap(eq)
            equity_div = f'<img src="data:image/png;base64,{equity_b64}" alt="Equity Curve"/>'
            drawdown_div = f'<img src="data:image/png;base64,{drawdown_b64}" alt="Drawdown"/>'
            heatmap_div = f'<img src="data:image/png;base64,{heatmap_b64}" alt="Monthly Returns"/>'

        bm_section = self._render_benchmark_section()
        sa_section = self._render_sub_account_section()
        attr_section = self._render_attribution_section()

        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Tear Sheet — {_esc(self.result.strategy_name)}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>{_esc(self.result.strategy_name)}</h1>
<div class="subtitle">
Run: {self.result.run_id} &nbsp;|&nbsp; Config fingerprint: {self.result.config.fingerprint()}
</div>

<div class="cards">{cards_html}</div>

<div class="chart">{equity_div}</div>
<div class="chart">{drawdown_div}</div>
<div class="chart">{heatmap_div}</div>{sa_section}{bm_section}{attr_section}

<h2 style="margin-top: 20px;">Metrics</h2>
<table>{metrics_rows}</table>

<div class="footer">
Generated: {_now_iso()} &nbsp;|&nbsp; Bars: {eq.height} &nbsp;|&nbsp;
Initial Cash: {self.result.initial_cash} &nbsp;|&nbsp;
Strategy: {_esc(self.result.strategy_name)}
</div>
</div></body></html>"""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dict."""
        d: dict[str, object] = {
            "strategy_name": self.result.strategy_name,
            "run_id": self.result.run_id,
            "fingerprint": self.result.config.fingerprint(),
            "config": self.result.config.to_dict(),
        }
        if self.metrics is not None:
            d["metrics"] = self.metrics.to_dict()
        return d

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_cards(self) -> str:
        """Render summary metric cards."""
        m = self.metrics
        if m is None:
            return ""

        def card(label: str, value: str, fmt: str = "") -> str:
            return (
                f'<div class="card"><div class="val">{fmt}{value}</div>'
                f'<div class="lbl">{label}</div></div>'
            )

        parts = [
            card("Total Return", _pct(m.total_return)),
            card("CAGR", _pct(m.annualized_return)),
            card("Sharpe", _d(m.sharpe_ratio)),
            card("Sortino", _d(m.sortino_ratio)),
            card("Calmar", _d(m.calmar_ratio)),
            card("Max DD", _pct(m.max_drawdown)),
            card("Volatility", _pct(m.annualized_volatility)),
            card("Trades", str(m.total_trades)),
        ]
        return "\n".join(parts)

    def _render_metrics_table(self) -> str:
        """Render a full metrics table."""
        m = self.metrics
        if m is None:
            return "<tr><td>No metrics available</td></tr>"

        rows: list[tuple[str, str]] = [
            ("Strategy", self.result.strategy_name),
            ("Run ID", self.result.run_id),
            ("Total Return", _pct(m.total_return)),
            ("Log Return", _pct(m.log_return)),
            ("Annualized Return (CAGR)", _pct(m.annualized_return)),
            ("Annualized Volatility", _pct(m.annualized_volatility)),
            ("Sharpe Ratio", _d(m.sharpe_ratio)),
            ("Sortino Ratio", _d(m.sortino_ratio)),
            ("Calmar Ratio", _d(m.calmar_ratio)),
            ("Max Drawdown", _pct(m.max_drawdown)),
            ("Max Drawdown Duration", f"{m.max_drawdown_duration} bars"),
            ("Total Fees", _d(m.total_fees)),
            ("Total Turnover", _d(m.total_turnover)),
            ("Turnover Rate", _d(m.turnover_rate)),
            ("Total Trades", str(m.total_trades)),
            ("Number of Bars", str(m.n_bars)),
        ]
        return "".join(f"<tr><td>{_esc(k)}</td><td>{v}</td></tr>" for k, v in rows)

    # ------------------------------------------------------------------
    # Benchmark rendering helpers
    # ------------------------------------------------------------------

    def _render_benchmark_section(self) -> str:
        """Render the benchmark comparison section (cards + table)."""
        bc = self.benchmark_compare
        if bc is None:
            return ""

        cards = self._render_benchmark_cards(bc)
        table = self._render_benchmark_table(bc)
        return f"""
<div class="bm-section">
<h2 class="bm-title" style="margin-top: 20px;">Benchmark Comparison</h2>
<div class="cards">{cards}</div>
<table>{table}</table>
</div>"""

    # ------------------------------------------------------------------
    # Sub-account rendering helpers
    # ------------------------------------------------------------------

    def _render_sub_account_section(self) -> str:
        """Render the sub-account equity curves and summary when available."""
        sa_eq = self.result.sub_account_equity
        if not sa_eq:
            return ""

        if self.backend == "plotly":
            chart_html = _plotly_sub_account_curves(sa_eq, self.result.equity_curve)
        else:
            chart_b64 = _plot_sub_account_curves(sa_eq, self.result.equity_curve)
            chart_html = (
                f'<img src="data:image/png;base64,{chart_b64}" alt="Sub-Account Equity Curves"/>'
            )
        cards = self._render_sub_account_cards(sa_eq)
        table = self._render_sub_account_table(sa_eq)

        return f"""
<div class="sa-section">
<h2 class="sa-title" style="margin-top: 20px;">Sub-Account Equity</h2>
<div class="cards">{cards}</div>
<div class="chart">{chart_html}</div>
<table>{table}</table>
</div>"""

    @staticmethod
    def _render_sub_account_cards(
        sa_eq: dict[str, pl.DataFrame],
    ) -> str:
        """Render per-sub-account summary metric cards."""

        def card(label: str, value: str, fmt: str = "") -> str:
            return (
                f'<div class="card"><div class="val">{fmt}{value}</div>'
                f'<div class="lbl">{label}</div></div>'
            )

        parts: list[str] = []
        for name, df in sa_eq.items():
            if df.height < 2:
                continue
            first = float(df["equity"].cast(pl.Float64)[0])
            last = float(df["equity"].cast(pl.Float64)[-1])
            ret = (last - first) / first if first > 0 else 0.0
            parts.append(card(f"{name} Equity", f"{last:,.0f}"))
            parts.append(card(f"{name} Return", f"{ret * 100:.2f}%", fmt=("+" if ret >= 0 else "")))
        return "\n".join(parts)

    @staticmethod
    def _render_sub_account_table(
        sa_eq: dict[str, pl.DataFrame],
    ) -> str:
        """Render a per-sub-account metrics table."""
        headers = [
            "Sub-Account",
            "Initial Equity",
            "Final Equity",
            "Return",
            "Max Drawdown",
            "Bars",
        ]
        header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"

        rows: list[str] = []
        for name, df in sa_eq.items():
            if df.height == 0:
                continue
            eq_vals = df["equity"].cast(pl.Float64).to_numpy().astype("float64")
            first = float(eq_vals[0])
            last = float(eq_vals[-1])
            ret = (last - first) / first if first > 0 else 0.0

            # Max drawdown
            running_max = first
            max_dd = 0.0
            for v in eq_vals:
                if v > running_max:
                    running_max = v
                dd = (v - running_max) / running_max if running_max > 0 else 0.0
                if dd < max_dd:
                    max_dd = dd

            rows.append(
                f"<tr>"
                f"<td>{_esc(name)}</td>"
                f"<td>{first:,.0f}</td>"
                f"<td>{last:,.0f}</td>"
                f"<td>{ret * 100:+.2f}%</td>"
                f"<td>{max_dd * 100:.2f}%</td>"
                f"<td>{df.height}</td>"
                f"</tr>"
            )
        return header_row + "".join(rows)

    # ------------------------------------------------------------------
    # Benchmark rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_benchmark_cards(bc: BenchmarkCompareResult) -> str:
        """Render benchmark comparison metric cards."""

        def card(label: str, value: str, fmt: str = "") -> str:
            return (
                f'<div class="card"><div class="val">{fmt}{value}</div>'
                f'<div class="lbl">{label}</div></div>'
            )

        parts = [
            card(
                "Excess Return",
                _pct(bc.excess_return),
                fmt=("+" if bc.excess_return >= 0 else ""),
            ),
            card(
                "Alpha",
                _pct(bc.alpha),
                fmt=("+" if bc.alpha >= 0 else ""),
            ),
            card("Beta", _d(bc.beta)),
            card("Tracking Error", _pct(bc.tracking_error)),
            card("Info Ratio", _d(bc.information_ratio)),
            card("Excess Max DD", _pct(bc.excess_max_drawdown)),
        ]
        return "\n".join(parts)

    @staticmethod
    def _render_benchmark_table(bc: BenchmarkCompareResult) -> str:
        """Render a full benchmark comparison metrics table."""
        rows: list[tuple[str, str]] = [
            ("Benchmark Return", _pct(bc.benchmark_return)),
            ("Benchmark CAGR", _pct(bc.benchmark_annualized_return)),
            ("Benchmark Volatility", _pct(bc.benchmark_volatility)),
            ("Benchmark Max Drawdown", _pct(bc.benchmark_max_drawdown)),
            ("Excess Return", _pct(bc.excess_return)),
            ("Excess Max Drawdown", _pct(bc.excess_max_drawdown)),
            ("Alpha (Jensen's)", _pct(bc.alpha)),
            ("Beta", _d(bc.beta)),
            ("Tracking Error", _pct(bc.tracking_error)),
            ("Information Ratio", _d(bc.information_ratio)),
        ]
        return "".join(f"<tr><td>{_esc(k)}</td><td>{v}</td></tr>" for k, v in rows)

    # ------------------------------------------------------------------
    # Attribution rendering helpers
    # ------------------------------------------------------------------

    def _render_attribution_section(self) -> str:
        """Render the cost attribution and trade log section."""
        parts: list[str] = []

        if self.cost_attribution is not None and self.cost_attribution.height > 0:
            cost_table = self._render_cost_table(self.cost_attribution)
            parts.append(f"""
<div class="attr-section">
<h2 class="attr-title" style="margin-top: 20px;">Cost Attribution</h2>
<table>{cost_table}</table>
</div>""")

        if self.pnl_attribution is not None and self.pnl_attribution.height > 0:
            pnl_table = self._render_pnl_table(self.pnl_attribution)
            parts.append(f"""
<div class="attr-section">
<h2 class="attr-title" style="margin-top: 20px;">PnL Attribution (by Symbol)</h2>
<table>{pnl_table}</table>
</div>""")

        if self.trade_journal is not None and self.trade_journal.height > 0:
            trade_table = self._render_trade_log(self.trade_journal)
            parts.append(f"""
<div class="attr-section">
<h2 class="attr-title" style="margin-top: 20px;">Trade Journal</h2>
<div class="collapse">{trade_table}</div>
</div>""")

        if self.brinson_attribution is not None and self.brinson_attribution.height > 0:
            brinson_table = self._render_brinson_table(self.brinson_attribution)
            parts.append(f"""
<div class="attr-section">
<h2 class="attr-title" style="margin-top: 20px;">Brinson Attribution (by Industry)</h2>
<div class="collapse">{brinson_table}</div>
</div>""")

        if self.factor_regression is not None:
            fr = self.factor_regression
            factor_rows = "".join(
                f"<tr><td>{_esc(f.name)}</td>"
                f"<td>{_d(f.beta)}</td>"
                f"<td>{_d(f.t_stat)}</td>"
                f"<td>{_d(f.p_value)}</td>"
                f"<td>{_money(float(f.contribution_pnl))}</td></tr>"
                for f in fr.factors
            )
            headers = ["Factor", "Beta", "t-stat", "p-value", "Contribution PnL"]
            header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
            factor_table = header_row + factor_rows

            summary = (
                f"<p>Alpha: {_pct(fr.alpha)} "
                f"(t={_d(fr.alpha_tstat)}) &nbsp;|&nbsp; "
                f"R²: {_d(fr.r_squared)} &nbsp;|&nbsp; "
                f"Adj R²: {_d(fr.adj_r_squared)} &nbsp;|&nbsp; "
                f"Periods: {fr.n_periods}</p>"
            )
            parts.append(f"""
<div class="attr-section">
<h2 class="attr-title" style="margin-top: 20px;">Factor Regression Attribution</h2>
{summary}
<table>{factor_table}</table>
</div>""")

        if self.session_attribution is not None and len(self.session_attribution.sessions) > 0:
            session_table = self._render_session_table(self.session_attribution)
            unclassified = self.session_attribution.unclassified_count
            note = ""
            if unclassified > 0:
                note = (
                    f'<p style="font-size:0.8em;color:#999;">'
                    f"{unclassified} unclassified periods</p>"
                )
            parts.append(f"""
<div class="attr-section">
<h2 class="attr-title" style="margin-top: 20px;">Session Attribution</h2>
<table>{session_table}</table>
{note}
</div>""")

        return "\n".join(parts)

    @staticmethod
    def _render_cost_table(df: pl.DataFrame) -> str:
        """Render cost attribution table."""
        headers = [
            "Symbol",
            "Notional",
            "Fee",
            "Slippage",
            "Total Cost",
            "Fee (bps)",
            "Slippage (bps)",
            "Fills",
        ]
        rows = [
            f"<tr><td>{_esc(str(r['symbol']))}</td>"
            f"<td>{_money(r['total_notional'])}</td>"
            f"<td>{_money(r['total_fee'])}</td>"
            f"<td>{_money(r['total_slippage'])}</td>"
            f"<td>{_money(r['total_cost'])}</td>"
            f"<td>{r['fee_rate_bps']:.2f}</td>"
            f"<td>{r['slippage_rate_bps']:.2f}</td>"
            f"<td>{r['n_fills']}</td></tr>"
            for r in df.iter_rows(named=True)
        ]
        header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
        return header_row + "".join(rows)

    @staticmethod
    def _render_pnl_table(df: pl.DataFrame) -> str:
        """Render PnL attribution table."""
        headers = ["Symbol", "Realized PnL", "Fees", "Net PnL", "Trades"]
        rows = [
            f"<tr><td>{_esc(str(r['symbol']))}</td>"
            f"<td>{_money(r['total_realized_pnl'])}</td>"
            f"<td>{_money(r['total_fee'])}</td>"
            f"<td>{_money(r['net_pnl'])}</td>"
            f"<td>{r['n_trades']}</td></tr>"
            for r in df.iter_rows(named=True)
        ]
        header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
        return header_row + "".join(rows)

    @staticmethod
    def _render_trade_log(df: pl.DataFrame) -> str:
        """Render the trade journal as a scrollable table.

        Only the first 50 rows are shown.
        """
        display = df.head(50)
        headers = [
            "Fill ID",
            "Symbol",
            "Side",
            "Qty",
            "Price",
            "Fee",
            "Slippage",
            "Avg Cost",
            "Realized PnL",
            "Time",
        ]

        header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"

        rows = []
        for r in display.iter_rows(named=True):
            ts = str(r.get("fill_time", ""))
            if len(ts) > 19:
                ts = ts[:19]
            rows.append(
                f"<tr><td>{_esc(str(r['fill_id']))}</td>"
                f"<td>{_esc(str(r['symbol']))}</td>"
                f"<td>{r['side']}</td>"
                f"<td>{r['qty']:.2f}</td>"
                f"<td>{r['price']:.4f}</td>"
                f"<td>{r['fee']:.4f}</td>"
                f"<td>{r['slippage']:.4f}</td>"
                f"<td>{r['avg_cost_at_trade']:.4f}</td>"
                f"<td>{r['realized_pnl']:.2f}</td>"
                f"<td>{_esc(ts)}</td></tr>"
            )

        table_html = f"<table>{header_row}{''.join(rows)}</table>"
        if df.height > 50:
            table_html += (
                f'<p style="font-size:0.8em;color:#999;">Showing 50 of {df.height} fills</p>'
            )
        return table_html

    @staticmethod
    def _render_brinson_table(df: pl.DataFrame) -> str:
        """Render Brinson attribution results table."""
        headers = [
            "Date",
            "Industry",
            "Portfolio Wt",
            "Benchmark Wt",
            "Allocation",
            "Selection",
            "Interaction",
            "Active Return",
        ]
        header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"

        rows = []
        for r in df.iter_rows(named=True):
            dt_str = str(r.get("dt", ""))
            if len(dt_str) > 10:
                dt_str = dt_str[:10]
            rows.append(
                f"<tr>"
                f"<td>{_esc(dt_str)}</td>"
                f"<td>{_esc(str(r['industry_l1']))}</td>"
                f"<td>{r['portfolio_weight']:.2%}</td>"
                f"<td>{r['benchmark_weight']:.2%}</td>"
                f"<td>{r['allocation']:.4%}</td>"
                f"<td>{r['selection']:.4%}</td>"
                f"<td>{r['interaction']:.4%}</td>"
                f"<td>{r['active_return']:.4%}</td>"
                f"</tr>"
            )

        return header_row + "".join(rows)

    @staticmethod
    def _render_session_table(result: SessionAttributionResult) -> str:
        """Render session attribution results table."""
        headers = [
            "Session",
            "Count",
            "Total Return",
            "Mean Return",
            "Std Return",
            "Sharpe",
            "Win Rate",
            "Contribution PnL",
        ]
        header_row = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"

        rows = []
        for s in result.sessions:
            rows.append(
                f"<tr>"
                f"<td>{_esc(s.name)}</td>"
                f"<td>{s.count}</td>"
                f"<td>{_pct(s.total_return)}</td>"
                f"<td>{_pct(s.mean_return)}</td>"
                f"<td>{_pct(s.std_return)}</td>"
                f"<td>{_d(s.sharpe)}</td>"
                f"<td>{_pct(s.win_rate)}</td>"
                f"<td>{_money(float(s.contribution_pnl))}</td>"
                f"</tr>"
            )

        return header_row + "".join(rows)


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


@dataclass
class Reporter:
    """Backtest result reporter with JSON, Parquet, and HTML export.

    Parameters
    ----------
    result : BacktestResult
        The completed backtest result.
    metrics : BacktestMetrics | None
        Pre-computed metrics.
    benchmark_compare : BenchmarkCompareResult | None
        Pre-computed benchmark comparison metrics.
    backend : str
        Chart rendering backend for HTML tear sheets: ``"plotly"`` (default,
        interactive) or ``"matplotlib"`` (static PNG images).
    auto_attribution : bool
        If True (default), automatically compute trade journal, cost
        attribution, and PnL attribution from ``result.fills`` when
        generating a tear sheet.
    """

    result: BacktestResult
    metrics: BacktestMetrics | None = None
    benchmark_compare: BenchmarkCompareResult | None = None
    backend: str = "plotly"
    auto_attribution: bool = True

    def tear_sheet(self) -> TearSheet:
        """Return a ``TearSheet`` sub-report for this result."""
        trade_journal: pl.DataFrame | None = None
        cost_attr: pl.DataFrame | None = None
        pnl_attr: pl.DataFrame | None = None

        if self.auto_attribution and self.result.fills:
            trade_journal = compute_trade_journal(self.result.fills)
            cost_attr = compute_cost_attribution(self.result.fills)
            pnl_attr = compute_pnl_attribution(self.result.fills)

        return TearSheet(
            result=self.result,
            metrics=self.metrics,
            benchmark_compare=self.benchmark_compare,
            trade_journal=trade_journal,
            cost_attribution=cost_attr,
            pnl_attribution=pnl_attr,
            backend=self.backend,
        )

    def save(
        self,
        output_dir: str,
        *,
        formats: tuple[str, ...] = ("json", "parquet"),
    ) -> Path:
        """Write result data to the given directory.

        Parameters
        ----------
        output_dir : str
            Directory path to write files into.
        formats : tuple of str
            Output formats. Supported: ``"json"``, ``"parquet"``, ``"html"``.

        Returns
        -------
        Path
            The output directory path.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        for fmt in formats:
            if fmt == "json":
                self._write_manifest(out / "manifest.json")
            elif fmt == "parquet":
                self._write_parquet(out)
            elif fmt == "html":
                html = self.tear_sheet().to_html()
                (out / "tear_sheet.html").write_text(html, encoding="utf-8")
            else:
                raise ValueError(f"unsupported output format: {fmt}")

        return out

    def _write_manifest(self, path: Path) -> None:
        manifest: dict[str, object] = {
            "run_id": self.result.run_id,
            "strategy_name": self.result.strategy_name,
            "fingerprint": self.result.config.fingerprint(),
            "config": self.result.config.to_dict(),
            "summary": {
                "initial_cash": str(self.result.initial_cash),
                "final_cash": str(self.result.final_account.cash),
                "final_equity": str(
                    self.result.equity_curve["equity"][-1]
                    if self.result.equity_curve.height > 0
                    else self.result.final_account.cash
                ),
            },
        }
        if self.metrics is not None:
            manifest["metrics"] = self.metrics.to_dict()

        path.write_text(
            json.dumps(manifest, indent=2, cls=_DecimalEncoder, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_parquet(self, out: Path) -> None:
        equity_path = out / "equity.parquet"
        self.result.equity_curve.write_parquet(str(equity_path), compression="zstd")

        if self.result.fills:
            fills_df = pl.DataFrame([_fill_to_row(f) for f in self.result.fills])
            fills_df.write_parquet(str(out / "fills.parquet"), compression="zstd")

        if self.result.orders:
            orders_df = pl.DataFrame([_order_to_row(o) for o in self.result.orders])
            orders_df.write_parquet(str(out / "orders.parquet"), compression="zstd")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    """HTML-escape a string."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _pct(d: Decimal) -> str:
    """Format a Decimal as a percentage string."""
    return f"{float(d) * 100:.2f}%"


def _d(d: Decimal) -> str:
    """Format a Decimal as a decimal string."""
    return f"{float(d):.4f}"


def _now_iso() -> str:
    """Return the current time as an ISO string."""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _money(val: float) -> str:
    """Format a monetary value."""
    return f"{val:,.2f}"


# Ensure numpy is importable for heatmap
import numpy as np  # noqa: E402, F811
