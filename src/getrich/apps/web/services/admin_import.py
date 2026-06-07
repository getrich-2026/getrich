"""后台导入模块业务逻辑。"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from getrich.apps.web.errors import BadRequest, NotFound
from getrich.apps.web.schemas.admin_import import ImportPreviewIn, StrategyUpsertIn


if TYPE_CHECKING:
    from psycopg import AsyncConnection


_TZ_SH = ZoneInfo("Asia/Shanghai")
_MAX_CSV_ROWS = 100_000
_DAILY_REQUIRED_COLUMNS = {"trade_date", "daily_return"}
_SIGNAL_REQUIRED_COLUMNS = {"type", "action", "symbol", "published_at"}
_SIGNAL_TYPES = {"entry", "exit", "adjust", "alert"}
_SIGNAL_ACTIONS = {"buy", "sell", "hold", "close"}
_SIGNAL_DIRECTIONS = {"long", "short"}
_SIGNAL_URGENCIES = {"low", "normal", "high", "critical"}
_SIGNAL_STATUSES = {"active", "expired", "cancelled"}


async def upsert_strategy(
    db: AsyncConnection,
    *,
    body: StrategyUpsertIn,
    admin_user_id: str,
) -> dict[str, Any]:
    """创建或更新策略基础信息。

    Args:
        db: PostgreSQL 异步连接。
        body: 策略基础信息请求体。
        admin_user_id: 当前管理员用户 ID。

    Returns:
        创建或更新后的策略摘要。

    Time Complexity:
        O(1)，只执行固定数量 SQL。
    Space Complexity:
        O(1)。
    """
    _ = admin_user_id
    monthly = _parse_decimal_required(body.subscription_monthly, "subscription_monthly")
    yearly = _parse_decimal_required(body.subscription_yearly, "subscription_yearly")
    if monthly < 0 or yearly < 0:
        raise BadRequest("subscription price must be >= 0")

    sql = """
        INSERT INTO strategies (
            strategy_code, name, summary, description, detail_html,
            category_id, type, asset_class, market, risk_level, run_status, pub_status,
            author_id, cover_image, subscription_monthly, subscription_yearly,
            backtest_start, backtest_end, created_at, updated_at
        )
        VALUES (
            %(strategy_code)s, %(name)s, %(summary)s, %(description)s, %(detail_html)s,
            %(category_id)s, %(strategy_type)s, %(asset_class)s, %(market)s, %(risk_level)s,
            %(run_status)s, %(pub_status)s, %(author_id)s, %(cover_image)s,
            %(subscription_monthly)s, %(subscription_yearly)s, %(backtest_start)s,
            %(backtest_end)s, NOW(), NOW()
        )
        ON CONFLICT (strategy_code) DO UPDATE SET
            name = EXCLUDED.name,
            summary = EXCLUDED.summary,
            description = EXCLUDED.description,
            detail_html = EXCLUDED.detail_html,
            category_id = EXCLUDED.category_id,
            type = EXCLUDED.type,
            asset_class = EXCLUDED.asset_class,
            market = EXCLUDED.market,
            risk_level = EXCLUDED.risk_level,
            run_status = EXCLUDED.run_status,
            pub_status = EXCLUDED.pub_status,
            author_id = EXCLUDED.author_id,
            cover_image = EXCLUDED.cover_image,
            subscription_monthly = EXCLUDED.subscription_monthly,
            subscription_yearly = EXCLUDED.subscription_yearly,
            backtest_start = EXCLUDED.backtest_start,
            backtest_end = EXCLUDED.backtest_end,
            updated_at = NOW()
        RETURNING id, strategy_code, name, pub_status, run_status
    """
    params = {
        "strategy_code": body.strategy_code,
        "name": body.name,
        "summary": body.summary,
        "description": body.description,
        "detail_html": body.detail_html,
        "category_id": body.category_id,
        "strategy_type": body.strategy_type,
        "asset_class": body.asset_class,
        "market": body.market,
        "risk_level": body.risk_level,
        "run_status": body.run_status,
        "pub_status": body.pub_status,
        "author_id": body.author_id,
        "cover_image": body.cover_image,
        "subscription_monthly": monthly,
        "subscription_yearly": yearly,
        "backtest_start": body.backtest_start,
        "backtest_end": body.backtest_end,
    }
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        row = await cur.fetchone()

    await db.commit()
    return {
        "strategy_id": str(row["id"]),
        "strategy_code": row["strategy_code"],
        "name": row["name"],
        "pub_status": row["pub_status"],
        "run_status": row["run_status"],
    }


async def preview_import(
    db: AsyncConnection,
    *,
    body: ImportPreviewIn,
    admin_user_id: str,
) -> dict[str, Any]:
    """解析 CSV 并保存预检作业。

    Args:
        db: PostgreSQL 异步连接。
        body: 预检请求体。
        admin_user_id: 当前管理员用户 ID。

    Returns:
        导入作业摘要、预览行和错误明细。

    Time Complexity:
        O(n)，n 为 CSV 行数。
    Space Complexity:
        O(n)，需要保存有效行供提交阶段复用。
    """
    rows = _parse_csv_rows(body.csv_text)
    if body.import_type == "strategy_daily_returns":
        validated_rows, errors = await _validate_daily_return_rows(db, rows, body.strategy_code)
        derived = _derive_daily_return_payload(
            validated_rows,
            method=body.return_calc_method,
            initial_nav=body.initial_nav,
            trading_days_per_year=body.trading_days_per_year,
            risk_free_rate=body.risk_free_rate,
        )
        errors.extend(_derived_nav_errors(derived["equity_rows"]))
        source_rows: list[dict[str, Any]] = validated_rows
    else:
        validated_rows, errors = await _validate_signal_rows(db, rows, body.strategy_code)
        derived = {"equity_rows": [], "monthly_rows": [], "snapshot_rows": []}
        source_rows = validated_rows

    existing_keys = await _count_existing_keys(db, body.import_type, source_rows)
    status = "validated" if not errors else "blocked"
    summary = {
        "total_rows": len(rows),
        "valid_rows": len(source_rows),
        "error_rows": len(errors),
        "duplicate_rows": _count_duplicate_rows(body.import_type, source_rows),
        "will_insert": max(len(source_rows) - existing_keys, 0),
        "will_update": existing_keys if body.mode == "upsert" else 0,
        "return_calc_method": body.return_calc_method,
        "initial_nav": body.initial_nav,
        "trading_days_per_year": body.trading_days_per_year,
        "risk_free_rate": body.risk_free_rate,
        "derived_equity_rows": len(derived["equity_rows"]),
        "derived_monthly_rows": len(derived["monthly_rows"]),
        "derived_snapshot_rows": len(derived["snapshot_rows"]),
    }
    preview_rows = source_rows[:100]
    job_code = _make_job_code()
    file_sha256 = hashlib.sha256(body.csv_text.encode("utf-8")).hexdigest()

    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO import_jobs (
                job_code, import_type, strategy_id, file_name, file_sha256,
                mode, status, summary, preview_rows, validated_rows, created_by,
                created_at, updated_at
            )
            VALUES (
                %(job_code)s, %(import_type)s, %(strategy_id)s, %(file_name)s,
                %(file_sha256)s, %(mode)s, %(status)s, %(summary)s, %(preview_rows)s,
                %(validated_rows)s, %(created_by)s, NOW(), NOW()
            )
            """,
            {
                "job_code": job_code,
                "import_type": body.import_type,
                "strategy_id": source_rows[0]["strategy_id"] if source_rows else None,
                "file_name": body.file_name,
                "file_sha256": file_sha256,
                "mode": body.mode,
                "status": status,
                "summary": Jsonb(summary),
                "preview_rows": Jsonb(preview_rows),
                "validated_rows": Jsonb(source_rows),
                "created_by": admin_user_id,
            },
        )
        for err in errors:
            await cur.execute(
                """
                INSERT INTO import_job_errors (
                    job_id, row_number, column_name, error_code, message, raw_row
                )
                SELECT id, %(row_number)s, %(column_name)s, %(error_code)s,
                       %(message)s, %(raw_row)s
                FROM import_jobs
                WHERE job_code = %(job_code)s
                """,
                {
                    "job_code": job_code,
                    "row_number": err["row_number"],
                    "column_name": err.get("column"),
                    "error_code": err["error_code"],
                    "message": err["message"],
                    "raw_row": Jsonb(err.get("raw_row") or {}),
                },
            )
    await db.commit()

    return {
        "job_id": job_code,
        "status": status,
        "summary": summary,
        "preview_rows": preview_rows,
        "errors": errors[:100],
    }


