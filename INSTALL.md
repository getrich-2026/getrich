# GetRich 安装与使用指南

## 安装方法

### 方法一：开发模式安装（推荐）

在项目根目录执行：

```powershell
pip install -e .
```

这会将项目安装为可编辑模式，修改代码后无需重新安装即可生效。

### 方法二：直接安装

```powershell
pip install .
```

### 方法三：仅安装依赖

```powershell
pip install -r requirements.txt
```

## 路径配置说明

项目提供了三种方式来解决模块导入路径问题：

### 1. 使用 setup_path.pth（已配置）

在 site-packages 中创建 `.pth` 文件，永久添加项目路径：
- 文件位置：`e:\project\getrich\setup_path.pth`
- 内容：项目根目录路径
- 适用场景：开发环境

### 2. 使用根目录 __init__.py（新增）

在任何脚本开头导入根目录的 `__init__.py`：

```python
# 方式 A: 直接导入（自动添加路径）
import sys
import os
sys.path.insert(0, r'e:\project\getrich')
import __init__

# 方式 B: 在脚本中手动添加
import sys
sys.path.insert(0, r'e:\project\getrich')

# 然后即可正常导入模块
from Data.GetRich_StockData_AK import *
from OptionLib.GetRich_ImpliesVolCal import *
```

### 3. 使用 pip install -e .（最佳实践）

执行开发模式安装后，可以在任何地方直接导入：

```python
from Data.GetRich_StockData_AK import *
from OptionLib.GetRich_ImpliesVolCal import *
from Data.clickhouse.api import ClickHouseAPI
```

## 验证安装

```powershell
# 验证包是否安装成功
pip show getrich

# 测试导入
python -c "from Data import GetRich_StockData_AK; print('导入成功')"

# 运行测试
pytest tests/
```

## 模块结构

安装后可用的主要模块：

- `Data`: 数据采集与处理
  - `Data.GetRich_StockData_AK`: 股票数据
  - `Data.GetRich_FuturesData_AK`: 期货数据
  - `Data.GetRich_OptionData_AK`: 期权数据
  - `Data.clickhouse`: ClickHouse 数据库接口

- `OptionLib`: 期权分析工具
  - `OptionLib.GetRich_ImpliesVolCal`: 隐含波动率计算
  - `OptionLib.GetRich_StraAnalysis_pricer`: 期权定价
  - `OptionLib.GetRich_StraAnalysis_riskanalyzer`: 风险分析
  - `OptionLib.GetRich_StraAnalysis_visualizer`: 可视化工具

## 常见问题

### Q: ModuleNotFoundError: No module named 'Data'

**解决方案**：
1. 确保执行了 `pip install -e .`
2. 或在脚本开头添加路径：`sys.path.insert(0, r'e:\project\getrich')`

### Q: 如何在 Jupyter Notebook 中使用？

```python
# 在 notebook 第一个单元格中
import sys
sys.path.insert(0, r'e:\project\getrich')

# 然后正常导入
from Data import GetRich_StockData_AK
```

### Q: 开发时需要重新安装吗？

使用 `pip install -e .` 的可编辑模式，修改代码后无需重新安装。

## 卸载

```powershell
pip uninstall getrich
```
