"""gr-tools 是依赖图最底层的叶子，不许依赖任何一方包。

一旦这里悄悄 import 了 ``gr_data``（例如为了复用它的 logger），
依赖图就成环了：gr-data 想用 gr-tools 的读文件能力时会互相 import。
用 AST 静态扫描，能发现藏在函数体里的延迟 import。
"""

from __future__ import annotations

import ast
from pathlib import Path

import gr_tools


#: 一方包全集，需与 gr-backtest 的 test_package_boundaries.py 保持同步。
FIRST_PARTY = {
    "gr_api",
    "gr_backtest",
    "gr_data",
    "gr_db",
    "gr_factor",
    "gr_signal",
    "gr_tools",
}

_SRC_ROOT = Path(gr_tools.__file__).resolve().parent


def _imported_top_level_packages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".", 1)[0])
    return found


def test_gr_tools_never_imports_first_party_packages() -> None:
    offenders: list[str] = []

    for source in sorted(_SRC_ROOT.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        forbidden = (_imported_top_level_packages(source) & FIRST_PARTY) - {"gr_tools"}
        offenders.extend(f"{source.relative_to(_SRC_ROOT)} -> {name}" for name in sorted(forbidden))

    assert not offenders, "gr-tools 依赖了一方包（它必须是无一方依赖的叶子）：\n  " + "\n  ".join(
        offenders
    )