async def commit_import(
    db: AsyncConnection,
    *,
    job_code: str,
    admin_user_id: str,
) -> dict[str, Any]:
    """提交已经通过预检的导入作业。

    Args:
        db: PostgreSQL 异步连接。
        job_code: 导入作业编码。
        admin_user_id: 当前管理员用户 ID。

    Returns:
        提交结果和影响行数。

    Time Complexity:
        O(n)，n 为预检有效行数。
    Space Complexity:
        O(n)，日涨跌幅导入需要派生净值和月度收益。
    """
    job = await _fetch_job(db, job_code)
    if job["status"] != "validated":
        raise BadRequest(f"import job is not ready to commit: {job['status']}")

    rows = job["validated_rows"] or []
    summary = job["summary"] or {}
    if job["import_type"] == "strategy_daily_returns":
        affected = await _commit_daily_returns(
            db,
            rows,
            method=summary.get("return_calc_method") or "compound",
            initial_nav=float(summary.get("initial_nav") or 1.0),
            trading_days_per_year=int(summary.get("trading_days_per_year") or 252),
            risk_free_rate=float(summary.get("risk_free_rate") or 0.0),
        )
    elif job["import_type"] == "strategy_signals":
        affected = await _commit_signals(db, rows, mode=job["mode"])
    else:
        raise BadRequest(f"unsupported import type: {job['import_type']}")

    async with db.cursor() as cur:
        await cur.execute(
            """
            UPDATE import_jobs
            SET status = 'committed',
                committed_by = %s,
                committed_at = NOW(),
                summary = summary || %s::jsonb,
                updated_at = NOW()
            WHERE job_code = %s
            """,
            (admin_user_id, json.dumps({"affected_rows": affected}), job_code),
        )
    await db.commit()

    return {"job_id": job_code, "status": "committed", "affected_rows": affected}


