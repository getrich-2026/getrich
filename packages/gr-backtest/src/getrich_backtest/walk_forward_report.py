"""Walk-forward analysis and HTML reporting helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import plotly.graph_objects as go
import plotly.io as pio
import polars as pl


if TYPE_CHECKING:
    from getrich_backtest.metrics import BacktestMetrics
    from getrich_backtest.walk_forward import WalkForwardResult


_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; padding: 20px; background: #f5f5f5; color: #333; }
.wrap { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.4em; margin: 0 0 4px; }
h2 { font-size: 1.1em; margin-top: 20px; }
.subtitle { color: #666; font-size: 0.85em; margin-bottom: 16px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
.card { background: #fff; border-radius: 8px; padding: 12px 18px;
        flex: 0 0 auto; min-width: 120px;
        box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.card .val { font-size: 1.3em; font-weight: 600; }
.card .lbl { font-size: 0.75em; color: #888; margin-top: 2px; }
.chart { background: #fff; border-radius: 8px; padding: 12px; margin-bottom: 16px;
         box-shadow: 0 1px 3px rgba(0,0,0,.1); }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px;
        overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
th, td { padding: 6px 12px; text-align: left; border-bottom: 1px solid #eee;
         font-size: 0.85em; }
th { background: #fafafa; font-weight: 600; color: #555; }
.empty { background: #fff; border-radius: 8px; padding: 16px; color: #777;
         box-shadow: 0 1px 3px rgba(0,0,0,.1); }
.footer { margin-top: 16px; font-size: 0.75em; color: #999; }
"""


