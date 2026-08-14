"""Multi-strategy CLI — runs multiple strategies in parallel.

Usage::

    GETRICH_CONFIG='[{"name":"macross","strategy_id":"uuid1","symbols":["AU2606"]}]' \\
        python -m getrich.apps.strategy.cli_multi
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from getrich.apps.strategy.scheduler import (
    MultiStrategyRunner,
    StrategyConfig,
)


logger = logging.getLogger(__name__)

_ENV_CONFIG = "GETRICH_CONFIG"


def _load_configs() -> list[StrategyConfig]:
    raw = os.getenv(_ENV_CONFIG)
    if not raw:
        logger.error("%s environment variable is required", _ENV_CONFIG)
        sys.exit(1)
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in %s: %s", _ENV_CONFIG, exc)
        sys.exit(1)
    if not isinstance(entries, list):
        logger.error("%s must be a JSON array of strategy configs", _ENV_CONFIG)
        sys.exit(1)

    configs: list[StrategyConfig] = []
    for i, entry in enumerate(entries):
        try:
            configs.append(
                StrategyConfig(
                    name=entry["name"],
                    strategy_id=entry["strategy_id"],
                    symbols=tuple(entry["symbols"]),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("Invalid config at index %d: %s", i, exc)
            sys.exit(1)

    if not configs:
        logger.error("No valid strategy configs found in %s", _ENV_CONFIG)
        sys.exit(1)
    return configs


async def _main() -> None:
    configs = _load_configs()
    runner = MultiStrategyRunner(configs)
    result = await runner.run_all()

    # JSON line output (journald-friendly)
    sys.stdout.write(
        json.dumps(result.to_dict(), ensure_ascii=False, default=str) + "\n"
    )
    sys.stdout.flush()

    # Exit non-zero if any strategy had an error
    if result.errors:
        logger.warning(
            "Multi-strategy cycle complete — %d signals across %d configs, %d errors",
            result.total_signals,
            len(configs),
            len(result.errors),
        )
        sys.exit(1 if len(result.errors) == len(configs) else 0)
    else:
        logger.info(
            "Multi-strategy cycle complete — %d signals across %d configs",
            result.total_signals,
            len(configs),
        )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
