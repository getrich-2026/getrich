"""gr-data 统一命令行入口。

用法::

    gr-data raw <provider> [--mode init|update] [--only a,b]
    gr-data ingest <provider> [--only a,b] [--force-ownership]
    gr-data stream <provider> [--symbols ...]          # 长驻，需真实 SDK
    gr-data own list | set <target> <provider> <channel> | release <target>

provider ∈ {yinhe, ricequant, insight, tushare}（stream 仅 yinhe/insight）。
"""

from __future__ import annotations

import argparse
import sys

from gr_data.config.pipeline import Config, load_config
from gr_data.db.sync import PgConfig, connect
from gr_data.logging import configure_logging, get_logger


log = get_logger("cli")


def _configure_logging_from(cfg: Config) -> None:
    lg = cfg.section("logging")
    configure_logging(
        level=lg.get("level", "INFO"),
        log_dir=lg.get("dir") if lg.get("dir") else None,
        json_format=bool(lg.get("json", False)),
        console=bool(lg.get("console", True)),
    )


def _pg(cfg: Config) -> PgConfig:
    return PgConfig.from_dict(cfg.section("postgres"))


def _split(val: str | None) -> list[str] | None:
    return [x.strip() for x in val.split(",") if x.strip()] if val else None


def cmd_raw(args: argparse.Namespace, cfg: Config) -> int:
    from gr_data.raw import run_provider

    results = run_provider(args.provider, cfg, mode=args.mode, only=_split(args.only))
    for ds, n in results.items():
        log.info("raw %s/%s -> %d", args.provider, ds, n)
    print(f"raw {args.provider} 完成: {results}")
    return 0


def cmd_ingest(args: argparse.Namespace, cfg: Config) -> int:
    from gr_data.ingest import run_provider

    with connect(_pg(cfg)) as conn:
        results = run_provider(
            args.provider,
            conn,
            cfg,
            only=_split(args.only),
            force_ownership=args.force_ownership,
        )
    for r in results:
        log.info("ingest %s -> rows=%d warnings=%d", r.target, r.rows_written, len(r.warnings))
    print(
        f"ingest {args.provider} 完成: "
        + ", ".join(f"{r.target}={r.rows_written}" for r in results)
    )
    return 0


def cmd_own(args: argparse.Namespace, cfg: Config) -> int:
    from gr_data.common.ownership import OwnershipManager

    with connect(_pg(cfg)) as conn:
        mgr = OwnershipManager(conn)
        if args.action == "list":
            for o in mgr.list_all():
                print(f"  {o.target} <- {o.provider} ({o.channel})")
        elif args.action == "set":
            mgr.claim(args.target, args.provider, channel=args.channel, force=True)
            conn.commit()
            print(f"已登记 {args.target} -> {args.provider} ({args.channel})")
        elif args.action == "release":
            mgr.release(args.target)
            conn.commit()
            print(f"已解除 {args.target} 归属")
    return 0


def cmd_stream(args: argparse.Namespace, cfg: Config) -> int:
    print(
        "stream 为长驻实时进程，需注入已登录的供应商 SDK。"
        "请在部署脚本中构造 handler、claim_ownership 后驱动 bridge/PgTickWriter。"
        "详见 docs/layers/stream.md。"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gr-data", description="GetRich 数据接入层 CLI")
    p.add_argument("--config", help="配置文件路径", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    raw = sub.add_parser("raw", help="抓取 raw 数据落 parquet")
    raw.add_argument("provider", choices=["yinhe", "ricequant", "insight", "tushare"])
    raw.add_argument("--mode", choices=["init", "update"], default="update")
    raw.add_argument("--only", help="逗号分隔的 fetcher 子集")
    raw.set_defaults(func=cmd_raw)

    ing = sub.add_parser("ingest", help="入库到 PostgreSQL")
    ing.add_argument("provider", choices=["yinhe", "ricequant", "insight", "tushare"])
    ing.add_argument("--only", help="逗号分隔的 importer 子集")
    ing.add_argument("--force-ownership", action="store_true", help="允许转移目标表归属")
    ing.set_defaults(func=cmd_ingest)

    st = sub.add_parser("stream", help="实时行情入库（长驻）")
    st.add_argument("provider", choices=["yinhe", "insight"])
    st.add_argument("--symbols", help="逗号分隔的订阅标的")
    st.set_defaults(func=cmd_stream)

    # 建库与迁移不在这里 —— DDL 的唯一真源是 gr-db，用 `gr-db migrate`。

    own = sub.add_parser("own", help="表归属管理")
    own.add_argument("action", choices=["list", "set", "release"])
    own.add_argument("target", nargs="?", help="如 market.stock_bar_1d")
    own.add_argument("provider", nargs="?")
    own.add_argument("channel", nargs="?", default="ingest", choices=["ingest", "stream"])
    own.set_defaults(func=cmd_own)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    cfg = load_config(args.config)
    _configure_logging_from(cfg)
    try:
        return args.func(args, cfg)
    except RuntimeError as exc:
        # 缺凭证／缺供应商 SDK 是**预期内**的配置问题，不是程序缺陷：
        # 打一行可执行的提示就够了，甩一整页 traceback 只会淹没真正的原因。
        # 其他异常照常抛出，保留完整栈便于排查。
        log.error("%s", exc)
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
