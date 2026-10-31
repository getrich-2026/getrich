"""持仓诊断纯计算模块（D-021）。

只依赖标准库、numpy、polars 与 gr-tools；不查库、不 import API 服务层或数据接入代码，
边界由 ``tests/test_diagnosis_calc_boundaries.py`` 静态守卫。取数与组装在
``gr_api.services.diagnosis``，这里的函数可以直接对照手算案例单测。
"""

from __future__ import annotations
