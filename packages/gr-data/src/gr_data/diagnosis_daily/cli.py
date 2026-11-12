"""有界、前台执行的诊断日更命令；调度由仓外运维负责。"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from gr_data.common.paths import RawPaths
from gr_data.config.pipeline import Config
from gr_data.db.postgres.sync import connect

from . import apply, latest_publication, prepare
from .evidence import write_json


log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("diagnosis-daily", help="两阶段诊断日更（前台、有界）")
    parser.add_argument("action", choices=("prepare", "apply", "run", "status"))
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--artifact", type=Path, help="单日阶段A产物目录；apply时必填")
    parser.add_argument("--reuse-raw", type=Path, help="复用完整原件，仍重新执行只读预检")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, cfg: Config) -> int:
    from gr_data.cli import _pg
    from gr_data.raw.ricequant.client import RqdatacClient
    from gr_data.raw.tushare.client import TushareProClient

    pg = _pg(cfg)
    root = RawPaths(cfg.raw_root).dataset_dir("diagnosis", "daily")
    state = root / "last-run.json"
    try:
        if args.action == "apply":
            if args.artifact is None:
                raise ValueError("apply requires --artifact")
            result = apply(pg, args.artifact)
        elif args.action == "status":
            with connect(pg) as conn, conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                p = latest_publication(conn)
                result = {
                    "latest_publication": p["data_version_id"],
                    "as_of_date": str(p["as_of_date"]),
                    "valid": p["valid"],
                    "last_run": json.loads(state.read_text()) if state.exists() else None,
                }
        else:
            environment = cfg.environment
            if environment is None:
                raise ValueError("Daily CLI requires an explicit environment snapshot")
            ts = TushareProClient(environment.values.get("TUSHARE_TOKEN", ""))
            rq = RqdatacClient(
                license_key=environment.values.get("RICEQUANT_API_KEY", ""),
                connect_timeout=5,
                timeout=60,
            )
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            last_closed = now.date() if now.time() >= time(15) else now.date() - timedelta(days=1)
            if args.action == "prepare":
                if args.day is None or args.day > last_closed:
                    raise ValueError("prepare requires a completed target trading day")
                artifact = args.artifact or root / str(args.day)
                prepared = prepare(
                    pg, artifact, args.day, tushare=ts, ricequant=rq, reuse_raw=args.reuse_raw
                )
                result = {
                    "status": "ready",
                    "day": str(args.day),
                    "artifact": str(artifact),
                    "version_id": prepared["version_id"],
                }
            else:
                with connect(pg) as conn, conn.transaction():
                    conn.execute("SET TRANSACTION READ ONLY")
                    previous = latest_publication(conn)
                    first = args.start or previous["as_of_date"] + timedelta(days=1)
                    last = args.end or last_closed
                    if not previous["valid"]:
                        raise ValueError("Latest publication is invalid")
                    if args.start is None and first > last and last <= last_closed:
                        result = {"status": "up_to_date", "as_of_date": str(previous["as_of_date"])}
                        write_json(state, result)
                        print(json.dumps(result))
                        return 0
                    if first > last or last > last_closed:
                        raise ValueError("Invalid completed trading-day range")
                    dates = conn.execute(
                        (
                            "SELECT trading_day FROM meta.trading_calendar WHERE exchange='XSHG' "
                            "AND is_open AND trading_day BETWEEN %s AND %s ORDER BY trading_day"
                        ),
                        (first, last),
                    ).fetchall()
                    count = conn.execute(
                        (
                            "SELECT count(*) FROM meta.trading_calendar WHERE exchange='XSHG' AND"
                            " trading_day BETWEEN %s AND %s"
                        ),
                        (first, last),
                    ).fetchone()
                    if count is None or count[0] != (last - first).days + 1:
                        raise ValueError("Trading calendar does not cover the requested range")
                results = []
                for (day,) in dates:
                    artifact = root / str(day)
                    write_json(
                        state,
                        {"status": "running", "day": day, "phase": "A", "artifact": str(artifact)},
                    )
                    # 已准备批次按固定观察恢复；不在失败后换原件冒充同一批次。
                    if not (artifact / "prepared.json").exists():
                        prepare(pg, artifact, day, tushare=ts, ricequant=rq)
                    write_json(
                        state,
                        {"status": "running", "day": day, "phase": "B", "artifact": str(artifact)},
                    )
                    results.append(apply(pg, artifact))
                    write_json(
                        state,
                        {
                            "status": "published",
                            "day": day,
                            "version_id": results[-1]["version_id"],
                        },
                    )
                result = {"status": "complete", "publications": results}
        if args.action != "status":
            write_json(state, {"status": "success", "action": args.action, "result": result})
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        # 不输出供应商异常原文或连接参数；详细阶段诊断见对应产物status。
        previous_state = json.loads(state.read_text()) if state.exists() else {}
        artifact = (
            args.artifact
            if args.artifact is not None
            else (Path(previous_state["artifact"]) if previous_state.get("artifact") else None)
        )
        detail = {}
        if artifact is not None and (artifact / "status.json").exists():
            detail = json.loads((artifact / "status.json").read_text())
        reason = (
            str(exc)
            if isinstance(exc, ValueError) or type(exc).__module__.startswith("gr_data.")
            else "Inspect private artifact status for upstream failure"
        )
        write_json(
            state,
            {
                **previous_state,
                "status": "failed",
                "action": args.action,
                "error_type": type(exc).__name__,
                "reason": reason,
                "failed_stage": detail.get("stage") or detail.get("phase"),
                "artifact": str(artifact) if artifact else None,
            },
        )
        log.error(
            "Diagnostic daily update failed action=%s type=%s", args.action, type(exc).__name__
        )
        return 1
