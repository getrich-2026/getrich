"""`TableContract` 本体。

放在单独模块里，是为了让按 schema 切分的各个契约模块（meta/market/factor/…）
都能 import 它而不产生循环：`contracts/__init__.py` 只做 re-export。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TableContract:
    """一张目标表的契约。"""

    schema: str
    table: str
    columns: tuple[str, ...]  # 规范列（不含 DB 自动维护的 updated_at）
    conflict_keys: tuple[str, ...]  # ON CONFLICT 键（= 业务主键）
    # 显式 PG 类型名，供 COPY 时 `cursor.copy().set_types()` 使用。
    # 语义是**要么不填，要么把 columns 全部填齐**（见 db/copy.py::upsert_rows）：
    # 只填一半会让 set_types 的位置参数与列错位，是比不填更糟的失败模式。
    # 绝大多数表留空即可 —— psycopg 对 str/int/float/date 的类型推断没有问题，
    # 只有 jsonb 与数组列必须显式声明（推断出的 float8[] 喂给 real[] 是隐式转换，
    # 能跑但脆；全 NULL 的首行还会让推断直接退化）。
    column_types: tuple[tuple[str, str], ...] = field(default=())

    def __post_init__(self) -> None:
        if self.column_types:
            declared = tuple(c for c, _ in self.column_types)
            if declared != self.columns:
                raise ValueError(
                    f"{self.schema}.{self.table} 的 column_types 必须与 columns 同序同全量："
                    f"columns={self.columns} column_types={declared}"
                )

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"

    def pg_types_for(self, cols: Sequence[str]) -> list[str] | None:
        """按给定列顺序返回 PG 类型名；未声明 column_types 则返回 None。

        `cols` 是 upsert 实际写入的列（可以是 columns 的子集或另一种顺序）。
        出现未声明类型的列直接抛错，而不是悄悄退回类型推断 —— 声明了一半
        比完全不声明更危险。
        """
        if not self.column_types:
            return None
        mapping = dict(self.column_types)
        missing = [c for c in cols if c not in mapping]
        if missing:
            raise ValueError(f"{self.qualified} 的 column_types 缺少列：{missing}")
        return [mapping[c] for c in cols]