async def list_import_history(db: AsyncConnection) -> dict[str, Any]:
    """查询最近导入作业。

    Time Complexity:
        O(k)，k 为返回作业数量，上限 20。
    Space Complexity:
        O(k)。
    """
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT job_code, import_type, file_name, mode, status, summary,
                   created_by, committed_by, created_at, committed_at
            FROM import_jobs
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        rows = await cur.fetchall()
    return {"list": [_format_job_row(row) for row in rows]}


async def get_import_job(db: AsyncConnection, *, job_code: str) -> dict[str, Any]:
    """查询单个导入作业详情。

    Time Complexity:
        O(1)。
    Space Complexity:
        O(1)。
    """
    job = await _fetch_job(db, job_code)
    return _format_job_row(job)


async def list_import_errors(db: AsyncConnection, *, job_code: str) -> dict[str, Any]:
    """查询导入作业错误明细。

    Time Complexity:
        O(e)，e 为错误行数量。
    Space Complexity:
        O(e)。
    """
    async with db.cursor() as cur:
        await cur.execute("SELECT id FROM import_jobs WHERE job_code = %s", (job_code,))
        job = await cur.fetchone()
        if job is None:
            raise NotFound(f"import job not found: {job_code}")
        await cur.execute(
            """
            SELECT row_number, column_name, error_code, message, raw_row
            FROM import_job_errors
            WHERE job_id = %s
            ORDER BY row_number ASC, id ASC
            """,
            (job["id"],),
        )
        rows = await cur.fetchall()
    return {
        "list": [
            {
                "row_number": row["row_number"],
                "column": row["column_name"],
                "error_code": row["error_code"],
                "message": row["message"],
                "raw_row": row["raw_row"],
            }
            for row in rows
        ]
    }


def _parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
    text = csv_text.lstrip("\ufeff")
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise BadRequest("csv header is required")
    rows: list[dict[str, str]] = []
    for raw in reader:
        if len(rows) >= _MAX_CSV_ROWS:
            raise BadRequest("csv row count exceeds 100000")
        rows.append({str(k): (v or "").strip() for k, v in raw.items() if k is not None})
    if not rows:
        raise BadRequest("csv data row is required")
    return rows


