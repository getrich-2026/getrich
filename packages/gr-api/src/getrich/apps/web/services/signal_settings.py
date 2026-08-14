"""推送设置业务逻辑（用户全局 + 策略覆盖）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from getrich.apps.web.errors import NotFound


if TYPE_CHECKING:
    from psycopg import AsyncConnection

    from getrich.apps.web.schemas.subscription import (
        GlobalSettingsIn,
        StrategySettingsPatch,
    )


_DEFAULT_CHANNELS = {
    "app_push": True,
    "sms": False,
    "email": False,
    "wechat_service": False,
    "websocket": True,
}
_DEFAULT_QUIET_HOURS = {"enabled": False, "start": "22:00", "end": "08:30"}
_DEFAULT_URGENCY = ["normal", "high", "critical"]


# ---------------------------------------------------------------- 用户全局


async def get_global_settings(
    db: AsyncConnection,
    *,
    user_id: str,
) -> dict[str, Any]:
    """GET /user/signal-settings"""
    async with db.cursor() as cur:
        await cur.execute(
            """
            SELECT push_enabled, channels, confidence_threshold,
                   urgency_filter, quiet_hours, trading_hours_only
            FROM user_signal_settings WHERE user_id = %s
            """,
            (user_id,),
        )
        row = await cur.fetchone()

        if row is None:
            # 未初始化则返回默认值（不写库；首次 PUT 时再 upsert）
            global_settings = {
                "confidence_threshold": 0.50,
                "urgency_filter": _DEFAULT_URGENCY,
                "quiet_hours": _DEFAULT_QUIET_HOURS,
                "trading_hours_only": False,
            }
            push_enabled = True
            channels = dict(_DEFAULT_CHANNELS)
        else:
            global_settings = {
                "confidence_threshold": float(row["confidence_threshold"]),
                "urgency_filter": list(row["urgency_filter"] or _DEFAULT_URGENCY),
                "quiet_hours": row["quiet_hours"] or _DEFAULT_QUIET_HOURS,
                "trading_hours_only": row["trading_hours_only"],
            }
            push_enabled = row["push_enabled"]
            channels = _merge_channels(_DEFAULT_CHANNELS, row["channels"] or {})

        # 策略覆盖列表
        await cur.execute(
            """
            SELECT s.strategy_code,
                   us.push_enabled,
                   us.confidence_threshold,
                   us.notify_entry_only
            FROM user_strategy_signal_settings us
            JOIN strategies s ON s.id = us.strategy_id
            WHERE us.user_id = %s
            ORDER BY us.updated_at DESC
            """,
            (user_id,),
        )
        overrides = await cur.fetchall()

    return {
        "push_enabled": push_enabled,
        "channels": channels,
        "global_settings": global_settings,
        "strategy_overrides": [
            {
                "strategy_id": r["strategy_code"],
                "push_enabled": r["push_enabled"],
                "confidence_threshold": float(r["confidence_threshold"])
                if r["confidence_threshold"] is not None
                else None,
                "notify_entry_only": r["notify_entry_only"],
            }
            for r in overrides
        ],
    }


async def update_global_settings(
    db: AsyncConnection,
    *,
    user_id: str,
    body: GlobalSettingsIn,
) -> dict[str, Any]:
    """PUT /user/signal-settings"""
    # 取现有值用于合并
    current = await get_global_settings(db, user_id=user_id)

    push_enabled = body.push_enabled if body.push_enabled is not None else current["push_enabled"]

    new_channels = dict(current["channels"])
    if body.channels is not None:
        for k, v in body.channels.model_dump(exclude_none=True).items():
            new_channels[k] = v

    gs = current["global_settings"]
    new_threshold = gs["confidence_threshold"]
    new_urgency = gs["urgency_filter"]
    new_quiet = dict(gs["quiet_hours"])
    new_trading_only = gs["trading_hours_only"]

    if body.global_settings is not None:
        gs_in = body.global_settings
        if gs_in.confidence_threshold is not None:
            new_threshold = gs_in.confidence_threshold
        if gs_in.urgency_filter is not None:
            new_urgency = gs_in.urgency_filter
        if gs_in.trading_hours_only is not None:
            new_trading_only = gs_in.trading_hours_only
        if gs_in.quiet_hours is not None:
            qh = gs_in.quiet_hours.model_dump(exclude_none=True)
            new_quiet.update(qh)

    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO user_signal_settings
                (user_id, push_enabled, channels, confidence_threshold,
                 urgency_filter, quiet_hours, trading_hours_only)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                push_enabled = EXCLUDED.push_enabled,
                channels = EXCLUDED.channels,
                confidence_threshold = EXCLUDED.confidence_threshold,
                urgency_filter = EXCLUDED.urgency_filter,
                quiet_hours = EXCLUDED.quiet_hours,
                trading_hours_only = EXCLUDED.trading_hours_only,
                updated_at = NOW()
            """,
            (
                user_id,
                push_enabled,
                json.dumps(new_channels),
                new_threshold,
                new_urgency,
                json.dumps(new_quiet),
                new_trading_only,
            ),
        )
        await db.commit()

    return {"updated": True}


