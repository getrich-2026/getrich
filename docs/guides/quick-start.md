# getrich 快速开始

欢迎使用 getrich 量化交易系统！本指南帮你快速上手。

## 安装

### 环境要求
- Python 3.8+
- ClickHouse 21.3+

### 安装步骤
```bash
# 1. 克隆项目
git clone https://github.com/your-repo/getrich.git
cd getrich

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 ClickHouse（Docker）
docker run -d --name clickhouse -p 8123:8123 clickhouse/clickhouse-server
```

## 基本使用

### 表操作

```python
from Data.clickhouse.table.bar import MinBarTable
import pandas as pd

# 创建表
table = MinBarTable()
table.create()

# 插入数据
data = pd.DataFrame({
    'date': [20250101],
    'time': [93000000],
    'symbol': ['SH.600000'],
    'open': [10000], 'high': [10100],
    'low': [9900], 'close': [10050],
    'volume': [1000000], 'turnover': [10050000000],
    'pre_close': [10000], 'open_interest': [0],
    'pre_settle_price': [0], 'settle_price': [0],
    'local_time': [pd.Timestamp('2025-01-01 09:30:00')]
})
table.insert(data)

# 查询数据
df = table.read(
    symbols='SH.600000',
    start_date='2025-01-01',
    end_date='2025-01-31'
)
```

### 使用连接池（高并发）

```python
from Data.clickhouse import ClickHouseConnectionPool

# 创建连接池
pool = ClickHouseConnectionPool(
    host='localhost',
    min_size=2,
    max_size=10
)

# 表使用连接池
table = MinBarTable(pool=pool)
table.insert(data)
```

## 数据采集

```python
from Data.akshare.GetRich_StockData_AK import StockDataCollector

collector = StockDataCollector()
stock_data = collector.get_stock_data(
    symbol='000001',
    start_date='20250101',
    end_date='20250131'
)
```

## 期权分析

```python
from OptionLib.GetRich_ImpliesVolCal import ImpliedVolatilityCalculator

iv_calc = ImpliedVolatilityCalculator()
iv = iv_calc.calculate_iv(
    underlying_price=100.0,
    strike_price=105.0,
    time_to_expiry=0.25,
    risk_free_rate=0.05,
    option_price=2.5,
    option_type='call'
)
```

## 下一步

- � [表操作详细指南](../clickhouse/table/usage-guide.md)
- � [表结构设计](../clickhouse/table/table-design.md)
- � [连接池使用](../clickhouse/pool-usage.md)
- 🏗️ [系统架构](../architecture/system-overview.md)