from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class QualityIssue:
    rule: str
    severity: str
    detail: dict[str, Any]


def validate_bars(
    df: pd.DataFrame,
    *,
    freq: str,
    price_jump_warn_pct: float | None = None,
    expected_minutes_per_day: int | None = None,
    expected_trading_days: list[Any] | tuple[Any, ...] | None = None,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if df.empty:
        return [QualityIssue("empty_frame", "warn", {"freq": freq})]

    for column in ["open", "high", "low", "close", "volume", "amount"]:
        if column not in df.columns:
            issues.append(QualityIssue("missing_column", "error", {"column": column}))

    if {"open", "high", "low", "close"}.issubset(df.columns):
        null_price = df[df[["open", "high", "low", "close"]].isna().any(axis=1)]
        if not null_price.empty:
            issues.append(QualityIssue("null_price", "error", {"rows": int(len(null_price))}))
        bad_ohlc = df[
            (df["high"] < df[["open", "close", "low"]].max(axis=1))
            | (df["low"] > df[["open", "close", "high"]].min(axis=1))
        ]
        if not bad_ohlc.empty:
            issues.append(QualityIssue("ohlc_relation", "error", {"rows": int(len(bad_ohlc))}))

    for column in [
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "volume",
        "amount",
        "open_interest",
        "settle",
        "pre_settle",
        "limit_up",
        "limit_down",
    ]:
        if column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce")
            bad = df[values.fillna(0) < 0]
            if not bad.empty:
                issues.append(QualityIssue("negative_value", "error", {"column": column, "rows": int(len(bad))}))

    if "adj_factor" in df.columns:
        bad_factor = df[df["adj_factor"].notna() & (df["adj_factor"] <= 0)]
        if not bad_factor.empty:
            issues.append(QualityIssue("adj_factor_non_positive", "error", {"rows": int(len(bad_factor))}))

    issues.extend(_validate_duplicate_keys(df))
    issues.extend(_validate_missing_trading_days(df, expected_trading_days=expected_trading_days))
    issues.extend(_validate_expected_minutes(df, freq=freq, expected_minutes_per_day=expected_minutes_per_day))

    if price_jump_warn_pct is not None:
        issues.extend(_validate_price_jump(df, threshold=price_jump_warn_pct))

    return issues


def _validate_duplicate_keys(df: pd.DataFrame) -> list[QualityIssue]:
    key_columns = ["instrument_id", "dt"]
    if not set(key_columns).issubset(df.columns):
        return []

    duplicate_mask = df.duplicated(key_columns, keep=False)
    if not duplicate_mask.any():
        return []

    samples = (
        df.loc[duplicate_mask, key_columns]
        .head(5)
        .assign(dt=lambda frame: frame["dt"].astype(str))
        .to_dict(orient="records")
    )
    return [
        QualityIssue(
            "duplicate_bar_key",
            "error",
            {"rows": int(duplicate_mask.sum()), "key_columns": key_columns, "samples": samples},
        )
    ]


def _validate_missing_trading_days(
    df: pd.DataFrame,
    *,
    expected_trading_days: list[Any] | tuple[Any, ...] | None,
) -> list[QualityIssue]:
    if not expected_trading_days or not {"instrument_id", "trading_day"}.issubset(df.columns):
        return []

    expected = {str(day)[:10] for day in expected_trading_days}
    if not expected:
        return []

    frame = df[["instrument_id", "trading_day"]].dropna().copy()
    frame["trading_day"] = frame["trading_day"].astype(str).str[:10]
    missing_rows: list[dict[str, object]] = []
    for instrument_id, group in frame.groupby("instrument_id", sort=True):
        present = set(group["trading_day"])
        missing = sorted(expected - present)
        if missing:
            missing_rows.append(
                {
                    "instrument_id": _json_value(instrument_id),
                    "missing_days": missing[:5],
                    "missing_count": len(missing),
                }
            )
    if not missing_rows:
        return []

    return [
        QualityIssue(
            "missing_trading_day_bars",
            "warn",
            {
                "expected_days": len(expected),
                "instrument_count": len(missing_rows),
                "missing_count": int(sum(int(row["missing_count"]) for row in missing_rows)),
                "samples": missing_rows[:5],
            },
        )
    ]


def _validate_expected_minutes(
    df: pd.DataFrame,
    *,
    freq: str,
    expected_minutes_per_day: int | None,
) -> list[QualityIssue]:
    if freq != "1m" or expected_minutes_per_day is None:
        return []
    if expected_minutes_per_day <= 0:
        raise ValueError("expected_minutes_per_day must be positive")
    if not {"instrument_id", "trading_day", "dt"}.issubset(df.columns):
        return []

    frame = df[["instrument_id", "trading_day", "dt"]].dropna().drop_duplicates().copy()
    if frame.empty:
        return []

    counts = frame.groupby(["instrument_id", "trading_day"], sort=True)["dt"].nunique().reset_index(name="minute_count")
    missing = counts[counts["minute_count"] < expected_minutes_per_day]
    extra = counts[counts["minute_count"] > expected_minutes_per_day]
    issues: list[QualityIssue] = []
    if not missing.empty:
        sample_frame = missing.head(5).copy()
        sample_frame["trading_day"] = sample_frame["trading_day"].astype(str)
        issues.append(
            QualityIssue(
                "missing_minute_bars",
                "warn",
                {
                    "expected_minutes_per_day": int(expected_minutes_per_day),
                    "rows": int(len(missing)),
                    "samples": sample_frame.to_dict(orient="records"),
                },
            )
        )
    if not extra.empty:
        sample_frame = extra.head(5).copy()
        sample_frame["trading_day"] = sample_frame["trading_day"].astype(str)
        issues.append(
            QualityIssue(
                "extra_minute_bars",
                "warn",
                {
                    "expected_minutes_per_day": int(expected_minutes_per_day),
                    "rows": int(len(extra)),
                    "samples": sample_frame.to_dict(orient="records"),
                },
            )
        )
    return issues


def _json_value(value: Any) -> object:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def _validate_price_jump(df: pd.DataFrame, *, threshold: float) -> list[QualityIssue]:
    if threshold < 0:
        raise ValueError("price_jump_warn_pct must be non-negative")

    order_column = "dt" if "dt" in df.columns else "trading_day" if "trading_day" in df.columns else None
    if order_column is None or not {"instrument_id", "close"}.issubset(df.columns):
        return []

    sorted_df = df[["instrument_id", order_column, "close"]].copy()
    sorted_df["close"] = pd.to_numeric(sorted_df["close"], errors="coerce")
    sorted_df = sorted_df.dropna(subset=["instrument_id", order_column, "close"])
    if sorted_df.empty:
        return []

    sorted_df = sorted_df.sort_values(["instrument_id", order_column], kind="mergesort")
    sorted_df["prev_close"] = sorted_df.groupby("instrument_id")["close"].shift(1)
    sorted_df["abs_return_pct"] = (sorted_df["close"] / sorted_df["prev_close"] - 1).abs()
    jumps = sorted_df[(sorted_df["prev_close"] > 0) & (sorted_df["abs_return_pct"] > threshold)]
    if jumps.empty:
        return []

    sample_columns = ["instrument_id", order_column, "close", "prev_close", "abs_return_pct"]
    sample_frame = jumps.head(5)[sample_columns].copy()
    sample_frame[order_column] = sample_frame[order_column].astype(str)
    samples = sample_frame.to_dict(orient="records")
    return [
        QualityIssue(
            "price_jump",
            "warn",
            {
                "threshold_pct": float(threshold),
                "order_column": order_column,
                "rows": int(len(jumps)),
                "max_abs_return_pct": float(jumps["abs_return_pct"].max()),
                "samples": samples,
            },
        )
    ]


def write_quality_issues(conn: Connection, *, run_id: int, issues: list[QualityIssue]) -> None:
    if not issues:
        return
    conn.execute(
        text(
            """
            INSERT INTO ops.data_quality_check (run_id, rule, severity, detail)
            VALUES (:run_id, :rule, :severity, CAST(:detail AS jsonb))
            """
        ),
        [
            {
                "run_id": run_id,
                "rule": issue.rule,
                "severity": issue.severity,
                "detail": json.dumps(issue.detail),
            }
            for issue in issues
        ],
    )


def has_error(issues: list[QualityIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)