# ---------------------------------------------------------------- 策略覆盖


async def get_strategy_settings(
    db: AsyncConnection,
    *,
    user_id: str,
    strategy_code: str,
) -> dict[str, Any]:
    """GET /strategies/{strategy_code}/signal-settings"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id FROM strategies WHERE strategy_code = %s",
            (strategy_code,),
        )
        strat = await cur.fetchone()
        if strat is None:
            raise NotFound(f"strategy not found: {strategy_code}")

        await cur.execute(
            """
            SELECT push_enabled, confidence_threshold, notify_entry_only
            FROM user_strategy_signal_settings
            WHERE user_id = %s AND strategy_id = %s
            """,
            (user_id, strat["id"]),
        )
        row = await cur.fetchone()

        # 全局兜底（用于继承）
        await cur.execute(
            """
            SELECT channels, urgency_filter, confidence_threshold
            FROM user_signal_settings WHERE user_id = %s
            """,
            (user_id,),
        )
        gl = await cur.fetchone()

    if gl is not None:
        global_channels = _merge_channels(_DEFAULT_CHANNELS, gl["channels"] or {})
        global_urgency = list(gl["urgency_filter"] or _DEFAULT_URGENCY)
        global_threshold = float(gl["confidence_threshold"])
    else:
        global_channels = dict(_DEFAULT_CHANNELS)
        global_urgency = list(_DEFAULT_URGENCY)
        global_threshold = 0.50

    if row is None:
        return {
            "strategy_id": strategy_code,
            "enabled": True,
            "channels": global_channels,
            "urgency_filter": global_urgency,
            "confidence_threshold": global_threshold,
            "notify_entry_only": False,
        }

    threshold = (
        float(row["confidence_threshold"])
        if row["confidence_threshold"] is not None
        else global_threshold
    )
    return {
        "strategy_id": strategy_code,
        "enabled": row["push_enabled"],
        "channels": global_channels,  # 渠道在策略级不再额外存储，继承全局
        "urgency_filter": global_urgency,
        "confidence_threshold": threshold,
        "notify_entry_only": row["notify_entry_only"],
    }


async def update_strategy_settings(
    db: AsyncConnection,
    *,
    user_id: str,
    strategy_code: str,
    body: StrategySettingsPatch,
) -> dict[str, Any]:
    """PUT /strategies/{strategy_code}/signal-settings"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id FROM strategies WHERE strategy_code = %s",
            (strategy_code,),
        )
        strat = await cur.fetchone()
        if strat is None:
            raise NotFound(f"strategy not found: {strategy_code}")

        # 读现有
        await cur.execute(
            """
            SELECT push_enabled, confidence_threshold, notify_entry_only
            FROM user_strategy_signal_settings
            WHERE user_id = %s AND strategy_id = %s
            """,
            (user_id, strat["id"]),
        )
        cur_row = await cur.fetchone()

        push_enabled = cur_row["push_enabled"] if cur_row else True
        threshold = cur_row["confidence_threshold"] if cur_row else None
        notify_entry_only = cur_row["notify_entry_only"] if cur_row else False

        if body.enabled is not None:
            push_enabled = body.enabled
        if body.confidence_threshold is not None:
            threshold = body.confidence_threshold
        if body.notify_entry_only is not None:
            notify_entry_only = body.notify_entry_only

        await cur.execute(
            """
            INSERT INTO user_strategy_signal_settings
                (user_id, strategy_id, push_enabled, confidence_threshold, notify_entry_only)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, strategy_id) DO UPDATE SET
                push_enabled = EXCLUDED.push_enabled,
                confidence_threshold = EXCLUDED.confidence_threshold,
                notify_entry_only = EXCLUDED.notify_entry_only,
                updated_at = NOW()
            """,
            (user_id, strat["id"], push_enabled, threshold, notify_entry_only),
        )
        await db.commit()

    return {"strategy_id": strategy_code, "updated": True}


# ---------------------------------------------------------------- helpers


def _merge_channels(default: dict[str, bool], stored: dict[str, Any]) -> dict[str, bool]:
    out = dict(default)
    for k in default:
        if k in stored:
            out[k] = bool(stored[k])
    return out
