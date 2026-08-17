"""选股标的池的模拟数据：30 个交易日的全量快照。

**全部是编造的数据**，代码是真实 A 股代码段格式但名称刻意写成「模拟股 NN」，
不对应任何真实证券，也不含任何真实行情或业绩数字。

生成结果落在 ``tests/fixtures/picks/`` 下，CSV 与 Parquet 各一份，内容相同：

* ``strategy_picks_30d.csv``     —— 人可读，可以直接丢给导入 CLI 做冒烟
* ``strategy_picks_30d.parquet`` —— 走 Parquet 读取路径的用例用它

两份都是「长表」：比导入契约多一列 ``trading_day``。导入是按天的，用例取某天
的切片再 ``drop("trading_day")`` 即可，这样 30 天只占两个文件，不用塞 30 份 CSV。

重新生成（结果是确定性的，同样的种子必然产出同样的字节）::

    uv run python packages/gr-api/tests/fixture_picks.py
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import polars as pl


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "picks"
CSV_PATH = FIXTURE_DIR / "strategy_picks_30d.csv"
PARQUET_PATH = FIXTURE_DIR / "strategy_picks_30d.parquet"

#: 导入契约的 7 列，顺序与 CSV 模板一致。
PICK_COLUMNS = (
    "symbol",
    "symbol_name",
    "entry_date",
    "rank",
    "score",
    "suggest_weight",
    "reason_text",
)

_SEED = 20260817
_FIRST_DAY = date(2026, 7, 1)
_DAYS = 30
_POOL_SIZE = 20
#: 每日换手数量的取值范围（含），0 表示当天池子不动。
_TURNOVER = (0, 3)


def trading_days(count: int = _DAYS, start: date = _FIRST_DAY) -> list[date]:
    """连续 ``count`` 个工作日（周一至周五）。

    刻意只跳周末、不跳法定节假日 —— 模拟数据的日历由
    :func:`build_frame` 的使用方一并写进 ``meta.trading_calendar``，
    两边用同一套日期，``holding_trading_days`` 才对得上。
    """
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _universe(size: int = 60) -> list[tuple[str, str]]:
    """候选池：``(带后缀代码, 名称)``，全部为编造值。"""
    prefixes = (("6000", "SH"), ("6008", "SH"), ("0000", "SZ"), ("3007", "SZ"), ("8307", "BJ"))
    out: list[tuple[str, str]] = []
    for index in range(size):
        head, suffix = prefixes[index % len(prefixes)]
        code = f"{head}{index:02d}.{suffix}"
        out.append((code, f"模拟股{index + 1:02d}"))
    return out


def build_frame(days: int = _DAYS, start: date = _FIRST_DAY) -> pl.DataFrame:
    """生成 30 天的全量快照长表（多一列 ``trading_day``）。

    数据形态刻意贴近真实上传习惯：

    * 首日给出 ``entry_date``（带入系统上线前的历史持仓，走 ``provided`` 分支），
      之后一律留空让系统按连续在池推算 —— 这正是 CSV 模板要求的填法；
    * 每天换掉 0–3 只，制造出池 / 重新入池，用来验证入池日的继承与重置；
    * ``rank`` 按 ``score`` 降序给，但**留几个空**，验证「系统不按行序推断排名」；
    * ``suggest_weight`` 是等权小数，合计约等于 1（合计不校验，见设计文档 §4.2）。

    Time Complexity:
        O(days × pool_size)。
    Space Complexity:
        同上。
    """
    rng = random.Random(_SEED)
    universe = _universe()
    calendar = trading_days(days, start)

    pool = [universe[i] for i in range(_POOL_SIZE)]
    spare = universe[_POOL_SIZE:]
    rows: list[dict[str, str]] = []

    for day_index, day in enumerate(calendar):
        if day_index:
            churn = rng.randint(*_TURNOVER)
            for _ in range(churn):
                if not spare:
                    break
                dropped = pool.pop(rng.randrange(len(pool)))
                pool.append(spare.pop(rng.randrange(len(spare))))
                spare.append(dropped)

        scored = sorted(
            ((code, name, round(rng.uniform(60, 95), 1)) for code, name in pool),
            key=lambda item: item[2],
            reverse=True,
        )
        weight = round(1 / len(scored), 4)
        for rank, (code, name, score) in enumerate(scored, start=1):
            rows.append(
                {
                    "trading_day": day.isoformat(),
                    "symbol": code,
                    "symbol_name": name,
                    # 只在首日填，之后留空由系统继承（CSV 模板的约定）。
                    "entry_date": "" if day_index else (day - timedelta(days=7)).isoformat(),
                    # 每 7 条留一个空 rank：验证 NULL 排末尾且系统不按行序补。
                    "rank": "" if rank % 7 == 0 else str(rank),
                    "score": f"{score:.1f}",
                    "suggest_weight": f"{weight:.4f}",
                    "reason_text": f"模拟理由：评分 {score:.1f}，第 {day_index + 1} 个交易日快照",
                }
            )

    return pl.DataFrame(
        rows,
        schema={col: pl.Utf8 for col in ("trading_day", *PICK_COLUMNS)},
    )


def load_frame() -> pl.DataFrame:
    """读回 Parquet 固件（全列字符串，与导入路径的口径一致）。"""
    return pl.read_parquet(PARQUET_PATH)


def day_slice(frame: pl.DataFrame, day: date) -> pl.DataFrame:
    """取某一交易日的切片，并去掉 ``trading_day`` 列 —— 即导入契约的 7 列。"""
    return frame.filter(pl.col("trading_day") == day.isoformat()).drop("trading_day")


def write_fixtures() -> tuple[Path, Path]:
    """重新生成两份固件文件，返回它们的路径。"""
    frame = build_frame()
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    frame.write_csv(CSV_PATH)
    frame.write_parquet(PARQUET_PATH)
    return CSV_PATH, PARQUET_PATH


if __name__ == "__main__":
    csv_path, parquet_path = write_fixtures()
    written = pl.read_parquet(parquet_path)
    print(f"{len(written)} rows × {written.width} cols")
    print(f"  {csv_path}")
    print(f"  {parquet_path}")
