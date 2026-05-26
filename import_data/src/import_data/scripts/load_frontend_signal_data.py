from __future__ import annotations

import argparse
import csv
import html
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from import_data.core.config import settings
from import_data.core.logger import Logger


LOGGER = Logger(__name__)
UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "getrich.frontend_signal")

SQL_DIR = Path("sql/init/frontend_signal")
DATA_DIR = Path("frontend-data")
INIT_SQL_FILES = tuple(f"{idx:02d}" for idx in range(14))

ACTION_MAP = {
    "conditional": "open",
}
RUN_STATUS_MAP = {
    "real_trade": "live",
    "sim_trade": "paper",
}
DIRECTION_MAP = {
    "conditional": "neutral",
}
TAG_GROUP_MAP = {
    "asset": "asset_class",
}
USER_STATUS_MAP = {
    "active": 1,
    "normal": 1,
    "banned": 2,
    "deleted": 3,
}


def project_root() -> Path:
    """返回仓库根目录。

    Time Complexity: O(1).
    Space Complexity: O(1).
    """
    return Path(__file__).resolve().parents[4]


def stable_uuid(entity: str, key: str) -> str:
    """基于业务 code 生成稳定 UUID，保证导入幂等。

    Args:
        entity: 实体类型。
        key: 业务唯一键。

    Returns:
        稳定 UUID 字符串。

    Time Complexity: O(len(entity) + len(key)).
    Space Complexity: O(1).
    """
    return str(uuid.uuid5(UUID_NAMESPACE, f"{entity}:{key}"))


def blank_to_none(value: Any) -> Any:
    """把 CSV 空字符串归一为 None。

    Time Complexity: O(1).
    Space Complexity: O(1).
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def to_decimal(value: Any) -> Decimal | None:
    """转换 CSV 数值为 Decimal，空值保留为 None。

    Time Complexity: O(len(value)).
    Space Complexity: O(1).
    """
    value = blank_to_none(value)
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def to_int(value: Any) -> int | None:
    """转换 CSV 整数字段，空值保留为 None。

    Time Complexity: O(len(value)).
    Space Complexity: O(1).
    """
    value = blank_to_none(value)
    if value is None:
        return None
    return int(str(value).strip())


def to_bool(value: Any) -> bool | None:
    """转换 CSV 布尔字段，空值保留为 None。

    Time Complexity: O(len(value)).
    Space Complexity: O(1).
    """
    value = blank_to_none(value)
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def parse_date(value: Any) -> date | None:
    """解析 CSV 日期字段，支持 YYYY-MM-DD 和 YYYY/MM/DD。

    Time Complexity: O(len(value)).
    Space Complexity: O(1).
    """
    value = blank_to_none(value)
    if value is None:
        return None
    text = str(value).strip()
    if "/" in text:
        return datetime.strptime(text, "%Y/%m/%d").date()
    return date.fromisoformat(text)


def parse_json(value: Any, default: Any) -> Any:
    """解析 JSON 字段，空值返回 default。

    Time Complexity: O(len(value)).
    Space Complexity: O(len(value)).
    """
    value = blank_to_none(value)
    if value is None:
        return default
    return json.loads(str(value))


def parse_pg_text_array(value: Any) -> list[str]:
    """解析 PostgreSQL 风格的简单 text[] 字面量。

    Time Complexity: O(len(value)).
    Space Complexity: O(len(value)).
    """
    value = blank_to_none(value)
    if value is None:
        return []
    text = str(value).strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    return [item.strip() for item in text.split(",") if item.strip()]


def read_csv_dicts(root: Path, name: str) -> list[dict[str, str]]:
    """读取 UTF-8 BOM 兼容的 CSV 字典行。

    Time Complexity: O(n * m)，n 为行数，m 为列数。
    Space Complexity: O(n * m)。
    """
    path = root / DATA_DIR / name
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def read_signal_rows(root: Path) -> list[dict[str, str]]:
    """读取信号 CSV，并兼容部分行缺失 position_pct/confidence 两列的情况。

    Time Complexity: O(n * m)，n 为行数，m 为列数。
    Space Complexity: O(n * m)。
    """
    path = root / DATA_DIR / "06_signals.csv"
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.reader(file))
    header = rows[0]
    result: list[dict[str, str]] = []
    for line_no, row in enumerate(rows[1:], start=2):
        if len(row) == len(header):
            values = row
        elif len(row) == len(header) - 2:
            values = row[:17] + ["", ""] + row[17:]
        else:
            raise ValueError(
                f"Unexpected column count in 06_signals.csv line {line_no}: "
                f"{len(row)} != {len(header)}"
            )
        result.append(dict(zip(header, values, strict=True)))
    return result


def render_markdown_as_html(markdown_text: str) -> str:
    """把小型 Markdown 简单渲染为 HTML，避免新增依赖。

    Time Complexity: O(n)，n 为文本长度。
    Space Complexity: O(n)。
    """
    blocks: list[str] = []
    list_open = False
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            if not list_open:
                blocks.append("<ul>")
                list_open = True
            blocks.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if list_open:
            blocks.append("</ul>")
            list_open = False
        if line.startswith("# "):
            blocks.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            blocks.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line:
            blocks.append(f"<p>{html.escape(line)}</p>")
    if list_open:
        blocks.append("</ul>")
    return "\n".join(blocks)


def connect() -> Connection[Any]:
    """按 .env 中 PG_* 配置连接 PostgreSQL。

    Time Complexity: O(1).
    Space Complexity: O(1).
    """
    cfg = settings.postgres
    dsn = f"postgresql://{cfg.user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.database}"
    return psycopg.connect(dsn, options="-c timezone=Asia/Shanghai")


def ensure_schema(conn: Connection[Any], root: Path, init_schema: bool) -> None:
    """在目标库缺少 frontend schema 时按初始化 SQL 创建结构。

    Time Complexity: O(f)，f 为 SQL 文件数量。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'frontend'
            """
        )
        existing_tables = {row[0] for row in cur.fetchall()}

    required_tables = {
        "users",
        "strategies",
        "signals",
        "strategy_equity_curve",
        "user_strategy_subscriptions",
    }
    if required_tables.issubset(existing_tables):
        return
    if existing_tables:
        missing = sorted(required_tables - existing_tables)
        raise RuntimeError(
            "frontend schema is partially initialized; missing tables: "
            + ", ".join(missing)
        )
    if not init_schema:
        raise RuntimeError("frontend schema is missing; rerun with --init-schema")

    for path in sorted((root / SQL_DIR).glob("*.sql")):
        if path.name[:2] not in INIT_SQL_FILES or path.name == "14_mock_data.sql":
            continue
        LOGGER.info("执行初始化 SQL: %s", path.name)
        with path.open(encoding="utf-8") as file:
            conn.execute(file.read())


def load_users(conn: Connection[Any], root: Path) -> dict[str, str]:
    """导入作者和演示用户。

    Time Complexity: O(n)，n 为用户数。
    Space Complexity: O(n)。
    """
    rows = read_csv_dicts(root, "02_author_users.csv")
    user_ids = {row["user_code"]: stable_uuid("user", row["user_code"]) for row in rows}
    with conn.cursor() as cur:
        for row in rows:
            user_id = user_ids[row["user_code"]]
            cur.execute(
                """
                INSERT INTO frontend.users (
                    id, username, display_name, avatar_url, bio, status, updated_at
                )
                VALUES (
                    %(id)s, %(username)s, %(display_name)s, %(avatar_url)s,
                    %(bio)s, %(status)s, NOW()
                )
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    display_name = EXCLUDED.display_name,
                    avatar_url = EXCLUDED.avatar_url,
                    bio = EXCLUDED.bio,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "id": user_id,
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "avatar_url": blank_to_none(row["avatar_url"]),
                    "bio": blank_to_none(row["bio"]),
                    "status": USER_STATUS_MAP.get(row["status"], 1),
                },
            )
            cur.execute(
                """
                INSERT INTO frontend.user_auth (
                    user_id, auth_type, identifier, verified
                )
                VALUES (%(user_id)s, %(auth_type)s, %(identifier)s, TRUE)
                ON CONFLICT (auth_type, identifier) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    verified = EXCLUDED.verified
                """,
                {
                    "user_id": user_id,
                    "auth_type": row["auth_type"],
                    "identifier": row["identifier"],
                },
            )
    return user_ids


