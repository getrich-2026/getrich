"""``gr-picks`` 命令行入口：把本地产出的标的池文件导进数据库。

这是 :func:`gr_api.services.pick_import.import_picks` 的薄壳，不含任何业务逻辑。

    uv run gr-picks import --strategy STR_STK_001 --trading-day 2026-08-12 \\
        --file picks.csv [--dry-run] [--overwrite] [--allow-empty]

退出码：0 成功（含 ``--dry-run`` 预检通过），1 有阻断错误或参数非法。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from gr_api.errors import ApiError
from gr_api.services.pick_import import PickImportResult, import_picks_sync
from gr_tools import human


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gr-picks", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="导入某个策略某一交易日的标的池")
    imp.add_argument("--strategy", required=True, help="策略 UUID 或 strategy_code")
    imp.add_argument("--trading-day", required=True, help="交易日 YYYY-MM-DD")
    imp.add_argument("--file", required=True, type=Path, help=".csv 或 .parquet 文件路径")
    imp.add_argument("--uploaded-by", default=None, help="操作者 user UUID，可不填")
    imp.add_argument("--note", default=None, help="本期备注，会展示给前端")
    imp.add_argument(
        "--overwrite",
        action="store_true",
        help="该交易日已有生效批次时覆盖（旧批次置 superseded）",
    )
    imp.add_argument(
        "--allow-empty",
        action="store_true",
        help="接受 0 行的池子，表示确认当日空仓",
    )
    imp.add_argument("--dry-run", action="store_true", help="只预检不写库")
    imp.add_argument("-v", "--verbose", action="store_true", help="打印 DEBUG 日志")
    return parser


def _report(result: PickImportResult, elapsed: float) -> None:
    summary = result.summary
    print(
        f"[{result.status}] {result.strategy_code} {result.trading_day} "
        f"— {human.unit(summary.get('valid_rows', 0), 'row')} valid / "
        f"{human.unit(summary.get('total_rows', 0), 'row')} total "
        f"({human.sec2str(elapsed)})"
    )
    if result.batch_id is not None:
        print(f"  batch_id={result.batch_id}")
    if summary.get("will_delete"):
        print(f"  superseded an existing batch with {summary['will_delete']} item(s)")
    for warning in result.warnings:
        print(f"  WARN  {warning}")
    for err in result.errors[:100]:
        print(
            f"  ERROR row {err['row_number']} [{err['column']}] "
            f"{err['error_code']}: {err['message']}"
        )
    if len(result.errors) > 100:
        print(f"  ... and {len(result.errors) - 100} more error(s)")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    started = time.monotonic()
    try:
        result = import_picks_sync(
            strategy=args.strategy,
            trading_day=args.trading_day,
            source=args.file,
            uploaded_by=args.uploaded_by,
            note=args.note,
            overwrite=args.overwrite,
            allow_empty=args.allow_empty,
            dry_run=args.dry_run,
        )
    except ApiError as exc:
        # 结构性问题（策略不存在、乱序上传、已有批次）：一条消息说清楚就够了。
        print(f"[failed] {exc.message}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"[failed] {exc}", file=sys.stderr)
        return 1

    _report(result, time.monotonic() - started)
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