@dataclass(frozen=True)
class WalkForwardReport:
    """Analysis and reporting helpers for a walk-forward result."""

    result: WalkForwardResult

    def isoos_comparison(self, *, metric: str | None = None) -> pl.DataFrame:
        """Return selected train metrics beside validation metrics by window."""
        metric_name = metric or self.result.select_metric
        rows: list[dict[str, object]] = []
        for window_result in self.result.completed():
            best_trial = window_result.best_trial
            train_metrics = best_trial.metrics if best_trial is not None else None
            validation_metrics = window_result.validation_metrics
            if train_metrics is None or validation_metrics is None:
                continue

            train_metric = _metric_decimal(train_metrics, metric_name)
            validation_metric = _metric_decimal(validation_metrics, metric_name)
            if train_metric is None or validation_metric is None:
                continue

            best_params = dict(best_trial.trial.params)
            row: dict[str, object] = {
                "walk_forward_id": self.result.walk_forward_id,
                "window_index": window_result.window.index,
                "train_start": window_result.window.train_start,
                "train_end": window_result.window.train_end,
                "val_start": window_result.window.val_start,
                "val_end": window_result.window.val_end,
                "best_trial_id": best_trial.trial.trial_id,
                "best_run_id": best_trial.trial.run_id,
                "validation_run_id": (
                    window_result.validation_result.run_id
                    if window_result.validation_result is not None
                    else None
                ),
                "metric": metric_name,
                "train_metric": train_metric,
                "validation_metric": validation_metric,
                "metric_delta": validation_metric - train_metric,
                "drop_off_ratio": _safe_ratio(validation_metric, train_metric),
                "best_params": best_params,
            }
            for name, value in best_params.items():
                row[f"param_{name}"] = value
            rows.append(row)
        return pl.DataFrame(rows)

    def window_metrics_frame(self) -> pl.DataFrame:
        """Return train and validation metrics flattened by walk-forward window."""
        rows: list[dict[str, object]] = []
        for window_result in self.result.completed():
            best_trial = window_result.best_trial
            row: dict[str, object] = {
                "walk_forward_id": self.result.walk_forward_id,
                "window_index": window_result.window.index,
                "train_start": window_result.window.train_start,
                "train_end": window_result.window.train_end,
                "val_start": window_result.window.val_start,
                "val_end": window_result.window.val_end,
                "best_trial_id": best_trial.trial.trial_id if best_trial is not None else None,
                "best_run_id": best_trial.trial.run_id if best_trial is not None else None,
                "validation_run_id": (
                    window_result.validation_result.run_id
                    if window_result.validation_result is not None
                    else None
                ),
            }
            if best_trial is not None and best_trial.metrics is not None:
                row.update(
                    {f"train_{name}": value for name, value in best_trial.metrics.to_dict().items()}
                )
            if window_result.validation_metrics is not None:
                row.update(
                    {
                        f"validation_{name}": value
                        for name, value in window_result.validation_metrics.to_dict().items()
                    }
                )
            rows.append(row)
        return pl.DataFrame(rows)

    def best_params_per_window(self) -> pl.DataFrame:
        """Return selected best parameters for each completed window."""
        rows: list[dict[str, object]] = []
        for window_result in self.result.completed():
            best_trial = window_result.best_trial
            if best_trial is None:
                continue
            best_params = dict(best_trial.trial.params)
            row: dict[str, object] = {
                "walk_forward_id": self.result.walk_forward_id,
                "window_index": window_result.window.index,
                "best_trial_id": best_trial.trial.trial_id,
                "best_run_id": best_trial.trial.run_id,
                "best_params": best_params,
            }
            for name, value in best_params.items():
                row[f"param_{name}"] = value
            rows.append(row)
        return pl.DataFrame(rows)

    def parameter_stability(
        self,
        param_x: str,
        param_y: str | None = None,
        *,
        metric: str | None = None,
    ) -> pl.DataFrame:
        """Aggregate selected parameter frequency and validation metric by parameter value."""
        metric_name = metric or self.result.select_metric
        groups: dict[tuple[object, ...], list[Decimal]] = {}
        seen_params: set[str] = set()

        for window_result in self.result.completed():
            best_trial = window_result.best_trial
            if best_trial is None:
                continue
            params = dict(best_trial.trial.params)
            seen_params.update(params)
            if param_x not in params or (param_y is not None and param_y not in params):
                continue
            key = (params[param_x],) if param_y is None else (params[param_x], params[param_y])
            groups.setdefault(key, [])
            metric_value = _metric_decimal(window_result.validation_metrics, metric_name)
            if metric_value is not None:
                groups[key].append(metric_value)

        missing = [
            name for name in (param_x, param_y) if name is not None and name not in seen_params
        ]
        if missing:
            raise ValueError(f"parameter not found in completed best params: {', '.join(missing)}")

        rows: list[dict[str, object]] = []
        for key, values in groups.items():
            row: dict[str, object] = {
                f"param_{param_x}": key[0],
                "count": len(values),
                "mean_validation_metric": _mean_decimal(values),
                "metric": metric_name,
            }
            if param_y is not None:
                row[f"param_{param_y}"] = key[1]
            rows.append(row)
        return pl.DataFrame(rows)

    def oos_equity_curve(self) -> pl.DataFrame:
        """Return concatenated out-of-sample equity curve segments."""
        return self.result.oos_equity_curve()

    def consistency_summary(self, *, metric: str | None = None) -> dict[str, object]:
        """Summarize train-vs-validation consistency for the selected metric."""
        metric_name = metric or self.result.select_metric
        train_values: list[Decimal] = []
        validation_values: list[Decimal] = []
        for row in self.isoos_comparison(metric=metric_name).iter_rows(named=True):
            train_metric = _decimal_or_none(row["train_metric"])
            validation_metric = _decimal_or_none(row["validation_metric"])
            if train_metric is None or validation_metric is None:
                continue
            train_values.append(train_metric)
            validation_values.append(validation_metric)

        mean_train = _mean_decimal(train_values)
        mean_validation = _mean_decimal(validation_values)
        mean_delta = None
        if train_values and validation_values:
            deltas = [
                val - train for train, val in zip(train_values, validation_values, strict=True)
            ]
            mean_delta = _mean_decimal(deltas)

        rank_corr = None
        if len(train_values) >= 2 and len(validation_values) >= 2:
            rank_corr = _spearman_rank_corr(
                [float(value) for value in train_values],
                [float(value) for value in validation_values],
            )

        return {
            "walk_forward_id": self.result.walk_forward_id,
            "metric": metric_name,
            "total_windows": len(self.result.windows),
            "completed_windows": len(self.result.completed()),
            "failed_windows": len(self.result.failed()),
            "mean_train_metric": mean_train,
            "mean_validation_metric": mean_validation,
            "mean_metric_delta": mean_delta,
            "drop_off_ratio": _safe_ratio(mean_validation, mean_train),
            "rank_corr_is_oos": rank_corr,
        }

    def summary(self, *, metric: str | None = None) -> dict[str, object]:
        """Return the base walk-forward summary plus IS/OOS diagnostics."""
        summary = dict(self.result.summary())
        summary.update(self.consistency_summary(metric=metric))
        return summary

    def to_html(self, *, metric: str | None = None) -> str:
        """Generate a standalone walk-forward HTML report."""
        metric_name = metric or self.result.select_metric
        consistency = self.consistency_summary(metric=metric_name)
        isoos = self.isoos_comparison(metric=metric_name)
        params = self.best_params_per_window()
        equity = self.oos_equity_curve()

        cards_html = _render_cards(
            [
                ("Completed", str(consistency["completed_windows"])),
                ("Failed", str(consistency["failed_windows"])),
                ("Mean Train", _format_value(consistency["mean_train_metric"])),
                ("Mean Validation", _format_value(consistency["mean_validation_metric"])),
                ("Drop-off", _format_value(consistency["drop_off_ratio"])),
                ("IS/OOS Rank Corr", _format_value(consistency["rank_corr_is_oos"])),
            ]
        )
        equity_html = (
            _plotly_oos_equity(equity) if not equity.is_empty() else _empty("No OOS equity")
        )
        isoos_chart = (
            _plotly_is_oos_comparison(isoos, metric=metric_name)
            if not isoos.is_empty()
            else _empty("No IS/OOS metric pairs")
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>WalkForward Report — {_esc(self.result.walk_forward_id)}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>WalkForward Report — {_esc(self.result.walk_forward_id)}</h1>
<div class="subtitle">
Metric: {_esc(metric_name)} &nbsp;|&nbsp; Refit: {_esc(self.result.refit)} &nbsp;|&nbsp;
Windows: {len(self.result.windows)}
</div>

<div class="cards">{cards_html}</div>

<h2>OOS Equity Curve</h2>
<div class="chart">{equity_html}</div>

<h2>Train vs Validation Metric</h2>
<div class="chart">{isoos_chart}</div>

<h2>Selected Parameters</h2>
{_frame_table(params, max_rows=50)}

<h2>IS/OOS Comparison</h2>
{_frame_table(isoos, max_rows=50)}

<div class="footer">
Generated by getrich_backtest WalkForwardReport &nbsp;|&nbsp; Metric: {_esc(metric_name)}
</div>
</div></body></html>"""


def _metric_decimal(metrics: BacktestMetrics | None, name: str) -> Decimal | None:
    if metrics is None:
        return None
    return _decimal_or_none(getattr(metrics, name, None))


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float | str):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return None


def _mean_decimal(values: Iterable[Decimal]) -> Decimal | None:
    values_tuple = tuple(values)
    if not values_tuple:
        return None
    return sum(values_tuple, Decimal("0")) / Decimal(len(values_tuple))


def _safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _spearman_rank_corr(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    x_ranks = _average_ranks(x)
    y_ranks = _average_ranks(y)
    mean_x = sum(x_ranks) / len(x_ranks)
    mean_y = sum(y_ranks) / len(y_ranks)
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(x_ranks, y_ranks, strict=True))
    denom_x = sum((a - mean_x) ** 2 for a in x_ranks)
    denom_y = sum((b - mean_y) ** 2 for b in y_ranks)
    denominator = (denom_x * denom_y) ** 0.5
    if denominator == 0:
        return None
    return numerator / denominator


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        rank = (i + 1 + j) / 2
        for original_index, _ in indexed[i:j]:
            ranks[original_index] = rank
        i = j
    return ranks


def _plotly_oos_equity(equity: pl.DataFrame) -> str:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=equity["dt"].to_list(),
            y=equity["equity"].cast(pl.Float64).to_list(),
            mode="lines",
            name="OOS Equity",
            line=dict(color="#2563eb", width=1.5),
        )
    )
    fig.update_layout(
        template="plotly_white",
        height=380,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(rangeslider=dict(visible=True), title=None),
        yaxis=dict(title="Equity", tickformat=",.0f"),
        hovermode="x unified",
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _plotly_is_oos_comparison(isoos: pl.DataFrame, *, metric: str) -> str:
    windows = isoos["window_index"].to_list()
    train = [_float_or_none(value) for value in isoos["train_metric"].to_list()]
    validation = [_float_or_none(value) for value in isoos["validation_metric"].to_list()]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=windows, y=train, name="Train", marker_color="#2563eb"))
    fig.add_trace(go.Bar(x=windows, y=validation, name="Validation", marker_color="#f97316"))
    fig.update_layout(
        template="plotly_white",
        height=360,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(title="Window"),
        yaxis=dict(title=metric),
        barmode="group",
        hovermode="x unified",
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _render_cards(cards: list[tuple[str, str]]) -> str:
    return "\n".join(
        '<div class="card">'
        f'<div class="val">{_esc(value)}</div>'
        f'<div class="lbl">{_esc(label)}</div>'
        "</div>"
        for label, value in cards
    )


def _frame_table(frame: pl.DataFrame, *, max_rows: int) -> str:
    if frame.is_empty():
        return _empty("No rows")
    columns = frame.columns
    header = "<tr>" + "".join(f"<th>{_esc(column)}</th>" for column in columns) + "</tr>"
    rows: list[str] = []
    for row in frame.head(max_rows).iter_rows(named=True):
        rows.append(
            "<tr>"
            + "".join(f"<td>{_esc(_format_value(row[column]))}</td>" for column in columns)
            + "</tr>"
        )
    return f"<table>{header}{''.join(rows)}</table>"


def _empty(message: str) -> str:
    return f'<div class="empty">{_esc(message)}</div>'


def _format_value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"{float(value):.4f}"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _float_or_none(value: object) -> float | None:
    decimal = _decimal_or_none(value)
    return float(decimal) if decimal is not None else None


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
