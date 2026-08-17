"""包边界回归测试：回测引擎不许反向依赖上层包。

这是本次重构最容易悄悄退化的一条约束。历史上 ``gr_backtest.__init__`` 直接
re-export 了实盘信号（``SignalProducer`` 等）和回测作业队列
（``PgBacktestJobStore``），于是：

* ``import gr_backtest`` 会把 FastAPI、Celery、Redis 一起拖进纯计算路径；
* 单独安装 ``gr-backtest`` 直接 ``ModuleNotFoundError``（见 DECISIONS.md D-004）。

这里用静态 AST 扫描，而不是 ``import`` 后看属性 —— 后者只能发现「已经被导入」
的情况，发现不了藏在函数体里的延迟 import。
"""

from __future__ import annotations

import ast
from pathlib import Path

import gr_backtest


#: 引擎允许依赖的一方包。gr-data 提供配置与数据库连接，gr-tools 是无一方
#: 依赖的通用工具叶子，两者都在引擎下层。
ALLOWED_FIRST_PARTY = {"gr_data", "gr_tools"}

#: 一方包全集；不在 ALLOWED 里的都算反向依赖。
FIRST_PARTY = {
    "gr_api",
    "gr_backtest",
    "gr_data",
    "gr_db",
    "gr_factor",
    "gr_signal",
    "gr_tools",
}

_SRC_ROOT = Path(gr_backtest.__file__).resolve().parent


def _imported_top_level_packages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".", 1)[0])
    return found


def test_engine_never_imports_upper_layer_packages() -> None:
    offenders: list[str] = []

    for source in sorted(_SRC_ROOT.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        forbidden = (_imported_top_level_packages(source) & FIRST_PARTY) - (
            ALLOWED_FIRST_PARTY | {"gr_backtest"}
        )
        for name in sorted(forbidden):
            offenders.append(f"{source.relative_to(_SRC_ROOT)} -> {name}")

    assert not offenders, "回测引擎出现了反向依赖（引擎只能依赖 gr_data）：\n  " + "\n  ".join(
        offenders
    )


def test_moved_symbols_are_not_re_exported() -> None:
    """已迁出的符号不能再从引擎导出，否则等于把依赖悄悄加回来。"""
    moved = {
        # -> gr_signal.live
        "Signal": "gr_signal.live",
        "SignalProducer": "gr_signal.live",
        "SignalWriter": "gr_signal.live",
        "EvalSignalWriter": "gr_signal.live",
        "LiveSignalError": "gr_signal.live",
        "SignalProductionError": "gr_signal.live",
        # -> gr_api.jobs.persistence
        "PgBacktestJobStore": "gr_api.jobs.persistence",
        "BacktestJobError": "gr_api.jobs.persistence",
    }
    leaked = [
        f"{name}（应在 {home}）" for name, home in moved.items() if hasattr(gr_backtest, name)
    ]
    assert not leaked, "引擎重新导出了已迁出的符号：" + ", ".join(leaked)


def test_engine_still_exports_its_own_public_api() -> None:
    """反向清理不能误伤引擎自己的公开入口。"""
    for name in ("Backtest", "RunConfig", "BacktestResult", "PgBarLoader", "Strategy"):
        assert hasattr(gr_backtest, name), f"引擎公开 API 缺失: {name}"
