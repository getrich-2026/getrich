"""gold_miner - 主程序入口.

用法:
    conda activate quant

    python main.py init                       # 全量初始化
    python main.py update                     # 每日增量更新
    python main.py update --only kline_day    # 只跑指定 fetcher (可多次)
    python main.py list                       # 列出所有已注册 fetcher
    python main.py -c other.yaml update       # 指定其他配置文件
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import Config
from src.fetchers import FetchMode
from src.logger import setup_logger
from src.registry import REGISTRY_CLASSES
from src.runner import Runner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gold_miner",
        description="AmazingData 本地化 parquet 抓取系统",
    )
    p.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="全量初始化")
    p_init.add_argument("--only", action="append", help="只跑指定 fetcher (可多次)")

    p_upd = sub.add_parser("update", help="增量更新 (每日定时用)")
    p_upd.add_argument("--only", action="append", help="只跑指定 fetcher (可多次)")

    sub.add_parser("list", help="列出所有已注册的 fetcher")
    return p


def cmd_list(cfg: Config) -> int:
    print(f"data_dir = {cfg.storage.data_dir}")
    print()
    print(f"{'name':<18} {'type':<14} {'enabled':<8} class")
    print("-" * 72)
    for cls in REGISTRY_CLASSES:
        name = cls.NAME
        enabled = cfg.fetcher_enabled.get(name, False)
        print(f"{name:<18} {cls.TYPE:<14} {str(enabled):<8} {cls.__name__}")
    # 提示 config 里出现但 registry 没登记的名字
    known = {c.NAME for c in REGISTRY_CLASSES}
    extra = [k for k in cfg.fetcher_enabled if k not in known]
    if extra:
        print()
        print("WARNING: config.yaml references unknown fetchers:", extra)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        return 2
    cfg = Config.load(cfg_path)

    log = setup_logger(level=cfg.logging.level, file=cfg.logging.file)
    log.info("gold_miner cmd=%s config=%s", args.cmd, cfg_path)

    if args.cmd == "list":
        return cmd_list(cfg)

    runner = Runner(cfg)
    mode = FetchMode.INIT if args.cmd == "init" else FetchMode.UPDATE
    runner.run(mode=mode, only=args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
