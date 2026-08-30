"""Provider 归属管理器。

规则：数据库内**同一张目标表只能由一个 provider 写入**（行情/元数据/实时同理）。
归属登记在 ``ops.table_ownership``。ingest/stream 写库前必须先 ``claim`` 或 ``check``，
防止两个 provider 串写同一张表导致来源不一致。

操作语义：
- ``claim(target, provider, channel)``：登记归属。若已被**另一** provider 占用则拒绝，
  除非 ``force=True``（转移归属，会记日志）。
- ``check(target, provider)``：只读校验，归属冲突时抛 ``OwnershipError``。
- ``owner(target)``：返回当前归属 provider 或 None。
- ``release(target)``：解除归属。

``channel`` ∈ {ingest, stream}，区分批量入库与实时写入两类写入通道。

**唯一的例外是 `MULTI_SOURCE_TABLES`**，见下方常量的注释。
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg


OWNERSHIP_TABLE = "ops.table_ownership"

#: 天生多源的表：**主键里含 `source`**，每个 provider 只写自己那一批行。
#:
#: 单表单一来源这条铁律要挡的是「两家供应商往同一批行里写不同口径的值，事后
#: 分不清哪行是谁的」。`meta.symbol_map` 的主键是 `(source, source_symbol)`，
#: 它的**用途就是跨源对齐**（AGENTS.md §3.4）：tushare 写 `600000.SH`、
#: datayes 写 `600000.XSHG`，两批行天然不重叠，谁写的一目了然。
#: 对它套用表级归属会让第二个 provider 永远 claim 不到，而这不是铁律要防的情形。
#:
#: 加表进这个集合的门槛：**主键必须含 `source`**，且各 provider 的行确实互不覆盖。
#: 不满足就不要加 —— 这是唯一的例外口子，开大了铁律就没了。
MULTI_SOURCE_TABLES = frozenset({"meta.symbol_map"})


class OwnershipError(RuntimeError):
    """目标表归属冲突。"""


@dataclass(frozen=True)
class Ownership:
    target: str  # 形如 'market.stock_bar_1d'
    provider: str  # 'yinhe' | 'ricequant' | 'insight'
    channel: str  # 'ingest' | 'stream'


class OwnershipManager:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def owner(self, target: str) -> Ownership | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT target, provider, channel FROM {OWNERSHIP_TABLE} WHERE target = %s",
                (target,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Ownership(target=row[0], provider=row[1], channel=row[2])

    def check(self, target: str, provider: str) -> None:
        """校验 provider 是否有权写 target；冲突抛 OwnershipError。未登记则放行（首次写）。"""
        if target in MULTI_SOURCE_TABLES:
            return
        current = self.owner(target)
        if current is not None and current.provider != provider:
            raise OwnershipError(
                f"表 {target} 当前归属 provider='{current.provider}'"
                f"（channel={current.channel}），拒绝 provider='{provider}' 写入。"
                f"如需切换数据源请显式转移归属（force/release）。"
            )

    def claim(
        self, target: str, provider: str, channel: str = "ingest", *, force: bool = False
    ) -> Ownership:
        """登记/确认归属。冲突且非 force 时抛 OwnershipError。

        `MULTI_SOURCE_TABLES` 里的表直接放行且**不登记**：登记了反而会让
        `own list` 显示一个误导性的「唯一 owner」。
        """
        if target in MULTI_SOURCE_TABLES:
            return Ownership(target=target, provider=provider, channel=channel)
        current = self.owner(target)
        if current is not None and current.provider != provider and not force:
            raise OwnershipError(
                f"表 {target} 已归属 provider='{current.provider}'，"
                f"provider='{provider}' 不能 claim。需转移请用 force=True。"
            )
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {OWNERSHIP_TABLE} (target, provider, channel, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (target) DO UPDATE
                  SET provider = EXCLUDED.provider,
                      channel = EXCLUDED.channel,
                      updated_at = now()
                """,
                (target, provider, channel),
            )
        return Ownership(target=target, provider=provider, channel=channel)

    def release(self, target: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"DELETE FROM {OWNERSHIP_TABLE} WHERE target = %s", (target,))

    def list_all(self) -> list[Ownership]:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT target, provider, channel FROM {OWNERSHIP_TABLE} ORDER BY target")
            return [Ownership(target=r[0], provider=r[1], channel=r[2]) for r in cur.fetchall()]
