"""限流与重试工具。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar


T = TypeVar("T")


def sleep_s(seconds: float) -> None:
    if seconds and seconds > 0:
        time.sleep(seconds)


class PermanentError(RuntimeError):
    """确定性失败，重试没有意义（缺凭证、缺 SDK、参数非法等）。

    :func:`retry_call` 遇到它会立即抛出，不做退避。缺 token 这类问题重试 5 次
    要白等约 45 秒，而且真正的原因会被一串重试日志淹没。
    """


def retry_call(
    fn: Callable[..., T],
    *args: Any,
    max_retries: int = 5,
    backoff_base: float = 3.0,
    logger: logging.Logger | None = None,
    **kwargs: Any,
) -> T:
    """指数退避重试：等待 = backoff_base * 2^(attempt-1)。重试耗尽抛原异常。

    :class:`PermanentError` 不重试，直接抛出。
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except PermanentError:
            # 配置类错误重试多少次都是同样的结果，立刻抛给调用方。
            raise
        except Exception as exc:  # noqa: BLE001 - 供应商异常种类多，统一重试
            last_exc = exc
            if attempt >= max_retries:
                break
            wait = backoff_base * (2 ** (attempt - 1))
            if logger:
                logger.warning(
                    "调用失败，第 %d/%d 次重试，%.1fs 后重试: %s",
                    attempt,
                    max_retries,
                    wait,
                    exc,
                )
            sleep_s(wait)
    assert last_exc is not None
    raise last_exc