def load_categories_and_tags(conn: Connection[Any], root: Path) -> dict[str, int]:
    """导入策略分类和标签。

    Time Complexity: O(c + t)，c 为分类数，t 为标签数。
    Space Complexity: O(t)。
    """
    with conn.cursor() as cur:
        for row in read_csv_dicts(root, "03_categories.csv"):
            cur.execute(
                """
                INSERT INTO frontend.strategy_categories (
                    id, name, description, icon_url, sort_order
                )
                VALUES (%(id)s, %(name)s, %(description)s, %(icon_url)s, %(sort_order)s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    icon_url = EXCLUDED.icon_url,
                    sort_order = EXCLUDED.sort_order
                """,
                {
                    "id": row["category_id"],
                    "name": row["name"],
                    "description": blank_to_none(row["description"]),
                    "icon_url": blank_to_none(row["icon_url"]),
                    "sort_order": to_int(row["sort_order"]) or 0,
                },
            )

        for row in read_csv_dicts(root, "04_tags.csv"):
            cur.execute(
                """
                INSERT INTO frontend.tags (slug, name, tag_group)
                VALUES (%(slug)s, %(name)s, %(tag_group)s)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    tag_group = EXCLUDED.tag_group
                """,
                {
                    "slug": row["tag_code"],
                    "name": row["name"],
                    "tag_group": TAG_GROUP_MAP.get(row["category"], row["category"]),
                },
            )
        cur.execute("SELECT slug, id FROM frontend.tags")
        return {row[0]: row[1] for row in cur.fetchall()}


