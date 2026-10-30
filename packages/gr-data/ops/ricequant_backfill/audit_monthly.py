"""全市场米筐样本的只读验收；不得打印环境、凭据或 raw 根目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from gr_data.common.paths import RawPaths
from gr_data.common.ricequant_risk_quality import validate_daily_risk
from gr_data.common.ricequant_specs import semantic_hash
from gr_data.config import load_postgres, make_pg_dsn
from gr_data.config.pipeline import load_config
from gr_data.config.ricequant_risk import parse_risk_options
from gr_data.db.risk_receipts import get_importer_version
from gr_data.raw.ricequant.risk_shapes import STYLE_FACTORS
from gr_data.raw.ricequant.riskmodel import read_bundles
from gr_tools.config import load_environment
from psycopg import IsolationLevel
from psycopg.rows import dict_row


BASE = Path(__file__).resolve().parent
REPO = Path("/Volumes/myssd/project/getrich")
MODELS = ("v1", "v2", "v2trd")
PIECES = ("exposure", "covariance", "factor_return", "specific_risk", "specific_return")


class AuditError(RuntimeError):
    """只携带本脚本定义的安全检查代号，不携带数据库或文件异常原文。"""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AuditError(code)


def distribution(values: Any) -> dict[str, Any]:
    arr = np.asarray(values, dtype=float)
    require(arr.ndim == 1 and np.isfinite(arr).all(), "invalid_summary_values")
    if not arr.size:
        return {"count": 0}
    labels = ("minimum", "p05", "p25", "median", "p75", "p95", "maximum")
    result = dict(
        zip(labels, np.quantile(arr, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1]).tolist(), strict=True)
    )
    return {"count": int(arr.size), **result}


def query(conn: psycopg.Connection, sql: str, args: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def same_values(actual: Any, expected: Any, *, real: bool, code: str) -> dict[str, Any]:
    actual_array = np.asarray(actual, dtype=float)
    expected_array = np.asarray(expected, dtype=float)
    require(actual_array.shape == expected_array.shape, f"{code}_shape")
    require(np.isfinite(actual_array).all() and np.isfinite(expected_array).all(), f"{code}_finite")
    # REAL 的文本读取会转回 float64；重投 float32 后要求逐值相等，不放宽相对误差。
    if real:
        require(
            np.array_equal(actual_array.astype(np.float32), expected_array.astype(np.float32)),
            f"{code}_value",
        )
    else:
        require(np.array_equal(actual_array, expected_array), f"{code}_value")
    return {
        "value_count": int(actual_array.size),
        "max_absolute_readback_difference": float(np.max(np.abs(actual_array - expected_array)))
        if actual_array.size
        else 0.0,
        "comparison": "exact_after_float32_cast" if real else "exact_float64",
    }


def expected_values(frames: dict, units: dict) -> dict[str, np.ndarray]:
    """独立按声明单位换算，避免仅调用 writer 自证；风险量统一年化百分比平方。"""
    cov_scale = {
        "dec2_daily": 2520000.0,
        "pct2_daily": 252.0,
        "dec2_annual": 10000.0,
        "pct2_annual": 1.0,
    }
    risk_scale = {
        "dec_daily": 2520000.0,
        "pct_daily": 252.0,
        "dec_annual": 10000.0,
        "pct_annual": 1.0,
    }
    return {
        "exposure": frames["exposure"].to_numpy(dtype=float),
        "covariance": frames["covariance"].to_numpy(dtype=float) * cov_scale[units["covariance"]],
        "factor_return": frames["factor_return"].to_numpy(dtype=float)
        * {"dec_daily": 1.0, "pct_daily": 0.01}[units["factor_return"]],
        "specific_return": frames["specific_return"].to_numpy(dtype=float)
        * {"dec_daily": 100.0, "pct_daily": 1.0}[units["specific_return"]],
        "specific_risk": np.square(frames["specific_risk"].to_numpy(dtype=float))
        * risk_scale[units["specific_risk"]],
    }


def row_size_stats(conn: psycopg.Connection, run_id: uuid.UUID) -> dict[str, Any]:
    stats = query(
        conn,
        """SELECT count(*) AS row_count,
        avg(pg_column_size(c.evidence))::float8 AS avg_evidence_bytes,
        max(pg_column_size(c.evidence)) AS max_evidence_bytes,
        avg(pg_column_size(c))::float8 AS avg_row_bytes,
        max(pg_column_size(c)) AS max_row_bytes
        FROM factor.model_run_coverage c WHERE run_id=%s""",
        (run_id,),
    )[0]
    stats["measurement_note"] = (
        "pg_column_size measures stored datum/row size; whole relation footprint below "
        "includes all runs, indexes and TOAST."
    )
    return stats


def listing_day_sensitivity(
    conn: psycopg.Connection,
    days: list[date],
    ids: list[int],
    predicted_pct: np.ndarray,
    codes: dict[int, str],
    listing_dates: dict[int, date | None],
    baseline: dict[int, dict],
    original_outliers: list[dict],
) -> dict[str, Any]:
    """仅作敏感性对照：排除上市首日这一条收益，不改主对照或生产数值。"""
    day_set = set(days)
    affected = [iid for iid in ids if listing_dates.get(iid) in day_set]
    revised = dict(baseline)
    removed_rows = 0
    if affected:
        rows = query(
            conn,
            """SELECT instrument_id, count(*) AS observed_rows,
                count(*) FILTER (WHERE close>0 AND close<'Infinity'::numeric
                    AND pre_close>0 AND pre_close<'Infinity'::numeric) AS valid_returns,
                stddev_samp(CASE WHEN close>0 AND close<'Infinity'::numeric
                    AND pre_close>0 AND pre_close<'Infinity'::numeric
                    THEN (close/pre_close-1)::float8 END) AS daily_std
            FROM market.stock_bar_1d
            JOIN unnest(%s::bigint[], %s::date[]) AS l(instrument_id,list_date)
                USING (instrument_id)
            WHERE source='tushare' AND dt>=%s AND dt<=%s AND dt=ANY(%s)
                AND dt<>l.list_date
            GROUP BY instrument_id""",
            (affected, [listing_dates[iid] for iid in affected], days[0], days[-1], days),
        )
        recomputed = {row["instrument_id"]: row for row in rows}
        for iid in affected:
            after = recomputed.get(iid)
            removed_rows += baseline.get(iid, {}).get("observed_rows", 0) - (
                after["observed_rows"] if after is not None else 0
            )
            revised[iid] = after or {
                "instrument_id": iid,
                "observed_rows": 0,
                "valid_returns": 0,
                "daily_std": None,
            }
    ratios, realized, outside = [], [], []
    after_by_id = {}
    exclusions = {
        "no_bars": 0,
        "fewer_than_100_valid_returns": 0,
        "zero_volatility": 0,
        "nonfinite_volatility": 0,
    }
    dropped_below_minimum = 0
    for iid, predicted in zip(ids, predicted_pct, strict=True):
        row = revised.get(iid)
        sigma = row.get("daily_std") if row is not None else None
        if row is None or row["observed_rows"] == 0:
            excluded_reason = "no_bars"
        elif row["valid_returns"] < 100:
            excluded_reason = "fewer_than_100_valid_returns"
        elif sigma is None or not math.isfinite(float(sigma)):
            excluded_reason = "nonfinite_volatility"
        elif sigma <= 0:
            excluded_reason = "zero_volatility"
        else:
            excluded_reason = None
        if baseline.get(iid, {}).get("valid_returns", 0) >= 100 and (
            row is None or row["valid_returns"] < 100
        ):
            dropped_below_minimum += 1
        if excluded_reason is not None:
            exclusions[excluded_reason] += 1
            after_by_id[iid] = {
                "status": "excluded",
                "reason": excluded_reason,
                "valid_returns": row["valid_returns"] if row is not None else 0,
            }
            continue
        past_pct = float(sigma) * math.sqrt(252) * 100
        ratio = float(predicted / past_pct)
        ratios.append(ratio)
        realized.append(past_pct)
        after_by_id[iid] = {
            "status": "included",
            "valid_returns": row["valid_returns"],
            "past_annual_volatility_pct": past_pct,
            "ratio": ratio,
            "outside_0_5_2": ratio < 0.5 or ratio > 2,
        }
        if ratio < 0.5 or ratio > 2:
            outside.append(
                {
                    "instrument_id": iid,
                    "canonical_symbol": codes[iid],
                    **after_by_id[iid],
                }
            )
    return {
        "interpretation": (
            "Sensitivity analysis only; primary comparison is unchanged. The listing-day "
            "pre_close is not this stock's previous trading-day market close. Its substitute "
            "reference has not been externally verified as the IPO issue price. No data, "
            "model forecast, R1/R2 threshold or calibration is modified."
        ),
        "exclusion_rule": "Remove only the return with dt equal to frozen canonical list_date",
        "window_start": str(days[0]),
        "window_end_inclusive": str(days[-1]),
        "calendar_days": 120,
        "minimum_valid_returns": 100,
        "standard_deviation_ddof": 1,
        "annualization_days": 252,
        "listing_date_inside_window_stock_count": len(affected),
        "unknown_listing_date_stock_count": sum(listing_dates.get(iid) is None for iid in ids),
        "removed_listing_day_rows": removed_rows,
        "remaining_pair_count": len(ratios),
        "excluded": exclusions,
        "dropped_below_minimum_after_removal": dropped_below_minimum,
        "realized_annual_volatility_pct": distribution(realized),
        "prediction_to_past_realized_ratio": distribution(ratios),
        "ratio_outside_0_5_2_count": len(outside),
        "ratio_outside_0_5_2_fraction": len(outside) / len(ratios) if ratios else None,
        "remaining_outliers": sorted(outside, key=lambda row: row["ratio"]),
        "original_outliers_before_after": [
            {
                "instrument_id": row["instrument_id"],
                "canonical_symbol": row["canonical_symbol"],
                "list_date": str(listing_dates[row["instrument_id"]])
                if listing_dates.get(row["instrument_id"]) is not None
                else None,
                "predicted_annual_volatility_pct": row["predicted_annual_volatility_pct"],
                "before": {
                    key: row[key]
                    for key in ("past_annual_volatility_pct", "ratio", "valid_returns")
                },
                "after": after_by_id[row["instrument_id"]],
            }
            for row in sorted(original_outliers, key=lambda row: row["ratio"])
        ],
    }


def realized_comparison(
    conn: psycopg.Connection,
    day: date,
    ids: list[int],
    predicted_pct: np.ndarray,
    codes: dict[int, str],
    listing_dates: dict[int, date | None],
) -> dict[str, Any]:
    calendar = query(
        conn,
        """SELECT trading_day FROM meta.trading_calendar
        WHERE exchange='XSHG' AND is_open AND trading_day<=%s
        ORDER BY trading_day DESC LIMIT 120""",
        (day,),
    )
    days = sorted(row["trading_day"] for row in calendar)
    require(len(days) == 120 and days[-1] == day, "realized_calendar_not_120_ending_on_day")
    # DATE 与 DATE 比较，不借会话时区转为 timestamp；简单收益不串联股票、不填停牌空日。
    stats = query(
        conn,
        """SELECT instrument_id,
        count(*) AS observed_rows,
        count(*) FILTER (WHERE dt<>trading_day) AS date_mismatch_rows,
        count(*) FILTER (WHERE close>0 AND close<'Infinity'::numeric
            AND pre_close>0 AND pre_close<'Infinity'::numeric) AS valid_returns,
        stddev_samp(CASE WHEN close>0 AND close<'Infinity'::numeric
            AND pre_close>0 AND pre_close<'Infinity'::numeric
            THEN (close/pre_close-1)::float8 END) AS daily_std
        FROM market.stock_bar_1d
        WHERE source='tushare' AND instrument_id=ANY(%s)
        AND dt>=%s AND dt<=%s AND dt=ANY(%s)
        GROUP BY instrument_id""",
        (ids, days[0], day, days),
    )
    by_id = {row["instrument_id"]: row for row in stats}
    require(all(row["date_mismatch_rows"] == 0 for row in stats), "tushare_dt_trading_day_mismatch")
    ratios, realized, details = [], [], []
    excluded = {
        "no_bars": 0,
        "fewer_than_100_valid_returns": 0,
        "zero_volatility": 0,
        "nonfinite_volatility": 0,
    }
    for instrument_id, predicted in zip(ids, predicted_pct, strict=True):
        row = by_id.get(instrument_id)
        if row is None:
            excluded["no_bars"] += 1
            continue
        if row["valid_returns"] < 100:
            excluded["fewer_than_100_valid_returns"] += 1
            continue
        sigma = row["daily_std"]
        if sigma is None or not math.isfinite(float(sigma)):
            excluded["nonfinite_volatility"] += 1
            continue
        if sigma <= 0:
            excluded["zero_volatility"] += 1
            continue
        past_pct = float(sigma) * math.sqrt(252) * 100
        ratio = float(predicted / past_pct)
        ratios.append(ratio)
        realized.append(past_pct)
        if ratio < 0.5 or ratio > 2:
            details.append(
                {
                    "instrument_id": instrument_id,
                    "canonical_symbol": codes[instrument_id],
                    "predicted_annual_volatility_pct": float(predicted),
                    "past_annual_volatility_pct": past_pct,
                    "ratio": ratio,
                    "valid_returns": row["valid_returns"],
                }
            )
    require(len(ratios) > 0, "no_valid_prediction_vs_history_pairs")
    return {
        "interpretation": (
            "Ex-post comparison of model forecast with the preceding realized window "
            "ending on and including trading_day; not future realized validation or calibration."
        ),
        "window_start": str(days[0]),
        "window_end_inclusive": str(day),
        "calendar_days": 120,
        "simple_return": "close / pre_close - 1",
        "source": "tushare",
        "standard_deviation_ddof": 1,
        "annualization_days": 252,
        "minimum_valid_returns": 100,
        "included_risk_stocks": len(ids),
        "excluded": excluded,
        "observed_bar_rows": sum(row["observed_rows"] for row in stats),
        "missing_bar_slots": len(ids) * 120 - sum(row["observed_rows"] for row in stats),
        "invalid_return_rows": sum(row["observed_rows"] - row["valid_returns"] for row in stats),
        "realized_annual_volatility_pct": distribution(realized),
        "prediction_to_past_realized_ratio": distribution(ratios),
        "ratio_outside_0_5_2_count": len(details),
        "ratio_outside_0_5_2_fraction": len(details) / len(ratios),
        "largest_ratio_outliers": sorted(details, key=lambda row: row["ratio"], reverse=True)[:20],
        "smallest_ratio_outliers": sorted(details, key=lambda row: row["ratio"])[:20],
        "sensitivity_excluding_listing_day": listing_day_sensitivity(
            conn, days, ids, predicted_pct, codes, listing_dates, by_id, details
        ),
    }


def coverage_acceptance(manifest: dict) -> dict[str, Any]:
    """仅允许双方上市日一致的首日特异收益缺口；发布门槛保持原值。"""
    day = manifest["day"]
    coverage = manifest["coverage"]
    require(bool(coverage), "production_coverage_denominator")
    require(not manifest["universe"].get("unresolved"), "unresolved_universe")
    gaps = []
    for row in coverage:
        pieces = row["pieces"]
        require(
            isinstance(pieces, dict) and all(type(value) is bool for value in pieces.values()),
            "coverage_piece_flags_not_boolean",
        )
        if row["status"] == "included":
            require(
                pieces == {"exposure": True, "specific_risk": True, "specific_return": True},
                "included_piece_missing",
            )
            continue
        evidence = row.get("evidence") or {}
        canonical = evidence.get("canonical") or {}
        supplier = evidence.get("supplier")
        require(
            row["status"] == "partial_bundle"
            and pieces == {"exposure": True, "specific_risk": True, "specific_return": False}
            and canonical.get("list_date") == day
            and isinstance(supplier, list)
            and bool(supplier)
            and all(isinstance(ref, dict) and ref.get("listed_date") == day for ref in supplier),
            "coverage_gap_not_known_ipo_specific_return",
        )
        gaps.append(
            {
                "instrument_id": row["instrument_id"],
                "canonical_symbol": row["canonical_symbol"],
                "request_code": row["request_code"],
                "listing_day": day,
                "missing_piece": "specific_return",
            }
        )
    counts = manifest["coverage_counts"]
    candidate, complete = len(coverage), len(coverage) - len(gaps)
    require(candidate > 0 and 0 < complete <= candidate, "production_coverage_denominator")
    require(
        counts["candidate"] == candidate and counts["complete"] == complete,
        "coverage_summary_candidate_complete",
    )
    reasons = ["complete_coverage_below_99_9_percent"] if complete * 1000 < candidate * 999 else []
    return {
        "status": "passed",
        "continuation_allowed": True,
        "publication_eligible": not reasons,
        "publication_reasons": reasons,
        "known_ipo_gaps": gaps,
        "next_day_pending_instrument_ids": [row["instrument_id"] for row in gaps],
        "expected_coverage_warning_categories": int(bool(gaps)),
    }


def audit_special_dates(conn: psycopg.Connection, manifest: dict) -> dict[str, Any]:
    """核验换码边界与在市停牌个股；不把停牌推断为风险模型缺覆盖的理由。"""
    day = date.fromisoformat(manifest["day"])
    coverage = manifest["coverage"]
    result = {}
    if day in {date(2025, 2, 14), date(2025, 2, 17)}:
        entries = [
            row
            for row in coverage
            if row["canonical_symbol"] in {"300114.SZ", "302132.SZ"}
            or {"300114.XSHE", "302132.XSHE"}.intersection(row["input_codes"])
        ]
        require(len(entries) == 1, "symbol_change_300114_302132_candidate")
        expected = "300114.XSHE" if day == date(2025, 2, 14) else "302132.XSHE"
        row = entries[0]
        require(
            row["request_code"] == expected and row["status"] == "included",
            "symbol_change_300114_302132_request_or_coverage",
        )
        result["symbol_change_300114_302132"] = {
            "status": "passed",
            "instrument_id": row["instrument_id"],
            "request_code": row["request_code"],
            "coverage_status": row["status"],
        }
    if day == date(2026, 10, 21):
        stocks = query(
            conn,
            "SELECT instrument_id,symbol,list_date,delist_date FROM meta.instruments "
            "WHERE asset='stock' AND exchange='XSHE' AND symbol='000016.SZ'",
        )
        require(len(stocks) == 1, "000016_canonical_identity")
        stock = stocks[0]
        require(
            stock["list_date"] is not None
            and stock["list_date"] <= day
            and (stock["delist_date"] is None or day < stock["delist_date"]),
            "000016_not_in_market_on_day",
        )
        events = query(
            conn,
            "SELECT suspend_type,suspend_timing FROM market.stock_suspend_event "
            "WHERE instrument_id=%s AND trading_day=%s AND source='tushare'",
            (stock["instrument_id"], day),
        )
        require(
            len(events) == 1
            and events[0]["suspend_type"] == "S"
            and events[0]["suspend_timing"] is None,
            "000016_full_day_suspension_not_verified",
        )
        entries = [row for row in coverage if row["instrument_id"] == stock["instrument_id"]]
        require(
            len(entries) == 1
            and entries[0]["request_code"] == "000016.XSHE"
            and entries[0]["status"] == "included",
            "000016_missing_risk_coverage",
        )
        result["000016_in_market_full_day_suspension"] = {
            "status": "passed",
            "instrument_id": stock["instrument_id"],
            "in_market": True,
            "suspend_type": "S",
            "suspend_timing": None,
            "coverage_status": entries[0]["status"],
        }
    return result


def audit_import_evidence(
    conn: psycopg.Connection,
    options: Any,
    manifest: dict,
    run_id: uuid.UUID,
    expected_written: int,
    successes: list[dict],
    *,
    importer_version: str,
) -> dict[str, Any]:
    """只读核对 2a 身份、不可变收据、绑定及当前观察的采集/导入双水位。"""
    day = date.fromisoformat(manifest["day"])
    observed = datetime.fromisoformat(manifest["observed_at"])
    observation_id = manifest["observation_id"]
    manifest_hash = semantic_hash(manifest)
    variant_id = options.variant_id
    require(
        options.purpose == "production" and options.universe_policy == "listed_cn_a_v2",
        "production_policy",
    )
    variants = query(
        conn, "SELECT * FROM factor.dataset_variant WHERE variant_id=%s", (variant_id,)
    )
    require(len(variants) == 1, "dataset_variant_missing_or_duplicate")
    variant = variants[0]
    require(
        variant["provider"] == "ricequant"
        and variant["dataset_name"] == "rq_risk_model"
        and variant["purpose"] == "production"
        and variant["identity"] == manifest["identity"] == options.identity
        and semantic_hash(variant["identity"]) == variant_id,
        "dataset_variant_identity",
    )
    bindings = query(conn, "SELECT * FROM factor.model_run_binding WHERE run_id=%s", (run_id,))
    require(len(bindings) == 1, "model_run_binding_missing_or_duplicate")
    binding = bindings[0]
    require(
        binding["variant_id"] == variant_id
        and binding["observation_id"] == observation_id
        and binding["trading_day"] == day,
        "model_run_binding_identity",
    )
    receipts = query(
        conn, "SELECT * FROM factor.import_receipt WHERE receipt_id=%s", (binding["receipt_id"],)
    )
    require(len(receipts) == 1, "import_receipt_missing_or_duplicate")
    receipt = receipts[0]
    expected_receipt_id = uuid.uuid5(
        uuid.NAMESPACE_URL, f"factor.risk_bundle:{manifest_hash}:{importer_version}"
    )
    require(
        receipt["receipt_id"] == expected_receipt_id
        and receipt["target"] == "factor.risk_bundle"
        and receipt["variant_id"] == variant_id
        and receipt["manifest_hash"] == manifest_hash
        and receipt["importer_version"] == importer_version
        and receipt["observation_id"] == observation_id
        and receipt["trading_day"] == day,
        "import_receipt_identity_or_current_importer_version",
    )
    require(receipt["rows_written"] == expected_written, "import_receipt_rows")
    require(receipt["committed_at"] >= observed, "import_receipt_before_capture")
    same_receipts = query(
        conn,
        "SELECT receipt_id FROM factor.import_receipt WHERE target=%s "
        "AND manifest_hash=%s AND importer_version=%s",
        ("factor.risk_bundle", manifest_hash, importer_version),
    )
    require(
        len(same_receipts) == 1 and same_receipts[0]["receipt_id"] == expected_receipt_id,
        "import_receipt_replay_uniqueness",
    )
    same_bindings = query(
        conn,
        "SELECT run_id FROM factor.model_run_binding WHERE receipt_id=%s",
        (expected_receipt_id,),
    )
    require(
        len(same_bindings) == 1 and same_bindings[0]["run_id"] == run_id, "receipt_run_uniqueness"
    )
    partition = f"{variant_id}/{day}/{observation_id}"
    checkpoints = query(
        conn,
        "SELECT * FROM factor.import_checkpoint WHERE provider=%s "
        "AND dataset_name=%s AND partition_key=%s",
        ("ricequant", "rq_risk_model", partition),
    )
    require(len(checkpoints) == 1, "capture_checkpoint_missing_or_duplicate")
    checkpoint = checkpoints[0]
    require(
        checkpoint["variant_id"] == variant_id
        and checkpoint["observation_id"] == observation_id
        and checkpoint["trading_day"] == day
        and checkpoint["capture_manifest_hash"] == manifest_hash
        and checkpoint["captured_at"] == observed,
        "capture_checkpoint_identity_or_actual_time",
    )
    require(
        checkpoint["state"]
        == {
            "manifest_hash": manifest_hash,
            "purpose": "production",
            "contract": options.identity["contract"],
        },
        "capture_checkpoint_immutable_state",
    )
    require(
        checkpoint["import_receipt_id"] == expected_receipt_id
        and checkpoint["imported_at"] == receipt["committed_at"]
        and checkpoint["watermark_date"] == day
        and checkpoint["watermark_ts"] is None
        and checkpoint["imported_at"] >= checkpoint["captured_at"],
        "import_checkpoint_receipt_or_dual_watermark",
    )
    # 独立重算获批的 production 覆盖门槛，不调用 writer 的私有判断函数。
    status_counts = Counter(row["status"] for row in manifest["coverage"])
    candidate = len(manifest["coverage"])
    complete = status_counts["included"]
    reasons = []
    if complete * 1000 < candidate * 999:
        reasons.append("complete_coverage_below_99_9_percent")
    for status in ("universe_boundary_unknown", "unmapped_symbol"):
        if status_counts[status]:
            reasons.append(status)
    require(candidate > 0 and 0 < complete <= candidate, "production_coverage_denominator")
    quality = receipt["quality"]
    require(
        quality.get("publication_eligible") is (not reasons)
        and quality.get("publication_reasons") == reasons,
        "receipt_production_threshold_result",
    )
    accepted = coverage_acceptance(manifest)
    require(reasons == accepted["publication_reasons"], "unapproved_publication_reason")
    require(
        not quality.get("warnings") and not quality.get("covariance", {}).get("warnings"),
        "unreviewed_numeric_quality_warning",
    )
    for row in successes:
        request = row["request"]
        expected_warning_count = (
            len(quality.get("warnings", [])) + accepted["expected_coverage_warning_categories"]
        )
        require(row["warning_count"] == expected_warning_count, "etl_warning_category_count")
        require(request.get("receipt_id") == str(expected_receipt_id), "etl_receipt_id")
        require(request.get("quality") == quality, "etl_receipt_quality")
        if not request.get("replay"):
            require(
                row["started_at"] <= receipt["committed_at"] <= row["finished_at"],
                "receipt_outside_first_success_etl_interval",
            )
    return {
        "status": "passed",
        "variant_registered": True,
        "manifest_hash": manifest_hash,
        "receipt_id": str(expected_receipt_id),
        "importer_version": importer_version,
        "importer_version_matches_current_committed_source": True,
        "rows_written": receipt["rows_written"],
        "run_binding_verified": True,
        "capture_checkpoint": {
            "partition_key": partition,
            "captured_at": checkpoint["captured_at"].isoformat(),
            "capture_manifest_hash": checkpoint["capture_manifest_hash"],
        },
        "import_checkpoint": {
            "import_receipt_id": str(checkpoint["import_receipt_id"]),
            "imported_at": checkpoint["imported_at"].isoformat(),
            "watermark_date": str(checkpoint["watermark_date"]),
            "watermark_ts": None,
        },
        "time_semantics": (
            "captured_at is actual raw observed_at; imported_at is receipt insertion time "
            "visible only after commit; per-observation checkpoints do not prove "
            "continuous historical coverage"
        ),
        "publication_gate": {
            "eligible": not reasons,
            "complete": complete,
            "candidate": candidate,
            "complete_fraction": complete / candidate,
            "minimum_complete_fraction": 0.999,
            "known_ipo_continuation_allowed": accepted["continuation_allowed"],
            "universe_boundary_unknown": status_counts["universe_boundary_unknown"],
            "unmapped_symbol": status_counts["unmapped_symbol"],
            "reasons": reasons,
            "note": (
                "Import qualification only; no D-022 generation or official read permission "
                "is established by this audit."
            ),
        },
    }


def audit_bundle(
    conn: psycopg.Connection,
    options: Any,
    manifest: dict,
    frames: dict,
    *,
    realized: bool,
    importer_version: str,
) -> dict:
    day = date.fromisoformat(manifest["day"])
    observed = datetime.fromisoformat(manifest["observed_at"])
    require(observed.tzinfo is not None and observed.utcoffset() is not None, "observed_at_naive")
    run_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"ricequant-risk:{options.variant_id}:{manifest['day']}:{manifest['observation_id']}",
    )
    runs = query(conn, "SELECT * FROM factor.model_run WHERE run_id=%s", (run_id,))
    require(len(runs) == 1, "model_run_missing_or_duplicate")
    run = runs[0]
    units = run["units"]
    require(run["source"] == "ricequant" and run["calibrated"] is False, "source_or_calibrated")
    require(run["estimated_at"] == observed, "run_observed_time")
    require(run["annualization_basis"] == "annual_252", "annualization_basis")
    require(units["purpose"] == manifest["purpose"] == "production", "purpose")
    require(
        units["source_units"] == options.source_units
        and units["units_evidence"] == options.units_evidence,
        "source_units_or_evidence",
    )
    for name, expected in {
        "factor_return": "dec_daily",
        "specific_return": "pct_daily",
        "covariance": "pct2_annual",
        "specific_risk": "pct2_annual",
    }.items():
        require(units[name] == expected, "normalized_units")
    for key in ("universe_hash", "coverage_hash", "coverage_counts", "observation_id"):
        require(units[key] == manifest[key], f"run_{key}")
    require(units["variant_id"] == options.variant_id, "run_variant")
    for key in ("symbol_rules_version", "symbol_rules_hash"):
        require(
            units["universe_evidence"][key] == manifest["universe"]["reference"][key],
            "rule_metadata",
        )
    require(units["raw_files_hash"] == semantic_hash(manifest["files"]), "run_raw_files_hash")
    require(units["trading_day"] == str(day), "run_trading_day")
    order = list(frames["exposure"].columns)
    k = len(order)
    require(run["factor_order"] == order and run["factor_count"] == k, "run_factor_order")
    require(
        run["factor_order_hash"] == hashlib.md5("|".join(order).encode()).hexdigest(),
        "factor_order_hash",
    )
    require(
        run["factor_set_hash"] == hashlib.md5("|".join(sorted(order)).encode()).hexdigest(),
        "factor_set_hash",
    )
    definitions = query(
        conn,
        "SELECT factor_code,factor_type,ordinal FROM factor.definition "
        "WHERE model_id=%s ORDER BY ordinal",
        (run["model_id"],),
    )
    require(
        [row["factor_code"] for row in definitions] == order
        and [row["ordinal"] for row in definitions] == list(range(k)),
        "definition_order",
    )
    coverage = manifest["coverage"]
    accepted_coverage = coverage_acceptance(manifest)
    require(manifest["coverage_hash"] == semantic_hash(coverage), "manifest_coverage_hash")
    require(
        manifest["universe_hash"] == semantic_hash(manifest["universe"]), "manifest_universe_hash"
    )
    ledger = query(
        conn,
        "SELECT * FROM factor.model_run_coverage WHERE run_id=%s ORDER BY instrument_id",
        (run_id,),
    )
    expected_ledger = {row["instrument_id"]: row for row in coverage}
    require(
        len(ledger) == len(expected_ledger) == len(manifest["universe"]["candidates"]),
        "coverage_candidate_count",
    )
    for stored in ledger:
        require(stored["instrument_id"] in expected_ledger, "coverage_unexpected_id")
        raw = expected_ledger[stored["instrument_id"]]
        require(
            stored["trading_day"] == day and stored["available_at"] == observed,
            "coverage_date_available",
        )
        for key in ("input_codes", "request_code", "status", "pieces", "evidence"):
            require(stored[key] == raw[key], f"coverage_{key}")
    status_counts = dict(Counter(row["status"] for row in ledger))
    require(
        status_counts == dict(Counter(row["status"] for row in coverage)), "coverage_status_counts"
    )
    included = {
        row["request_code"]: row["instrument_id"] for row in coverage if row["status"] == "included"
    }
    ordered_codes = list(frames["exposure"].index)
    require(set(ordered_codes) == set(included), "included_raw_intersection")
    ids = [included[code] for code in ordered_codes]
    expected = expected_values(frames, options.source_units)
    comparisons = {}
    actual = {}
    row_counts = {}
    for piece in PIECES:
        rows = query(conn, f"SELECT * FROM factor.{piece} WHERE run_id=%s", (run_id,))
        row_counts[piece] = len(rows)
        require(
            all(row["trading_day"] == day and row["available_at"] == observed for row in rows),
            f"{piece}_day_available",
        )
        if piece in ("exposure", "covariance", "factor_return"):
            require(all(row["factor_count"] == k for row in rows), f"{piece}_factor_count")
        if piece in ("covariance", "factor_return"):
            require(len(rows) == 1, f"{piece}_row_count")
            value_column = "cov_flat" if piece == "covariance" else "ret_vector"
            actual[piece] = np.asarray(rows[0][value_column], dtype=float)
            expected_piece = (
                expected[piece][np.triu_indices(k)] if piece == "covariance" else expected[piece][0]
            )
        else:
            by_id = {row["instrument_id"]: row for row in rows}
            require(
                len(rows) == len(by_id) == len(ids) and set(by_id) == set(ids),
                f"{piece}_complete_intersection",
            )
            column = {
                "exposure": "exposure",
                "specific_risk": "specific_var",
                "specific_return": "specific_ret",
            }[piece]
            actual[piece] = np.asarray([by_id[iid][column] for iid in ids], dtype=float)
            if piece == "specific_risk":
                require(all(row["source"] == "ricequant" for row in rows), "specific_risk_source")
            expected_piece = expected[piece] if piece == "exposure" else expected[piece][0]
        comparisons[piece] = same_values(
            actual[piece], expected_piece, real=piece != "covariance", code=piece
        )
    cov = np.zeros((k, k), dtype=float)
    cov[np.triu_indices(k)] = actual["covariance"]
    cov = cov + np.triu(cov, 1).T
    industry_indices = [
        i
        for i, factor in enumerate(order)
        if factor not in STYLE_FACTORS[options.model] | {"comovement"}
    ]
    industries = actual["exposure"][:, industry_indices]
    require(
        np.isin(industries, [0.0, 1.0]).all() and np.all(industries.sum(axis=1) == 1),
        "industry_one_hot",
    )
    require(np.all(actual["exposure"][:, order.index("comovement")] == 1), "country_not_one")
    quality = validate_daily_risk(actual["exposure"], cov, actual["specific_risk"])
    predicted = np.sqrt(
        np.einsum("ij,ij->i", actual["exposure"] @ cov, actual["exposure"])
        + actual["specific_risk"]
    )
    successes = query(
        conn,
        """SELECT status,trading_day,start_date,end_date,rows_written,
        warning_count,request,started_at,finished_at FROM ops.etl_job_run
        WHERE provider='ricequant' AND dataset_name='rq_risk_model'
        AND request->>'model_run_id'=%s ORDER BY started_at""",
        (str(run_id),),
    )
    good = [row for row in successes if row["status"] == "success"]
    require(bool(good), "success_etl_missing")
    expected_written = sum(row_counts.values()) + len(ledger)
    for row in good:
        require(row["trading_day"] == row["start_date"] == row["end_date"] == day, "etl_day")
        require(
            row["rows_written"] == (0 if row["request"].get("replay") else expected_written)
            and row["finished_at"] >= row["started_at"],
            "etl_rows_or_time",
        )
        request = row["request"]
        for key in ("coverage_hash", "universe_hash", "coverage_counts", "observation_id"):
            require(request[key] == manifest[key], f"etl_{key}")
        require(
            request["purpose"] == "production" and request["variant_id"] == options.variant_id,
            "etl_purpose_variant",
        )
        require(
            request["model"] == options.model
            and request["industry_mapping"] == options.industry_mapping,
            "etl_model",
        )
        require(request["raw_files_hash"] == semantic_hash(manifest["files"]), "etl_raw_files_hash")
        require(
            request["manifest_ref"].endswith(f"/{day}/{manifest['observation_id']}/manifest.json"),
            "etl_manifest_ref",
        )
    import_evidence = audit_import_evidence(
        conn,
        options,
        manifest,
        run_id,
        expected_written,
        good,
        importer_version=importer_version,
    )
    special_checks = audit_special_dates(conn, manifest)
    quota = manifest.get("quota_observation") or {}
    before, after = quota.get("before") or {}, quota.get("after") or {}
    used_before, used_after = before.get("bytes_used"), after.get("bytes_used")
    delta = (
        used_after - used_before
        if isinstance(used_before, (int, float)) and isinstance(used_after, (int, float))
        else None
    )
    result = {
        "status": "passed",
        "model": options.model,
        "industry_mapping": options.industry_mapping,
        "trading_day": str(day),
        "run_id": str(run_id),
        "variant_id": options.variant_id,
        "observation_id": manifest["observation_id"],
        "observed_at": manifest["observed_at"],
        "purpose": "production",
        "calibrated": False,
        "factor_count": k,
        "factor_order": order,
        "source_units": options.source_units,
        "units_evidence": options.units_evidence,
        "row_counts": row_counts,
        "coverage_counts": manifest["coverage_counts"],
        "coverage_status_counts": status_counts,
        "source_unresolved_count": len(manifest["universe"]["unresolved"]),
        "known_ipo_gaps": accepted_coverage["known_ipo_gaps"],
        "next_day_pending_instrument_ids": accepted_coverage["next_day_pending_instrument_ids"],
        "continuation_allowed": accepted_coverage["continuation_allowed"],
        "publication_eligible": accepted_coverage["publication_eligible"],
        "special_checks": special_checks,
        "not_included_candidates": [
            {
                "instrument_id": row["instrument_id"],
                "canonical_symbol": row["canonical_symbol"],
                "status": row["status"],
                "pieces": row["pieces"],
            }
            for row in coverage
            if row["status"] != "included"
        ],
        "country_all_one": True,
        "industry_one_hot_all": True,
        "arrays_all_finite": True,
        "raw_to_pg_value_checks": comparisons,
        "quality": quality,
        "import_evidence": import_evidence,
        "success_etl_records": len(good),
        "failed_etl_records_for_same_run": sum(row["status"] == "failed" for row in successes),
        "etl_warning_counts": [row["warning_count"] for row in good],
        "coverage_storage": row_size_stats(conn, run_id),
        "quota_observation": {
            "before": before,
            "after": after,
            "counter_delta_bytes": delta,
            "note": (
                "Counter may lag or reset; zero or negative delta is not proof of zero transfer. "
                "Use task quota probes for finalized traffic."
            ),
        },
    }
    if realized:
        result["prediction_vs_history"] = realized_comparison(
            conn,
            day,
            ids,
            predicted,
            {row["instrument_id"]: row["canonical_symbol"] for row in coverage},
            {
                row["instrument_id"]: date.fromisoformat(row["list_date"])
                if row.get("list_date")
                else None
                for row in manifest["universe"]["reference"]["metadata"]["instruments"]
            },
        )
    else:
        result["prediction_vs_history"] = {"status": "not_run", "reason": "explicit_skip_realized"}
    return result


def save_json(path: Path, report: dict) -> None:
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument("--config-dir", type=Path, default=BASE)
    parser.add_argument("--output", type=Path, default=BASE / "audit_samples.json")
    parser.add_argument("--skip-realized", action="store_true")
    parser.add_argument("--observation-id")
    parser.add_argument("--importer-version")
    args = parser.parse_args()
    report = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "transaction": "REPEATABLE READ READ ONLY",
        "models": [],
    }
    stage = "verify_current_committed_importer"
    try:
        importer_version = get_importer_version(require_clean=True)
        if args.importer_version is not None:
            require(importer_version == args.importer_version, "expected_importer_not_current")
        report["importer_version"] = importer_version
        stage = "load_environment"
        env = load_environment(root=REPO)
        pg = load_postgres(env)
        stage = "connect_read_only"
        with psycopg.connect(make_pg_dsn(pg), row_factory=dict_row, autocommit=False) as conn:
            conn.isolation_level = IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute("SET LOCAL timezone='Asia/Shanghai'")
                cur.execute("SET LOCAL statement_timeout='180s'")
            transaction = query(
                conn,
                "SELECT current_setting('transaction_read_only') AS read_only, "
                "current_setting('transaction_isolation') AS isolation",
            )[0]
            require(
                transaction == {"read_only": "on", "isolation": "repeatable read"},
                "transaction_not_read_only_repeatable",
            )
            stage = "verify_receipt_migration"
            migrations = query(
                conn,
                "SELECT file_name FROM ops.schema_migrations WHERE file_name=%s",
                ("049_risk_import_receipts.sql",),
            )
            require(len(migrations) == 1, "migration_049_not_recorded")
            report["receipt_migration"] = migrations[0]["file_name"]
            for model in dict.fromkeys(args.models):
                stage = f"{model}:load_config"
                config_path = args.config_dir / (model + ".yaml")
                require(config_path.is_file(), "model_config_missing")
                cfg = load_config(config_path, environment=env)
                options = parse_risk_options(cfg.section("providers", "ricequant", "risk_model"))
                require(
                    options.model == model
                    and options.contract_version == "v2"
                    and options.purpose == "production"
                    and options.universe_policy == "listed_cn_a_v2"
                    and date(2024, 1, 30)
                    <= options.start_date
                    <= options.end_date
                    <= date(2026, 10, 21),
                    "monthly_config_identity_or_authorized_date_range",
                )
                stage = f"{model}:read_verified_raw"
                found = 0
                bundles = list(
                    read_bundles(
                        RawPaths(cfg.raw_root), options, observation_id=args.observation_id
                    )
                )
                selected = [
                    item
                    for item in bundles
                    if args.observation_id is None
                    or item[0]["observation_id"] == args.observation_id
                ]
                require(len(selected) == 1, "explicit_observation_required_or_missing")
                for manifest, frames in selected:
                    found += 1
                    stage = f"{model}:audit_raw_and_database"
                    result = audit_bundle(
                        conn,
                        options,
                        manifest,
                        frames,
                        realized=not args.skip_realized,
                        importer_version=importer_version,
                    )
                    report["models"].append(result)
                require(found > 0, "raw_sample_missing")
            stage = "coverage_relation_storage"
            report["coverage_relation_storage"] = query(
                conn,
                """SELECT
                pg_total_relation_size('factor.model_run_coverage'::regclass)
                    AS total_bytes_including_indexes_toast,
                pg_table_size('factor.model_run_coverage'::regclass) AS table_bytes_including_toast,
                pg_indexes_size('factor.model_run_coverage'::regclass) AS indexes_bytes,
                (SELECT count(*) FROM factor.model_run_coverage) AS all_run_row_count""",
            )[0]
            conn.rollback()
        report["status"] = "passed"
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_json(args.output, report)
        summary = {
            "status": "passed",
            "samples": [
                {
                    "model": item["model"],
                    "trading_day": item["trading_day"],
                    "run_id": item["run_id"],
                    "coverage_counts": item["coverage_counts"],
                    "condition_number": item["quality"]["covariance"]["condition_number"],
                    "annual_volatility_pct": item["quality"]["total_volatility_pct"],
                    "prediction_vs_history_ratio": item["prediction_vs_history"].get(
                        "prediction_to_past_realized_ratio"
                    ),
                    "coverage_storage": item["coverage_storage"],
                    "import_evidence": item["import_evidence"],
                }
                for item in report["models"]
            ],
            "coverage_relation_storage": report["coverage_relation_storage"],
        }
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as exc:
        report.update(
            status="failed",
            failed_stage=stage,
            error_type=type(exc).__name__,
            failed_check=str(exc)
            if isinstance(exc, AuditError)
            else "external_error_details_suppressed",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        try:
            save_json(args.output, report)
        except Exception:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "failed_stage": stage,
                        "error_type": type(exc).__name__,
                        "report_write_failed": True,
                    }
                ),
                file=sys.stderr,
            )
            return 1
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in ("status", "failed_stage", "error_type", "failed_check")
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
