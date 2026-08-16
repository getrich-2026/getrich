"""通用数据质量校验。

按 CLAUDE.md 数据完整性规则：显式处理空集、缺列、重复键、null，不静默丢弃。
校验只「报告」问题，是否中断由调用方决定。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class QualityReport:
    dataset: str
    row_count: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, msg: str) -> None:
        self.issues.append(msg)

    def __str__(self) -> str:
        head = f"[{self.dataset}] rows={self.row_count} ok={self.ok}"
        if self.issues:
            return head + "\n  - " + "\n  - ".join(self.issues)
        return head


def check_dataframe(
    df: pd.DataFrame,
    *,
    dataset: str,
    required_columns: list[str],
    key_columns: list[str] | None = None,
    not_null_columns: list[str] | None = None,
) -> QualityReport:
    """对入库前的 DataFrame 做基础校验。"""
    rep = QualityReport(dataset=dataset, row_count=len(df))

    if df.empty:
        rep.add("空数据集")
        return rep

    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        rep.add(f"缺少必需列: {missing}")
        return rep  # 缺列后续检查无意义

    if key_columns:
        dups = int(df.duplicated(subset=key_columns).sum())
        if dups:
            rep.add(f"重复主键 {key_columns}: {dups} 行")

    for col in not_null_columns or []:
        if col in df.columns:
            nulls = int(df[col].isna().sum())
            if nulls:
                rep.add(f"列 {col} 存在 {nulls} 个 null")

    return rep