def load_strategies(
    conn: Connection[Any],
    root: Path,
    user_ids: dict[str, str],
) -> dict[str, str]:
    """导入策略主表。

    Time Complexity: O(n)，n 为策略数。
    Space Complexity: O(n)。
    """
    rows = read_csv_dicts(root, "01_strategy_base.csv")
    author_id = user_ids.get("AUTHOR_001") or next(iter(user_ids.values()))
    strategy_ids = {
        row["strategy_code"]: stable_uuid("strategy", row["strategy_code"])
        for row in rows
    }
    with conn.cursor() as cur:
        for row in rows:
            strategy_id = strategy_ids[row["strategy_code"]]
            description = blank_to_none(row["description"])
            detail_html = blank_to_none(row["detail_html"])
            if detail_html and str(detail_html).endswith(".md"):
                markdown_path = root / DATA_DIR / str(detail_html).removeprefix("./")
                markdown_text = markdown_path.read_text(encoding="utf-8")
                description = description or markdown_text
                detail_html = render_markdown_as_html(markdown_text)

            cur.execute(
                """
                INSERT INTO frontend.strategies (
                    id, strategy_code, author_id, name, summary, description,
                    detail_html, cover_image, category_id, type, asset_class, market,
                    target_horizon, risk_level, access_tier, payg_price,
                    payg_duration_days, subscription_monthly, subscription_yearly,
                    backtest_start, backtest_end, pub_status, run_status,
                    config, version, version_reason, published_at, updated_at
                )
                VALUES (
                    %(id)s, %(strategy_code)s, %(author_id)s, %(name)s,
                    %(summary)s, %(description)s, %(detail_html)s,
                    %(cover_image)s, %(category_id)s, %(type)s, %(asset_class)s,
                    %(market)s, %(target_horizon)s, %(risk_level)s,
                    %(access_tier)s, %(payg_price)s, %(payg_duration_days)s,
                    %(subscription_monthly)s, %(subscription_yearly)s,
                    %(backtest_start)s, %(backtest_end)s, %(pub_status)s,
                    %(run_status)s, %(config)s, %(version)s, %(version_reason)s,
                    %(published_at)s, NOW()
                )
                ON CONFLICT (strategy_code) DO UPDATE SET
                    author_id = EXCLUDED.author_id,
                    name = EXCLUDED.name,
                    summary = EXCLUDED.summary,
                    description = EXCLUDED.description,
                    detail_html = EXCLUDED.detail_html,
                    cover_image = EXCLUDED.cover_image,
                    category_id = EXCLUDED.category_id,
                    type = EXCLUDED.type,
                    asset_class = EXCLUDED.asset_class,
                    market = EXCLUDED.market,
                    target_horizon = EXCLUDED.target_horizon,
                    risk_level = EXCLUDED.risk_level,
                    access_tier = EXCLUDED.access_tier,
                    payg_price = EXCLUDED.payg_price,
                    payg_duration_days = EXCLUDED.payg_duration_days,
                    subscription_monthly = EXCLUDED.subscription_monthly,
                    subscription_yearly = EXCLUDED.subscription_yearly,
                    backtest_start = EXCLUDED.backtest_start,
                    backtest_end = EXCLUDED.backtest_end,
                    pub_status = EXCLUDED.pub_status,
                    run_status = EXCLUDED.run_status,
                    config = EXCLUDED.config,
                    version = EXCLUDED.version,
                    version_reason = EXCLUDED.version_reason,
                    published_at = EXCLUDED.published_at,
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "id": strategy_id,
                    "strategy_code": row["strategy_code"],
                    "author_id": author_id,
                    "name": row["name"],
                    "summary": blank_to_none(row["summary"]),
                    "description": description,
                    "detail_html": detail_html,
                    "cover_image": blank_to_none(row["cover_image"]),
                    "category_id": blank_to_none(row["category_id"]),
                    "type": row["type"],
                    "asset_class": row["asset_class"],
                    "market": row["market"],
                    "target_horizon": blank_to_none(row["target_horizon"]),
                    "risk_level": row["risk_level"],
                    "access_tier": to_int(row["access_tier"]) or 0,
                    "payg_price": to_decimal(row["payg_price"]),
                    "payg_duration_days": to_int(row["payg_duration_days"]),
                    "subscription_monthly": to_decimal(row["subscription_monthly"]),
                    "subscription_yearly": to_decimal(row["subscription_yearly"]),
                    "backtest_start": parse_date(row["backtest_start"]),
                    "backtest_end": parse_date(row["backtest_end"]),
                    "pub_status": row["pub_status"],
                    "run_status": RUN_STATUS_MAP.get(
                        row["run_status"], row["run_status"]
                    ),
                    "config": Jsonb(parse_json(row["config"], {})),
                    "version": row["version"],
                    "version_reason": blank_to_none(row["version_reason"]),
                    "published_at": blank_to_none(row["published_at"]),
                },
            )
    return strategy_ids


def load_strategy_tags(
    conn: Connection[Any],
    root: Path,
    strategy_ids: dict[str, str],
    tag_ids: dict[str, int],
) -> None:
    """导入策略标签关联。

    Time Complexity: O(n)，n 为关联数。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        for row in read_csv_dicts(root, "05_strategy_tags.csv"):
            cur.execute(
                """
                INSERT INTO frontend.strategy_tags (strategy_id, tag_id)
                VALUES (%(strategy_id)s, %(tag_id)s)
                ON CONFLICT DO NOTHING
                """,
                {
                    "strategy_id": strategy_ids[row["strategy_code"]],
                    "tag_id": tag_ids[row["tag_code"]],
                },
            )


def load_equity_curve(
    conn: Connection[Any],
    root: Path,
    strategy_ids: dict[str, str],
) -> None:
    """从日度净值 CSV 导入策略净值曲线。

    Time Complexity: O(n)，n 为日度行数。
    Space Complexity: O(n)。
    """
    rows = read_csv_dicts(root, "STR_IF_001_daily_since_20220630.csv")
    strategy_id = strategy_ids["STR_IF_001"]
    max_nav: Decimal | None = None
    payload: list[dict[str, Any]] = []
    for row in rows:
        nav = to_decimal(row["netvalue"])
        if nav is None or nav <= 0:
            raise ValueError(f"Invalid nav in equity curve: {row}")
        max_nav = nav if max_nav is None else max(max_nav, nav)
        drawdown = nav / max_nav - Decimal("1")
        payload.append(
            {
                "strategy_id": strategy_id,
                "trade_date": parse_date(row["date"]),
                "nav": nav,
                "cumulative_return": nav - Decimal("1"),
                "daily_return": to_decimal(row["ret_total"]),
                "drawdown": drawdown,
                "benchmark_nav": None,
                "position_ratio": None,
            }
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO frontend.strategy_equity_curve (
                strategy_id, trade_date, nav, cumulative_return, daily_return,
                drawdown, benchmark_nav, position_ratio
            )
            VALUES (
                %(strategy_id)s, %(trade_date)s, %(nav)s, %(cumulative_return)s,
                %(daily_return)s, %(drawdown)s, %(benchmark_nav)s,
                %(position_ratio)s
            )
            ON CONFLICT (strategy_id, trade_date) DO UPDATE SET
                nav = EXCLUDED.nav,
                cumulative_return = EXCLUDED.cumulative_return,
                daily_return = EXCLUDED.daily_return,
                drawdown = EXCLUDED.drawdown,
                benchmark_nav = EXCLUDED.benchmark_nav,
                position_ratio = EXCLUDED.position_ratio
            """,
            payload,
        )


def load_performance(
    conn: Connection[Any],
    root: Path,
    strategy_ids: dict[str, str],
) -> None:
    """导入绩效快照和月度收益。

    Time Complexity: O(s + m)，s 为快照数，m 为月收益数。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        for row in read_csv_dicts(root, "11_performance_snapshot_optional.csv"):
            values = {
                key: to_decimal(value)
                for key, value in row.items()
                if key
                not in {
                    "strategy_code",
                    "snapshot_date",
                    "max_drawdown_start",
                    "max_drawdown_end",
                    "max_drawdown_recovery",
                    "total_trades",
                    "max_consecutive_wins",
                    "max_consecutive_losses",
                }
            }
            values.update(
                {
                    "strategy_id": strategy_ids[row["strategy_code"]],
                    "snapshot_date": parse_date(row["snapshot_date"]),
                    "max_drawdown_start": parse_date(row["max_drawdown_start"]),
                    "max_drawdown_end": parse_date(row["max_drawdown_end"]),
                    "max_drawdown_recovery": parse_date(row["max_drawdown_recovery"]),
                    "total_trades": to_int(row["total_trades"]),
                    "max_consecutive_wins": to_int(row["max_consecutive_wins"]),
                    "max_consecutive_losses": to_int(row["max_consecutive_losses"]),
                }
            )
            cur.execute(
                """
                INSERT INTO frontend.strategy_performance_snapshot (
                    strategy_id, snapshot_date, total_return, annualized_return,
                    ytd_return, recent_1m_return, recent_3m_return,
                    recent_6m_return, recent_1y_return, max_drawdown,
                    max_drawdown_start, max_drawdown_end, max_drawdown_recovery,
                    annualized_volatility, downside_deviation, sharpe_ratio,
                    sortino_ratio, calmar_ratio, information_ratio, total_trades,
                    win_rate, profit_factor, avg_win, avg_loss,
                    max_consecutive_wins, max_consecutive_losses,
                    avg_holding_days, var_95, cvar_95, beta, alpha
                )
                VALUES (
                    %(strategy_id)s, %(snapshot_date)s, %(total_return)s,
                    %(annualized_return)s, %(ytd_return)s, %(recent_1m_return)s,
                    %(recent_3m_return)s, %(recent_6m_return)s,
                    %(recent_1y_return)s, %(max_drawdown)s,
                    %(max_drawdown_start)s, %(max_drawdown_end)s,
                    %(max_drawdown_recovery)s, %(annualized_volatility)s,
                    %(downside_deviation)s, %(sharpe_ratio)s,
                    %(sortino_ratio)s, %(calmar_ratio)s,
                    %(information_ratio)s, %(total_trades)s, %(win_rate)s,
                    %(profit_factor)s, %(avg_win)s, %(avg_loss)s,
                    %(max_consecutive_wins)s, %(max_consecutive_losses)s,
                    %(avg_holding_days)s, %(var_95)s, %(cvar_95)s,
                    %(beta)s, %(alpha)s
                )
                ON CONFLICT (strategy_id, snapshot_date) DO UPDATE SET
                    total_return = EXCLUDED.total_return,
                    annualized_return = EXCLUDED.annualized_return,
                    ytd_return = EXCLUDED.ytd_return,
                    recent_1m_return = EXCLUDED.recent_1m_return,
                    recent_3m_return = EXCLUDED.recent_3m_return,
                    recent_6m_return = EXCLUDED.recent_6m_return,
                    recent_1y_return = EXCLUDED.recent_1y_return,
                    max_drawdown = EXCLUDED.max_drawdown,
                    max_drawdown_start = EXCLUDED.max_drawdown_start,
                    max_drawdown_end = EXCLUDED.max_drawdown_end,
                    max_drawdown_recovery = EXCLUDED.max_drawdown_recovery,
                    annualized_volatility = EXCLUDED.annualized_volatility,
                    downside_deviation = EXCLUDED.downside_deviation,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    sortino_ratio = EXCLUDED.sortino_ratio,
                    calmar_ratio = EXCLUDED.calmar_ratio,
                    information_ratio = EXCLUDED.information_ratio,
                    total_trades = EXCLUDED.total_trades,
                    win_rate = EXCLUDED.win_rate,
                    profit_factor = EXCLUDED.profit_factor,
                    avg_win = EXCLUDED.avg_win,
                    avg_loss = EXCLUDED.avg_loss,
                    max_consecutive_wins = EXCLUDED.max_consecutive_wins,
                    max_consecutive_losses = EXCLUDED.max_consecutive_losses,
                    avg_holding_days = EXCLUDED.avg_holding_days,
                    var_95 = EXCLUDED.var_95,
                    cvar_95 = EXCLUDED.cvar_95,
                    beta = EXCLUDED.beta,
                    alpha = EXCLUDED.alpha
                """,
                values,
            )

        for row in read_csv_dicts(root, "12_monthly_returns_optional.csv"):
            cur.execute(
                """
                INSERT INTO frontend.strategy_monthly_returns (
                    strategy_id, year, month, monthly_return
                )
                VALUES (%(strategy_id)s, %(year)s, %(month)s, %(monthly_return)s)
                ON CONFLICT (strategy_id, year, month) DO UPDATE SET
                    monthly_return = EXCLUDED.monthly_return
                """,
                {
                    "strategy_id": strategy_ids[row["strategy_code"]],
                    "year": to_int(row["year"]),
                    "month": to_int(row["month"]),
                    "monthly_return": to_decimal(row["monthly_return"]),
                },
            )


def normalized_signals(root: Path) -> list[dict[str, Any]]:
    """归一化信号 CSV，保留原始枚举到 reason_detail。

    Time Complexity: O(n)，n 为信号数。
    Space Complexity: O(n)。
    """
    signals: list[dict[str, Any]] = []
    for row in read_signal_rows(root):
        original_action = row["action"]
        original_direction = row["direction"]
        action = ACTION_MAP.get(original_action, original_action)
        direction = DIRECTION_MAP.get(original_direction, original_direction)
        reason_detail = parse_json(row["reason_detail"], {})
        if original_action != action:
            reason_detail["source_action"] = original_action
        if original_direction != direction:
            reason_detail["source_direction"] = original_direction
        confidence = to_decimal(row["confidence"]) or Decimal("0.50")
        signals.append(
            {
                **row,
                "id": stable_uuid("signal", row["signal_code"]),
                "batch_id": stable_uuid("signal_batch", row["batch_code"]),
                "parent_signal_id": (
                    stable_uuid("signal", row["parent_signal_code"])
                    if blank_to_none(row["parent_signal_code"])
                    else None
                ),
                "action": action,
                "direction": direction,
                "position_pct": to_decimal(row["position_pct"]),
                "confidence": confidence,
                "reason_detail": reason_detail,
            }
        )
    return signals


def load_signals(
    conn: Connection[Any],
    root: Path,
    strategy_ids: dict[str, str],
) -> dict[str, str]:
    """导入信号批次和信号主表。

    Time Complexity: O(n)，n 为信号数。
    Space Complexity: O(n)。
    """
    signals = normalized_signals(root)
    batches: dict[str, dict[str, Any]] = {}
    for row in signals:
        batch_code = row["batch_code"]
        published_at = row["published_at"]
        batch = batches.setdefault(
            batch_code,
            {
                "id": row["batch_id"],
                "strategy_id": strategy_ids[row["strategy_code"]],
                "batch_code": batch_code,
                "note": "Imported from frontend-data/06_signals.csv",
                "published_at": published_at,
            },
        )
        if published_at < batch["published_at"]:
            batch["published_at"] = published_at

    signal_ids = {row["signal_code"]: row["id"] for row in signals}
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO frontend.signal_batches (
                id, strategy_id, batch_code, note, published_at
            )
            VALUES (
                %(id)s, %(strategy_id)s, %(batch_code)s, %(note)s, %(published_at)s
            )
            ON CONFLICT (batch_code) DO UPDATE SET
                strategy_id = EXCLUDED.strategy_id,
                note = EXCLUDED.note,
                published_at = EXCLUDED.published_at
            """,
            list(batches.values()),
        )
        for row in signals:
            cur.execute(
                """
                INSERT INTO frontend.signals (
                    id, signal_code, strategy_id, batch_id, parent_signal_id,
                    market, exchange, symbol, symbol_name, type, action, direction,
                    entry_low, entry_high, trigger_price, target_price,
                    stop_loss_price, suggested_quantity, position_pct, confidence,
                    urgency, reason, reason_detail, logic_summary, option_type,
                    strike_price, expiry_date, greeks, access_tier,
                    delay_free_hours, status, expire_at, published_at, result,
                    exit_price, pnl_pct, resolved_at
                )
                VALUES (
                    %(id)s, %(signal_code)s, %(strategy_id)s, %(batch_id)s,
                    %(parent_signal_id)s, %(market)s, %(exchange)s, %(symbol)s,
                    %(symbol_name)s, %(type)s, %(action)s, %(direction)s,
                    %(entry_low)s, %(entry_high)s, %(trigger_price)s,
                    %(target_price)s, %(stop_loss_price)s,
                    %(suggested_quantity)s, %(position_pct)s, %(confidence)s,
                    %(urgency)s, %(reason)s, %(reason_detail)s, %(logic_summary)s,
                    %(option_type)s, %(strike_price)s, %(expiry_date)s,
                    %(greeks)s, %(access_tier)s, %(delay_free_hours)s,
                    %(status)s, %(expire_at)s, %(published_at)s, %(result)s,
                    %(exit_price)s, %(pnl_pct)s, %(resolved_at)s
                )
                ON CONFLICT (signal_code) DO UPDATE SET
                    strategy_id = EXCLUDED.strategy_id,
                    batch_id = EXCLUDED.batch_id,
                    parent_signal_id = EXCLUDED.parent_signal_id,
                    market = EXCLUDED.market,
                    exchange = EXCLUDED.exchange,
                    symbol = EXCLUDED.symbol,
                    symbol_name = EXCLUDED.symbol_name,
                    type = EXCLUDED.type,
                    action = EXCLUDED.action,
                    direction = EXCLUDED.direction,
                    entry_low = EXCLUDED.entry_low,
                    entry_high = EXCLUDED.entry_high,
                    trigger_price = EXCLUDED.trigger_price,
                    target_price = EXCLUDED.target_price,
                    stop_loss_price = EXCLUDED.stop_loss_price,
                    suggested_quantity = EXCLUDED.suggested_quantity,
                    position_pct = EXCLUDED.position_pct,
                    confidence = EXCLUDED.confidence,
                    urgency = EXCLUDED.urgency,
                    reason = EXCLUDED.reason,
                    reason_detail = EXCLUDED.reason_detail,
                    logic_summary = EXCLUDED.logic_summary,
                    option_type = EXCLUDED.option_type,
                    strike_price = EXCLUDED.strike_price,
                    expiry_date = EXCLUDED.expiry_date,
                    greeks = EXCLUDED.greeks,
                    access_tier = EXCLUDED.access_tier,
                    delay_free_hours = EXCLUDED.delay_free_hours,
                    status = EXCLUDED.status,
                    expire_at = EXCLUDED.expire_at,
                    published_at = EXCLUDED.published_at,
                    result = EXCLUDED.result,
                    exit_price = EXCLUDED.exit_price,
                    pnl_pct = EXCLUDED.pnl_pct,
                    resolved_at = EXCLUDED.resolved_at
                """,
                {
                    "id": row["id"],
                    "signal_code": row["signal_code"],
                    "strategy_id": strategy_ids[row["strategy_code"]],
                    "batch_id": row["batch_id"],
                    "parent_signal_id": row["parent_signal_id"],
                    "market": row["market"],
                    "exchange": blank_to_none(row["exchange"]),
                    "symbol": row["symbol"],
                    "symbol_name": blank_to_none(row["symbol_name"]),
                    "type": row["type"],
                    "action": row["action"],
                    "direction": blank_to_none(row["direction"]),
                    "entry_low": to_decimal(row["entry_low"]),
                    "entry_high": to_decimal(row["entry_high"]),
                    "trigger_price": to_decimal(row["trigger_price"]),
                    "target_price": to_decimal(row["target_price"]),
                    "stop_loss_price": to_decimal(row["stop_loss_price"]),
                    "suggested_quantity": to_int(row["suggested_quantity"]),
                    "position_pct": row["position_pct"],
                    "confidence": row["confidence"],
                    "urgency": row["urgency"] or "normal",
                    "reason": blank_to_none(row["reason"]),
                    "reason_detail": Jsonb(row["reason_detail"]),
                    "logic_summary": blank_to_none(row["logic_summary"]),
                    "option_type": blank_to_none(row["option_type"]),
                    "strike_price": to_decimal(row["strike_price"]),
                    "expiry_date": parse_date(row["expiry_date"]),
                    "greeks": Jsonb(parse_json(row["greeks"], {})),
                    "access_tier": to_int(row["access_tier"]) or 0,
                    "delay_free_hours": to_int(row["delay_free_hours"]),
                    "status": row["status"],
                    "expire_at": blank_to_none(row["expire_at"]),
                    "published_at": row["published_at"],
                    "result": blank_to_none(row["result"]),
                    "exit_price": to_decimal(row["exit_price"]),
                    "pnl_pct": to_decimal(row["pnl_pct"]),
                    "resolved_at": blank_to_none(row["resolved_at"]),
                },
            )
    return signal_ids


def load_signal_snapshots(
    conn: Connection[Any],
    root: Path,
    signal_ids: dict[str, str],
) -> None:
    """导入信号行情快照。

    Time Complexity: O(n)，n 为快照数。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        for row in read_csv_dicts(root, "07_signal_market_snapshots.csv"):
            cur.execute(
                """
                INSERT INTO frontend.signal_market_snapshot (
                    signal_id, symbol, snapshot_time, open, high, low, close,
                    volume, turnover, open_interest, basis, indicators,
                    implied_vol, greeks_snapshot
                )
                VALUES (
                    %(signal_id)s, %(symbol)s, %(snapshot_time)s, %(open)s,
                    %(high)s, %(low)s, %(close)s, %(volume)s, %(turnover)s,
                    %(open_interest)s, %(basis)s, %(indicators)s,
                    %(implied_vol)s, %(greeks_snapshot)s
                )
                ON CONFLICT (signal_id, symbol, snapshot_time) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    turnover = EXCLUDED.turnover,
                    open_interest = EXCLUDED.open_interest,
                    basis = EXCLUDED.basis,
                    indicators = EXCLUDED.indicators,
                    implied_vol = EXCLUDED.implied_vol,
                    greeks_snapshot = EXCLUDED.greeks_snapshot
                """,
                {
                    "signal_id": signal_ids[row["signal_code"]],
                    "symbol": row["symbol"],
                    "snapshot_time": row["snapshot_time"],
                    "open": to_decimal(row["open"]),
                    "high": to_decimal(row["high"]),
                    "low": to_decimal(row["low"]),
                    "close": to_decimal(row["close"]),
                    "volume": to_int(row["volume"]),
                    "turnover": to_decimal(row["turnover"]),
                    "open_interest": to_int(row["open_interest"]),
                    "basis": to_decimal(row["basis"]),
                    "indicators": Jsonb(parse_json(row["indicators"], {})),
                    "implied_vol": to_decimal(row["implied_vol"]),
                    "greeks_snapshot": Jsonb(parse_json(row["greeks_snapshot"], {})),
                },
            )


def load_user_signal_reads(
    conn: Connection[Any],
    root: Path,
    user_ids: dict[str, str],
    signal_ids: dict[str, str],
) -> None:
    """导入用户信号阅读和执行状态。

    Time Complexity: O(n)，n 为状态行数。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        for row in read_csv_dicts(root, "08_user_signal_reads.csv"):
            cur.execute(
                """
                INSERT INTO frontend.user_signal_reads (
                    user_id, signal_id, read_at, is_executed, executed_price,
                    executed_qty, executed_at, note
                )
                VALUES (
                    %(user_id)s, %(signal_id)s, %(read_at)s, %(is_executed)s,
                    %(executed_price)s, %(executed_qty)s, %(executed_at)s,
                    %(note)s
                )
                ON CONFLICT (user_id, signal_id) DO UPDATE SET
                    read_at = EXCLUDED.read_at,
                    is_executed = EXCLUDED.is_executed,
                    executed_price = EXCLUDED.executed_price,
                    executed_qty = EXCLUDED.executed_qty,
                    executed_at = EXCLUDED.executed_at,
                    note = EXCLUDED.note
                """,
                {
                    "user_id": user_ids[row["user_code"]],
                    "signal_id": signal_ids[row["signal_code"]],
                    "read_at": row["read_at"],
                    "is_executed": to_bool(row["is_executed"]) or False,
                    "executed_price": to_decimal(row["executed_price"]),
                    "executed_qty": to_int(row["executed_qty"]),
                    "executed_at": blank_to_none(row["executed_at"]),
                    "note": blank_to_none(row["note"]),
                },
            )


def strategy_subscription_price(
    conn: Connection[Any], strategy_id: str, plan_type: str
) -> Decimal:
    """读取策略订阅价格；缺失时返回 0，用于 mock 订单。

    Time Complexity: O(1).
    Space Complexity: O(1).
    """
    column = "subscription_yearly" if plan_type == "yearly" else "subscription_monthly"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COALESCE({column}, 0) FROM frontend.strategies WHERE id = %s",
            (strategy_id,),
        )
        return cur.fetchone()[0]


def load_subscriptions(
    conn: Connection[Any],
    root: Path,
    user_ids: dict[str, str],
    strategy_ids: dict[str, str],
) -> None:
    """导入策略订阅，并为 source_order_no 生成可追踪 mock 订单。

    Time Complexity: O(n)，n 为订阅行数。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        for row in read_csv_dicts(root, "09_subscription_permissions.csv"):
            user_id = user_ids[row["user_code"]]
            strategy_id = strategy_ids[row["strategy_code"]]
            source_order_no = blank_to_none(row["source_order_no"])
            source_order_id = (
                stable_uuid("order", str(source_order_no)) if source_order_no else None
            )
            if source_order_id:
                price = strategy_subscription_price(conn, strategy_id, row["plan_type"])
                cur.execute(
                    """
                    INSERT INTO frontend.orders (
                        id, order_no, user_id, subtotal, discount_amount, total,
                        status, paid_at, created_at
                    )
                    VALUES (
                        %(id)s, %(order_no)s, %(user_id)s, %(subtotal)s, 0,
                        %(total)s, 'paid', %(paid_at)s, NOW()
                    )
                    ON CONFLICT (order_no) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        subtotal = EXCLUDED.subtotal,
                        total = EXCLUDED.total,
                        status = EXCLUDED.status,
                        paid_at = EXCLUDED.paid_at
                    """,
                    {
                        "id": source_order_id,
                        "order_no": source_order_no,
                        "user_id": user_id,
                        "subtotal": price,
                        "total": price,
                        "paid_at": row["start_date"],
                    },
                )
                cur.execute(
                    """
                    INSERT INTO frontend.order_items (
                        id, order_id, item_type, item_id, item_name, unit_price,
                        quantity, subtotal, plan_type, duration_days, meta
                    )
                    VALUES (
                        %(id)s, %(order_id)s, 'strategy_subscription',
                        %(item_id)s, %(item_name)s, %(unit_price)s, 1,
                        %(subtotal)s, %(plan_type)s, %(duration_days)s, %(meta)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        order_id = EXCLUDED.order_id,
                        item_id = EXCLUDED.item_id,
                        item_name = EXCLUDED.item_name,
                        unit_price = EXCLUDED.unit_price,
                        subtotal = EXCLUDED.subtotal,
                        plan_type = EXCLUDED.plan_type,
                        duration_days = EXCLUDED.duration_days,
                        meta = EXCLUDED.meta
                    """,
                    {
                        "id": stable_uuid("order_item", str(source_order_no)),
                        "order_id": source_order_id,
                        "item_id": strategy_id,
                        "item_name": row["strategy_code"],
                        "unit_price": price,
                        "subtotal": price,
                        "plan_type": row["plan_type"],
                        "duration_days": (
                            parse_date(row["expire_date"])
                            - parse_date(row["start_date"])
                        ).days,
                        "meta": Jsonb({"source": "frontend-data"}),
                    },
                )

            if row["access_mode"] == "subscription":
                cur.execute(
                    """
                    INSERT INTO frontend.user_strategy_subscriptions (
                        id, user_id, strategy_id, plan_type, status, auto_renew,
                        start_date, expire_date, source_order_id, cancelled_at,
                        cancel_reason, updated_at
                    )
                    VALUES (
                        %(id)s, %(user_id)s, %(strategy_id)s, %(plan_type)s,
                        %(status)s, %(auto_renew)s, %(start_date)s,
                        %(expire_date)s, %(source_order_id)s, %(cancelled_at)s,
                        %(cancel_reason)s, NOW()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        auto_renew = EXCLUDED.auto_renew,
                        expire_date = EXCLUDED.expire_date,
                        source_order_id = EXCLUDED.source_order_id,
                        cancelled_at = EXCLUDED.cancelled_at,
                        cancel_reason = EXCLUDED.cancel_reason,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "id": stable_uuid(
                            "strategy_subscription",
                            f"{row['user_code']}:{row['strategy_code']}:{row['start_date']}",
                        ),
                        "user_id": user_id,
                        "strategy_id": strategy_id,
                        "plan_type": row["plan_type"],
                        "status": row["status"],
                        "auto_renew": to_bool(row["auto_renew"]) or False,
                        "start_date": parse_date(row["start_date"]),
                        "expire_date": parse_date(row["expire_date"]),
                        "source_order_id": source_order_id,
                        "cancelled_at": blank_to_none(row["cancelled_at"]),
                        "cancel_reason": blank_to_none(row["cancel_reason"]),
                    },
                )


def load_push_settings(
    conn: Connection[Any],
    root: Path,
    user_ids: dict[str, str],
    strategy_ids: dict[str, str],
) -> None:
    """导入用户全局和策略级推送配置。

    Time Complexity: O(n)，n 为配置行数。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        for row in read_csv_dicts(root, "10_push_settings.csv"):
            user_id = user_ids[row["user_code"]]
            if row["push_scope"] == "global":
                cur.execute(
                    """
                    INSERT INTO frontend.user_signal_settings (
                        user_id, push_enabled, channels, confidence_threshold,
                        urgency_filter, quiet_hours, trading_hours_only, updated_at
                    )
                    VALUES (
                        %(user_id)s, %(push_enabled)s, %(channels)s,
                        %(confidence_threshold)s, %(urgency_filter)s,
                        %(quiet_hours)s, %(trading_hours_only)s, NOW()
                    )
                    ON CONFLICT (user_id) DO UPDATE SET
                        push_enabled = EXCLUDED.push_enabled,
                        channels = EXCLUDED.channels,
                        confidence_threshold = EXCLUDED.confidence_threshold,
                        urgency_filter = EXCLUDED.urgency_filter,
                        quiet_hours = EXCLUDED.quiet_hours,
                        trading_hours_only = EXCLUDED.trading_hours_only,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "user_id": user_id,
                        "push_enabled": to_bool(row["push_enabled"]) or False,
                        "channels": Jsonb(parse_json(row["channels"], {})),
                        "confidence_threshold": to_decimal(row["confidence_threshold"])
                        or Decimal("0.50"),
                        "urgency_filter": parse_pg_text_array(row["urgency_filter"]),
                        "quiet_hours": Jsonb(parse_json(row["quiet_hours"], {})),
                        "trading_hours_only": to_bool(row["trading_hours_only"])
                        or False,
                    },
                )
            else:
                cur.execute(
                    """
                    INSERT INTO frontend.user_strategy_signal_settings (
                        user_id, strategy_id, push_enabled, confidence_threshold,
                        notify_entry_only, updated_at
                    )
                    VALUES (
                        %(user_id)s, %(strategy_id)s, %(push_enabled)s,
                        %(confidence_threshold)s, %(notify_entry_only)s, NOW()
                    )
                    ON CONFLICT (user_id, strategy_id) DO UPDATE SET
                        push_enabled = EXCLUDED.push_enabled,
                        confidence_threshold = EXCLUDED.confidence_threshold,
                        notify_entry_only = EXCLUDED.notify_entry_only,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "user_id": user_id,
                        "strategy_id": strategy_ids[row["strategy_code"]],
                        "push_enabled": to_bool(row["push_enabled"]) or False,
                        "confidence_threshold": to_decimal(row["confidence_threshold"]),
                        "notify_entry_only": to_bool(row["notify_entry_only"]) or False,
                    },
                )


def refresh_strategy_counts(conn: Connection[Any]) -> None:
    """刷新策略信号数和订阅数冗余字段。

    Time Complexity: O(s + n)，s 为策略数，n 为订阅/信号数。
    Space Complexity: O(1)。
    """
    conn.execute(
        """
        UPDATE frontend.strategies s
        SET
            signal_count = COALESCE(sig.cnt, 0),
            subscriber_count = COALESCE(sub.cnt, 0),
            updated_at = NOW()
        FROM (
            SELECT id FROM frontend.strategies
        ) base
        LEFT JOIN (
            SELECT strategy_id, COUNT(*)::INT AS cnt
            FROM frontend.signals
            GROUP BY strategy_id
        ) sig ON sig.strategy_id = base.id
        LEFT JOIN (
            SELECT strategy_id, COUNT(*)::INT AS cnt
            FROM frontend.user_strategy_subscriptions
            WHERE status = 'active' AND expire_date >= CURRENT_DATE
            GROUP BY strategy_id
        ) sub ON sub.strategy_id = base.id
        WHERE s.id = base.id
        """
    )


def log_counts(conn: Connection[Any], tables: Iterable[str]) -> None:
    """输出导入后核心表行数。

    Time Complexity: O(t)，t 为表数量。
    Space Complexity: O(1)。
    """
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM frontend.{table}")
            LOGGER.info("frontend.%s rows=%s", table, cur.fetchone()[0])


def load_all(init_schema: bool) -> None:
    """执行完整导入流程。

    Time Complexity: O(n)，n 为所有 CSV 行数总和。
    Space Complexity: O(n)。
    """
    root = project_root()
    with connect() as conn:
        ensure_schema(conn, root, init_schema)
        user_ids = load_users(conn, root)
        tag_ids = load_categories_and_tags(conn, root)
        strategy_ids = load_strategies(conn, root, user_ids)
        load_strategy_tags(conn, root, strategy_ids, tag_ids)
        load_equity_curve(conn, root, strategy_ids)
        load_performance(conn, root, strategy_ids)
        signal_ids = load_signals(conn, root, strategy_ids)
        load_signal_snapshots(conn, root, signal_ids)
        load_user_signal_reads(conn, root, user_ids, signal_ids)
        load_subscriptions(conn, root, user_ids, strategy_ids)
        load_push_settings(conn, root, user_ids, strategy_ids)
        refresh_strategy_counts(conn)
        conn.commit()
        log_counts(
            conn,
            (
                "users",
                "strategy_categories",
                "tags",
                "strategies",
                "strategy_equity_curve",
                "strategy_performance_snapshot",
                "strategy_monthly_returns",
                "signal_batches",
                "signals",
                "signal_market_snapshot",
                "user_signal_reads",
                "orders",
                "user_strategy_subscriptions",
                "user_signal_settings",
                "user_strategy_signal_settings",
            ),
        )


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    Time Complexity: O(1).
    Space Complexity: O(1).
    """
    parser = argparse.ArgumentParser(
        description="Load frontend-data CSV files into frontend PostgreSQL schema."
    )
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help="Create frontend schema from sql/init/frontend_signal when missing.",
    )
    return parser.parse_args()


def main() -> None:
    """脚本入口。

    Time Complexity: O(n)，n 为所有 CSV 行数总和。
    Space Complexity: O(n)。
    """
    args = parse_args()
    load_all(init_schema=args.init_schema)


if __name__ == "__main__":
    main()
