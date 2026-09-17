"""标准库日志配置与 JSON 格式；导入不产生配置或文件副作用。"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from gr_tools.config import DEFAULT_LOG_FORMAT


_HANDLER_NAME = "getrich.output"
_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """输出单行 JSON，保留结构化上下文且不允许覆盖核心字段。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RECORD_FIELDS and key != "context" and not key.startswith("_")
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        payload.update(
            ts=self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            level=record.levelname,
            logger=record.name,
            msg=record.getMessage(),
            request_id=getattr(record, "request_id", "-"),
        )
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    level: str | int = "INFO",
    *,
    file_path: str | Path | None = None,
    text_format: str = DEFAULT_LOG_FORMAT,
    json_format: bool = False,
    console: bool = True,
    filters: Sequence[logging.Filter] = (),
) -> None:
    """入口显式配置 root 输出，重配仅关闭本函数管理的 handler。

    不清除宿主框架或测试安装的 handler。业务 filter 安装到输出 handler，
    使传播到 root 的子 logger 记录也能获得上下文。并发运行期间不应重配。
    文件创建失败向调用方传播，原有输出配置保持不变。
    """
    # 在创建文件或替换 handler 前校验格式与级别。
    probe = logging.Logger("configuration")
    probe.setLevel(level)
    formatter = (
        JsonFormatter()
        if json_format
        else logging.Formatter(text_format, defaults={"request_id": "-"})
    )
    handlers: list[logging.Handler] = []
    if file_path is not None:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(formatter)
        for log_filter in filters:
            handler.addFilter(log_filter)
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if handler.name == _HANDLER_NAME:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(probe.level)
    for handler in handlers:
        root.addHandler(handler)
