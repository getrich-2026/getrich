"""人性化格式化：给日志和 CLI 输出用。

移植自 ``lntools.format.human``（2026-08-17），改动：
* 去掉 pandas 依赖，日期归一走 stdlib；
* ``datetime_str`` 不再依赖 lntools 的 timeutils，快捷格式在本模块内定义；
* 进度条 ``track`` 在没装 tqdm 时退化成节流文本输出。

这些函数只负责「给人看」，**不要**用它们的输出做解析或存库。
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Sequence, Sized
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar


T = TypeVar("T")

Reporter = Callable[[str], None]

#: ``datetime_str`` 的快捷格式名。
SHORTCUTS = {
    "wide": "%Y-%m-%d",
    "standard": "%Y/%m/%d",
    "compact": "%Y%m%d",
    "datetime": "%Y-%m-%d %H:%M:%S",
}


def path(path_str: str | Path | None) -> str:
    """路径能相对当前工作目录就显示相对路径，否则显示绝对路径。"""
    if not path_str:
        return ""
    try:
        resolved = Path(path_str).expanduser().resolve()
        cwd = Path.cwd()
        if resolved.is_relative_to(cwd):
            return str(resolved.relative_to(cwd))
        return str(resolved)
    except (ValueError, OSError):
        return str(path_str)


def unit(n: int | float, unit_name: str, decimal: int = 0, auto_scale: bool = False) -> str:
    """把数量和单位拼成可读文本。

    Args:
        n: 数量。
        unit_name: 单位名（英文单数形式）。
        decimal: 小数位数。
        auto_scale: 是否自动换算成 K / M / B / T。

    Returns:
        如 ``1 apple`` / ``10 apples`` / ``1.5K users``。

    Raises:
        ValueError: ``decimal`` 为负。
    """
    if decimal < 0:
        raise ValueError("decimal places cannot be negative")

    value = float(n)
    prefix = ""

    if auto_scale and abs(value) >= 1000:
        for candidate in ("", "K", "M", "B", "T"):
            prefix = candidate
            if abs(value) < 1000.0 or candidate == "T":
                break
            value /= 1000.0
        if decimal == 0 and value % 1 != 0:
            decimal = 1

    text = f"{value:.{decimal}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")

    plural = "s" if (value != 1.0 or prefix) and not unit_name.endswith("s") else ""
    return f"{text}{prefix} {unit_name}{plural}"


def bytes_size(n: int | float, decimal: int = 1) -> str:
    """字节数转 B / KB / MB / GB / TB / PB。"""
    value = float(n)
    for suffix in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024.0:
            return f"{int(value)} {suffix}" if suffix == "B" else f"{value:.{decimal}f} {suffix}"
        value /= 1024.0
    return f"{value:.{decimal}f} EB"


def sec2str(s: float) -> str:
    """秒数转可读时长，如 ``1.50s`` / ``2 mins 30s`` / ``1 hr 5 mins``。"""
    if s < 0:
        return f"-{sec2str(-s)}"
    if s < 0.001:
        return f"{s * 1e6:.0f}µs"
    if s < 1:
        return f"{s * 1e3:.0f}ms"
    if s < 60:
        return f"{s:.2f}s" if s < 10 else f"{s:.1f}s"

    delta = timedelta(seconds=int(s))
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if delta.days > 0:
        parts.append(unit(delta.days, "day"))
    if hours > 0:
        parts.append(unit(hours, "hr"))
    if minutes > 0:
        parts.append(unit(minutes, "min"))
    if delta.days == 0 and hours == 0 and secs > 0:
        parts.append(f"{secs}s")
    return " ".join(parts[:2])


def lists(items: Sequence[Any] | None, n: int = 3, formatter: Callable[[Any], str] = str) -> str:
    """列表截断预览，如 ``[1, 2, 3] (& 5 others)``。"""
    if items is None:
        return "None"
    if hasattr(items, "tolist"):
        items = items.tolist()
    if not isinstance(items, list | tuple | str):
        items = list(items) if isinstance(items, Iterable) else [items]

    length = len(items)
    if length == 0:
        return "[]"
    if length <= n:
        return f"[{', '.join(formatter(x) for x in items)}]"
    shown = ", ".join(formatter(x) for x in items[:n])
    return f"[{shown}] (& {unit(length - n, 'other')})"


def _to_date(value: Any) -> date:
    """把 ``date`` / ``datetime`` / ``YYYY-MM-DD`` / ``YYYYMMDD`` 归一成 ``date``。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int):
        text = str(value)
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(str(value).strip()[:10])


def ranges(days: Sequence[Any], sort: bool = True) -> str:
    """日期序列压缩成区间描述，如 ``2026-08-11 ~ 2026-08-14 (4 days, 4D)``。"""
    if not days:
        return "No dates"
    try:
        parsed = [_to_date(d) for d in days]
    except (ValueError, TypeError):
        return f"{len(days)} items (invalid dates)"

    if len(parsed) == 1:
        return f"{parsed[0]:%Y-%m-%d} (1 day)"
    if sort:
        parsed = sorted(parsed)

    start, end = parsed[0], parsed[-1]
    span_days = (end - start).days + 1

    years, remainder = divmod(span_days, 365)
    months = remainder // 30
    if years == 0 and months < 2:
        span_text = f"{span_days}D"
    else:
        span_text = (f"{years}Y" if years else "") + (f"{months}M" if months else "")
    return f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} ({len(parsed)} days, {span_text})"


def datetime_str(d: Any, method: str = "wide") -> str:
    """按快捷格式名或 strftime 模板格式化日期。

    Args:
        d: ``date`` / ``datetime`` / ISO 字符串 / ``YYYYMMDD`` 整数。
        method: :data:`SHORTCUTS` 里的名字，或任意 strftime 模板。

    Returns:
        格式化结果；解析失败时原样 ``str()`` 返回，不抛异常。
    """
    try:
        parsed = _to_date(d)
    except (ValueError, TypeError):
        return str(d)
    return parsed.strftime(SHORTCUTS.get(method, method))


def _track_text(
    items: Iterable[T],
    msg: str,
    total: int | None,
    reporter: Reporter,
    report_every: int,
) -> Generator[T, None, None]:
    last_pct = -1
    for index, item in enumerate(items):
        count = index + 1
        if total:
            pct = int(count * 100 / total)
            if pct > last_pct or count == total:
                reporter(f"{msg}: {count / total:.0%} ({count}/{total})")
                last_pct = pct
        elif count == 1 or (report_every > 0 and count % report_every == 0):
            reporter(f"{msg}: {count} items")
        yield item


def track(
    sequence: Iterable[T] | int,
    msg: str = "Processing",
    total: int | None = None,
    reporter: Reporter = print,
    report_every: int = 100,
    **tqdm_kwargs: Any,
) -> Generator[T, None, None]:
    """带进度显示地遍历序列；没装 tqdm 时退化成节流文本输出。"""
    items: Iterable[Any] = range(sequence) if isinstance(sequence, int) else sequence
    if total is None and isinstance(items, Sized):
        total = len(items)

    try:
        from tqdm import tqdm
    except ImportError:
        yield from _track_text(items, msg, total, reporter, report_every)
        return

    with tqdm(items, desc=msg, total=total, leave=True, dynamic_ncols=True, **tqdm_kwargs) as bar:
        yield from bar


__all__ = [
    "SHORTCUTS",
    "bytes_size",
    "datetime_str",
    "lists",
    "path",
    "ranges",
    "sec2str",
    "track",
    "unit",
]