async def _validate_daily_return_rows(
    db: AsyncConnection,
    rows: list[dict[str, str]],
    strategy_code: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strategy_codes = {
        strategy_code or row.get("strategy_code", "")
        for row in rows
        if strategy_code or row.get("strategy_code")
    }
    strategy_map = await _load_strategy_map(db, strategy_codes)
    valid: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for idx, row in enumerate(rows, start=2):
        row_errors = _missing_column_errors(row, _DAILY_REQUIRED_COLUMNS, idx)
        code = strategy_code or row.get("strategy_code", "")
        if not code:
            row_errors.append(_err(idx, "strategy_code", "required", "strategy_code is required", row))
        if code and code not in strategy_map:
            row_errors.append(_err(idx, "strategy_code", "not_found", "strategy not found", row))
        trade_date = _parse_date(row.get("trade_date"), idx, "trade_date", row, row_errors)
        daily_return = _parse_float(row.get("daily_return"), idx, "daily_return", row, row_errors)
        benchmark_daily_return = _parse_float_optional(
            row.get("benchmark_daily_return"), idx, "benchmark_daily_return", row, row_errors,
        )
        position_ratio = _parse_float_optional(
            row.get("position_ratio"), idx, "position_ratio", row, row_errors,
        )
        if daily_return is not None and daily_return <= -1:
            row_errors.append(
                _err(idx, "daily_return", "out_of_range", "daily_return must be > -1", row)
            )
        if position_ratio is not None and not 0 <= position_ratio <= 1:
            row_errors.append(
                _err(idx, "position_ratio", "out_of_range", "position_ratio must be in [0, 1]", row)
            )
        if code and trade_date:
            key = (code, trade_date.isoformat())
            if key in seen:
                row_errors.append(_err(idx, "trade_date", "duplicate", "duplicate trade_date", row))
            seen.add(key)
        if row_errors:
            errors.extend(row_errors)
            continue
        strategy_ref = strategy_map[code]
        valid.append(
            {
                "strategy_code": code,
                "strategy_id": strategy_ref["id"],
                "trade_date": trade_date.isoformat(),
                "daily_return": daily_return,
                "benchmark_daily_return": benchmark_daily_return,
                "position_ratio": position_ratio,
            }
        )
    return valid, errors


async def _validate_signal_rows(
    db: AsyncConnection,
    rows: list[dict[str, str]],
    strategy_code: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strategy_codes = {
        strategy_code or row.get("strategy_code", "")
        for row in rows
        if strategy_code or row.get("strategy_code")
    }
    strategy_map = await _load_strategy_map(db, strategy_codes)
    valid: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for idx, row in enumerate(rows, start=2):
        row_errors = _missing_column_errors(row, _SIGNAL_REQUIRED_COLUMNS, idx)
        code = strategy_code or row.get("strategy_code", "")
        if not code:
            row_errors.append(_err(idx, "strategy_code", "required", "strategy_code is required", row))
        if code and code not in strategy_map:
            row_errors.append(_err(idx, "strategy_code", "not_found", "strategy not found", row))

        signal_type = row.get("type", "")
        action = row.get("action", "")
        direction = row.get("direction") or "long"
        urgency = row.get("urgency") or "normal"
        status = row.get("status") or "active"
        published_at = _parse_datetime(row.get("published_at"), idx, "published_at", row, row_errors)
        expire_at = _parse_datetime_optional(row.get("expire_at"), idx, "expire_at", row, row_errors)
        signal_code = row.get("signal_code") or _stable_signal_code(code, row, published_at)

        _check_allowed(signal_type, _SIGNAL_TYPES, idx, "type", row, row_errors)
        _check_allowed(action, _SIGNAL_ACTIONS, idx, "action", row, row_errors)
        _check_allowed(direction, _SIGNAL_DIRECTIONS, idx, "direction", row, row_errors)
        _check_allowed(urgency, _SIGNAL_URGENCIES, idx, "urgency", row, row_errors)
        _check_allowed(status, _SIGNAL_STATUSES, idx, "status", row, row_errors)

        confidence = _parse_float_optional(row.get("confidence"), idx, "confidence", row, row_errors)
        position_pct = _parse_float_optional(row.get("position_pct"), idx, "position_pct", row, row_errors)
        if confidence is not None and not 0 <= confidence <= 1:
            row_errors.append(_err(idx, "confidence", "out_of_range", "confidence must be in [0, 1]", row))
        if position_pct is not None and not 0 <= position_pct <= 1:
            row_errors.append(
                _err(idx, "position_pct", "out_of_range", "position_pct must be in [0, 1]", row)
            )
        if signal_code in seen_codes:
            row_errors.append(_err(idx, "signal_code", "duplicate", "duplicate signal_code", row))
        seen_codes.add(signal_code)

        reason_detail = _parse_json(row.get("reason_detail"), idx, "reason_detail", row, row_errors)
        decimal_fields = {
            "trigger_price": _parse_decimal_optional(row.get("trigger_price"), idx, "trigger_price", row, row_errors),
            "target_price": _parse_decimal_optional(row.get("target_price"), idx, "target_price", row, row_errors),
            "stop_loss_price": _parse_decimal_optional(row.get("stop_loss_price"), idx, "stop_loss_price", row, row_errors),
        }
        suggested_quantity = _parse_int_optional(
            row.get("suggested_quantity"), idx, "suggested_quantity", row, row_errors,
        )

        if row_errors:
            errors.extend(row_errors)
            continue
        strategy_ref = strategy_map[code]
        valid.append(
            {
                "strategy_code": code,
                "strategy_id": strategy_ref["id"],
                "market": strategy_ref["market"],
                "signal_code": signal_code,
                "type": signal_type,
                "action": action,
                "direction": direction,
                "symbol": row.get("symbol", ""),
                "symbol_name": row.get("symbol_name") or None,
                "exchange": row.get("exchange") or None,
                "trigger_price": _decimal_to_str(decimal_fields["trigger_price"]),
                "target_price": _decimal_to_str(decimal_fields["target_price"]),
                "stop_loss_price": _decimal_to_str(decimal_fields["stop_loss_price"]),
                "suggested_quantity": suggested_quantity,
                "position_pct": position_pct,
                "confidence": confidence if confidence is not None else 0.5,
                "urgency": urgency,
                "reason": row.get("reason") or None,
                "reason_detail": reason_detail,
                "status": status,
                "published_at": published_at.isoformat(),
                "expire_at": expire_at.isoformat() if expire_at else None,
                "parent_signal_code": row.get("parent_signal_code") or None,
            }
        )
    return valid, errors


def _derive_daily_return_payload(
    rows: list[dict[str, Any]],
    *,
    method: str,
    initial_nav: float,
    trading_days_per_year: int,
    risk_free_rate: float,
) -> dict[str, list[dict[str, Any]]]:
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_strategy[row["strategy_id"]].append(row)

    equity_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    for strategy_id, strategy_rows in by_strategy.items():
        sorted_rows = sorted(strategy_rows, key=lambda item: item["trade_date"])
        nav = initial_nav
        benchmark_nav = initial_nav
        high_water = nav
        compound_total = 1.0
        simple_total = 0.0
        benchmark_compound_total = 1.0
        benchmark_simple_total = 0.0
        daily_values: list[float] = []
        monthly_values: dict[tuple[int, int], list[float]] = defaultdict(list)
        drawdowns: list[float] = []
        for row in sorted_rows:
            daily_return = float(row["daily_return"])
            daily_values.append(daily_return)
            trade_date = date.fromisoformat(row["trade_date"])
            monthly_values[(trade_date.year, trade_date.month)].append(daily_return)
            if method == "compound":
                compound_total *= 1 + daily_return
                cumulative_return = compound_total - 1
                nav = initial_nav * compound_total
            else:
                simple_total += daily_return
                cumulative_return = simple_total
                nav = initial_nav * (1 + simple_total)
            high_water = max(high_water, nav)
            drawdown = nav / high_water - 1
            drawdowns.append(drawdown)

            benchmark_daily = row.get("benchmark_daily_return")
            current_benchmark_nav = None
            if benchmark_daily is not None:
                if method == "compound":
                    benchmark_compound_total *= 1 + float(benchmark_daily)
                    current_benchmark_nav = initial_nav * benchmark_compound_total
                else:
                    benchmark_simple_total += float(benchmark_daily)
                    current_benchmark_nav = initial_nav * (1 + benchmark_simple_total)
                benchmark_nav = current_benchmark_nav
            elif benchmark_nav != initial_nav:
                current_benchmark_nav = benchmark_nav

            equity_rows.append(
                {
                    "strategy_id": strategy_id,
                    "trade_date": row["trade_date"],
                    "nav": nav,
                    "cumulative_return": cumulative_return,
                    "daily_return": daily_return,
                    "drawdown": drawdown,
                    "benchmark_nav": current_benchmark_nav,
                    "position_ratio": row.get("position_ratio"),
                }
            )
        for (year, month), values in monthly_values.items():
            monthly_rows.append(
                {
                    "strategy_id": strategy_id,
                    "year": year,
                    "month": month,
                    "monthly_return": _period_return(values, method),
                }
            )
        if sorted_rows:
            total_return = equity_rows[-1]["cumulative_return"]
            annualized_return = _annualize_return(
                total_return, len(sorted_rows), method, trading_days_per_year,
            )
            annualized_volatility = _annualized_volatility(daily_values, trading_days_per_year)
            sharpe_ratio = (
                (annualized_return - risk_free_rate) / annualized_volatility
                if annualized_volatility > 0
                else None
            )
            snapshot_rows.append(
                {
                    "strategy_id": strategy_id,
                    "snapshot_date": sorted_rows[-1]["trade_date"],
                    "total_return": total_return,
                    "annualized_return": annualized_return,
                    "max_drawdown": min(drawdowns) if drawdowns else 0.0,
                    "annualized_volatility": annualized_volatility,
                    "sharpe_ratio": sharpe_ratio,
                }
            )
    return {
        "equity_rows": equity_rows,
        "monthly_rows": monthly_rows,
        "snapshot_rows": snapshot_rows,
    }


async def _commit_daily_returns(
    db: AsyncConnection,
    rows: list[dict[str, Any]],
    *,
    method: str,
    initial_nav: float,
    trading_days_per_year: int,
    risk_free_rate: float,
) -> int:
    payload = _derive_daily_return_payload(
        rows,
        method=method,
        initial_nav=initial_nav,
        trading_days_per_year=trading_days_per_year,
        risk_free_rate=risk_free_rate,
    )
    affected = 0
    async with db.cursor() as cur:
        for row in payload["equity_rows"]:
            await cur.execute(
                """
                INSERT INTO strategy_equity_curve (
                    strategy_id, trade_date, nav, cumulative_return, daily_return,
                    drawdown, benchmark_nav, position_ratio
                )
                VALUES (
                    %(strategy_id)s, %(trade_date)s, %(nav)s, %(cumulative_return)s,
                    %(daily_return)s, %(drawdown)s, %(benchmark_nav)s, %(position_ratio)s
                )
                ON CONFLICT (strategy_id, trade_date) DO UPDATE SET
                    nav = EXCLUDED.nav,
                    cumulative_return = EXCLUDED.cumulative_return,
                    daily_return = EXCLUDED.daily_return,
                    drawdown = EXCLUDED.drawdown,
                    benchmark_nav = EXCLUDED.benchmark_nav,
                    position_ratio = EXCLUDED.position_ratio
                """,
                row,
            )
            affected += 1
        for row in payload["monthly_rows"]:
            await cur.execute(
                """
                INSERT INTO strategy_monthly_returns (
                    strategy_id, year, month, monthly_return
                )
                VALUES (
                    %(strategy_id)s, %(year)s, %(month)s, %(monthly_return)s
                )
                ON CONFLICT (strategy_id, year, month) DO UPDATE SET
                    monthly_return = EXCLUDED.monthly_return
                """,
                row,
            )
            affected += 1
        for row in payload["snapshot_rows"]:
            await cur.execute(
                """
                INSERT INTO strategy_performance_snapshot (
                    strategy_id, snapshot_date, total_return, annualized_return,
                    max_drawdown, annualized_volatility, sharpe_ratio
                )
                VALUES (
                    %(strategy_id)s, %(snapshot_date)s, %(total_return)s,
                    %(annualized_return)s, %(max_drawdown)s,
                    %(annualized_volatility)s, %(sharpe_ratio)s
                )
                ON CONFLICT (strategy_id, snapshot_date) DO UPDATE SET
                    total_return = EXCLUDED.total_return,
                    annualized_return = EXCLUDED.annualized_return,
                    max_drawdown = EXCLUDED.max_drawdown,
                    annualized_volatility = EXCLUDED.annualized_volatility,
                    sharpe_ratio = EXCLUDED.sharpe_ratio
                """,
                row,
            )
            affected += 1

        by_strategy: dict[str, list[date]] = defaultdict(list)
        for row in rows:
            by_strategy[row["strategy_id"]].append(date.fromisoformat(row["trade_date"]))
        for strategy_id, dates in by_strategy.items():
            await cur.execute(
                """
                UPDATE strategies
                SET backtest_start = LEAST(COALESCE(backtest_start, %s), %s),
                    backtest_end = GREATEST(COALESCE(backtest_end, %s), %s),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (min(dates), min(dates), max(dates), max(dates), strategy_id),
            )
    return affected


async def _commit_signals(db: AsyncConnection, rows: list[dict[str, Any]], *, mode: str) -> int:
    affected = 0
    async with db.cursor() as cur:
        for row in rows:
            await cur.execute(
                """
                SELECT id
                FROM signals
                WHERE signal_code = %(parent_signal_code)s
                """,
                {"parent_signal_code": row.get("parent_signal_code")},
            )
            parent = await cur.fetchone()
            params = dict(row)
            params["parent_signal_id"] = parent["id"] if parent else None
            params["reason_detail"] = Jsonb(row.get("reason_detail") or {})
            sql = """
                INSERT INTO signals (
                    signal_code, strategy_id, market, type, action, direction, symbol,
                    symbol_name, exchange, trigger_price, target_price,
                    stop_loss_price, suggested_quantity, position_pct, confidence,
                    urgency, reason, reason_detail, status, published_at, expire_at,
                    parent_signal_id, created_at
                )
                VALUES (
                    %(signal_code)s, %(strategy_id)s, %(market)s, %(type)s, %(action)s,
                    %(direction)s, %(symbol)s, %(symbol_name)s, %(exchange)s,
                    %(trigger_price)s, %(target_price)s, %(stop_loss_price)s,
                    %(suggested_quantity)s, %(position_pct)s, %(confidence)s,
                    %(urgency)s, %(reason)s, %(reason_detail)s, %(status)s,
                    %(published_at)s, %(expire_at)s, %(parent_signal_id)s, NOW()
                )
            """
            if mode == "upsert":
                sql += """
                    ON CONFLICT (signal_code) DO UPDATE SET
                        market = EXCLUDED.market,
                        type = EXCLUDED.type,
                        action = EXCLUDED.action,
                        direction = EXCLUDED.direction,
                        symbol = EXCLUDED.symbol,
                        symbol_name = EXCLUDED.symbol_name,
                        exchange = EXCLUDED.exchange,
                        trigger_price = EXCLUDED.trigger_price,
                        target_price = EXCLUDED.target_price,
                        stop_loss_price = EXCLUDED.stop_loss_price,
                        suggested_quantity = EXCLUDED.suggested_quantity,
                        position_pct = EXCLUDED.position_pct,
                        confidence = EXCLUDED.confidence,
                        urgency = EXCLUDED.urgency,
                        reason = EXCLUDED.reason,
                        reason_detail = EXCLUDED.reason_detail,
                        status = EXCLUDED.status,
                        published_at = EXCLUDED.published_at,
                        expire_at = EXCLUDED.expire_at,
                        parent_signal_id = EXCLUDED.parent_signal_id
                """
            else:
                sql += " ON CONFLICT (signal_code) DO NOTHING"
            await cur.execute(sql, params)
            affected += 1
    return affected


async def _load_strategy_map(
    db: AsyncConnection,
    strategy_codes: set[str],
) -> dict[str, dict[str, str]]:
    if not strategy_codes:
        return {}
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id, strategy_code, market FROM strategies WHERE strategy_code = ANY(%s)",
            (list(strategy_codes),),
        )
        rows = await cur.fetchall()
    return {
        row["strategy_code"]: {"id": str(row["id"]), "market": row["market"]}
        for row in rows
    }


async def _count_existing_keys(
    db: AsyncConnection,
    import_type: str,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    async with db.cursor() as cur:
        if import_type == "strategy_daily_returns":
            count = 0
            grouped: dict[str, list[date]] = defaultdict(list)
            for row in rows:
                grouped[row["strategy_id"]].append(date.fromisoformat(row["trade_date"]))
            for strategy_id, dates in grouped.items():
                await cur.execute(
                    """
                    SELECT COUNT(*)::int AS cnt
                    FROM strategy_equity_curve
                    WHERE strategy_id = %s AND trade_date = ANY(%s)
                    """,
                    (strategy_id, dates),
                )
                count += int((await cur.fetchone())["cnt"])
            return count
        await cur.execute(
            "SELECT COUNT(*)::int AS cnt FROM signals WHERE signal_code = ANY(%s)",
            ([row["signal_code"] for row in rows],),
        )
        return int((await cur.fetchone())["cnt"])


async def _fetch_job(db: AsyncConnection, job_code: str) -> dict[str, Any]:
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT id, job_code, import_type, strategy_id, file_name, file_sha256,
                   mode, status, summary, preview_rows, validated_rows,
                   created_by, committed_by, created_at, committed_at
            FROM import_jobs
            WHERE job_code = %s
            """,
            (job_code,),
        )
        row = await cur.fetchone()
    if row is None:
        raise NotFound(f"import job not found: {job_code}")
    return row


def _format_job_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["job_code"],
        "import_type": row["import_type"],
        "file_name": row["file_name"],
        "mode": row["mode"],
        "status": row["status"],
        "summary": row["summary"] or {},
        "created_by": str(row["created_by"]),
        "committed_by": str(row["committed_by"]) if row.get("committed_by") else None,
        "created_at": _dt(row.get("created_at")),
        "committed_at": _dt(row.get("committed_at")),
    }


def _period_return(values: list[float], method: str) -> float:
    if method == "simple":
        return sum(values)
    acc = 1.0
    for value in values:
        acc *= 1 + value
    return acc - 1


def _annualize_return(
    total_return: float,
    row_count: int,
    method: str,
    trading_days_per_year: int,
) -> float:
    if row_count <= 0:
        return 0.0
    if method == "simple":
        return total_return * trading_days_per_year / row_count
    return (1 + total_return) ** (trading_days_per_year / row_count) - 1


def _annualized_volatility(values: list[float], trading_days_per_year: int) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.pstdev(values) * math.sqrt(trading_days_per_year)


def _derived_nav_errors(equity_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for idx, row in enumerate(equity_rows, start=2):
        if row["nav"] <= 0:
            errors.append(
                {
                    "row_number": idx,
                    "column": "daily_return",
                    "error_code": "invalid_derived_nav",
                    "message": "derived nav must stay > 0",
                    "raw_row": row,
                }
            )
    return errors


def _count_duplicate_rows(import_type: str, rows: list[dict[str, Any]]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicates = 0
    for row in rows:
        if import_type == "strategy_daily_returns":
            key = (row["strategy_id"], row["trade_date"])
        else:
            key = (row["signal_code"],)
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _missing_column_errors(
    row: dict[str, str],
    columns: set[str],
    row_number: int,
) -> list[dict[str, Any]]:
    return [
        _err(row_number, column, "required", f"{column} is required", row)
        for column in columns
        if not row.get(column)
    ]


def _check_allowed(
    value: str,
    allowed: set[str],
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> None:
    if value not in allowed:
        errors.append(
            _err(row_number, column, "invalid_enum", f"{column} must be one of {sorted(allowed)}", raw_row)
        )


def _parse_date(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(_err(row_number, column, "invalid_date", "invalid date, expected YYYY-MM-DD", raw_row))
        return None


def _parse_datetime(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(_err(row_number, column, "invalid_datetime", "invalid ISO datetime", raw_row))
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_TZ_SH)
    return parsed.astimezone(_TZ_SH)


def _parse_datetime_optional(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> datetime | None:
    if not value:
        return None
    return _parse_datetime(value, row_number, column, raw_row, errors)


def _parse_float(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        errors.append(_err(row_number, column, "invalid_number", "invalid number", raw_row))
        return None
    if not math.isfinite(parsed):
        errors.append(_err(row_number, column, "invalid_number", "NaN and Inf are not allowed", raw_row))
        return None
    return parsed


def _parse_float_optional(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> float | None:
    if not value:
        return None
    return _parse_float(value, row_number, column, raw_row, errors)


def _parse_decimal_required(value: str, column: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise BadRequest(f"invalid decimal: {column}") from exc


def _parse_decimal_optional(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> Decimal | None:
    if not value:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        errors.append(_err(row_number, column, "invalid_decimal", "invalid decimal", raw_row))
        return None
    if not parsed.is_finite():
        errors.append(_err(row_number, column, "invalid_decimal", "NaN and Inf are not allowed", raw_row))
        return None
    return parsed


def _parse_int_optional(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        errors.append(_err(row_number, column, "invalid_integer", "invalid integer", raw_row))
        return None
    if parsed < 0:
        errors.append(_err(row_number, column, "out_of_range", "integer must be >= 0", raw_row))
        return None
    return parsed


def _parse_json(
    value: str | None,
    row_number: int,
    column: str,
    raw_row: dict[str, str],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        errors.append(_err(row_number, column, "invalid_json", "invalid JSON object", raw_row))
        return {}
    if not isinstance(parsed, dict):
        errors.append(_err(row_number, column, "invalid_json", "JSON value must be an object", raw_row))
        return {}
    return parsed


def _stable_signal_code(
    strategy_code: str,
    row: dict[str, str],
    published_at: datetime | None,
) -> str:
    seed = "|".join(
        [
            strategy_code,
            published_at.isoformat() if published_at else "",
            row.get("symbol", ""),
            row.get("type", ""),
            row.get("action", ""),
        ]
    )
    return f"SIG_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16].upper()}"


def _make_job_code() -> str:
    now = datetime.now(_TZ_SH).strftime("%Y%m%d%H%M%S")
    return f"IMPORT_{now}_{uuid4().hex[:8].upper()}"


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _dt(value: Any) -> str:
    if value is None:
        return ""
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _err(
    row_number: int,
    column: str,
    code: str,
    message: str,
    raw_row: dict[str, str],
) -> dict[str, Any]:
    return {
        "row_number": row_number,
        "column": column,
        "error_code": code,
        "message": message,
        "raw_row": raw_row,
    }
