"""D-021：诊断纯计算模块只依赖标准库、numpy、polars 与 gr-tools。

一旦为了省事在这里 import 服务层、schema、数据库驱动或 gr_data，公式就无法脱离
数据库单测，取数与计算的边界也会悄悄消失。用 AST 静态扫描，能发现函数体内的延迟 import。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import gr_api.diagnosis_calc


_SRC_ROOT = Path(gr_api.diagnosis_calc.__file__).resolve().parent
_ALLOWED_THIRD_PARTY = {"numpy", "polars", "gr_tools"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.append("gr_api.diagnosis_calc")  # 相对导入只能指向本模块
            elif node.module:
                names.append(node.module)
    return names


def _allowed(module: str) -> bool:
    top = module.split(".", 1)[0]
    if top in sys.stdlib_module_names or top == "__future__":
        return True
    if top in _ALLOWED_THIRD_PARTY:
        return True
    return module == "gr_api.diagnosis_calc" or module.startswith("gr_api.diagnosis_calc.")


def test_diagnosis_calc_imports_stay_within_pure_dependencies() -> None:
    sources = sorted(p for p in _SRC_ROOT.rglob("*.py") if "__pycache__" not in p.parts)
    assert sources, "diagnosis_calc package has no sources"
    offenders = [
        f"{source.relative_to(_SRC_ROOT)} -> {module}"
        for source in sources
        for module in _imports(source)
        if not _allowed(module)
    ]
    assert not offenders, "diagnosis_calc 依赖了取数或 API 层：\n  " + "\n  ".join(offenders)
