"""数量、字节数与时长的可读格式化，供日志和 CLI 展示。

输出经过舍入或截断，不应用于解析、计算或存库。
"""

from __future__ import annotations

from math import isfinite


def _finite_float(value: int | float) -> float:
    """统一拒绝非有限值及超出 float 表示范围的整数。"""
    try:
        number = float(value)
    except OverflowError:
        raise ValueError("value must be finite and within float range") from None
    if not isfinite(number):
        raise ValueError("value must be finite and within float range")
    return number


def _trim_zeros(text: str) -> str:
    """去掉小数部分的尾零，并把 ``-0`` 归一为 ``0``。"""
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def unit(n: int | float, unit_name: str, decimal: int = 0, auto_scale: bool = False) -> str:
    """格式化数量；英文复数仅通过追加 s 处理，不处理不规则词形。

    Args:
        n: 有限数量，支持负数；未缩放的整数保留精确值。
        unit_name: 英文单数单位名，已以 s 结尾时不重复追加。
        decimal: 最多保留的小数位数，输出去掉小数部分的尾零。
        auto_scale: 按 1000 进位至 K / M / B / T；缩放后 decimal 为 0
            且有小数时保留一位，舍入达到进位阈值时继续进位。

    Returns:
        如 ``1 apple`` / ``10 apples`` / ``1.5K users``。
        未缩放且显示值绝对值为 1 时使用单数。

    Raises:
        ValueError: decimal 为负，或 n 无法表示为有限 float。
    """
    if decimal < 0:
        raise ValueError("decimal places cannot be negative")
    value = _finite_float(n)
    prefixes = ("", "K", "M", "B", "T")
    index = 0
    if auto_scale:
        while abs(value) >= 1000 and index < len(prefixes) - 1:
            value /= 1000
            index += 1

    precision = 1 if index and decimal == 0 and value % 1 else decimal
    text = str(int(n)) if index == 0 and isinstance(n, int) else f"{value:.{precision}f}"
    if auto_scale and index < len(prefixes) - 1 and abs(float(text)) >= 1000:
        value /= 1000
        index += 1
        precision = 1 if decimal == 0 and value % 1 else decimal
        text = f"{value:.{precision}f}"
    text = _trim_zeros(text)

    singular = index == 0 and text in {"1", "-1"}
    plural = "" if singular or unit_name.endswith("s") else "s"
    return f"{text}{prefixes[index]} {unit_name}{plural}"


def bytes_size(n: int | float, decimal: int = 1) -> str:
    """按 1024 进位显示字节数，沿用 B / KB / MB / GB / TB / PB / EB 命名。

    Args:
        n: 有限字节数，支持负数。
        decimal: B 以上单位最多保留的小数位数，输出去掉小数部分的尾零；
            B 截断到整数。

    Returns:
        如 ``512 B`` / ``1 KB`` / ``1.5 KB``；舍入达到 1024 时进位，最大单位为 EB。

    Raises:
        ValueError: decimal 为负，或 n 无法表示为有限 float。
    """
    if decimal < 0:
        raise ValueError("decimal places cannot be negative")
    value = _finite_float(n)
    suffixes = ("B", "KB", "MB", "GB", "TB", "PB", "EB")
    index = 0
    while abs(value) >= 1024 and index < len(suffixes) - 1:
        value /= 1024
        index += 1
    text = str(int(n)) if index == 0 else f"{value:.{decimal}f}"
    if index < len(suffixes) - 1 and abs(float(text)) >= 1024:
        value /= 1024
        index += 1
        text = f"{value:.{decimal}f}"
    return f"{_trim_zeros(text)} {suffixes[index]}"


def sec2str(s: float) -> str:
    """将有限秒数格式化为时长，支持零与负数。

    一分钟以内使用 µs / ms / s；一分钟以上截断到整秒，
    最多显示两个非零单位，达到一小时后不显示秒。

    Args:
        s: 有限秒数。

    Returns:
        如 ``1.50s`` / ``2 mins 30s`` / ``1 hr 5 mins``。

    Raises:
        ValueError: s 无法表示为有限 float。
    """
    value = _finite_float(s)
    sign = "-" if value < 0 else ""
    value = abs(value)
    # 按舍入后的显示值选单位：round() 与格式化的取整规则一致，
    # 如 0.9996 显示为 1.00s 而不是 1000ms
    if round(value * 1e6) == 0:
        return "0µs"
    if round(value * 1e6) < 1000:
        return f"{sign}{value * 1e6:.0f}µs"
    if round(value * 1e3) < 1000:
        return f"{sign}{value * 1e3:.0f}ms"
    if round(value, 2) < 10:
        return f"{sign}{value:.2f}s"
    if round(value, 1) < 60:
        return f"{sign}{value:.1f}s"

    # 59.95～60 秒舍入后已达一分钟，不能截断回 59s
    days, remainder = divmod(max(int(value), 60), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(unit(days, "day"))
    if hours:
        parts.append(unit(hours, "hr"))
    if minutes:
        parts.append(unit(minutes, "min"))
    if days == 0 and hours == 0 and secs:
        parts.append(f"{secs}s")
    return sign + " ".join(parts[:2])


__all__ = ["bytes_size", "sec2str", "unit"]
