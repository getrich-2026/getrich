"""
GetRich 量化交易系统

本项目为量化交易系统，采用模块化设计，核心模块包括：
- Data: 数据采集与处理模块
- OptionLib: 期权分析与定价模块

使用本文件可确保项目根目录被添加到 Python 搜索路径中。
"""

import sys
import os

# 获取项目根目录的绝对路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 将项目根目录添加到 Python 搜索路径
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 版本信息
__version__ = "0.1.0"
__author__ = "GetRich Team"

# 导出主要模块（可选）
# from . import Data
# from . import OptionLib
