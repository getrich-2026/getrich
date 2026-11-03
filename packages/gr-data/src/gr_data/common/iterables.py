"""序列分块与可迭代对象展开。"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import TypeVar


T = TypeVar("T")


# ---- 切块 ----
def chunk_list(items: Sequence[T], size: int) -> Iterator[list[T]]:
    if size <= 0:
        raise ValueError("size must be > 0")
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def flatten_iter(it: Iterable[Iterable[T]]) -> list[T]:
    out: list[T] = []
    for sub in it:
        out.extend(sub)
    return out
